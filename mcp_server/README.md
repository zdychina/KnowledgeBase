# Cloud Core Knowledge MCP Server

云核心网知识证据底座 MCP Server。通过 MCP 协议暴露 serving 后端的检索和证据评估能力，供任意 Agent 接入。

## 前提

- Python 3.10+
- serving 后端正在运行（默认 `http://127.0.0.1:8000`）
- 依赖：`pip install "mcp>=1.0,<2.0" httpx`

## 两种运行模式

### 模式 1：stdio（Claude Code 本地集成）

```bash
python -m mcp_server
# 等同于
python -m mcp_server --transport stdio
```

Claude Code 通过 `.mcp.json` 自动启动，无需手动运行。

### 模式 2：HTTP（内网暴露，供其他 Agent / Postman 使用）

```bash
python -m mcp_server --transport streamable-http --port 9000
```

输出：
```
MCP Server starting on http://0.0.0.0:9000 (transport=streamable-http)
```

此时内网其他机器可通过 `http://<你的IP>:9000/mcp` 接入。

也可以用环境变量：

```bash
MCP_TRANSPORT=streamable-http MCP_PORT=9000 python -m mcp_server
```

## 给其他人的接入信息

你只需要告诉对方以下信息：

```
MCP Server 地址：http://<你的内网IP>:9000/mcp
Transport 类型：streamable-http
协议版本：2024-11-05
```

对方 Agent 的 MCP Client 配置示例（以 Claude Desktop 为例，编辑 `claude_desktop_config.json`）：

```json
{
  "mcpServers": {
    "cloud-core-knowledge": {
      "url": "http://192.168.x.x:9000/mcp",
      "transport": "streamable-http"
    }
  }
}
```

如果对方的 MCP Client 是代码形式（mcp SDK）：

```python
from mcp.client.streamable_http import streamablehttp_client

async with streamablehttp_client("http://192.168.x.x:9000/mcp") as (read, write, _):
    async with ClientSession(read, write) as session:
        await session.initialize()
        result = await session.call_tool("health_check")
```

## Postman 测试

MCP 协议是 JSON-RPC over HTTP，每个请求是 `POST /mcp`。

### 关键约束

1. **Headers 必须包含**：
   - `Content-Type: application/json`
   - `Accept: application/json, text/event-stream`

2. **Session 机制**：第一次 `initialize` 返回的响应头中有 `Mcp-Session-Id`，后续所有请求必须带上这个 Header。

### 步骤 1：初始化会话

```
POST http://127.0.0.1:9000/mcp
Content-Type: application/json
Accept: application/json, text/event-stream
```

Body (raw JSON):
```json
{
  "jsonrpc": "2.0",
  "id": 1,
  "method": "initialize",
  "params": {
    "protocolVersion": "2024-11-05",
    "capabilities": {},
    "clientInfo": {
      "name": "postman-test",
      "version": "1.0"
    }
  }
}
```

响应头中找到 `Mcp-Session-Id`，复制其值（如 `257fd3e5f2ad45c7ab715d4d3c3246d8`）。

响应体（SSE 格式，`data:` 行后面是 JSON）：
```json
{
  "jsonrpc": "2.0",
  "id": 1,
  "result": {
    "protocolVersion": "2024-11-05",
    "capabilities": { ... },
    "serverInfo": {
      "name": "cloud-core-knowledge",
      "version": "1.27.1"
    },
    "instructions": "云核心网知识证据底座 MCP Server。..."
  }
}
```

### 步骤 2：查看可用工具

```
POST http://127.0.0.1:9000/mcp
Content-Type: application/json
Accept: application/json, text/event-stream
Mcp-Session-Id: <步骤1拿到的Session-ID>
```

Body:
```json
{
  "jsonrpc": "2.0",
  "id": 2,
  "method": "tools/list",
  "params": {}
}
```

### 步骤 3：调用 health_check

```
POST http://127.0.0.1:9000/mcp
Mcp-Session-Id: <Session-ID>
```

Body:
```json
{
  "jsonrpc": "2.0",
  "id": 3,
  "method": "tools/call",
  "params": {
    "name": "health_check",
    "arguments": {}
  }
}
```

### 步骤 4：调用 search_knowledge

```json
{
  "jsonrpc": "2.0",
  "id": 4,
  "method": "tools/call",
  "params": {
    "name": "search_knowledge",
    "arguments": {
      "query": "什么是业务感知",
      "domain": "cloud_core_network"
    }
  }
}
```

### 步骤 5：调用 evaluate_evidence

用步骤 4 返回的 `items` 构造摘要：

```json
{
  "jsonrpc": "2.0",
  "id": 5,
  "method": "tools/call",
  "params": {
    "name": "evaluate_evidence",
    "arguments": {
      "items_summary": [
        {"evidence_role": "direct_answer", "score": 0.92, "semantic_role": "concept"},
        {"evidence_role": "support", "score": 0.78, "semantic_role": "constraint"}
      ],
      "intent": "concept_lookup",
      "query": "什么是业务感知"
    }
  }
}
```

### 步骤 6：读取资源（可选）

```json
{
  "jsonrpc": "2.0",
  "id": 6,
  "method": "resources/read",
  "params": {
    "uri": "evidence://semantic-rules"
  }
}
```

## 环境变量

| 变量 | 默认值 | 说明 |
|------|--------|------|
| `SERVING_URL` | `http://127.0.0.1:8000` | serving 后端地址 |
| `HEALTH_TIMEOUT` | `5.0` | health 请求超时（秒） |
| `SEARCH_TIMEOUT` | `60.0` | search 请求超时（秒） |
| `MCP_TRANSPORT` | `stdio` | 传输模式 |
| `MCP_HOST` | `0.0.0.0` | HTTP 绑定地址 |
| `MCP_PORT` | `9000` | HTTP 绑定端口 |

## 可用工具

| 工具 | 用途 |
|------|------|
| `health_check` | 检查 serving 后端是否可用 |
| `search_knowledge` | 检索知识库，返回结构化证据包 |
| `evaluate_evidence` | 纯规则评估证据充分性 |

## 典型调用顺序

```
1. health_check() → 确认后端可用
2. search_knowledge(query="...") → 获取证据包
3. evaluate_evidence(items_summary=..., intent=..., query=...) → 评估是否足够回答
4. 根据评估结果（answer_now / answer_with_caution / ask_followup）决定如何回答
```
