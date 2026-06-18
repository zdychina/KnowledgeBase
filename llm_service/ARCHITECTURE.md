# llm_service 内部架构

> **模块级实现文档。** 系统级架构请参见 `docs/architecture/*`。
> 状态：2026-06-18 由 Claude 基于 commit `<HEAD>` 全核刷新。
> 配套入口文档：[`README.md`](./README.md) / [`QUICKSTART.md`](./QUICKSTART.md)。

## 1. 模块全图

（TODO：Task 5 用真实文件清单替换）

## 2. 启动生命周期

> 来源：`main.py` lifespan + `runtime/worker.py` + `runtime/task_manager.py`（具体 lifespan 钩子在 Task 5 补全）。

```
main.py lifespan
  ├─ LlmRuntimeDB 连接池初始化（PostgreSQL）
  ├─ TemplateRegistry 启动（cache_ttl 控制缓存）
  ├─ Provider / ModelProvider 实例化
  ├─ PersistWriter 启动（后台批写协程）        ← Task 2 补细节
  ├─ LLMService 实例化（持有上述依赖）
  ├─ Worker.start(concurrency=N)
  │    └─ N × _loop()：claim → execute → complete/fail
  └─ LeaseRecovery.start(interval=30s)
       └─ _loop()：扫 status='running' AND lease_expires_at<now → fail/重排
关闭顺序（lifespan shutdown）：
  Worker.stop() → LeaseRecovery.stop() → PersistWriter.stop() → DB 关闭
```

## 3. 数据流

llm_service 同时承担 **异步队列型** 与 **同步直通型** 两种语义，二者通过不同入口分流。

### 3.1 异步 chat（`LLMService.submit` → `POST /api/v1/tasks`）

```
Client.submit()
  → LLMService.submit()
       ├─ _resolve_template()：模板展开为 messages/schema（string.Template $var）
       └─ _submit_with_idempotency()：
            ├─ 查 idempotency_key 是否已有未终态任务 → 命中直接返回旧 task_id
            └─ 一个 transaction 内插入 agent_llm_tasks(queued) + agent_llm_requests
            └─ EventBus.emit("submitted")
Client 通过 GET /tasks/{id} / GET /tasks/{id}/result 轮询
Worker._loop()
  → TaskManager.claim()                         ← PostgreSQL FOR UPDATE SKIP LOCKED
  → Worker._execute_task()
       └─ _execute_chat()
            └─ LLMService.execute_chat_attempt()
                 ├─ INSERT agent_llm_attempts(running)
                 ├─ provider.complete(messages, params, response_format?)
                 ├─ UPDATE agent_llm_attempts(succeeded|failed)
                 ├─ INSERT agent_llm_results（含 parse_error 用于 debug）
                 ├─ parse 成功 → TaskManager.complete() → status='succeeded'
                 └─ parse 失败 → TaskManager.fail() → 触发重试或 dead_letter
```

**关键约束**：`execute_chat_attempt` 在所有失败路径上**不再 re-raise**。Worker 的 safety net 仅兜底未捕获异常；re-raise 会触发 safety net 二次调用 `_mgr.fail()`，造成「双扣重试次数」bug（见 commit 1d83af1 / 74c23c6）。

### 3.2 同步 chat（`LLMService.execute` → `POST /api/v1/execute`，Serving 主用）

**与异步路径完全不同的快路径**——绕过 claim / worker，直接调 LLM 后立即返回。

```
Client.execute()
  → LLMService.execute()
       ├─ Phase 1：_resolve_template()
       ├─ Phase 2：provider.complete()（唯一阻塞步骤）
       ├─ parse_output()
       ├─ Phase 3：PersistWriter.enqueue(SyncChatRecord)  ← 内存队列，零 DB 阻塞
       └─ Phase 4：从内存直接返回响应
            └─ 成功 → {status:'succeeded', result:{parsed_output, ...}}
            └─ 解析失败 → {status:'failed', error:{error_type:'parse_failed'}}
            └─ provider 异常 → {status:'failed', error:{error_type, error_message}}
```

DB 落库由 `PersistWriter` 在后台批量异步执行（具体机制见 §6.2）。同步调用者完全看不到 DB 延迟。

### 3.3 异步 Embedding / Rerank（`submit_embedding` / `submit_rerank`）

走与 §3.1 相同的 `_submit_with_idempotency` 入队流程，但 `task_type='embedding'` 或 `'rerank'`。Worker 分派到 `_execute_embedding` / `_execute_rerank`：

```
Worker._execute_embedding()
  ├─ SELECT agent_llm_requests WHERE task_id=...
  ├─ INSERT agent_llm_attempts(running)
  ├─ model_provider.embed(texts, model, dimensions)
  ├─ UPDATE agent_llm_attempts(succeeded, raw_response)
  ├─ INSERT agent_llm_results(parse_status='not_required', parsed_output=raw)
  └─ TaskManager.complete() / fail()
```

Rerank 流程结构相同，仅 provider 调用与 text_output 拼装不同（含每文档 score）。

### 3.4 同步 Embedding / Rerank（`POST /api/v1/models/embeddings` 等）

经 `ModelService` 直通 ModelProvider，**同样绕过 worker**。

```
Client.embed() / rerank()
  → POST /api/v1/models/embeddings | /rerank
  → ModelService.embed(body) / rerank(body)
       ├─ model_provider.embed(texts, model, dimensions)
       │    └─ provider 异常 → enqueue(SyncModelRecord(status='failed')) → re-raise
       ├─ 提取 token_usage、构造 text_output（rerank 还拼装每文档 score）
       ├─ enqueue(SyncModelRecord(status='succeeded', raw_response_json=...))
       └─ 返回 EmbeddingResponse / RerankResponse
```

落库不在请求路径上：`enqueue` 是非阻塞 `Queue.put_nowait`，由后台 PersistWriter 批量写。

### 3.5 输出解析（`runtime/parser.py`）

`parse_output(raw_text, expected_type, schema)` 是 sync / async 共用的解析层：

| `expected_type` | 行为 |
|---|---|
| `text` | 直接返回原文，`parse_status='succeeded'` |
| `json_object` | 剥 ```json``` 围栏 → `json.loads` → 必须是 dict，否则 fail |
| `json_array` | 同上 → 必须是 list |
| 其它 | 走 json_object 分支但类型不校验 |

`schema` 非空时调用 `jsonschema.validate`：
- Schema 本身非法 → `parse_status='failed'`，`parse_error='invalid schema: ...'`
- 实例不匹配 → `parse_status='schema_invalid'`，`validation_errors=[message]`

`ParseResult.parse_status` 三态：`succeeded` / `failed` / `schema_invalid`。Worker / sync 路径都依据它决定 `_mgr.complete()` 还是 `_mgr.fail()`。

## 4. 任务状态机

### 4.1 `agent_llm_tasks.status` 取值

| 状态 | 含义 | 由谁设置 |
|---|---|---|
| `queued` | 已入队，等待 claim | submit / fail(可重试) |
| `running` | 已被 claim，正在执行 | claim |
| `succeeded` | 成功完成 | complete |
| `dead_letter` | 重试耗尽，进死信 | fail(不可重试) |
| `cancelled` | 用户取消 | cancel |

> 注意：`failed` **不是 task 表的合法 status 值**。它仅出现在 `agent_llm_attempts.status` 与同步响应中（`execute()` 返回 `"failed"` 表示该次 attempt 失败）。任务终态只有 `succeeded` / `dead_letter` / `cancelled`。

### 4.2 状态迁移矩阵

| 当前状态 | 事件 | 新状态 | 关键字段更新 | 事件 emit |
|---|---|---|---|---|
| (新建) | submit | `queued` | `available_at=now`, `attempt_count=0`, `max_attempts=N` | `submitted` |
| `queued` | claim | `running` | `started_at=now`, `lease_expires_at=now+lease_duration` | `claimed` |
| `running` | complete | `succeeded` | `attempt_count+=1`, `finished_at=now` | `succeeded` |
| `running` | fail & `new_count<max` | `queued` | `attempt_count+=1`, `available_at=now+backoff` | `retried` |
| `running` | fail & `new_count>=max` | `dead_letter` | `attempt_count+=1`, `finished_at=now` | `dead_letter` |
| `running` | lease 过期 & 可重试 | `queued`（经 fail） | 同 fail | `dead_letter` 内部 emit |
| `running` | lease 过期 & 不可重试 | `dead_letter`（经 fail） | 同 fail | `dead_letter` |
| `queued` | cancel | `cancelled` | `finished_at=now`（仅 queued 可取消） | `cancelled` |

### 4.3 退避公式

```
backoff_seconds = min(backoff_base ** new_attempt_count, backoff_max)
default: backoff_base=2.0, backoff_max=60.0  →  2, 4, 8, 16, 32, 60, 60...
```

由 `config.task.retry_backoff_base` / `retry_backoff_max` 配置。

### 4.4 Lease 机制

- `claim` 时 `lease_expires_at = now + lease_duration`（默认 300s）
- `LeaseRecovery` 每 30s 扫一次：`status='running' AND lease_expires_at < now`
- 命中：先把对应 attempt 标 `lease_expired`，再走 `fail()` 决定重试或死信

## 5. Provider 体系

### 5.1 模板系统（`runtime/template_registry.py` + `runtime/service.py::_resolve_template`）

- **存储**：表 `agent_llm_prompt_templates`，按 `(template_key, template_version, knowledge_domain)` UPSERT
- **查询**：`get_by_key(template_key, knowledge_domain)` — 精确匹配 domain 优先于 NULL（domain-specific overrides generic）
- **缓存**：内存字典 + TTL（`config.template.cache_ttl`）。`update` / `archive` 后缓存全清
- **白名单更新**：列名静态校验（`_ALLOWED_UPDATE_COLUMNS`），杜绝 SQL 注入
- **展开**：`string.Template($var).safe_substitute(input)`，未匹配变量保留原文
- **schema 注入**：`expected_output_type ∈ (json_object, json_array)` 且 schema 非空时，把 JSON Schema 追加到 system prompt（带"不要原样输出 Schema 定义本身"的中文说明）

### 5.2 幂等性（`runtime/idempotency.py`）

`find_existing_task(db, idempotency_key)`：
- 按 `succeeded → running → queued` 顺序找最新匹配
- 任意一步命中即返回，全部未命中返回 None（允许新建）

> **微差注意**：`LLMService._submit_with_idempotency` 自身的查询是「status NOT IN ('failed','dead_letter','cancelled') ORDER BY created_at DESC LIMIT 1」——返回任意非终态最新一条，与上面函数的优先级顺序不完全一致。两条路径并存：`TaskManager.submit` 走 `find_existing_task`；`LLMService.submit_*` 走自身内联查询。建议统一（见 handoff）。

### 5.3 事件总线（`runtime/event_bus.py`）

极简：每次 `emit(task_id, event_type, message, metadata)` = 一条 `INSERT INTO agent_llm_events`。无广播、无订阅者，事件表仅供 Dashboard / 排查使用。Task 1 已列各状态迁移对应的事件类型。

> Provider 协议、能力矩阵、扩展指南在 Task 3 写入（依赖 providers/* 的全核）。

## 6. 存储层

### 6.1 PostgreSQL Schema

llm_service 已迁离 SQLite（与 README v1.2 描述不符）。表清单（基于 SQL 模板与 pg_schema，pg_schema 细节 Task 5 补全）：

| 表 | 用途 | 关键字段 |
|---|---|---|
| `agent_llm_tasks` | 任务主表 | id, status, task_type, priority, attempt_count, max_attempts, lease_expires_at, idempotency_key |
| `agent_llm_requests` | 请求快照 | task_id, messages_json, input_json, params_json, expected_output_type, output_schema_json |
| `agent_llm_attempts` | 每次尝试 | task_id, attempt_no, status, raw_output_text, prompt/completion/total_tokens, latency_ms, error_type |
| `agent_llm_results` | 解析结果 | task_id, attempt_id, parse_status, parsed_output_json, text_output, parse_error, validation_errors_json |
| `agent_llm_events` | 状态变迁日志 | task_id, event_type, message, metadata_json |
| `agent_llm_prompt_templates` | 模板 CRUD | template_key, template_version, knowledge_domain, system_prompt, user_prompt_template |
| `agent_llm_model_calls` | **embedding/rerank 专属审计**（README 未提） | call_type, model, input_count, latency_ms, token_usage |

> README v1.2 标"6 张表"，实际 ≥ 7 张（多 `agent_llm_model_calls`）。

### 6.2 PersistWriter（`runtime/persist_writer.py`）

**目的**：把同步路径（execute / embed / rerank）的 DB 落库完全移出请求热路径，让同步调用者看不到 DB 延迟。

```
请求路径（同步）            后台路径
──────────────              ──────────────
provider.complete()         PersistWriter._writer_loop:
parse_output()                while running:
enqueue(SyncChatRecord)  ─→     item = queue.get(timeout=flush_interval)
return from memory             batch ← 取最多 batch_size 条
                                async with conn.transaction():
                                  _write_chat(record)  / _write_model(record)
```

**关键参数**（从 config 注入）：
- `queue_size=10000` — 内存队列上限
- `batch_size=20` — 单次最多批写条数
- `flush_interval=0.5s` — 即使数据少也定期刷
- `writer_count=1` — 后台写协程数

**降级策略**：队列满 → `put_nowait` 抛 `QueueFull` → 丢弃记录 + 计数 `self._dropped`；前 10 条 + 每 1000 条打 WARNING。**优先保证同步路径延迟，而非审计完整性**。

**事务粒度**：每条 record 一个 transaction，单条失败不影响批次内其它记录。

**SyncChatRecord 落库**（4 个 SQL，单事务）：
1. `INSERT agent_llm_tasks`（status 直接是最终态 `succeeded`/`failed`，`attempt_count=1`）
2. `INSERT agent_llm_requests`
3. `INSERT agent_llm_attempts`（按 final_status 选 OK / FAIL 模板）
4. `INSERT agent_llm_results`

**SyncModelRecord 落库**（最多 5 个 SQL）：
1. `INSERT agent_llm_tasks`（attempt_count=1, max_attempts=1，直接终态）
2. `INSERT agent_llm_requests`
3. `INSERT agent_llm_attempts`
4. `INSERT agent_llm_results`（仅 succeeded 时）
5. **`INSERT agent_llm_model_calls`**（embedding/rerank 专属审计表，记录 call_type/model/input_count/latency/tokens）

## 7. 配置与热重载

（TODO：Task 5 写环境变量 + 热重载机制）

## 8. 已知边界与限制

（TODO：Task 10 汇总）
