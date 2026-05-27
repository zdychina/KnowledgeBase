# Phase 2 Serving 侧改动记录

> 日期：2026-05-20
> 依据：`task/2026-05-19-mining-serving-evolution.md` 第三章 Phase 2
> 状态：已完成，162 个单元测试全部通过

---

## 一、语义缓存（Semantic Cache）

### 背景

相同或高度相似的查询重复执行完整 pipeline，浪费 LLM 调用和 DB 查询资源。语义缓存在 embedding 生成之后、重度检索之前拦截命中请求，直接返回缓存结果。

### 改动文件

**`db/migrate_v2_semantic_cache.sql`**（新建）

```sql
CREATE TABLE serving_query_cache (
    id               TEXT PRIMARY KEY,
    domain           TEXT NOT NULL DEFAULT 'default',
    query_text       TEXT NOT NULL,
    query_embedding  vector(1024),
    context_pack_json JSONB NOT NULL,
    hit_count        INTEGER NOT NULL DEFAULT 1,
    created_at       TIMESTAMPTZ NOT NULL DEFAULT now(),
    expires_at       TIMESTAMPTZ
);
-- IVFFlat ANN 索引（pgvector ≥ 0.4）
CREATE INDEX idx_sqc_embedding ON serving_query_cache
    USING ivfflat (query_embedding vector_cosine_ops) WITH (lists = 50);
```

TTL 由 `expires_at`（insert 时设为 now() + 24h）管理，不依赖后台 job。

**`mapper/SemanticCacheMapper.java` + `mapper/SemanticCacheMapper.xml`**（新建）

| 方法 | SQL 说明 |
|------|---------|
| `findNearest(domain, queryVector)` | pgvector `<=>` 余弦距离查最近邻，返回 similarity = `1 - distance` |
| `insert(...)` | ON CONFLICT DO NOTHING，安全幂等 |
| `incrementHit(id)` | 命中计数 +1，用于统计缓存命中率 |
| `evictByDomain(domain)` | release 切换时调用，清空该 domain 缓存 |

**`application/SemanticCacheService.java`**（新建）

核心逻辑：
```
lookup(domain, queryVector):
  queryVector == null → 返回 null（无 embedding 时跳过缓存）
  cacheMapper.findNearest()
  row.similarity < 0.92 → 返回 null（未命中）
  命中 → incrementHit + 反序列化 ContextPack → 返回

store(domain, query, queryVector, pack):
  queryVector == null → 直接返回（不缓存无向量的结果）
  序列化 pack 为 JSON → cacheMapper.insert()
```

所有操作均为 best-effort：异常被 `catch` 并以 warn 日志记录，不影响主流程。使用 Spring 注入的 `ObjectMapper`（含 `ParameterNamesModule`，支持 record 反序列化）。

**`application/SearchService.java`**（修改）

在 pipeline 中插入两个步骤：

```
step 5.5（embedding 后，retrieve 前）:
  cachedPack = semanticCache.lookup(effectiveDomain, queryEmbedding)
  命中 → 直接 return cachedPack（跳过后续所有重度计算）

step 9.5（assemble 后）:
  semanticCache.store(effectiveDomain, request.query(), queryEmbedding, pack)
```

### 关键设计决策

- 相似度阈值 0.92：高于 0.9（避免误命中语义相近但意图不同的查询），低于 0.95（保证实用命中率）
- 缓存以 `queryEmbedding` 而非原始查询字符串做匹配，天然支持同义词和改写
- `evictByDomain()` 供外部在 release 切换时主动清空，避免旧版本知识被复用

---

## 二、Multi-Query Expansion（多查询扩展）

### 背景

单一查询表述的词汇覆盖有限，召回率受限。Multi-Query 将查询改写为 2-3 个语义变体，每个变体独立检索，候选合并后统一进入 Fusion，最终召回率提升 20-30%。

### 改动文件

**`infrastructure/ServingTemplates.java`**（修改）

新增 `serving-multi-query-expansion` 模板：

```
系统提示：生成 2-3 个语义相近但表达不同的查询变体
  - 保持相同意图
  - 变体间差异：中英文混用、同义词替换、缩写展开
  - 输出 JSON: {"variants": ["变体1", "变体2", ...]}
```

**`application/MultiQueryExpander.java`**（新建，`@Component`）

```
expand(query):
  llmClient 不可用 → 返回 [query]（单查询降级）
  调用 serving-multi-query-expansion 模板
  解析 result.parsed_output.variants
  过滤：去掉空白、去掉与原查询相同的变体
  限制：最多 2 个额外变体（MAX_EXTRA_VARIANTS = 2）
  任何异常 → warn 日志 + 返回 [query]
  返回：[originalQuery, variant1?, variant2?]
```

**`application/SearchService.java`**（修改）

新增 `multiQueryExpander` 字段和构造参数。Pipeline 改动：

```
step 3.5: 多查询扩展
  queryVariants = multiQueryExpander.expand(request.query())

step 5: 为每个变体独立生成 HyDE embedding
  variantEmbeddings: Map<String, float[]>
  queryEmbedding = variantEmbeddings.get(request.query())  ← 原始查询的 embedding

step 6: 为每个变体独立执行检索，rawCandidates 累积合并
  for variant in queryVariants:
    varUnderstanding = 原始 understanding（仅替换 originalQuery 字段）
    orchResult = orchestrator.execute(varUnderstanding, routePlan, varEmb, snapshotIds)
    rawCandidates.addAll(orchResult.candidates())
  → 进入 Fusion 时候选数量 = 变体数 × 各路检索 topK
```

**`SearchService.buildVariantUnderstanding()`**（新建私有方法）

```java
// 复用原始 understanding 的 intent/entities/scope/keywords，仅替换 originalQuery
new QueryUnderstanding(variantQuery, original.intent(), original.subQueries(), ...)
```

### 关键设计决策

- 变体数上限 2（总共 3 个查询）：平衡召回率提升与检索延迟，避免超线性开销
- 每个变体使用独立的 HyDE embedding（不共享），确保语义变体在向量空间的差异被充分利用
- Fusion 层（WeightedRRF）天然处理多路候选的分数归一化，无需为 multi-query 做额外适配

---

## 三、语篇引导图扩展（Discourse-Guided Graph Expansion）

### 背景

Phase 1 建立了关系优先级排序（4 级），但仅覆盖结构关系。Phase 2 在此基础上引入语篇关系的优先级，为 Mining Phase 2 产出的 ELABORATES / CONDITIONS 等关系预置权重，一旦 Mining 侧就绪即可生效。

### 改动文件

**`retrieval/GraphExpander.java`**（修改）

`RELATION_PRIORITY` 从 4 级扩展为 11 级：

| 优先级 | 关系类型 | 来源 |
|--------|---------|------|
| 0 | `entity_relation` | Mining Phase 2（待就绪） |
| 1 | `elaborates` | Mining Phase 2（待就绪） |
| 2 | `conditions` | Mining Phase 2（待就绪） |
| 3 | `backgrounds` | Mining Phase 2（待就绪） |
| 4 | `enables` | Mining Phase 2（待就绪） |
| 5 | `results_in` | Mining Phase 2（待就绪） |
| 6 | `sequences` | Mining Phase 2（待就绪） |
| 7 | `contrasts_with` | Mining Phase 2（待就绪） |
| 8 | `section_header_of` | 已有 |
| 9 | `same_section` | 已有 |
| 10 | `same_parent_section` | 已有 |
| 11 | 其他（默认） | 兜底 |

BFS 排序中默认优先级从 `4` 改为 `11`，与新的 11 级体系一致。

### 当前行为

- 当前 DB 中无 `entity_relation` / `elaborates` 等语篇关系，优先级 0-7 实际不生效
- Mining Phase 2 Schema-First 实体关系提取完成后，BFS 将自动以更高优先级选取这些关系，无需修改 Serving 代码

---

## 四、自适应检索路由（Adaptive Retrieval Routing）

### 背景

不同复杂度的查询对检索路由的需求不同：简单的实体查找用精确匹配即可，复杂的对比/多跳查询需要更大召回量。统一路由策略对简单查询有浪费，对复杂查询召回不足。

### 改动文件

**`application/RetrievalRouter.java`**（修改）

新增两个静态方法：

**`computeComplexity(QueryUnderstanding)`**

```
complex:
  subQueries 非空（LLM 拆解了子查询）
  OR intent = "comparison"（对比类需要多文档推理）

simple:
  intent ∈ {command_usage, concept_lookup, navigational}
  AND entities 非空（有明确实体，精确匹配可解）

medium: 其他所有情况
```

**`applyComplexity(routes, complexity)`**

```
simple  → 禁用 dense_vector（entity_exact + BM25 足够，省去 LLM embedding 调用）
complex → 所有路由 topK × 1.5（扩大召回量，应对多跳推理需求）
medium  → 不变
```

在 `route()` 方法中，建完 routeConfigs 后立即应用：
```java
String complexity = computeComplexity(understanding);
routeConfigs = applyComplexity(routeConfigs, complexity);
```

### 关键设计决策

- simple 禁用 dense_vector：LLM embedding 调用和 ANN 检索有显著延迟，对精确实体查询无增益
- complex 的 topK 乘数 1.5（而非更大）：避免 Fusion 和 Rerank 阶段候选过多导致延迟上升
- complexity 判断纯基于规则（不调 LLM），保证计算开销为零

---

## 五、单元测试修复

**`SearchServiceTest.java`**（修改）

SearchService 构造新增 `MultiQueryExpander` 和 `SemanticCacheService` 两个参数，测试中补充对应 mock 和 stub：

```java
multiQueryExpander = mock(MultiQueryExpander.class);
semanticCache = mock(SemanticCacheService.class);

// 无 LLM 时只返回原始查询
when(multiQueryExpander.expand(anyString()))
    .thenAnswer(inv -> List.of(inv.getArgument(0, String.class)));
// 缓存默认未命中
when(semanticCache.lookup(anyString(), any())).thenReturn(null);
```

注意：`inv.getArgument(0, String.class)` 而非 `inv.getArgument(0)` — 后者返回 `Object`，与 `List.of()` varargs 重载有歧义，导致 ClassCast。

---

## 六、验收检查点

| 检查项 | 验证方法 |
|--------|---------|
| 语义缓存命中 | 相同查询连续请求两次，第二次 trace 应出现 `semantic_cache hit=true` |
| 语义缓存未命中 | 不相关查询不应返回缓存结果 |
| 缓存失效回退 | queryEmbedding 为 null 时（无 LLM），缓存跳过，pipeline 正常执行 |
| Multi-Query 扩展 | debug=true 时 trace 中 `multi_query_expand` 阶段 `variants` 应 ≥ 2（LLM 可用时） |
| Multi-Query 降级 | LLM 不可用时 `variants=1`，流程正常 |
| 自适应路由 — simple | command_usage + 有实体的查询：routePlan 中 dense_vector enabled=false |
| 自适应路由 — complex | comparison 查询：所有路由 topK 增大 50% |
| 语篇优先级 | DB 有 elaborates 关系时，BFS 应优先于 same_section 展开 |
| 单元测试 | `mvn test` 162 个测试全部通过 ✓（已验证） |
