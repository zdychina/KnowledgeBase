# agent_serving_zdy 优化建议

> 范围:`agent_serving_zdy`(Java 检索服务,Spring Boot + MyBatis + Postgres/pgvector,端口 8081)
> 评审日期:2026-06-12
> 核心链路:`SearchService` → `RetrievalOrchestrator` → 各 `Retriever` → `RerankPipeline` → `ContextAssembler`,辅以 `SemanticCacheService` / `SessionStore` / `LlmClient`。

整体设计已较成熟:虚拟线程做 embedding 并行、路由级异常隔离、trace/metrics、pgvector 服务端 ANN、domain 路由连接池。以下按**收益优先级**列出可继续优化的点,均附具体位置。

---

## 一、延迟:几处仍在串行(最大收益)

### 1. variant / sub-query 检索串行 — `SearchService.java:281-300`
6a 对每个 query variant、6b 对每个 sub-query(最多 4 个)依次 `orchestrator.execute(...)`,每次都打 DB。embedding 已并行,但耗时的检索仍串行。最坏 = (1 原始 + 2 变体 + 4 子查询) × 各路由耗时之和。
**改法**:复用已有的 `pipelineExecutor`(虚拟线程),用 `CompletableFuture` fan-out 后 merge,墙钟时间从“求和”降到“取最大”。

### 2. 单次 execute 内部路由串行 — `RetrievalOrchestrator.java:89`
FTS / dense / entity 三条路由在一个 `for` 里顺序执行,而它们互相独立。
**改法**:并行化后单次检索延迟 ≈ 最慢路由。需与第 7 点(连接池)配套。

### 3. 语义缓存命中太晚 — `SearchService.java:266-272`
缓存查找发生在 multi-query 扩展(`:216`,一次 LLM)**和**全部 variant 的 HyDE embedding(`:226-263`)之后。命中时已白付一次扩展 LLM + N-1 次 HyDE。而缓存只需**原始 query 的 embedding**,该 `originalEmbFuture` 在 QU 之前就已启动(`:129`)。
**改法**:把缓存查找提到扩展与额外 embedding **之前**,命中路径省掉一次 LLM + 多次 embedding。

### 4. HyDE 调用次数偏高 — `EmbeddingClient.embedHyDE:47`
每个文本走 HyDE = **1 次 LLM 生成 + 1 次 embedding**,且对每个 variant 和 sub-query 都做,一次请求可能 6-7 ×(生成+embed)往返。
**改法(三选一或组合)**:
- 只对原始 query 做 HyDE,变体/子查询用普通 embedding;
- 批量化最终 embedding 调用——`LlmClient.embed` 本就接收 `List<String>`,现状每次只传一条(`EmbeddingClient.java:28` `List.of(text)`),合并为一次 HTTP;
- 按 `queryComplexity` 决定是否开 HyDE。
- ⚠️ 涉及召回质量,建议配 A/B 或离线评测。

---

## 二、HTTP 客户端:无连接复用

### 5. RestTemplate 使用 `SimpleClientHttpRequestFactory` — `ServingBeans.java:102-107`
JDK 裸 `HttpURLConnection`,**无连接池**,每次调用 llm_service 都新建 TCP(+TLS)连接。配合虚拟线程并行 embedding 会形成“连接风暴”并重复付握手成本。
**改法**:换成池化工厂(Apache HttpClient5 或 JDK `HttpClient` + `HttpComponentsClientHttpRequestFactory`),按 `max-per-route` 调优。

### 6. 无重试/退避,超时未分级 — 同上
embed / rerank / generate 共用 60s read timeout。
**改法**:给幂等的 embed/rerank 加有限重试 + 更紧超时,再配整体 deadline,llm_service 抖动时可返回部分结果而非整体卡 60s。

---

## 三、Postgres / pgvector

### 7. 连接池 max=10 会卡住并行 — `application.yml:14`
并行化(variant × 路由)后瞬时并发 DB 查询可能远超 10,池子会把并行又串行化。
**改法**:按预期并发调大 Hikari,或给 fan-out 设上限,两者匹配。

### 8. dense ANN 查询的过滤可能打不到索引 — `AssetRetrievalEmbeddingMapper.xml:60-97`
`ORDER BY embedding_vector <=> ...` 上叠了 `snapshot_id IN (...)`、`embedding_dim=`、JSONB `@>`、`EXISTS` 子查询。pgvector 的 HNSW/IVFFlat 对强前置过滤不友好——过滤选择性高时,ANN 取回候选过滤后可能不足 topK,甚至退化为精确扫描。
**改法**:确认 HNSW 索引存在、调 `hnsw.ef_search`;pgvector 0.8 可开 `hnsw.iterative_scan`;`EXISTS` 段每行解析 JSONB(`:89`),建议把顶层 section title 预计算成列再建索引。

---

## 四、内存 / 缓存

### 9. SessionStore 的 session 永不过期 — `SessionStore.java:21`
每个 session 仅限 10 条 turn,但 `ConcurrentHashMap` 里的 **session 本身从不清理**,长期运行是慢性内存泄漏。且为进程内,多实例部署时多轮上下文失效。
**改法**:换成带 TTL/容量上限的缓存(Caffeine);要横向扩展则挪到 Redis。

### 10. 增加精确 query 的 L1 缓存
现状只有 pgvector 语义缓存(L2,需先算 embedding)。对完全相同的 query 文本做 hash → ContextPack 的 L1 缓存,可连 embedding 一起省掉。

---

## 五、可观测性(已不错,补两项)
已有 Micrometer + 每路由候选数 + rerank fallback。可再加:
- 缓存命中率 gauge;
- LLM 调用次数/延迟直方图(区分 hyde/embed/rerank);
- Hikari 池饱和度。
正好用于验证第 1/2/7 项改动效果。

---

## 落地优先级建议
1. **先做 3(缓存前移)+ 1/2(并行化)+ 5(连接池)**:纯收益、风险低、互相配合,可显著拉低 p50/p95。
2. **第 7 必须和 1/2 一起调**,否则并行被池子吃掉。
3. **4 和 8 收益大但涉及召回/语义**,建议配 A/B 或离线评测后再上。
