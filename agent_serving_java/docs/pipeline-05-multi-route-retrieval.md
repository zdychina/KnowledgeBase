# Pipeline Stage 05: 多路检索 (Multi-Route Retrieval)

## 概述

本阶段由 `RetrievalOrchestrator` 编排，对 Stage 03 决定的每条路由并行执行检索。每条路由独立运行、异常隔离，结果汇聚为统一的 `RetrievalCandidate` 列表。三条路由分别是：

1. **lexical_bm25**：PostgreSQL FTS 全文检索，带三级降级
2. **dense_vector**：pgvector 余弦相似度向量检索
3. **entity_exact**：JSONB 实体精确匹配

## 流程图

```
RetrievalOrchestrator.execute(understanding, routePlan, queryEmbedding, snapshotIds)
  │
  ├─ snapshotIds 为空? → return OrchestratorResult.empty()
  │
  ├─ 构建 RetrievalQuery（从 understanding + embedding）
  │
  ├─ 过滤 enabled=true 的路由
  │
  ├─ 对每条路由：
  │   ├─ retriever 未注册 → trace("not_registered"), skip
  │   ├─ dense_vector 但无 embedding → trace("no_embedding"), skip
  │   ├─ 执行 retriever.retrieve(query, snapshotIds, topK)
  │   │   ├─ 成功 → 标准化 source 名称，加入 allCandidates
  │   │   └─ 异常 → trace(error_message), continue
  │   └─ 记录 RouteTrace(name, attempted, candidateCount, latencyMs)
  │
  └─ return OrchestratorResult(allCandidates, traces)
```

## 输入

| 输入 | 类型 | 来源 | 说明 |
|------|------|------|------|
| `understanding` | QueryUnderstanding | Stage 02 | 原始查询、关键词、实体、子查询 |
| `routePlan` | RetrievalRoutePlan | Stage 03 | 路由配置列表、fusion 配置 |
| `queryEmbedding` | `float[]` | Stage 04 | 查询向量（可为 null） |
| `snapshotIds` | List\<String\> | Stage 04 | 限定检索范围 |

## 输出

### OrchestratorResult（record）

| 字段 | 类型 | 说明 |
|------|------|------|
| `candidates` | List\<RetrievalCandidate\> | 所有路由的候选结果汇总 |
| `routeTraces` | List\<RouteTrace\> | 每条路由的执行追踪 |

### RetrievalCandidate（record）

| 字段 | 类型 | 说明 |
|------|------|------|
| `retrievalUnitId` | String | 检索单元 ID（全局唯一） |
| `score` | double | 当前分数（检索/融合/重排后变化） |
| `source` | String | 来源路由名 |
| `metadata` | Map\<String, Object\> | 附加元数据（text, title, block_type 等） |
| `scoreChain` | ScoreChain | 分数演进链 |

### RouteTrace（record）

| 字段 | 类型 | 说明 |
|------|------|------|
| `name` | String | 路由名 |
| `attempted` | boolean | 是否尝试执行 |
| `candidateCount` | int | 返回候选数 |
| `skippedReason` | String | 跳过原因（空字符串表示未跳过） |
| `latencyMs` | double | 耗时毫秒 |

### ScoreChain（record）

| 字段 | 类型 | 说明 |
|------|------|------|
| `rawScore` | double | 初始检索分数 |
| `fusionScore` | double | 融合后分数 |
| `rerankScore` | double | 重排后分数 |
| `routeSources` | List\<String\> | 贡献路由列表 |

## 涉及的关键文件

| 文件 | 职责 |
|------|------|
| `pipeline/RetrievalOrchestrator.java` | **编排器**，循环执行每条路由，异常隔离 |
| `retrieval/Retriever.java` | 检索器接口：`retrieve(query, snapshotIds, topK)` |
| `retrieval/FtsRetriever.java` | FTS 三级降级检索器 |
| `retrieval/DenseVectorRetriever.java` | pgvector 向量检索器 |
| `retrieval/EntityExactRetriever.java` | 实体精确匹配检索器 |
| `domain/RetrievalQuery.java` | 检索查询 record |
| `domain/RetrievalCandidate.java` | 候选结果 record（不可变） |
| `domain/RouteTrace.java` | 路由追踪 record |
| `domain/ScoreChain.java` | 分数演进链 record |
| `domain/OrchestratorResult.java` | 编排结果 record |
| `domain/ServingConstants.java` | 路由名常量 |
| `mapper/AssetRetrievalUnitMapper.xml` | FTS/trigram/LIKE/entity SQL |
| `mapper/AssetRetrievalEmbeddingMapper.xml` | 向量检索 SQL |

---

## 路由 1：lexical_bm25（FtsRetriever）

### 概述

基于 PostgreSQL 全文检索，支持三级降级策略和 scope 过滤。

### 三级降级

```
Level 1: tsvector（websearch_to_tsquery）
  │  失败 →
  ├─ Level 2: pg_trgm（trigram similarity）
  │    失败 →
  │    └─ Level 3: LIKE 模糊匹配
  └─ scope 过滤消除所有结果时自动重试（去掉 scope）
```

### Level 1：tsvector 全文检索

```sql
SELECT ru.id, ru.document_snapshot_id, ru.text, ru.title, ru.block_type,
       ru.semantic_role, ru.source_refs_json, ru.facets_json,
       ru.target_type, ru.target_ref_json, ru.unit_type, ru.source_segment_id,
       ts_rank(
           to_tsvector('simple', ru.search_text),
           websearch_to_tsquery('simple', #{ftsQuery})
       ) AS fts_score
FROM asset_retrieval_units ru
WHERE to_tsvector('simple', ru.search_text) @@ websearch_to_tsquery('simple', #{ftsQuery})
  AND ru.document_snapshot_id IN (#{snapshotIds})
  AND ru.facets_json @> #{scopeParam}::jsonb   -- scope 过滤
ORDER BY fts_score DESC
LIMIT #{limit}
```

- 使用 `simple` 字典（非英文词干化），依赖 `search_text` 列
- `ftsQuery` 格式：`"token1 OR token2 OR token3"`
- 分数由 PostgreSQL 的 `ts_rank` 计算
- scope 通过 JSONB `@>` 包含操作下推到 SQL

### Level 2：pg_trgram 三元组相似度

```sql
SELECT ..., similarity(ru.text, #{queryText}) AS fts_score
FROM asset_retrieval_units ru
WHERE ru.text % #{queryText}   -- % 是 pg_trgm 相似度阈值操作符
  AND ru.document_snapshot_id IN (...)
ORDER BY fts_score DESC
LIMIT #{limit}
```

- `%` 操作符使用 `pg_trgm.similarity_threshold`（默认 0.3）
- 如果 PostgreSQL 未安装 `pg_trgm` 扩展，捕获 `BadSqlGrammarException` 跳过

### Level 3：LIKE 回退

```sql
SELECT ..., 0.0 AS fts_score
FROM asset_retrieval_units ru
WHERE (ru.text LIKE '%token1%' OR ru.text LIKE '%token2%' ...)
  AND ru.document_snapshot_id IN (...)
LIMIT #{limit}
```

- 数据库打分固定 0.0，Java 侧按关键词命中率重算：`score = hitCount / totalKeywords`
- 最后兜底，保证总能返回结果

### Tokenization

使用 jieba 分词（`ThreadLocal<JiebaSegmenter>`）处理中文查询：

```java
List<String> raw = SEGMENTER_TL.get().sentenceProcess(text);
List<String> filtered = raw.stream()
    .filter(t -> t.length() >= 2 || CJK_PATTERN.matcher(t).matches())
    .filter(t -> !STOPWORDS_ZH.contains(t) && !STOPWORDS_EN.contains(t.toLowerCase()))
    .collect(Collectors.toList());
return filtered.isEmpty() ? raw : filtered;  // 全被过滤则用原始 tokens
```

### Scope 过滤机制

所有三级共享 scope 过滤逻辑：

```java
static List<String> buildScopeJsonParams(Map<String, Object> scope) {
    // scope = {network_elements: ["SMF","UPF"]}
    // → params = ["{\"network_elements\":[\"SMF\",\"UPF\"]}"]
    // SQL: facets_json @> '{"network_elements":["SMF","UPF"]}'::jsonb
}
```

**自动重试**：当 scope 过滤消除了所有结果时，自动去掉 scope 重新查询。

### recallLimit = topK × 5

每级检索实际召回 `topK × 5` 条，为后续融合留出余量。

---

## 路由 2：dense_vector（DenseVectorRetriever）

### 概述

使用 pgvector 扩展的余弦距离操作符 `<=>`，在 PostgreSQL 内完成 ANN 搜索。不将向量加载到 JVM。

### SQL

```sql
SELECT re.retrieval_unit_id,
       (1 - (re.embedding_vector_vec <=> #{queryVector}::vector)) AS cosine_score,
       ru.document_snapshot_id, ru.text, ru.title, ru.block_type,
       ru.semantic_role, ru.source_refs_json, ru.facets_json,
       ru.target_type, ru.target_ref_json, ru.unit_type, ru.source_segment_id
FROM asset_retrieval_embeddings re
JOIN asset_retrieval_units ru ON re.retrieval_unit_id = ru.id
WHERE ru.document_snapshot_id IN (#{snapshotIds})
  AND re.embedding_dim = #{dim}
  AND ru.facets_json @> #{scopeParam}::jsonb   -- scope 过滤
ORDER BY re.embedding_vector_vec <=> #{queryVector}::vector
LIMIT #{topK}
```

### 关键点

- **`embedding_vector_vec`**：`vector(1024)` 类型列，由数据库 trigger 自动从 TEXT 列填充
- **`<=>`**：pgvector 余弦距离操作符，值域 [0, 2]，0 表示完全相同
- **cosine_score = 1 - distance**：转化为 [−1, 1] 的相似度
- **HNSW 索引**：`idx_asset_retrieval_embeddings_vec_hnsw` 加速 ANN 搜索
- **scope 自动重试**：同 FTS，scope 消除结果时去掉 scope 重试

### 向量格式化

```java
static String formatVector(float[] vec) {
    // [0.012,-0.034,0.567,...] → pgvector literal
    StringBuilder sb = new StringBuilder("[");
    for (int i = 0; i < vec.length; i++) {
        if (i > 0) sb.append(',');
        sb.append(vec[i]);
    }
    sb.append("]");
    return sb.toString();
}
```

### 自动跳过条件

在 Orchestrator 中：如果 `queryEmbedding == null || length == 0`，自动跳过此路由，trace 记录 `"no_embedding"`。

---

## 路由 3：entity_exact（EntityExactRetriever）

### 概述

通过 JSONB 数组查询找到实体名精确匹配的检索单元。固定高分 0.95。

### SQL

```sql
SELECT ru.id, ru.document_snapshot_id, ru.text, ru.title, ...,
       0.95 AS fts_score
FROM asset_retrieval_units ru
WHERE ru.document_snapshot_id IN (#{snapshotIds})
  AND ru.entity_refs_json != '[]'
  AND EXISTS (
      SELECT 1
      FROM jsonb_array_elements(ru.entity_refs_json::jsonb) AS e
      WHERE e->>'name' IN (#{entityNames})
  )
ORDER BY ru.weight DESC
LIMIT #{limit}
```

### 策略

1. **主策略**：从 `query.entities()` 提取 `name` 和 `normalizedName`
2. **降级策略**：无实体时用 `keywords`（≥2 字符）作为类实体词
3. **固定分 0.95**：精确匹配高置信度

### 无 scope 过滤

此路由不应用 scope 过滤，因为实体匹配已经足够精确。

---

## 检索器接口

```java
public interface Retriever {
    List<RetrievalCandidate> retrieve(RetrievalQuery query, List<String> snapshotIds, int topK);
}
```

### RetrievalQuery（record）

| 字段 | 类型 | 说明 |
|------|------|------|
| `originalQuery` | String | 原始查询 |
| `keywords` | List\<String\> | 关键词 |
| `entities` | List\<EntityRef\> | 实体列表 |
| `queryEmbedding` | float[] | 查询向量 |
| `subQueries` | List\<String\> | 子查询文本 |
| `intent` | String | 意图 |
| `scope` | Map\<String, Object\> | 作用域约束 |

## 具体实现细节

### 异常隔离机制

```java
for (var entry : routeConfigMap.entrySet()) {
    try {
        candidates = retriever.retrieve(retrievalQuery, snapshotIds, routeCfg.topK());
    } catch (Exception e) {
        // 记录异常到 trace，continue 不影响其他路由
        traces.add(new RouteTrace(routeName, false, 0, e.getMessage(), latencyMs));
        continue;
    }
    // 标准化 source，加入结果
    allCandidates.addAll(annotated);
    traces.add(new RouteTrace(routeName, true, annotated.size(), "", latencyMs));
}
```

### Source 标准化

```java
// 子检索器可能返回自己的 source 名（如 "trigram_fallback"）
// 标准化为路由名（如 "lexical_bm25"）
for (var c : candidates) {
    if (!routeName.equals(c.source())) {
        c = c.withSource(routeName);
    }
    annotated.add(c);
}
```

### Retriever 注册

在 `ServingBeans` 中通过 Map 注册：

```java
Map<String, Retriever> retrievers = Map.of(
    "lexical_bm25", ftsRetriever,
    "dense_vector", denseVectorRetriever,
    "entity_exact", entityExactRetriever
);
```

## 工业化参考

| 参考实践 | 说明 |
|----------|------|
| **Multi-Route Retrieval** | Google/Bing 的多信号检索标准架构 |
| **Exception Isolation** | 类似 Circuit Breaker 模式，一条路由故障不影响整体 |
| **Graceful Degradation** | FTS → trigram → LIKE 三级降级，保证总能返回结果 |
| **Scope Auto-Retry** | 类似查询优化器的 adaptive execution：计划 A 无结果则自动降级 |
| **Server-side ANN** | pgvector 的 HNSW 索引做近似最近邻，避免全表扫描 |
| **JSONB Containment** | PostgreSQL 原生 JSON 查询能力，无需额外索引引擎 |

## 当前实现的不足

### 1. 路由串行执行

当前所有路由在 Orchestrator 中是 `for` 循环串行执行，没有并行。

**改进方向**：使用 `CompletableFuture` 或虚拟线程并行执行各路由，减少总延迟。

### 2. FTS 使用 `simple` 字典

`websearch_to_tsquery('simple', ...)` 不支持中文分词。虽然 Java 侧用了 jieba 分词再拼接 OR，但数据库侧的 `to_tsvector('simple', ru.search_text)` 依赖 `search_text` 列的分词质量。

**改进方向**：安装 `pg_jieba` 扩展或使用 `zhparser`，让 PostgreSQL 原生支持中文分词。

### 3. trigram 搜索在 `text` 列上

`similarity(ru.text, #{queryText})` 对全文做三元组匹配，text 可能很长，性能差。

**改进方向**：对 `title` 或 `search_text` 列做 trigram 索引，或限制 trigram 只搜索短字段。

### 4. entity_exact 固定分 0.95

所有精确匹配一律 0.95，不区分实体类型和匹配质量。

**改进方向**：根据实体类型（network_element vs command）、匹配字段（name vs normalizedName）差异化打分。

### 5. 无检索结果缓存

相同查询 + 相同 snapshot 的检索结果没有缓存。高频查询浪费 DB 资源。

**改进方向**：添加 query hash + snapshotIds → candidates 的缓存层。

### 6. `selectTopKByVector` 未指定 embedding_dim 的默认值

SQL 中 `AND re.embedding_dim = #{dim}`，dim 来自 `queryVec.length`，始终等于配置的 1024。但数据库中可能存在不同 dim 的 embedding。

**改进方向**：确保数据库中只存一种 dim，或在配置中明确 dim 值。

### 7. jieba 分词器 ThreadLocal 初始化

`ThreadLocal.withInitial(JiebaSegmenter::new)` 首次调用时加载词典较慢。

**改进方向**：在 `@PostConstruct` 中预热一个 segmenter 实例。
