# agent_serving_zdy 代码导读

> 生成日期：2026-05-15  
> 对应分支：master

---

## 一、整体定位

这个模块是一个**多租户知识库检索引擎**，对外暴露一个 REST 接口，接受自然语言查询，经过一条 10 阶段 pipeline 处理后，返回结构化的上下文包（`ContextPack`）供上游 LLM 拼装 prompt 使用。它是 Python 原型的 Java 移植版，行为与 Python 对齐。

```
用户请求 → 理解查询意图 → 规划检索路由 → 多路并发检索
         → 结果融合 → 重排 → 组装上下文 → 返回
```

---

## 二、包结构总览

```
com.coremasterkb.serving
├── api/                 # HTTP 入口层
├── application/         # 业务编排层（pipeline 核心）
├── domain/              # 领域模型（全 record/不可变）
├── domainpack/          # 多租户：domain 配置 + DB 路由
├── retrieval/           # 三类检索器 + 图扩展
├── pipeline/            # 融合策略 + 检索编排器
├── rerank/              # 重排 pipeline
├── repository/          # 数据访问聚合层
├── mapper/              # MyBatis 接口 + result 类
├── entity/              # ORM 实体类
├── evidence/            # 证据角色分类
├── observability/       # 链路追踪 + 查询日志
├── infrastructure/      # 外部服务客户端
├── config/              # Spring Bean 显式装配
└── util/                # 工具类
```

---

## 三、请求入口：`api` 层

### `SearchController`

```
POST /api/v1/search  →  SearchService.search()  →  返回 ContextPack
```

- 请求体反序列化为 `SearchRequest`（record），字段：`query, scope, entities, debug, domain, channel, mode`
- 响应按固定字段顺序组装：`query, items, relations, sources, evidence_groups, issues, suggestions`，`debug` 字段仅在 `request.debug()==true` 时附加
- 入参校验在 `SearchService` 第一行完成（`query_required`）

### `GlobalExceptionHandler`

用 `@RestControllerAdvice` 集中映射业务异常到 HTTP 状态码：

| 异常类型 | message | HTTP |
|---|---|---|
| `IllegalArgumentException` | `query_required` | 400 |
| `IllegalArgumentException` | `unknown_domain` / `domain_disabled` | 400 |
| `IllegalArgumentException` | `no_active_release` | 503 |
| `IllegalArgumentException` | `multiple_active_releases` | 409 |
| `IllegalStateException` | `scenario_pack_missing` | 500 |
| `IllegalStateException` | `domain_database_unavailable` | 503 |
| 其他 | — | 500（泛化消息，不泄露细节） |

---

## 四、Pipeline 核心：`SearchService`

10 个阶段，每个阶段都被 `TraceCollector` 计时：

```java
// Stage 1 — 加载 Domain Profile（YAML 配置）
ServingDomainProfile profile = domainPackReader.getProfile(request.domain());

// Stage 2 — Query Understanding（LLM优先，规则兜底）
QueryUnderstanding understanding = quEngine.understand(query, profile);

// Stage 3 — Retrieval Router（意图→路由权重配置）
RetrievalRoutePlan routePlan = router.route(understanding, profile);

// Stage 4 — 解析 effectiveDomain/channel，验证 DB 可达
domainPoolManager.getDataSource(effectiveDomain);  // 触发懒建池+连通性检查
DomainContext.set(effectiveDomain);                // ThreadLocal，路由后续所有 JDBC 连接

// Stage 5 — 解析 ActiveScope（release + snapshots）
ActiveScope scope = assetRepository.resolveActiveScope(domain, channel);

// Stage 6 — 生成 Query Embedding（dense route 启用时）
queryEmbedding = embeddingClient.embed(query);

// Stage 7 — 多路检索（并发执行各 route）
OrchestratorResult orchResult = orchestrator.execute(understanding, routePlan,
                                                     queryEmbedding, scope.snapshotIds());

// Stage 8 — 融合（weighted_rrf / rrf / identity）
List<RetrievalCandidate> fused = fusion.fuse(rawCandidates, routePlan);

// Stage 9 — 重排（model → LLM → score 级联）
ranked = rerankPipeline.rerank(fused, routePlan, understanding);

// Stage 10 — 组装 ContextPack
pack = assembler.assemble(query, understanding, scope, ranked, routePlan);
```

**关键设计**：`DomainContext.set()` 在 `try...finally` 里，`finally` 里调用 `DomainContext.clear()`，确保 ThreadLocal 不泄露到线程池的其他请求。

---

## 五、Query Understanding：`QueryUnderstandingEngine`

### LLM 路径

调用 `LlmClient.execute("query_understanding", "serving-query-understanding", {query})`，解析返回的 `parsed_output`，提取：

- `intent`（7种）、`entities`、`sub_queries`、`keywords`、`scope`、`evidence_need`、`ambiguities`

任何异常都 catch 后降级到规则路径，`understanding.source()` 分别标记为 `"llm"` 或 `"rule"`。

### 规则路径（fallback）

| 步骤 | 实现 |
|---|---|
| 意图识别 | 先看有无 command 实体，再按关键词集优先级匹配（comparison > troubleshoot > procedure > concept > navigation > general） |
| 实体抽取 | ① Domain Pack 的 `extractor_rules`（正则列表）② 默认命令正则 `ADD/MOD/DEL/...` ③ 中文操作词映射（"新增"→ADD） |
| 范围提取 | 对 `products` 和 `network_elements` 列表做词边界正则匹配（静态列表预编译，避免重复 compile） |
| 关键词提取 | Jieba 分词 → 过滤停用词 → 过滤长度<2 的非 CJK token |

**线程安全**：`JiebaSegmenter` 非线程安全，用 `ThreadLocal<JiebaSegmenter>` 隔离（每个线程一个实例）。

---

## 六、路由规划：`RetrievalRouter`

将 `intent` 映射为各 route 的 `weight` 和 `top_k`：

```
default       → lexical_bm25(w=1.0,k=50)  dense_vector(w=0.9,k=50)  entity_exact(w=0.8,k=20)
command_usage → entity_exact(w=1.5,k=20)  lexical_bm25(w=1.2,k=50)  dense_vector(w=0.6,k=30)
concept_lookup→ dense_vector(w=1.1,k=50)  lexical_bm25(w=0.8,k=50)
troubleshoot  → lexical_bm25(w=1.0,k=50)  dense_vector(w=0.8,k=40)  entity_exact(w=0.7,k=15)
comparison    → lexical_bm25(w=1.0,k=50)  dense_vector(w=1.0,k=50)
```

Domain Pack 可覆盖这些权重（`profile.getRoutePolicyForIntent(intent)`）。路由数 >1 时 fusion 用 `weighted_rrf`，否则 `identity`。

---

## 七、多租户机制：`domainpack` 包

这是模块中最复杂的基础设施，4个类协作：

```
DomainRegistry          DomainPackReader
  ↓ 验证 domain 合法性    ↓ 加载 YAML 配置 (ServingDomainProfile)

DomainPoolManager       DomainRoutingDataSource
  ↓ 懒建 HikariCP 池      ↓ 实现 DataSource 接口
  ↓ 域 → DataSource map   ↓ 根据 ThreadLocal 路由 JDBC 连接
```

### 数据流

```
请求进来
  → DomainRegistry.validate()         检查 domain 存在且 enabled
  → DomainPoolManager.getDataSource() 懒建或取缓存的 HikariCP 池
  → DomainContext.set(domain)         设置 ThreadLocal
  → MyBatis 执行 SQL
    → DomainRoutingDataSource.getConnection()
      → DomainPoolManager.getDataSource(DomainContext.get())
      → 返回对应 domain 的连接
  → DomainContext.clear()             finally 块清理
```

### `DomainPoolManager`

- 启动时（`@PostConstruct`）：只打日志，不建连接（避免阻塞启动）
- 首次请求时：`computeIfAbsent` 懒建池，通过 `entry.databaseUrlEnv()` 读取环境变量中的 JDBC URL
- 关闭时（`@PreDestroy`）：遍历 `ownedPools` 关闭所有自建的池（不关闭 defaultDataSource，由 Spring 管理）

---

## 八、三类检索器：`retrieval` 包

### `FtsRetriever`（词法检索）

三级降级，任一级有结果即返回：

```
Level 1: PostgreSQL tsvector + websearch_to_tsquery（BM25 风格）
Level 2: pg_trgm trigram 相似度（pg_trgm 扩展不存在时跳过）
Level 3: LIKE %token% 兜底（按命中关键词比例打分）
```

每级都先带 scope 过滤，若 scope 导致空结果则 retry 不带 scope。
Jieba 分词后构造 `token1 OR token2 OR ...` 传给 `websearch_to_tsquery`。

### `DenseVectorRetriever`（语义检索）

服务端 ANN（pgvector），排序和评分全部在 PostgreSQL 完成：

```sql
SELECT ..., (1 - embedding_vector <=> #{queryVector}::vector) AS cosine_score
FROM asset_retrieval_embeddings re JOIN asset_retrieval_units ru ...
WHERE document_snapshot_id IN (...)
  AND embedding_dim = #{dim}
  AND facets_json @> #{scopeParam}::jsonb   -- scope 过滤下推 SQL
ORDER BY embedding_vector <=> #{queryVector}::vector
LIMIT #{topK}
```

`queryVector` 由 `EmbeddingClient` 调用 LLM 服务生成，格式化为 `[v0,v1,...,vn]` 字符串。
未配置 LLM URL 时 `EmbeddingClient.isConfigured()` 返回 false，`RetrievalOrchestrator` 自动跳过 dense route。

### `EntityExactRetriever`（实体精确匹配）

对 `entity_refs_json` JSONB 列做 `@>` containment 查询，无实体时降级为关键词匹配，固定返回高置信分 `0.95`。最适合 `command_usage` 意图（命令名精确查找）。

### `GraphExpander`（图扩展）

BFS 遍历段落关系图：

```
seeds → selectNeighbors(frontier) → nextFrontier → ... (maxDepth 层)
```

每个 `NeighborRow` 带 `fromId`（边的源节点），BFS 期间维护 `rootSeed` map（nodeId → 原始 seed），使扩展关系的 `fromId` 精确指向触发扩展的原始种子段落。

---

## 九、融合策略：`pipeline` 包

| 类 | 算法 | 使用场景 |
|---|---|---|
| `WeightedRRFFusion` | `score = Σ(weight × 1/(k+rank))` | 多路，default |
| `RRFFusion` | `score = Σ(1/(k+rank))` | 多路，无权重区分 |
| `IdentityFusion` | 原样透传 | 单路 |

`RetrievalOrchestrator` 对每个 route 独立执行，任一 route 抛异常时记录 trace（`success=false`，含实际耗时）并 continue，不影响其他 route。

---

## 十、重排 Pipeline：`rerank` 包

三阶级联，前一阶成功则跳过后续：

```
Stage 1: LlmServiceReranker  →  调用 LLM 服务 /api/v1/models/rerank
Stage 2: LlmReranker         →  通过 LLM 模板做文本排序（需 routePlan.rerank.method=cascade）
Stage 3: ScoreReranker       →  按现有 score 降序排列（永不失败）
```

统一后处理：
1. 回写 `ScoreChain.rerankScore`
2. 过滤 `score < 0.01` 的候选
3. 截断到 `assembly.maxItems`

---

## 十一、上下文组装：`ContextAssembler`

```
ranked candidates
  → buildSeedItems()          候选转 ContextItem（kind=retrieval_unit, role=seed）
  → resolveCandidateSources() 从 source_refs_json 提取 raw_segment_id
  → resolveSegmentsByIds()    查询原始段落数据
  → buildSourceItems()        段落转 ContextItem（kind=raw_segment, role=context）
  → graphExpander.expand()    BFS 图扩展（enabled 时）
  → buildExpandedItems()      扩展结果转 ContextItem（role=support）
  → getRelationsForSegments() 查询直接关系边
  → evidenceRoleClassifier    重新分类所有 seed item 的证据角色
  → buildSources()            查文档元数据，生成 SourceRef 列表
  → buildIssues()             no_result / low_confidence 检测
  → buildEvidenceGroups()     按 document_snapshot_id 分组聚合
  → 返回 ContextPack
```

---

## 十二、数据模型速查

| Record | 作用 |
|---|---|
| `SearchRequest` | API 入参 |
| `QueryUnderstanding` | 理解结果（意图+实体+关键词+范围） |
| `RetrievalRoutePlan` | 路由计划（routes + fusion + rerank + assembly 配置） |
| `RetrievalCandidate` | 单条检索结果（unit_id + score + metadata + ScoreChain） |
| `ScoreChain` | 分数拆解（rawScore, fusionScore, rerankScore, routeSources） |
| `ActiveScope` | 当前生效的 release + build + snapshotIds |
| `ContextItem` | 上下文条目（kind + role + text + score + citation…） |
| `ContextPack` | 最终响应（query + items + relations + sources + groups + issues） |

---

## 十三、观测性

### `TraceCollector`

每个请求新建一个实例，非线程安全（per-request 单线程使用）。
`totalDurationMs` 是从构造到 `buildTrace()` 的真实挂钟时间，各 stage 的 `durationMs` 是自己的 start→end 耗时（两者之差为 stage 间隙时间）。

### `QueryLogService` + `QueryLogAspect`

AOP 切面自动截获 `search()` 调用，异步写入 `serving_query_log` 表（记录 intent、candidates_found、result_items、execution_time_ms 等）。

### `LlmClient.isAvailable()`

健康检查结果缓存 30 秒，避免每次请求都打 `/health`。

---

## 十四、配置入口

`application.yml` → `ServingProperties`（`@ConfigurationProperties(prefix="serving")`）：

```yaml
serving:
  scenario-packs-dir: ../scenario_packs   # domain YAML 所在目录
  domain-registry-path: ../domain_registry.yaml
  default-domain: cloud_core_network
  llm:
    base-url: http://llm-service:8080    # 空 = dense/rerank/LLM理解全禁用
  embedding:
    model: text-embedding-3
    dimensions: 1024
  rerank:
    model: rerank-pro
```

所有 Bean 的显式装配在 `ServingBeans`（`@Configuration`）中，component-scan 组件不在此重复声明。

---

## 十五、关键路径图

```
POST /api/v1/search
       │
       ▼
SearchController
       │
       ▼
SearchService.search()
  ├─ [validate] query not blank
  ├─ [1] DomainPackReader      → ServingDomainProfile
  ├─ [2] QueryUnderstandingEngine → QueryUnderstanding
  ├─ [3] RetrievalRouter       → RetrievalRoutePlan
  ├─ [4] DomainPoolManager     → DataSource（懒建）
  │       DomainContext.set()  → ThreadLocal
  ├─ [5] AssetRepository       → ActiveScope
  ├─ [6] EmbeddingClient       → float[] queryEmbedding（可选）
  ├─ [7] RetrievalOrchestrator → List<RetrievalCandidate>
  │       ├─ FtsRetriever      → tsvector / trigram / LIKE
  │       ├─ DenseVectorRetriever → pgvector <=>
  │       └─ EntityExactRetriever → JSONB @>
  ├─ [8] FusionStrategy        → fused candidates
  ├─ [9] RerankPipeline        → ranked candidates
  └─ [10] ContextAssembler     → ContextPack
           └─ DomainContext.clear()（finally）
```
