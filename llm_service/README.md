# LLM Service — 方案架构文档

> 统一 LLM 调用与审计服务，为 Mining / Serving 提供集中式的模型调用能力。
> 版本：v1.1（生产就绪）| 数据库：agent_llm_runtime（6 张表）| 端口：8900

## 1. 系统定位

LLM Service 是一个**独立运行的 FastAPI 服务**，拥有自己的 SQLite 数据库（WAL 模式）。

**核心职责：**统一管理所有 LLM 调用的提交、执行、重试、结果解析和审计记录。Mining 和 Serving 不各自维护 LLM 调用逻辑，而是通过 `LLMClient` 或 HTTP API 调用本服务。

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
├── main.py                 # FastAPI 入口，初始化服务和组件
├── config.py               # 环境变量配置（LLM_SERVICE_* 前缀）
├── models.py               # API 请求/响应数据模型
├── db.py                   # SQLite 连接管理，DDL 从共享 SQL 文件加载
├── client.py               # Python LLMClient（Mining/Serving 调用入口）
│
├── runtime/
│   ├── service.py          # 顶层编排器：模板解析、任务提交/执行、响应构建
│   ├── task_manager.py     # 任务生命周期：提交、认领、完成、失败、取消
│   ├── executor.py         # 执行引擎：重试循环、调用 Provider、记录尝试
│   ├── worker.py           # 后台 Worker 进程：从队列获取任务并执行
│   ├── lease_recovery.py   # 租约恢复：处理超时任务（Worker 崩溃场景）
│   ├── event_bus.py        # 事件总线：记录任务状态变更事件
│   ├── template_registry.py# 模板注册表：Jinja2 模板管理
│   ├── parser.py           # 输出解析器：text / json_object / json_array
│   └── idempotency.py      # 幂等控制：基于 idempotency_key 防重复
│
├── providers/
│   ├── base.py             # ProviderProtocol 接口定义
│   ├── openai_compatible.py# OpenAI 兼容实现（DeepSeek、通义千问等）
│   └── mock.py             # Mock Provider（测试用）
│
├── api/
│   ├── tasks.py            # 任务 API：提交、查询、取消
│   ├── results.py          # 结果查询 API
│   ├── health.py           # 健康检查
│   └── templates.py        # 模板 CRUD API
│
├── dashboard/              # Web 监控看板（任务统计、调试）
├── templates/              # 内置 prompt 模板定义
└── tests/                  # 79 个测试用例
```

## 3. 数据流

### 3.1 同步执行（`execute()`）— Serving 场景

```
Client.execute()
  → POST /api/v1/execute
  → LLMService.submit()：创建任务（如已存在则复用）
  → 原子认领（atomic claim）
  → Executor.run()：
      → 构建 messages（模板 or 原始）
      → Provider.chat()：调用外部 LLM
      → Parser.parse()：解析输出
      → 记录 attempt + result + event
  → 构建 ExecuteResponse 返回
```

### 3.2 异步提交（`submit()`）— Mining 场景

```
Client.submit()
  → POST /api/v1/tasks
  → LLMService.submit()：幂等检查 → 创建任务到队列
  → 后台 Worker 循环：
      → TaskManager.claim()：获取任务
      → Executor.run()：执行（含重试）
      → 持久化到数据库
  → Client 轮询 get_result() 获取最终结果
```

## 4. 数据库设计（agent_llm_runtime，6 张表）

### 4.1 表结构与映射

| 表 | 职责 | 关键列 | 对应代码模块 |
|----|------|--------|-------------|
| `agent_llm_prompt_templates` | Prompt 模板管理 | template_key, version, system_prompt, user_prompt_template, output_schema | `template_registry.py` |
| `agent_llm_tasks` | 任务主表 | caller_domain, pipeline_stage, status, priority, idempotency_key, attempt_count | `task_manager.py` |
| `agent_llm_requests` | 请求参数 | task_id, provider, model, messages_json, input_json, params_json | `executor.py` |
| `agent_llm_attempts` | 每次调用尝试 | task_id, attempt_no, raw_output_text, tokens, latency_ms, error_type | `executor.py` |
| `agent_llm_results` | 解析结果 | task_id, parse_status, parsed_output_json, validation_errors | `parser.py` |
| `agent_llm_events` | 事件流水 | task_id, event_type(7种), message, created_at | `event_bus.py` |

### 4.2 任务状态机

```
queued → running → succeeded
                  → failed → (重试) → queued → ...
                  → dead_letter（耗尽 max_attempts）
         → cancelled
```

### 4.3 关键索引

- `(status, priority, created_at)` — 优先级队列查询
- `(task_id, attempt_no)` UNIQUE — 尝试有序
- `(task_id, created_at)` — 事件时间线

## 5. 关键设计决策

### 5.1 双模式调用

| 模式 | 方法 | 适用场景 | 行为 |
|------|------|---------|------|
| 同步 | `execute()` | Serving 在线查询 | 阻塞等待结果，超时 60s |
| 异步 | `submit()` | Mining 批量处理 | 返回 task_id，后台 Worker 执行 |

### 5.2 幂等控制

提交时可带 `idempotency_key`。相同 key 不创建新任务。优先级链：

```
succeeded > running > queued（返回已有的）> 允许新建
failed / dead_letter 不阻塞新提交
```

### 5.3 重试与退避

- 指数退避：`base ^ attempt_no`，上限 `backoff_max`
- 默认 3 次重试
- 所有尝试记录在 `agent_llm_attempts` 表
- 错误分类：timeout / connection_error / rate_limited / server_error / client_error

### 5.4 模板系统

- Jinja2 语法：`$variable` 占位符，`safe_substitute` 替换
- 模板状态管理：draft → active → archived
- 支持版本号：`(template_key, template_version)` UNIQUE
- 输出约束：`expected_output_type` + `output_schema_json`

### 5.5 输出解析

| 输出类型 | 处理方式 |
|---------|---------|
| `json_object` | 解析 JSON，可选 JSON Schema 校验，自动去 ````json` 标记 |
| `json_array` | 解析 JSON 数组 |
| `text` | 原样返回 |

### 5.6 不可变数据模式

所有内部 dataclass 使用 `frozen=True`，防止副作用，确保并发安全。

## 6. API 接口

| 方法 | 路径 | 说明 |
|------|------|------|
| GET | `/health` | 健康检查 |
| POST | `/api/v1/tasks` | 异步提交任务 |
| POST | `/api/v1/execute` | 同步执行（等结果） |
| GET | `/api/v1/tasks/{id}` | 查任务详情 |
| POST | `/api/v1/tasks/{id}/cancel` | 取消任务 |
| GET | `/api/v1/tasks/{id}/result` | 查解析结果 |
| GET | `/api/v1/tasks/{id}/attempts` | 查所有尝试 |
| GET | `/api/v1/tasks/{id}/events` | 查事件流水 |
| GET | `/dashboard` | Web 看板 |
| GET | `/dashboard/api/stats` | 统计 JSON |

## 7. 配置

所有配置通过 `LLM_SERVICE_` 前缀的环境变量：

| 变量 | 默认值 | 说明 |
|------|--------|------|
| `LLM_SERVICE_HOST` | `0.0.0.0` | 绑定地址 |
| `LLM_SERVICE_PORT` | `8900` | 端口 |
| `LLM_SERVICE_DB_PATH` | `data/llm_service.sqlite` | 数据库路径 |
| `LLM_SERVICE_PROVIDER_BASE_URL` | `https://api.deepseek.com` | LLM API 地址 |
| `LLM_SERVICE_PROVIDER_API_KEY` | — | API Key（必填） |
| `LLM_SERVICE_PROVIDER_MODEL` | `deepseek-chat` | 模型名 |
| `LLM_SERVICE_DEFAULT_MAX_ATTEMPTS` | `3` | 最大重试次数 |
| `LLM_SERVICE_LEASE_DURATION` | `300` | Worker 租约（秒） |
| `LLM_SERVICE_EXECUTE_TIMEOUT` | `60` | 同步执行超时（秒） |

## 8. 快速启动

```bash
# 1. 安装依赖
pip install -e .

# 2. 配置
export LLM_SERVICE_PROVIDER_API_KEY=sk-your-key

# 3. 启动
python -m llm_service

# 4. 验证
curl http://localhost:8900/health

# 5. 看板
浏览器访问 http://localhost:8900/dashboard

# 6. 测试（79 个用例）
pytest llm_service/tests/ -v
```

## 9. Mining / Serving 集成示例

### Mining（异步批量）

```python
from llm_service.client import LLMClient
llm = LLMClient()

# 批量提交
task_ids = [await llm.submit(
    caller_domain="mining",
    pipeline_stage="question_gen",
    template_key="mining-question-gen",
    input={"title": seg.title, "content": seg.text},
    idempotency_key=f"seg-{seg.id}-qgen",
) for seg in segments]

# 批量轮询结果
results = [await llm.get_result(tid) for tid in task_ids]
```

### Serving（同步在线）

```python
result = await llm.execute(
    caller_domain="serving",
    pipeline_stage="query_rewrite",
    template_key="serving-query-understanding",
    input={"query": user_query},
    expected_output_type="json_object",
)
rewritten = result["result"]["parsed_output"]["rewritten_query"]
```

## 10. 当前状态（v1.1）

### 已完成

- 同步/异步双模式调用
- 任务队列 + 后台 Worker
- 幂等控制（idempotency_key）
- 模板系统（Jinja2 + JSON Schema）
- 自动重试 + 指数退避
- 6 张表完整审计链
- Web 监控看板
- 79 个测试用例全覆盖
- 多 Provider 支持（DeepSeek / OpenAI / 通义千问 / Ollama）
- caller_context 约定（build_id / ref 追溯）

### 已知限制

- 单 SQLite 数据库，高并发可能成为瓶颈
- 单 Worker 进程，并发能力有限
- 无批量 API（需逐个提交）
- 无流式输出支持
- 无 WebSocket 实时通知

## 11. v1.2 演进方向

### 11.1 架构增强

| 方向 | 当前 | 目标 |
|------|------|------|
| 存储层 | SQLite 单文件 | 可迁移 PostgreSQL |
| 并发模型 | 单 Worker | 多 Worker + 连接池 |
| 模板管理 | 代码内置 | 数据库存储 + 动态加载 |
| 监控 | 简单 Web 看板 | Prometheus 指标 + 告警 |

### 11.2 功能增强

- **批量 API**：一次提交多个任务，减少 HTTP 往返
- **流式输出**：支持 SSE streaming 返回
- **模型路由**：根据 pipeline_stage 自动路由到不同模型
- **优先级动态调整**：运行时调整任务优先级
- **成本统计**：Token 用量和费用追踪

### 11.3 可靠性增强

- **租约恢复优化**：更精确的 Worker 崩溃检测
- **任务依赖**：支持任务间前置依赖关系
- **优雅关闭**：Worker 停止前完成当前任务

## 12. 新增 Provider 指南

1. 在 `providers/` 下创建新文件，实现 `ProviderProtocol` 接口
2. 实现 `chat(messages, model, params) -> ProviderResponse` 方法
3. 在 `config.py` 中添加对应的环境变量
4. 在 `executor.py` 中注册新 Provider
5. 添加对应测试

## 13. 相关文档

- [数据库 Schema](../databases/agent_llm_runtime/schemas/001_agent_llm_runtime.sqlite.sql)
- [集成指南](../docs/integration/llm-service-integration-guide.md)
- [快速上手](./QUICKSTART.md)
- [架构演示](../docs/architecture/coremasterkb-v1.2-architecture.html)
