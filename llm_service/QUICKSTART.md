# LLM Service 快速上手指南

## 概述

独立的 LLM 调用服务，FastAPI 进程，端口 8900。
- 支持任意 OpenAI 兼容接口（DeepSeek / OpenAI / 通义千问 / 硅基流动 / Ollama 等）
- 同步调用（等结果）+ 异步提交（后台执行）
- Prompt 模板管理（模板展开后发给模型）
- Web 看板，可查看每次调用的完整 prompt、结果、token 用量
- 所有数据存本地 SQLite，自动建库建表

## 目录结构

```
llm_service/
├── main.py              # 入口，启动 FastAPI
├── config.py            # 配置（从 .env 或环境变量读取）
├── db.py                # 数据库初始化
├── client.py            # Python SDK（Mining/Serving 接入用）
├── runtime/
│   ├── service.py       # 核心服务：提交、执行、模板解析
│   ├── worker.py        # 后台 Worker + LeaseRecovery
│   ├── task_manager.py  # 任务生命周期
│   ├── executor.py      # 执行器（调 provider）
│   ├── parser.py        # 输出解析（JSON/文本）
│   ├── event_bus.py     # 事件记录
│   └── template_registry.py  # 模板 CRUD
├── api/                 # REST API 路由
├── dashboard/           # Web 看板
└── templates/           # Jinja2 HTML 模板
```

## 1. 安装依赖

在项目根目录执行：

```bash
pip install fastapi uvicorn aiosqlite pydantic-settings httpx jsonschema jinja2
```

或者如果项目有 pyproject.toml：

```bash
pip install -e ".[llm]"
```

## 2. 配置 Provider

在项目根目录的 `.env` 文件中设置这三个必填项：

```
LLM_SERVICE_PROVIDER_API_KEY=你的API密钥
LLM_SERVICE_PROVIDER_BASE_URL=接口地址
LLM_SERVICE_PROVIDER_MODEL=模型名称
```

### 各平台配置示例

#### DeepSeek（默认，不用改 BASE_URL）

```
LLM_SERVICE_PROVIDER_API_KEY=sk-xxxxxxxxxxxx
LLM_SERVICE_PROVIDER_BASE_URL=https://api.deepseek.com
LLM_SERVICE_PROVIDER_MODEL=deepseek-chat
```

#### OpenAI

```
LLM_SERVICE_PROVIDER_API_KEY=sk-xxxxxxxxxxxx
LLM_SERVICE_PROVIDER_BASE_URL=https://api.openai.com/v1
LLM_SERVICE_PROVIDER_MODEL=gpt-4o-mini
```

#### 通义千问（DashScope 兼容模式）

```
LLM_SERVICE_PROVIDER_API_KEY=sk-xxxxxxxxxxxx
LLM_SERVICE_PROVIDER_BASE_URL=https://dashscope.aliyuncs.com/compatible-mode/v1
LLM_SERVICE_PROVIDER_MODEL=qwen-plus
```

#### 硅基流动（SiliconFlow）

```
LLM_SERVICE_PROVIDER_API_KEY=sk-xxxxxxxxxxxx
LLM_SERVICE_PROVIDER_BASE_URL=https://api.siliconflow.cn/v1
LLM_SERVICE_PROVIDER_MODEL=Qwen/Qwen2.5-7B-Instruct
```

#### 本地 Ollama

```
LLM_SERVICE_PROVIDER_API_KEY=ollama
LLM_SERVICE_PROVIDER_BASE_URL=http://localhost:11434/v1
LLM_SERVICE_PROVIDER_MODEL=qwen2.5:7b
```

### 可选配置

| 环境变量 | 默认值 | 说明 |
|---------|--------|------|
| `LLM_SERVICE_PORT` | 8900 | 服务端口 |
| `LLM_SERVICE_DB_PATH` | `data/llm_service.sqlite` | 数据库路径（自动创建） |
| `LLM_SERVICE_WORKER_CONCURRENCY` | 4 | Worker 并发数 |
| `LLM_SERVICE_DEFAULT_MAX_ATTEMPTS` | 3 | 最大重试次数 |
| `LLM_SERVICE_EXECUTE_TIMEOUT` | 60 | 同步执行超时秒数 |
| `LLM_SERVICE_PROVIDER_TIMEOUT` | 30 | Provider 请求超时秒数 |
| `LLM_SERVICE_PROVIDER_BYPASS_PROXY` | false | 绕过系统代理（内网机器设 true） |

## 3. 启动服务

```bash
# 在项目根目录执行
python -m llm_service
```

看到以下输出说明启动成功：

```
INFO:     Uvicorn running on http://0.0.0.0:8900 (Press CTRL+C to quit)
```

### 数据库说明

- **位置**：`data/llm_service.sqlite`（相对于项目根目录）
- **自动创建**：首次启动时如果文件不存在，会自动创建目录和数据库文件，并建好全部 6 张表
- **想重新开始**：`rm -f data/llm_service.sqlite`，再启动服务即可

### 验证启动

```bash
curl http://localhost:8900/health
# 返回：{"status":"ok"}
```

## 4. 创建 Prompt 模板

模板定义了 system prompt、用户提示词模板和期望输出类型。

### 创建文本摘要模板

```bash
curl -X POST http://localhost:8900/api/v1/templates \
  -H "Content-Type: application/json" \
  -d '{
    "template_key": "my-summary",
    "template_version": "1",
    "purpose": "中文摘要",
    "system_prompt": "你是一个助手，用中文简洁回答。",
    "user_prompt_template": "请用一句话总结以下内容：$text",
    "expected_output_type": "text"
  }'
```

### 创建问答生成模板

```bash
curl -X POST http://localhost:8900/api/v1/templates \
  -H "Content-Type: application/json" \
  -d '{
    "template_key": "my-qa",
    "template_version": "1",
    "purpose": "生成问答对",
    "system_prompt": "你是知识挖掘助手。返回JSON格式。",
    "user_prompt_template": "根据以下内容生成问答对：$content",
    "expected_output_type": "json_object"
  }'
```

### 查看已创建的模板

```bash
curl http://localhost:8900/api/v1/templates
```

### 模板语法说明

- `user_prompt_template` 中用 `$变量名` 引用 input 中的字段
- 例如模板是 `请总结：$text`，input 是 `{"text": "内容"}`，最终发给模型的就是 `请总结：内容`
- `expected_output_type` 三种值：`text`（纯文本）、`json_object`（JSON 对象）、`json_array`（JSON 数组）
- 调用时如果不指定 `expected_output_type`，会用模板里声明的类型

## 5. 同步调用（等结果，适合在线场景）

发送请求后等模型回复，直接返回完整结果。

```bash
curl -X POST http://localhost:8900/api/v1/execute \
  -H "Content-Type: application/json" \
  -d '{
    "caller_domain": "serving",
    "pipeline_stage": "normalizer",
    "template_key": "my-summary",
    "input": {"text": "Python是一种通用编程语言，支持面向对象和函数式编程。"}
  }'
```

返回示例：

```json
{
  "task_id": "06948ea6-...",
  "status": "succeeded",
  "attempts": 1,
  "total_tokens": 156,
  "latency_ms": 2340,
  "result": {
    "parse_status": "succeeded",
    "parsed_output": null,
    "text_output": "Python是一种支持面向对象和函数式编程的通用语言。",
    "validation_errors": []
  },
  "error": null
}
```

### 不用模板，直接发 messages

```bash
curl -X POST http://localhost:8900/api/v1/execute \
  -H "Content-Type: application/json" \
  -d '{
    "caller_domain": "serving",
    "pipeline_stage": "rerank",
    "messages": [
      {"role": "system", "content": "你是一个助手。"},
      {"role": "user", "content": "什么是FastAPI？用一句话回答。"}
    ],
    "expected_output_type": "text"
  }'
```

## 6. 异步提交（后台执行，适合批量场景）

提交后立刻返回 task_id，Worker 后台自动执行。

```bash
curl -X POST http://localhost:8900/api/v1/tasks \
  -H "Content-Type: application/json" \
  -d '{
    "caller_domain": "mining",
    "pipeline_stage": "retrieval_units",
    "template_key": "my-qa",
    "input": {"content": "FastAPI是一个现代Python Web框架。"},
    "metadata": {"caller_context": {"ref_type": "section", "ref_id": "sec-001"}}
  }'
```

返回：

```json
{"task_id": "e0cd2b67-...", "status": "queued", "idempotency_key": null, "created_at": "..."}
```

### 查看任务状态

```bash
# 把上面返回的 task_id 填进去
curl http://localhost:8900/api/v1/tasks/这里填task_id
```

状态变化：`queued` → `running` → `succeeded`（成功）/ `dead_letter`（耗尽重试）

### 批量提交示例

```bash
# 循环提交多个任务
for i in 1 2 3; do
  curl -s -X POST http://localhost:8900/api/v1/tasks \
    -H "Content-Type: application/json" \
    -d "{
      \"caller_domain\": \"mining\",
      \"pipeline_stage\": \"retrieval_units\",
      \"template_key\": \"my-qa\",
      \"input\": {\"content\": \"第${i}段内容\"},
      \"metadata\": {\"caller_context\": {\"ref_type\": \"section\", \"ref_id\": \"sec-00${i}\"}}
    }" | python -m json.tool
  echo "---"
done
```

## 7. 查看结果

### 通过 API

```bash
# 任务信息
curl http://localhost:8900/api/v1/tasks/这里填task_id

# 执行结果
curl http://localhost:8900/api/v1/tasks/这里填task_id/result

# 每次尝试详情
curl http://localhost:8900/api/v1/tasks/这里填task_id/attempts

# 事件时间线
curl http://localhost:8900/api/v1/tasks/这里填task_id/events
```

### 通过数据库

```bash
sqlite3 data/llm_service.sqlite

# 查看所有任务
SELECT substr(id,1,8) as id, status, caller_domain, pipeline_stage, attempt_count
FROM agent_llm_tasks ORDER BY created_at;

# 查看解析结果
SELECT substr(task_id,1,8), parse_status, text_output
FROM agent_llm_results;

# 查看原始模型输出
SELECT substr(task_id,1,8), raw_output_text FROM agent_llm_attempts
WHERE status='succeeded';

# 查看 token 用量
SELECT substr(task_id,1,8), total_tokens, latency_ms FROM agent_llm_attempts;

.quit
```

### 通过 Web 看板

浏览器打开：

| 页面 | 地址 |
|------|------|
| 看板首页 | http://localhost:8900/dashboard |
| API 文档 | http://localhost:8900/docs |
| 健康检查 | http://localhost:8900/health |

看板首页展示任务列表、状态筛选、token 统计。
点击任意 task_id 进入详情页，可以看到：
- **Request Config**：用了哪个模板、Provider、模型
- **Input Data**：传入的参数
- **Actual Prompt Sent to Model**：模板展开后发给模型的完整 prompt（含 system/user role）
- **Result**：模型输出（JSON 或文本），parse_status 是否成功
- **Attempts**：每次尝试的 token 数和延迟
- **Event Timeline**：submitted → claimed → succeeded 完整事件链
- **Raw Output**：模型原始返回文本（可展开查看）

## 8. 关闭服务

终端 `Ctrl+C`

## 9. 常见问题

### Q: 启动报 `PROVIDER_API_KEY is required`

`.env` 文件中没设 `LLM_SERVICE_PROVIDER_API_KEY`，或者 `.env` 不在项目根目录。

### Q: 异步任务一直 queued 不执行

检查 Worker 是否正常启动。启动日志里应该有 `Worker started with 4 concurrency`。如果是用 MockProvider 测试则不会有真实执行。

### Q: parse_status 是 failed 但原始输出是对的

常见原因是模型返回了 markdown 代码块包裹的 JSON（如 `` ```json [...] ``` ``）。当前 parser 已自动剥离代码块标记。如果仍然失败，检查 `expected_output_type` 是否和模型实际输出格式匹配。

### Q: 想换数据库位置

设环境变量：
```
LLM_SERVICE_DB_PATH=/your/path/llm.sqlite
```

### Q: 数据库里 6 张表分别是干什么的

| 表名 | 作用 |
|------|------|
| `agent_llm_prompt_templates` | Prompt 模板定义 |
| `agent_llm_tasks` | 任务主表（状态、调用方、优先级） |
| `agent_llm_requests` | 请求详情（发给模型的完整 messages、input、schema） |
| `agent_llm_attempts` | 每次尝试记录（token 用量、延迟、原始输出、错误信息） |
| `agent_llm_results` | 解析结果（JSON/文本输出、schema 校验结果） |
| `agent_llm_events` | 事件流水（submitted/claimed/succeeded/failed） |
