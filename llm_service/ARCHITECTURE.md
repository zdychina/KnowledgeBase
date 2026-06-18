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

经 `ModelService`（Task 2 补全）直通 provider，**同样绕过 worker**。审计落库由 `_record_sync_task` 类机制完成（具体在 §6.2 PersistWriter 中说明）。

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

（TODO：Task 2 + Task 3 写协议/能力矩阵/扩展指南）

## 6. 存储层

（TODO：Task 2 + Task 5 写 PostgreSQL schema + PersistWriter）

## 7. 配置与热重载

（TODO：Task 5 写环境变量 + 热重载机制）

## 8. 已知边界与限制

（TODO：Task 10 汇总）
