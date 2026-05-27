# Stage 5 — Discourse 语篇关系构建

> 审查文档 | 2026-05-21

---

## 1. 职责概述

Discourse 阶段负责：
1. 为每个 Segment 分配稳定 UUID (`build_seg_ids`)
2. 使用 LLM 滑动窗口分析 segment 间的语篇关系（RST 关系）
3. 过滤低置信度和非白名单关系
4. 输出 `SegmentRelationData` 列表用于 DB 写入

**关键特性**：
- LLM 调用阶段（I/O 密集），StreamingPipeline 多 worker 并发
- 依赖 `seg_ids`（由 `build_seg_ids()` 在 pipeline.py 中提前调用）
- 使用滑动窗口避免一次性发送过多 context 给 LLM

---

## 2. 输入与输出

### 输入
| 参数 | 类型 | 说明 |
|------|------|------|
| `segments` | `list[RawSegmentData]` | enrich 阶段产出 |
| `seg_ids` | `dict[str, str]` | segment key → UUID 映射 |

### 输出
```python
list[SegmentRelationData]  # 挂载到 DocumentContext.relations
```

### SegmentRelationData 核心字段 (models.py:286)
```
source_segment_key: str     # 源 segment 的 composite key (doc_key#index)
target_segment_key: str     # 目标 segment 的 composite key
relation_type: str          # 关系类型 (elaborates, causes, enables, ...)
weight: float               # 权重 (= confidence)
confidence: float           # LLM 返回的置信度
distance: int | None        # segment 间距 (绝对值)
metadata_json: dict         # {"source": "discourse_llm", "rst_relation": "elaborates"}
```

### 辅助输出
```python
dict[str, str]  # seg_ids: {segment_key: uuid_hex} — 挂载到 DocumentContext.seg_ids
```

---

## 3. 两部分功能

### 3.1 build_seg_ids

```python
def build_seg_ids(segments: list[RawSegmentData]) -> dict[str, str]:
    return {_make_segment_key(seg): uuid.uuid4().hex for seg in segments}

def _make_segment_key(seg: RawSegmentData) -> str:
    return f"{seg.document_key}#{seg.segment_index}"
```

- 为每个 segment 生成一个稳定的 UUID
- key 格式: `"doc_key#segment_index"` → `"abc123#0"`, `"abc123#1"`, ...
- **调用时机**: 在 pipeline.py 的 `segment_stage()` 中调用，早于 discourse stage

### 3.2 DiscourseRelationBuilder

---

## 4. RST 关系映射

### 4.1 LLM 输出 → DB 关系类型

| LLM 输出 | DB relation_type | 含义 |
|----------|-----------------|------|
| `ELABORATES` | `elaborates` | 阐述/详述 |
| `EVIDENCES` | `evidences` | 证据支持 |
| `CAUSES` | `causes` | 因果关系 |
| `RESULTS_IN` | `results_in` | 导致结果 |
| `BACKGROUNDS` | `backgrounds` | 背景信息 |
| `CONDITIONS` | `conditions` | 条件关系 |
| `SUMMARIZES` | `summarizes` | 总结概括 |
| `JUSTIFIES` | `justifies` | 论证/合理化 |
| `ENABLES` | `enables` | 使能/前提条件 |
| `CONTRASTS_WITH` | `contrasts_with` | 对比关系 |
| `PARALLELS` | `parallels` | 并行/类比 |
| `SEQUENCES` | `sequences` | 时序关系 |

### 4.2 白名单过滤 (`_RST_WHITELIST`)

只保留上述 12 种关系类型。不在白名单中的 → 丢弃。

**特殊处理**：LLM 返回 `"UNRELATED"` → 跳过（不产生 relation）。

---

## 5. 滑动窗口算法

### 5.1 窗口参数

| 参数 | 默认值 | 来源 |
|------|--------|------|
| `window_size` | 15 | `DomainProfile.retrieval_policy.discourse_window_size` |
| `min_confidence` | 0.5 | `DomainProfile.retrieval_policy.min_confidence` |
| `max_distance` | 5 | `DomainProfile.retrieval_policy.max_distance` |

**参数优先级**: constructor 参数 > profile 配置 > 硬编码默认值

### 5.2 窗口滑动

```python
for start in range(0, len(content_segs), window_size - 1):
    window = content_segs[start : start + window_size]
    if len(window) < 2:
        continue
    relations.extend(_analyze_window(window))
```

- 步长 = `window_size - 1`（有 1 个 segment 重叠）
- 示例: window_size=15, 40 个 segments
  - Window 1: seg[0:15]
  - Window 2: seg[14:29]
  - Window 3: seg[28:40]

### 5.3 预过滤

```python
content_segs = [s for s in segments if s.block_type != "heading"]
if len(content_segs) < 2:
    return []
```

- 只分析内容 segment，跳过 heading block
- 少于 2 个内容 segment → 无关系

### 5.4 窗口分析 (`_analyze_window`)

```
1. 格式化窗口内 segment:
   "[0] (SMF 配置指南) SMF 支持通过 CLI 命令进行配置..."
   "[1] (参数说明) 以下参数需要注意：..."
   ...

2. 提交 LLM 任务:
   template_key = "mining-discourse-relation"
   input = {"segments": "格式化文本..."}
   expected_output_type = "json_array"

3. 轮询结果:
   poll_all({"0": task_id}) → items

4. 解析结果:
   _parse_llm_results(items, window_segments)
```

### 5.5 LLM 输入格式

```
[0] (SMF 配置指南) SMF 支持通过 CLI 命令进行配置...
[1] (参数说明) 以下参数需要注意：...
[2] (配置步骤) 步骤一：登录设备...
```

每个 segment 限制 150 字符预览 (`seg.raw_text[:150]`)，换行替换为空格。

### 5.6 LLM 预期输出 (json_array)

```json
[
  {"source": 0, "target": 1, "relation": "ELABORATES", "confidence": 0.85},
  {"source": 1, "target": 2, "relation": "SEQUENCES", "confidence": 0.7},
  {"source": 0, "target": 2, "relation": "UNRELATED", "confidence": 0.3}
]
```

---

## 6. 结果解析 (`_parse_llm_results`)

```python
for item in items:
    source_idx = item.get("source")
    target_idx = item.get("target")
    relation = item.get("relation", "other")
    confidence = float(item.get("confidence", 0.5))

    # 1. 校验索引有效性
    if source_idx is None or target_idx is None: continue
    if source_idx >= len(segments) or target_idx >= len(segments): continue

    # 2. 映射关系类型
    rst_label = str(relation).upper()
    if rst_label == "UNRELATED": continue
    db_relation = _LLM_TO_DB_RELATION.get(rst_label)
    if db_relation is None: continue

    # 3. 构造 SegmentRelationData
    source_key = _make_segment_key(segments[source_idx])
    target_key = _make_segment_key(segments[target_idx])

    SegmentRelationData(
        source_segment_key=source_key,
        target_segment_key=target_key,
        relation_type=db_relation,
        weight=confidence,
        confidence=confidence,
        distance=abs(source_idx - target_idx),
        metadata_json={"source": "discourse_llm", "rst_relation": rst_label.lower()},
    )
```

**关键逻辑**：
- `source` / `target` 是窗口内的**相对索引** (0, 1, 2, ...)
- `_make_segment_key` 用窗口内的 segment 生成全局 key
- `confidence` 直接用作 `weight`
- `distance` 是窗口内索引差（不是全局索引差）
- 无效索引越界检查防止 LLM 幻觉

### 6.1 后过滤

```python
filtered = [
    r for r in all_relations
    if r.relation_type in _RST_WHITELIST
    and (r.confidence is None or r.confidence >= min_confidence)
]
```

两层过滤：
1. 关系类型在白名单中
2. 置信度 >= min_confidence (默认 0.5)

**注意**：`max_distance` 参数已从 profile 读取但在 `build()` 中**未被使用**，只存在 `__init__` 中赋值。

---

## 7. 配置参数

| 参数 | 来源 | 默认值 | 说明 |
|------|------|--------|------|
| `window_size` | profile.retrieval_policy | 15 | 滑动窗口大小 |
| `min_confidence` | profile.retrieval_policy | 0.5 | 最低置信度 |
| `max_distance` | profile.retrieval_policy | 5 | 最大距离 (未使用!) |
| `base_url` | constructor | `"http://localhost:8900"` | LLM Service 地址 |
| `knowledge_domain` | constructor | profile.domain_id | 知识领域 |

---

## 8. 关联文件清单

| 文件 | 行数 | 职责 |
|------|------|------|
| `mining/stages/relations/__init__.py` | 178 | build_seg_ids + DiscourseRelationBuilder |
| `mining/infra/llm_client.py` | 292 | LlmClient |
| `mining/contracts/models.py:286` | — | `SegmentRelationData` 数据类 |
| `mining/contracts/models.py:64` | — | `VALID_RELATION_TYPES` 常量 |
| `mining/infra/domain_pack.py` | — | RetrievalPolicy (discourse 阈值) |
| `mining/pipeline.py` | — | discourse_stage() |

---

## 9. 工业化参考

| 参考 | 说明 |
|------|------|
| RST (Rhetorical Structure Theory) | 经典语篇关系理论，我们的关系类型集基于此 |
| PDTB (Penn Discourse Treebank) | 另一种语篇标注体系 |
| SpaCy `DependencyParser` | 依存句法分析，可以在句子级做类似关系 |
| GraphRAG (Microsoft) | 社区检测 + 实体图构建，我们的关系是 segment 级而非实体级 |
| LlamaIndex `KnowledgeGraphIndex` | 构建知识图谱索引，类似但粒度不同 |
| neo4j / NetworkX | 图数据库/图库，我们用关系表存储 |

---

## 10. 当前不足

1. **`max_distance` 未使用**: 参数已从 profile 读取但 build() 中完全未使用，应该在过滤阶段应用 `r.distance <= max_distance`
2. **滑动窗口重叠导致重复关系**: 窗口步长 = window_size - 1，重叠的 segment 对可能在多个窗口中产生重复关系，无去重逻辑
3. **distance 是窗口内而非全局**: `abs(source_idx - target_idx)` 是窗口内的相对距离，不是文档中的全局位置差
4. **无结构性关系**: 只生成 RST 语篇关系，不生成 previous/next/same_section 等结构性关系（这些似乎在 pipeline.py 中直接构造？或由 DB 触发器处理？）
5. **confidence 转 float 可能抛异常**: `float(item.get("confidence", 0.5))` 如果 LLM 返回非数值字符串会崩溃
6. **segment 预览截断可能丢失关键信息**: `raw_text[:150]` 可能截断在关键词中间
7. **heading segment 被完全排除**: heading 只做 section_title 传播，但 heading 与后续内容之间可能存在语义关系
8. **LLM 调用粒度粗**: 每个窗口一次 LLM 调用，如果文档很大（数百 segments），LLM 调用次数 = segments / window_size
9. **无去重**: 窗口重叠导致同一对 segment 可能在不同窗口中产生多个 relation，无合并逻辑
10. **seg_ids 与 relation 构建 decoupled**: seg_ids 在 segment stage 生成，但 discourse 使用 _make_segment_key 而非 seg_ids dict 来标识 segment。这意味着 relation 的 source/target key 格式是 `doc_key#index`，不是 UUID
11. **无关系方向性验证**: LLM 可能返回 source=target 的自环关系，distance 计算为 None 但不会被过滤
