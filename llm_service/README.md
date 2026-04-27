# LLM Service

> 统一 LLM 调用与审计服务，为 Mining / Serving 提供集中式的模型调用能力。
> 版本：v1.1 | 数据库：agent_llm_runtime（6 张表）| 端口：8900 | 测试：84 passed

## 1. 系统定位

LLM Service 是一个**独立运行的 FastAPI 服务**，拥有自己的 SQLite 数据库（WAL 模式）。

**核心职责：** 统一管理所有 LLM 调用的提交、执行、重试、结果解析和审计记录。Mining 和 Serving 不各自维护 LLM 调用逻辑，而是通过 `LLMClient` 或 HTTP API 调用本服务。

```
┌─────────┐     ┌─────────┐
│ Mining  │     │ Serving │
│ (异步)  │     │ (同步)  │
└────┬────┘     └────┬────┘
     │  submit()     │  execute()
     │  get_result() │  直接返回
     └───────┬───────┘
             ▼
    ┌─────────────────┐
    │  LLM Service    │  ← 你在这里
    │  FastAPI :8900   │
    │  SQLite (WAL)   │
    │  Worker 进程     │
    └────────┬────────┘
             │
    ┌────────┼────────┐
    ▼        ▼        ▼
 DeepSeek  OpenAI  Ollama ...
```

## 2. 模块架构

```
llm_service/
├── __main__.py             # python -m llm_service 入口
├── main.py                 # FastAPI app 工厂，初始化 lifespan / worker / recovery
├── config.py               # 环境变量配置（LLM_SERVICE_* 前缀）
├── models.py               # API 请求/响应 Pydantic 模型
├── db.py                   # SQLite 连接（WAL + autocommit），DDL 从共享 SQL 加载
├── client.py               # Python LLMClient — Mining / Serving 的调用入口
│
├── runtime/
│   ├── service.py          # 顶层编排：模板解析、submit/execute、响应构建
│   ├── task_manager.py     # 任务生命周期：submit / claim / complete / fail / cancel
│   ├── executor.py         # 执行引擎（同步路径）：重试循环 + Provider 调用
│   ├── worker.py           # 后台 Worker + LeaseRecovery（异步路径）
│   ├── event_bus.py        # 事件总线：任务状态变更落库
│   ├── template_registry.py# 模板 CRUD（string.Template $var 语法）
│   ├── parser.py           # 输出解析：text / json_object / json_array + jsonschema 校验
│   └── idempotency.py      # 幂等控制：idempotency_key 防重复
│
├── providers/
│   ├── base.py             # ProviderProtocol 接口 + ProviderResponse / ProviderError
│   ├── openai_compatible.py# OpenAI 兼容 Provider（DeepSeek / Qwen / Ollama 等）
│   └── mock.py             # MockProvider（测试用）
│
├── api/
│   ├── tasks.py            # POST /tasks, POST /execute, GET /tasks/{id}, POST /cancel
│   ├── results.py          # GET /tasks/{id}/result, attempts, events
│   ├── health.py           # GET /health
│   └── templates.py        # 模板 CRUD API
│
├── dashboard/              # Web 监控看板
├── templates/              # Jinja2 HTML 模板（看板用）
└── tests/                  # 84 个测试用例
```

## 3. 数据流

### 3.1 同步执行（`execute()`）— Serving 场景

```
Client.execute()
  → POST /api/v1/execute
  → LLMService.submit()：创建任务（幂等复用）
  → LLMService.execute()：原子 claim（UPDATE WHERE status='queued'）
  → Executor.run()：
      → 构建 response_format hint
      → Provider.complete()：调用外部 LLM
      → parse_output()：解析 + jsonschema 校验
      → 记录 attempt + result + event
  → _build_execute_response()：返回完整结果
```

### 3.2 异步提交（`submit()`）— Mining 场景

```
Client.submit()
  → POST /api/v1/tasks
  → LLMService.submit()：幂等检查 → 解析模板 → 创建 task + request 行
  → 返回 task_id

  ── 后台 Worker（独立 DB 连接，并发=4）──
  → TaskManager.claim()：原子获取 queued 任务
  → Worker._execute_task()：
      → 读取 request 行的 messages / schema
      → Provider.complete() + parse_output()
      → complete() or fail()
  → LeaseRecovery：30s 一次，回收超时 lease

  ── 调用方轮询 ──
  → Client.get_result(task_id)：获取解析结果
```

## 4. 数据库设计

Schema 文件：`databases/agent_llm_runtime/schemas/001_agent_llm_runtime.sqlite.sql`

### 4.1 表结构

| 表 | 职责 | 关键列 |
|----|------|--------|
| `agent_llm_prompt_templates` | Prompt 模板管理 | template_key, version, system_prompt, user_prompt_template, output_schema_json |
| `agent_llm_tasks` | 任务主表 | caller_domain, pipeline_stage, status, priority, idempotency_key, attempt_count, max_attempts |
| `agent_llm_requests` | 请求参数快照 | task_id, provider, model, messages_json, input_json, params_json, expected_output_type, output_schema_json |
| `agent_llm_attempts` | 每次调用尝试 | task_id, attempt_no (UNIQUE), raw_output_text, tokens, latency_ms, error_type |
| `agent_llm_results` | 解析结果 | task_id, parse_status, parsed_output_json, text_output, validation_errors_json |
| `agent_llm_events` | 事件流水 | task_id, event_type (7种), message, created_at |

### 4.2 任务状态机

```
queued ──→ running ──→ succeeded
  │           │
  │           ├──→ failed ──→ queued (重试, backoff)
  │           │         └──→ dead_letter (耗尽 max_attempts)
  │           │
  └──→ cancelled
```

### 4.3 parse_status 状态

| 值 | 含义 |
|----|------|
| `succeeded` | 解析成功，如果提供了 schema 则校验也通过 |
| `failed` | JSON 解析失败 / 类型不匹配 |
| `schema_invalid` | JSON 解析成功但不符合 output_schema |

### 4.4 关键索引

- `(status, priority, created_at)` — 优先级队列 claim 查询
- `(task_id, attempt_no)` UNIQUE — 尝试有序
- `(task_id, created_at)` — 事件时间线

## 5. 关键设计决策

### 5.1 双模式调用

| 模式 | 方法 | 适用场景 | 行为 |
|------|------|---------|------|
| 同步 | `execute()` | Serving 在线查询 | 阻塞等待结果，默认超时 60s |
| 异步 | `submit()` | Mining 批量处理 | 立即返回 task_id，后台 Worker 并发执行 |

### 5.2 幂等控制

提交时可带 `idempotency_key`。相同 key 不创建新任务：

```
优先级：succeeded > running > queued → 返回已有 task_id
failed / dead_letter / cancelled → 允许创建新任务
```

### 5.3 重试与退避

- 指数退避：`backoff_base ^ attempt_no`，上限 `backoff_max`（默认 60s）
- 默认 `max_attempts=3`（首次 + 2 次重试）
- 所有尝试记录在 `agent_llm_attempts` 表，完整审计
- 错误分类：`timeout` / `connection_error` / `rate_limited` / `server_error` / `client_error` / `unexpected_error`

### 5.4 模板系统

- 模板语法：**Python `string.Template`**，使用 `$variable` 占位符，`safe_substitute` 替换（未匹配变量保留原样）
- 模板状态：`draft` → `active` → `archived`
- 唯一约束：`(template_key, template_version)`
- 调用方提供的 `messages` 优先于模板展开
- 调用方提供的 `expected_output_type` / `output_schema` 优先于模板默认值

### 5.5 三重 JSON 输出保障

当 `expected_output_type` 为 `json_object` 或 `json_array` 且提供了 `output_schema` 时：

1. **Prompt 注入**：将 JSON Schema 追加到 system prompt，告知模型输出格式约束
2. **response_format**：向 Provider 传 `response_format={"type": "json_object"}`（DeepSeek / GLM 支持）
3. **jsonschema 后校验**：`parse_output()` 用 `jsonschema.validate()` 验证输出，不匹配时返回 `parse_status="schema_invalid"` 并记录错误

### 5.6 DB 连接隔离

API service、Worker、LeaseRecovery 各使用独立的 DB 连接，避免并发写冲突。DB 使用 `isolation_level=None`（autocommit）+ WAL 模式。

### 5.7 Lease Recovery

- Worker claim 任务时设置 `lease_expires_at`（默认 300s）
- `LeaseRecovery` 每 30s 扫描 `status='running' AND lease_expires_at < now` 的任务
- 未耗尽重试次数 → re-queue；已耗尽 → dead_letter
- Worker 崩溃后任务不会永久卡住

## 6. API 接口详解

> 所有接口前缀：`/api/v1`
> 完整 URL：`http://localhost:8900/api/v1/...`

### 6.1 健康检查

```
GET /health
→ {"status": "ok"}
```

### 6.2 同步执行

```
POST /api/v1/execute
```

阻塞等待模型返回，直接返回完整结果。适合 Serving 在线场景。

**请求体（`TaskSubmitRequest`）：**

| 字段 | 类型 | 必填 | 说明 |
|------|------|------|------|
| `caller_domain` | string | 是 | 调用方域：`mining` / `serving` / 其他 |
| `pipeline_stage` | string | 是 | 管道阶段：`^[a-z][a-z0-9_]{1,63}$`（如 `normalizer`、`enrich`） |
| `template_key` | string | 否 | 模板 key（已有模板时使用） |
| `input` | object | 否 | 模板变量（与 template_key 配合，如 `{"text": "..."}`） |
| `messages` | array | 否 | 直接提供 messages（不用模板时使用，优先级高于模板） |
| `params` | object | 否 | 传给 Provider 的额外参数（如 `temperature`、`max_tokens`） |
| `expected_output_type` | string | 否 | `json_object` / `json_array` / `text`（默认 `json_object`） |
| `output_schema` | object | 否 | JSON Schema 用于输出校验（自动注入 prompt + post-validation） |
| `idempotency_key` | string | 否 | 幂等键（相同 key 复用已有任务） |
| `metadata` | object | 否 | 调用方自定义元数据（如 `caller_context`） |
| `max_attempts` | int | 否 | 最大重试次数（默认 3，范围 1-10） |
| `priority` | int | 否 | 优先级（默认 100，数值越大越优先） |

**响应示例：**

```json
{
  "task_id": "06948ea6-...",
  "status": "succeeded",
  "attempts": 1,
  "total_tokens": 156,
  "latency_ms": 2340,
  "result": {
    "parse_status": "succeeded",
    "parsed_output": {"summary": "Python是一种通用语言"},
    "text_output": null,
    "validation_errors": []
  },
  "error": null
}
```

**失败响应：**

```json
{
  "task_id": "...",
  "status": "dead_letter",
  "attempts": 3,
  "result": null,
  "error": {
    "error_type": "timeout",
    "error_message": "request timed out"
  }
}
```

### 6.3 异步提交

```
POST /api/v1/tasks
```

提交到队列，立即返回 task_id。后台 Worker 自动执行。

**请求体**：与 `execute` 完全相同（`TaskSubmitRequest`）。

**响应：**

```json
{
  "task_id": "e0cd2b67-...",
  "status": "queued",
  "idempotency_key": null,
  "created_at": "2026-04-27T10:30:00+00:00"
}
```

### 6.4 查询任务

```
GET /api/v1/tasks/{task_id}
```

返回任务详情：id、caller_domain、pipeline_stage、status、attempt_count、max_attempts、priority、metadata、时间戳等。

### 6.5 查询结果

```
GET /api/v1/tasks/{task_id}/result
```

返回解析结果：parse_status、parsed_output、text_output、parse_error、validation_errors。

### 6.6 查询尝试记录

```
GET /api/v1/tasks/{task_id}/attempts
```

返回所有尝试：每次的 status、tokens、latency_ms、error_type、raw_output_text。

### 6.7 查询事件流水

```
GET /api/v1/tasks/{task_id}/events
```

返回任务全生命周期事件：submitted → claimed → succeeded / retried → dead_letter。

### 6.8 取消任务

```
POST /api/v1/tasks/{task_id}/cancel
```

### 6.9 模板 CRUD

```
POST   /api/v1/templates          # 创建模板
GET    /api/v1/templates           # 列出所有模板
GET    /api/v1/templates/{key}     # 按 key 查询（返回最新 active 版本）
PUT    /api/v1/templates/{id}      # 更新模板
DELETE /api/v1/templates/{id}      # 归档模板（status → archived）
```

**创建模板请求体：**

| 字段 | 类型 | 必填 | 说明 |
|------|------|------|------|
| `template_key` | string | 是 | 模板标识（如 `mining-enrich`） |
| `template_version` | string | 否 | 版本号（默认 `"1"`） |
| `purpose` | string | 是 | 用途说明 |
| `system_prompt` | string | 否 | 系统 prompt |
| `user_prompt_template` | string | 是 | 用户 prompt 模板（`$variable` 语法） |
| `expected_output_type` | string | 否 | `json_object`（默认）/ `json_array` / `text` |
| `output_schema_json` | string | 否 | JSON Schema 字符串（如 `'{"type":"object","properties":{...}}'`） |
| `status` | string | 否 | `active`（默认）/ `draft` / `archived` |

### 6.10 看板

| 页面 | 地址 |
|------|------|
| 任务看板 | http://localhost:8900/dashboard |
| 统计 API | http://localhost:8900/dashboard/api/stats |
| Swagger 文档 | http://localhost:8900/docs |

## 7. Python SDK（LLMClient）

> 文件：`llm_service/client.py`

Mining 和 Serving 通过 `LLMClient` 调用，不需要直接拼 HTTP。

### 7.1 初始化

```python
from llm_service.client import LLMClient

# 默认连接 localhost:8900
client = LLMClient()

# 指定地址
client = LLMClient(base_url="http://your-server:8900")

# 共享 httpx.AsyncClient（推荐用于批量场景）
import httpx
http = httpx.AsyncClient(base_url="http://localhost:8900")
client = LLMClient(http_client=http)
```

### 7.2 同步执行（Serving 场景）

```python
result = await client.execute(
    caller_domain="serving",
    pipeline_stage="normalizer",
    template_key="serving-query-rewrite",
    input={"query": user_query},
)

# 读取结果
if result["status"] == "succeeded":
    parsed = result["result"]["parsed_output"]  # dict or None
    text = result["result"]["text_output"]       # str or None
    parse_status = result["result"]["parse_status"]  # succeeded / failed / schema_invalid
```

### 7.3 异步提交 + 轮询（Mining 场景）

```python
# 1. 批量提交
task_ids = []
for seg in segments:
    tid = await client.submit(
        caller_domain="mining",
        pipeline_stage="enrich",
        template_key="mining-enrich",
        input={"title": seg.title, "content": seg.text},
        idempotency_key=f"seg-{seg.id}-enrich",  # 防重复
        metadata={"caller_context": {"ref": {"type": "section", "id": seg.id}}},
    )
    task_ids.append(tid)

# 2. 轮询结果
for tid in task_ids:
    task = await client.get_task(tid)
    if task["status"] == "succeeded":
        result = await client.get_result(tid)
        output = result["parsed_output"]
    elif task["status"] == "dead_letter":
        attempts = await client.get_attempts(tid)
        last_error = attempts[-1]["error_message"]
```

### 7.4 不用模板，直接发 messages

```python
result = await client.execute(
    caller_domain="serving",
    pipeline_stage="rerank",
    messages=[
        {"role": "system", "content": "按相关性排序。"},
        {"role": "user", "content": f"Query: {q}\nDocs: {docs}"},
    ],
    expected_output_type="json_array",
)
```

### 7.5 带 Schema 校验

```python
result = await client.execute(
    caller_domain="mining",
    pipeline_stage="extract",
    template_key="mining-extract",
    input={"text": document_text},
    output_schema={
        "type": "object",
        "properties": {
            "entities": {
                "type": "array",
                "items": {
                    "type": "object",
                    "properties": {
                        "name": {"type": "string"},
                        "type": {"type": "string"},
                    },
                    "required": ["name", "type"],
                },
            },
        },
        "required": ["entities"],
    },
)

# 检查 schema 校验结果
if result["result"]["parse_status"] == "schema_invalid":
    errors = result["result"]["validation_errors"]  # ["'name' is a required property"]
```

### 7.6 完整方法列表

| 方法 | HTTP | 说明 |
|------|------|------|
| `submit(domain, stage, **kw)` | POST /tasks | 异步提交，返回 task_id |
| `execute(domain, stage, **kw)` | POST /execute | 同步执行，返回完整结果 |
| `get_task(task_id)` | GET /tasks/{id} | 查任务详情 |
| `get_result(task_id)` | GET /tasks/{id}/result | 查解析结果 |
| `get_attempts(task_id)` | GET /tasks/{id}/attempts | 查所有尝试 |
| `get_events(task_id)` | GET /tasks/{id}/events | 查事件流水 |
| `cancel(task_id)` | POST /tasks/{id}/cancel | 取消任务 |
| `close()` | — | 关闭 httpx 连接 |

## 8. 配置

所有配置通过 `LLM_SERVICE_` 前缀的环境变量（或 `.env` 文件）：

| 变量 | 默认值 | 说明 |
|------|--------|------|
| `LLM_SERVICE_HOST` | `0.0.0.0` | 绑定地址 |
| `LLM_SERVICE_PORT` | `8900` | 端口 |
| `LLM_SERVICE_DB_PATH` | `data/llm_service.sqlite` | 数据库路径（自动创建） |
| `LLM_SERVICE_PROVIDER_BASE_URL` | `https://api.deepseek.com` | LLM API 地址 |
| `LLM_SERVICE_PROVIDER_API_KEY` | — | API Key（**必填**） |
| `LLM_SERVICE_PROVIDER_MODEL` | `deepseek-chat` | 模型名 |
| `LLM_SERVICE_PROVIDER_TIMEOUT` | `30` | Provider 请求超时（秒） |
| `LLM_SERVICE_PROVIDER_BYPASS_PROXY` | `false` | 绕过系统代理 |
| `LLM_SERVICE_WORKER_CONCURRENCY` | `4` | Worker 并发数 |
| `LLM_SERVICE_DEFAULT_MAX_ATTEMPTS` | `3` | 最大重试次数 |
| `LLM_SERVICE_RETRY_BACKOFF_BASE` | `2.0` | 退避基数 |
| `LLM_SERVICE_RETRY_BACKOFF_MAX` | `60.0` | 退避上限（秒） |
| `LLM_SERVICE_LEASE_DURATION` | `300` | Worker 租约（秒） |
| `LLM_SERVICE_EXECUTE_TIMEOUT` | `60` | 同步执行超时（秒） |

## 9. 快速启动

```bash
# 1. 安装依赖
pip install -e .

# 2. 配置（在项目根目录 .env 中）
export LLM_SERVICE_PROVIDER_API_KEY=sk-your-key

# 3. 启动（启动 worker + lease recovery）
python -m llm_service

# 4. 验证
curl http://localhost:8900/health

# 5. 看板
# 浏览器访问 http://localhost:8900/dashboard

# 6. 测试
pytest llm_service/tests/ -v
```

## 10. 当前状态

### 已完成

- 同步 `/execute` + 异步 `/tasks` 双模式调用
- 后台 Worker（并发 4）+ LeaseRecovery
- 幂等控制（idempotency_key）
- 模板系统（string.Template + JSON Schema 注入）
- 三重 JSON 输出保障（prompt 注入 + response_format + jsonschema 校验）
- 自动重试 + 指数退避
- 6 张表完整审计链
- Web 监控看板
- 84 个测试用例全绿
- OpenAI 兼容 Provider（DeepSeek / Qwen / Ollama 等）
- Python SDK（`LLMClient`）

### 已知限制

- 单 SQLite 数据库（WAL 模式，当前并发场景够用）
- 无流式输出 / WebSocket 通知
- 无批量 API（需逐个提交）

## 11. 相关文档

- [快速上手指南](./QUICKSTART.md) — 从安装到使用的完整步骤
- [数据库 Schema](../databases/agent_llm_runtime/schemas/001_agent_llm_runtime.sqlite.sql)
- [Swagger 文档](http://localhost:8900/docs) — 启动服务后可访问
