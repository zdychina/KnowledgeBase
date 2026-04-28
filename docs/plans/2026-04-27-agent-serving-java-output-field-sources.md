# agent_serving_java 输出字段来源文档

> 版本：1.0 | 日期：2026-04-27

接口：`POST /api/v1/search`，响应体类型：`ContextPack`。

---

## 一、ContextQuery

> 全部来自内存，不查数据库。

| 字段 | 类型 | 来源 |
|------|------|------|
| `original` | string | `SearchRequest.query`，原样透传 |
| `normalized` | string | `NormalizedQuery.keywords` 以空格拼接 |
| `intent` | string | `NormalizedQuery.intent`，由 `QueryNormalizer` 规则引擎或 LLM 识别 |
| `keywords` | string[] | `NormalizedQuery.keywords`，分词并过滤停用词后的关键词列表 |
| `entities` | EntityRef[] | `NormalizedQuery.entities`，从查询中识别出的实体；若请求传入 `entities` 覆盖则为覆盖值 |
| `scope` | map | `NormalizedQuery.scope`，从查询中提取的范围约束；若请求传入 `scope` 覆盖则为覆盖值 |

---

## 二、ContextItem

响应中 `items` 数组包含三种 `role`，数据来源不同。

### 2.1 role = seed

> 来自 FTS 召回，数据源：`asset_retrieval_units`。

| 字段 | 类型 | 数据库表 | 列名 | 备注 |
|------|------|---------|------|------|
| `id` | string | `asset_retrieval_units` | `id` | |
| `kind` | string | — | — | 硬编码 `"retrieval_unit"` |
| `role` | string | — | — | 硬编码 `"seed"` |
| `text` | string | `asset_retrieval_units` | `text` | 返回给 LLM 的正文 |
| `score` | number | — | — | `ts_rank(to_tsvector('simple', search_text), ...)` 计算值，经 `ScoreReranker` 四阶段调整 |
| `title` | string | `asset_retrieval_units` | `title` | |
| `block_type` | string | `asset_retrieval_units` | `block_type` | |
| `semantic_role` | string | `asset_retrieval_units` | `semantic_role` | |
| `source_id` | string | `asset_retrieval_units` | `source_segment_id` | 指向对应 raw_segment 的 ID |
| `relation_to_seed` | string | — | — | 硬编码 `null` |
| `source_refs` | map | `asset_retrieval_units` | `source_refs_json` | JSON 字符串解析为 Map |
| `metadata` | map | — | — | 硬编码 `{}` |

### 2.2 role = context

> 由 seed 的 `source_segment_id` 关联查出，数据源：`asset_raw_segments` JOIN `asset_document_snapshots` JOIN `asset_document_snapshot_links` JOIN `asset_documents`。

| 字段 | 类型 | 数据库表 | 列名 | 备注 |
|------|------|---------|------|------|
| `id` | string | `asset_raw_segments` | `id` | |
| `kind` | string | — | — | 硬编码 `"raw_segment"` |
| `role` | string | — | — | 硬编码 `"context"` |
| `text` | string | `asset_raw_segments` | `raw_text` | |
| `score` | number | — | — | 硬编码 `0.0` |
| `title` | string | `asset_document_snapshots` | `title` | JOIN 获取 |
| `block_type` | string | `asset_raw_segments` | `block_type` | |
| `semantic_role` | string | `asset_raw_segments` | `semantic_role` | |
| `source_id` | string | `asset_documents` | `id` | JOIN 获取，指向来源文档 |
| `relation_to_seed` | string | — | — | 硬编码 `null` |
| `source_refs` | map | — | — | 硬编码 `{}` |
| `metadata` | map | — | — | 硬编码 `{}` |

### 2.3 role = support

> 由 `GraphExpander` BFS 图扩展得到，数据源与 context 相同（`asset_raw_segments` 及关联表）。

与 `context` 完全相同，仅以下两个字段不同：

| 字段 | 类型 | 值 |
|------|------|----|
| `role` | string | 硬编码 `"support"` |
| `relation_to_seed` | string | 硬编码 `"expanded_depth_1"` 或 `"expanded_depth_2"`（取决于 BFS 扩展层数） |

---

## 三、ContextRelation

> 数据源：`asset_raw_segment_relations`。

| 字段 | 类型 | 数据库表 | 列名 | 备注 |
|------|------|---------|------|------|
| `id` | string | `asset_raw_segment_relations` | `id` | DB 值为空时生成 UUID |
| `from_id` | string | `asset_raw_segment_relations` | `source_segment_id` | |
| `to_id` | string | `asset_raw_segment_relations` | `target_segment_id` | |
| `relation_type` | string | `asset_raw_segment_relations` | `relation_type` | |
| `distance` | integer | `asset_raw_segment_relations` | `distance` | 可为 null |

---

## 四、SourceRef

> 三表 JOIN 查询，数据源：`asset_documents` JOIN `asset_document_snapshot_links` JOIN `asset_document_snapshots`。

| 字段 | 类型 | 数据库表 | 列名 | 备注 |
|------|------|---------|------|------|
| `id` | string | `asset_documents` | `id` | |
| `document_key` | string | `asset_documents` | `document_key` | |
| `title` | string | `asset_document_snapshots` | `title` | JOIN 获取 |
| `relative_path` | string | `asset_document_snapshot_links` | `relative_path` | JOIN 获取 |
| `scope_json` | map | `asset_document_snapshots` | `scope_json` | JSON 字符串解析为 Map |
| `metadata` | map | — | — | 硬编码 `{}` |

---

## 五、Issue

> 不查数据库，由代码逻辑生成。

| `type` 值 | 触发条件 |
|-----------|---------|
| `no_result` | `items` 为空（FTS 无召回结果） |
| `low_confidence` | 全部候选的 `score < 0.1` |

---

## 六、suggestions

始终为空数组，当前版本未实现。

---

## 七、debug（仅 debug=true 时出现）

> 全部来自内存，不查数据库。

| 字段 | 来源 |
|------|------|
| `intent` | `QueryPlan.intent` |
| `keywords` | `QueryPlan.keywords` |
| `scope_constraints` | `QueryPlan.scopeConstraints` |
| `fusion_method` | `QueryPlan.retrieverConfig.fusionMethod` |
| `candidate_count` | 重排后候选数量 |
| `snapshot_ids` | `ActiveScope.snapshotIds`（查询 `asset_build_document_snapshots` 得到） |
| `release_id` | `ActiveScope.releaseId`（查询 `asset_publish_releases` 得到） |
| `build_id` | `ActiveScope.buildId`（查询 `asset_publish_releases` 得到） |
