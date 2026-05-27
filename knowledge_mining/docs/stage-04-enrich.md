# Stage 4 — Enrich 语义增强

> 审查文档 | 2026-05-21

---

## 1. 职责概述

Enrich 阶段负责：
1. 对每个 Segment 调用 LLM 进行深度理解
2. 提取实体引用 (entity_refs): 命令名、网元名、参数名等
3. 分类语义角色 (semantic_role): 概念、参数、示例、步骤等
4. 评估内容质量 (content_assessment): 是否有实质内容、是否为导航性文本
5. 推断文档类型 (document_type)

**关键特性**：
- 这是 pipeline 中第一个 LLM 调用阶段（I/O 密集）
- 通过 `StreamingPipeline` 多 worker 并发执行
- LLM 调用失败时**静默降级**：返回原始 segment，不中断 pipeline
- 使用异步提交 + 轮询模式与 LLM Service 交互

---

## 2. 输入与输出

### 输入
| 参数 | 类型 | 说明 |
|------|------|------|
| `segments` | `list[RawSegmentData]` | Segment 阶段产出的分段列表 |
| `profile` | `DomainProfile` (构造时) | 领域配置，含 entity_types 和 semantic_roles |

### 输出
```python
list[RawSegmentData]  # 同样数量，但字段已更新
```

### 更新的字段

| 字段 | 更新方式 | 说明 |
|------|----------|------|
| `semantic_role` | LLM 赋值 | "unknown" → "concept" / "parameter" / ... |
| `entity_refs_json` | LLM 提取 | [] → [{"type": "command", "name": "display version"}] |
| `metadata_json.llm_document_type` | LLM 推断 | 文档类型推断结果 |
| `metadata_json.content_assessment` | LLM 评估 | {is_substantive, is_navigation, assessment_reason} |

---

## 3. LLM 交互模式

### 3.1 架构

```
LlmEnricher (mining pipeline)
    ↕ HTTP
LlmClient (llm_client.py)
    ↕ HTTP
LLM Service (独立微服务, port 8900)
    ↕
LLM Provider (OpenAI-compatible API)
```

### 3.2 三阶段流程 (`enrich_batch`)

```
Phase 1: Submit — 批量提交所有 segment
  for idx, seg in enumerate(segments):
    task_id = client.submit_task(
      template_key="mining-segment-understanding",
      input={text, section_title, block_type},
      knowledge_domain=...,
      pipeline_stage="enrich",
      expected_output_type="json_object",
    )
    seg_tasks[idx] = task_id

Phase 2: Poll — 并发轮询所有任务
  llm_raw = client.poll_all(seg_tasks)

Phase 3: Apply — 将结果应用到 segment
  for idx, seg in enumerate(segments):
    if idx in llm_results:
      → _apply_llm_result(seg, result)
    else:
      → 原样返回 seg
```

### 3.3 LLM 模板输入

```json
{
  "text": "SMF 支持通过 CLI 命令进行配置...",
  "section_title": "SMF 配置指南",
  "block_type": "paragraph"
}
```

### 3.4 LLM 预期输出

```json
{
  "entities": [
    {"type": "command", "name": "display version"},
    {"type": "network_element", "name": "SMF"}
  ],
  "semantic_role": "concept",
  "document_type": "feature",
  "content_assessment": {
    "is_substantive": true,
    "is_navigation": false,
    "assessment_reason": "包含具体命令和参数说明"
  }
}
```

---

## 4. LlmClient 通信细节 (llm_client.py, 292 行)

### 4.1 连接管理

```python
class LlmClient:
    _base_url: str              # 默认 "http://localhost:8900"
    _timeout: int               # 默认 60s
    _bypass_proxy: bool         # 代理绕过
    _client: httpx.Client       # 复用连接
```

- 使用 httpx **同步**客户端（mining pipeline 是同步的）
- 单个 Client 实例复用，避免 TCP 重连开销
- `bypass_proxy=True` 时使用 `httpx.HTTPTransport()` 不走代理

### 4.2 API 端点

| 方法 | 端点 | 用途 |
|------|------|------|
| `submit_task` | `POST /api/v1/tasks` | 异步提交任务 |
| `poll_result` | `GET /api/v1/tasks/{id}` + `GET /api/v1/tasks/{id}/result` | 轮询单个任务 |
| `check_status` | `GET /api/v1/tasks/{id}` | 非阻塞状态检查 |
| `fetch_result` | `GET /api/v1/tasks/{id}/result` | 获取已完成任务结果 |
| `poll_all` | 组合 check_status + fetch_result | 并发轮询多个任务 |
| `execute` | `POST /api/v1/execute` | 同步执行 (未在 enrich 使用) |
| `register_template` | `POST /api/v1/templates` | 注册 prompt 模板 |
| `health_check` | `GET /health` | 健康检查 |

### 4.3 poll_all 循环机制

```python
pending = dict(task_ids)  # 所有待查询任务
while pending:
    still_pending = {}
    for key, task_id in pending.items():
        status = check_status(task_id)
        if status == "succeeded":
            result = fetch_result(task_id)
            results[key] = result
        elif status in ("failed", "dead_letter", "cancelled"):
            pass  # 丢弃
        else:  # queued / running / None(HTTP 错误)
            still_pending[key] = task_id
    pending = still_pending
    if pending:
        time.sleep(poll_interval)  # 默认 1s
```

**关键特性**：
- **无超时上限**：会一直轮询直到所有任务完成
- **HTTP 错误不放弃**：`check_status` 返回 None 时继续等待（LLM 服务暂时不可达）
- **顺序轮询**：虽然称为 "concurrent"，实际是 for 循环顺序检查所有 pending 任务
- 失败/死信/取消的任务直接丢弃，不会重试

### 4.4 提交 payload

```json
{
  "caller_service": "mining",
  "knowledge_domain": "cloud_core_network",
  "pipeline_stage": "enrich",
  "template_key": "mining-segment-understanding",
  "max_attempts": 3,
  "input": { "text": "...", "section_title": "...", "block_type": "..." },
  "expected_output_type": "json_object"
}
```

---

## 5. 结果应用 (`_apply_llm_result`)

### 5.1 实体引用过滤

```python
entity_refs = [
    {"type": e.get("type", "unknown"), "name": e.get("name", "")}
    for e in entities
    if e.get("name")
    and (not allowed_entity_types or e.get("type") in allowed_entity_types)
]
```

- `allowed_entity_types` 来自 `DomainProfile.entity_types`
- 如果 profile 未定义 entity_types（空 frozenset），则**不过滤**，接受所有类型
- 实体去重：基于 `(type, name)` 元组去重，合并到已有 entity_refs_json

### 5.2 语义角色校验

```python
if role and role in valid_roles and role != seg.semantic_role:
    changes["semantic_role"] = role
```

- `valid_roles` 来自 `DomainProfile.semantic_roles` 或全局 `VALID_SEMANTIC_ROLES`
- LLM 返回的角色不在合法集合中 → 忽略，保持原值
- 与原值相同 → 不更新（避免不必要的对象重建）

### 5.3 内容评估

```python
content_assessment = {
    k: v for k, v in assessment.items()
    if k in ("is_substantive", "is_navigation", "assessment_reason")
}
```

- 只保留三个字段，丢弃 LLM 可能返回的其他字段
- 存入 `metadata_json.content_assessment`

### 5.4 不可变更新

`RawSegmentData` 是 frozen dataclass，更新时创建新实例：

```python
return RawSegmentData(
    document_key=seg.document_key,      # 不变
    segment_index=seg.segment_index,    # 不变
    ...
    semantic_role=changes.get("semantic_role", seg.semantic_role),  # 可能变
    entity_refs_json=changes.get("entity_refs_json", seg.entity_refs_json),  # 可能变
    metadata_json=changes.get("metadata_json", seg.metadata_json),  # 可能变
)
```

无变化时 (`not changes`) 直接返回原对象。

---

## 6. 配置参数

| 参数 | 来源 | 默认值 | 说明 |
|------|------|--------|------|
| `base_url` | `LlmEnricher.__init__` | `"http://localhost:8900"` | LLM Service 地址 |
| `bypass_proxy` | `LlmEnricher.__init__` | `False` | 是否绕过代理 |
| `knowledge_domain` | `LlmEnricher.__init__` | profile.domain_id | 知识领域标识 |
| `profile` | `LlmEnricher.__init__` | `None` | DomainProfile (含 entity_types, semantic_roles) |
| `poll_interval` | `poll_all` | `1.0` | 轮询间隔(秒) |
| `max_attempts` | `submit_task` | `3` | LLM 服务端重试次数 |

**domain.yaml 中的相关配置**:

```yaml
mining:
  semantic_roles:
    - concept
    - parameter
    - example
    - note
    - procedure_step
    - troubleshooting_step
    - constraint
    - alarm
    - checklist
```

---

## 7. 关联文件清单

| 文件 | 行数 | 职责 |
|------|------|------|
| `mining/stages/enrich/__init__.py` | 162 | LlmEnricher + _apply_llm_result |
| `mining/infra/llm_client.py` | 292 | LlmClient — 同步 HTTP 客户端 |
| `mining/contracts/models.py:51` | — | `VALID_SEMANTIC_ROLES` 常量 |
| `mining/contracts/models.py:261` | — | `RawSegmentData` 数据类 |
| `mining/infra/domain_pack.py` | — | DomainProfile (semantic_roles, entity_types) |
| `mining/pipeline.py` | — | enrich_stage() 调用 enricher.enrich_batch() |

---

## 8. 工业化参考

| 参考 | 说明 |
|------|------|
| LangChain `LLMChain` | 类似的 LLM 调用 + 结果应用模式 |
| LlamaIndex `LLMExtractor` | 从文本中提取结构化信息 |
| Instructor (jxnl) | 用 Pydantic schema 约束 LLM 输出格式 |
| Azure OpenAI `Function Calling` | 结构化输出，我们用 json_object + 手动解析 |
| Unstructured.io `partition()` 的 element metadata | 类似的类型/角色标注 |
| Haystack `Extractor` | 命名实体识别 pipeline 组件 |

---

## 9. 当前不足

1. **poll_all 无超时**: 没有全局超时上限，如果 LLM 服务挂了某个任务永远不返回，pipeline 会永远阻塞
2. **轮询是顺序而非并发**: `poll_all` 的 for 循环是顺序的，N 个 pending 任务每轮发 N 次 HTTP 请求，不如用 ThreadPoolExecutor 真正并发
3. **LLM 失败静默降级**: Segment 的 enrich 失败时原样返回，但没有任何标记告知下游"此 segment 未被 enrich"。下游无法区分 "role=unknown 是 LLM 说它真是 unknown" 还是 "LLM 没调用成功"
4. **无重试机制**: LLM 提交失败直接跳过该 segment，不会重试
5. **entity 过滤逻辑**: `allowed_entity_types` 为空 frozenset 时不过滤，意味着无 profile 时接受 LLM 返回的所有实体类型，可能导致噪声
6. **结果解析脆弱**: 直接用 `result.get("entities", [])` 取 dict 值，如果 LLM 返回格式不匹配（如 entities 是字符串），会在后续 `e.get("name")` 报错
7. **content_assessment 未被使用**: enrich 写入了 `is_substantive` / `is_navigation`，但后续 stage（segment、retrieval_units）并未读取这些信息来做过滤
8. **template_key 硬编码**: `"mining-segment-understanding"` 写死在代码中，不支持 domain 级别的模板定制
9. **无 batch API**: 每个段落数据单独提交一个 LLM 任务，大量分段时请求数爆炸
10. **httpx Client 在错误时重建**: `close()` 后下次调用自动重建，但连续错误时频繁创建/销毁连接
11. **knowledge_domain 可能是 None**: 如果 profile 和显式参数都没提供，`knowledge_domain` 为 None，传到 LLM Service 变成 "unknown"
