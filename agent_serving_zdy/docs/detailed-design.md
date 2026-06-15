# agent_serving_zdy 详细设计文档

> 模块：CoreMasterKB 检索服务 `agent_serving_zdy`
> 技术栈：Java 21 / Spring Boot 3.2.5 / MyBatis 3.0.3 / PostgreSQL + pgvector
> Maven 坐标：`com.coremasterkb:agent-serving:0.1.0` · 监听端口 **8081**
> 编写日期：2026-06-15

本文是检索服务的组件级实现设计，覆盖架构分层、数据模型、检索主链路、可插拔策略、多域路由与连接池、配置热重载、对外 API、持久化契约、可观测性、部署与关键设计取舍。与 `software-design-spec.md`（评分举证摘要）互补，本文更偏完整工程实现细节。

---

## 1. 概述

### 1.1 模块定位

`agent_serving_zdy` 是旧 Python `agent_serving` 的 Java 重写版，承担 CoreMasterKB 的**在线检索（serving）**职责：接收自然语言查询，经过查询理解 → 多路召回 → 融合 → 重排 → 上下文组装，返回结构化的"证据上下文包"（`ContextPack`）供下游 LLM 问答消费。

它在系统中是只读消费方：
- 与 `knowledge_mining` 不直接通信，只通过 `asset_core` 数据库交接——serving 只读 mining 已 `publish_release` 的 active release。
- 调 `llm_service`（默认 8900）做 embedding / rerank / LLM 生成。
- 向 `main_control_service`（默认 8910）拉取每域配置（详见 §8 配置热重载）。

### 1.2 设计目标

| 目标 | 落地手段 |
|------|---------|
| **可扩展** | 召回 / 融合 / 重排三处均接口 + 策略模式，新增实现不动主链路 |
| **高可用** | 单路召回异常隔离；重排级联降级（model→llm→score）保证部分可用 |
| **多域** | 同一进程支撑多知识域，配置与 HikariCP 连接池按域隔离 |
| **可热更新** | 配置改动经 main_control 下发，内存快照 volatile 原子替换，不重启 JVM |
| **可观测** | 检索全链路 trace + Micrometer/Prometheus 指标 + AOP 查询日志落库 |
| **低尾延迟** | Java 21 虚拟线程并行化 embedding/HyDE 等 IO 密集调用 |

### 1.3 技术选型理由

| 选型 | 理由 |
|------|------|
| Java 21 虚拟线程 | embedding/HyDE 多文本并行，墙钟时间从"求和"降为"取最大"，低成本压尾延迟 |
| Spring Boot 3.2.5 | DI 装配可插拔策略 Bean；actuator 直出 Prometheus 指标 |
| MyBatis（手写 SQL） | pgvector ANN、FTS、JSONB 过滤需精细控制 SQL，ORM 抽象不合适 |
| Postgres + pgvector | 单库内同时支撑关系/全文/向量检索，免引入独立向量库 |
| jieba-analysis | 中文分词支撑 FTS/BM25 关键词路 |

---

## 2. 分层架构

按 DDD 思想单向向内依赖，划分为 10 个职责清晰的包：

```
api/            薄控制器：SearchController / AdminController / HealthController / GlobalExceptionHandler
  │             （只做 IO 编解码与异常翻译，零业务逻辑）
application/    应用编排：SearchService（主用例）/ ContextAssembler / QueryUnderstandingEngine
  │             MultiQueryExpander / RetrievalRouter / SemanticCacheService / SessionStore / TreeNavigator
pipeline/       检索编排：RetrievalOrchestrator + 融合策略（FusionStrategy → RRF/WeightedRRF/Identity）
retrieval/      召回策略：Retriever 接口 + Dense/FTS/Entity 实现 + GraphExpander
rerank/         重排策略：Reranker 接口 + Llm/Service/Score 实现 + RerankPipeline（级联）
domain/         领域模型：不可变 record 值对象（RetrievalCandidate / ContextPack / QueryUnderstanding ...）
domainpack/     多域配置与路由：DomainRegistry / DomainPoolManager / DomainRoutingDataSource / ConfigReloadService
evidence/       证据角色：EvidenceRoleClassifier
observability/  可观测：SearchMetrics / QueryLogAspect / QueryLogService / TraceCollector
infrastructure/ 外部出口：EmbeddingClient / LlmClient / MainControlClient / PgConfig / ServingTemplates
mapper/ entity/ repository/  持久化：MyBatis Mapper 接口 + XML + 实体 + AssetRepository/SchemaAdapter
config/         装配：ServingBeans（策略 Bean 注册）/ ServingProperties / CorsConfig
```

**分层原则**：
- `api` 极薄，业务全部在 `application`；
- `domain` 不依赖任何框架，纯值对象；
- 所有外部依赖（LLM、DB、main_control）收敛在 `infrastructure` 与 `domainpack`，便于替换与测试 mock。

---

## 3. 关键数据模型

核心领域对象均为**不可变 record**，提供 `withXxx()` 派生新实例（见 `RetrievalCandidate`）。

| 模型 | 角色 | 关键字段 |
|------|------|---------|
| `SearchRequest` | API 入参 | query（必填）、domain、channel、scope、mode、sessionId、complexityHint、debug |
| `QueryUnderstanding` | 查询理解结果 | intent、queryComplexity、entities、keywords、subQueries、scope、evidenceNeed、source |
| `RetrievalQuery` | 单次检索输入 | query、keywords、entities、embedding、subQueries、intent、scope、sectionPrefixes |
| `RetrievalCandidate` | 候选 | retrievalUnitId、score、source、metadata、**scoreChain** |
| `ScoreChain` | 打分链 | rawScore → fusionScore → rerankScore + routeSources |
| `RetrievalRoutePlan` | 路由计划 | routes(List\<RouteConfig\>)、fusion、rerank、assembly、expansion |
| `ContextPack` | API 出参 | query、items、relations、sources、evidenceGroups、issues、suggestions、debug |
| `Trace`/`RouteTrace`/`RerankTraceStep` | 可观测 | 逐阶段/逐路由/逐重排级决策留痕 |

**设计要点 — ScoreChain 可解释性**：把"原始分→融合分→重排分"三段打分显式建模并随候选透传（`RetrievalCandidate.withScoreChain`），使最终排序对调试完全可解释，是检索系统可维护性的关键设计。

**检索对象约定**：种子结果来自 `asset_retrieval_units`（含 embedding，存 `asset_retrieval_embeddings`）；段落级信息（`section_path`、`metadata_json`、`entity_refs_json`）在 `asset_raw_segments` 上，二者通过 `source_segment_id` 关联。这套语义词表（`block_type`/`semantic_role`/`unit_type`/15 种 RST `relation_type`/`facets_json` scope key）是 mining↔serving 必须对齐的硬契约。

---

## 4. 检索主链路

入口 `SearchService.search(SearchRequest)`（`application/SearchService.java`），完整阶段（每段经 `TraceCollector` 留痕）：

```
SearchController.search()  （薄：仅编解码 + 日志）
  └─> SearchService.search(request)
        0.  Session：若带 sessionId，取历史问题拼到 QU query 前（指代消解）
        ★   乐观启动原始 query 的 HyDE embedding future（与 QU 并行，虚拟线程）
        1.  Domain Profile 加载（DomainPackReader）
        2.  QueryUnderstanding：意图/复杂度/实体/关键词/子查询（LLM 优先，规则兜底）
        3.  RetrievalRouter.route()：复杂度为主 + 意图覆盖 → RetrievalRoutePlan
        4.  解析 domain/channel；DomainPoolManager.getDataSource() 校验 DB 可达
        ── DomainContext.set(domain) → 本线程后续 DB 走该域连接池 ──
        3.4 TreeNavigator.inferSections()：按实体推断相关章节（软加权 / 硬过滤）
        3.5 MultiQueryExpander.expand()：原始 query + 最多 2 个 LLM 变体
        5.  Embedding：对所有 variant + sub-query 并行 HyDE embedding（虚拟线程 fan-out）
        5.5 SemanticCacheService.lookup()：pgvector 语义缓存（命中即返回，跳过后续）
        6.  RetrievalOrchestrator.execute() × 每个 variant/sub-query：多路召回 → 合并候选
        7.  FusionStrategy.fuse()：weighted_rrf / rrf / identity
        8.  RerankPipeline.rerank()：model→llm→score 级联 + 6 步后处理
        9.  ContextAssembler.assemble()：图扩展 + 组装 ContextPack
        9.5 SemanticCacheService.store()（best-effort）
        9.6 SessionStore.recordTurn()
        ── finally: DomainContext.clear() ──
        10. debug=true 时附 trace/route_traces/understanding 等调试信息
  <── ContextPack
```

### 4.1 核心设计思想：问题放大

不是"拿原始问题查一次"，而是**一个问题 → 多个查询（原始 + ≤2 变体 + ≤4 子查询）× 多路召回器 → 海量候选融合收敛**。每个 variant/sub-query 都跑一遍 `orchestrator.execute()`，结果合并后统一融合、重排。

### 4.2 性能关键点

- **embedding 并行**：原始 query 的 HyDE future 在 QU **之前**就乐观启动（`SearchService.java:129`），step 5 收集所有 variant embedding 时复用，总延迟 ≈ 最慢单次 HyDE 而非求和。
- **语义缓存前置**：缓存查找放在 embedding 之后、重检索之前；命中则直接返回 `ContextPack`，跳过召回/融合/重排/组装。
- **DB 路由线程绑定**：`DomainContext.set/clear()` 用 ThreadLocal 把本次请求的所有 DB 操作绑定到对应域的连接池。

---

## 5. 可插拔策略设计

三处扩展点均以**策略模式 + 接口隔离**实现，对扩展开放、对修改封闭，Bean 在 `config/ServingBeans` 装配。

### 5.1 召回策略 `Retriever`

```java
public interface Retriever {
    List<RetrievalCandidate> retrieve(RetrievalQuery query, List<String> snapshotIds, int topK);
}
```

| 实现 | 路由名 | 机制 |
|------|--------|------|
| `FtsRetriever` | `lexical_bm25` | Postgres 全文检索 / BM25，jieba 中文分词 |
| `DenseVectorRetriever` | `dense_vector` | pgvector 余弦 ANN（服务端排序，JVM 不做向量计算） |
| `EntityExactRetriever` | `entity_exact` | 实体精确匹配 |

`RetrievalOrchestrator`（`pipeline/RetrievalOrchestrator.java`）按 route plan 执行启用路由：
- 路由未注册 → trace `not_registered` 跳过；
- `dense_vector` 无 embedding → trace `no_embedding` 自动跳过；
- **单路异常隔离**：每路 try/catch，失败记入 `RouteTrace` 而不中断其余路；
- 候选 source 归一化为规范路由名。

### 5.2 融合策略 `FusionStrategy`

```java
public interface FusionStrategy {
    List<RetrievalCandidate> fuse(List<RetrievalCandidate> candidates, RetrievalRoutePlan routePlan);
}
```

实现 `RRFFusion` / `WeightedRRFFusion` / `IdentityFusion`，由 `FusionConfig.method()` 选择。`RetrievalRouter` 规则：启用路由 > 1 时用 `weighted_rrf`（RRF k=60），否则 `identity`。

### 5.3 重排策略 `Reranker` + `RerankPipeline`（级联降级）

```java
public interface Reranker {
    // 返回 null 表示本级无法产出，触发降级到下一级
    List<RetrievalCandidate> rerank(List<RetrievalCandidate> candidates, QueryUnderstanding understanding);
}
```

`RerankPipeline`（`rerank/RerankPipeline.java`）级联 **model → llm → score**：
- model：模型重排（Service/Zhipu）；
- llm：仅当 `rerank.method ∈ {llm, cascade}` 时尝试；
- score：兜底，**必成功**（按已有分排序）。
- 前一级返回 null 或抛异常即降级，每级留 `RerankTraceStep`（含 latency、in/out count、失败 reason）。

级联后**统一 6 步后处理**：
1. 按 `source_segment_id` 去重（保留最高分）；
2. 低价值类型（`heading`/`toc`/`link`）× 0.5 降权；
3. 文本相似度去重（字符 bigram Jaccard > 0.9，兼容中英文免分词）；
4. 回填 `ScoreChain.rerankScore`；
5. 最低分阈值过滤（< 0.01 剔除）；
6. 截断到 `assembly.maxItems`（默认 10）。

> **设计价值**：`null 即降级` 的契约把"外部 LLM 不稳定"这一现实约束内建进类型语义，调用方无需写任何降级分支。

### 5.4 图扩展的分层归属

`graph_expand` **不作为召回通道**，而置于**组装阶段**（`ContextAssembler` + `retrieval/GraphExpander`），由 `AssemblyConfig.relationExpansion / relationTypes / maxRelationDepth` 控制。理由：它是对已选种子的**邻域补全**（沿 RST 关系扩展上下文），而非独立打分召回——这是一处经过权衡的分层归属决策。

`ContextAssembler` 用 20 种 RST 关系权重（`elaborates`=1.5 ... `same_parent_section`=0.3）作为扩展项初始分，并把关系类型映射到证据角色（support/background/...）。上下文有 3000 token（≈12000 字符）压缩预算。

---

## 6. 路由策略（intent × complexity 两层）

`RetrievalRouter.route()`（`application/RetrievalRouter.java`）采用两层策略：

1. **复杂度层（主选择器）** `queryComplexity`：
   - `simple` → `entity_exact`(w=1.5) + `lexical_bm25`(w=1.0)
   - `medium` → `lexical_bm25`(w=1.0) + `dense_vector`(w=0.9)
   - `complex` → 三路全开 + 默认图扩展
2. **意图层（覆盖）**：域 profile 提供 per-intent route policy 时覆盖复杂度默认；内置意图策略含 `command_usage`（entity_exact 主导）、`concept_lookup`（dense 主导）、`troubleshooting`、`comparison` 等。

意图还驱动：
- **rerank 方法**：`troubleshooting/comparison/procedure` 默认 `cascade`；complex 或需比较时也 cascade；否则 `score`。（精度：域 override > 内置意图默认 > 复杂度默认）
- **图扩展关系链**：`troubleshooting`→因果链（causes/results_in/enables...）、`comparison`→对比（contrasts_with/parallels）、`procedure`→目的/使能（purposes/enables/sequences）。

---

## 7. 多域路由与连接池隔离

```
请求 domain → DomainContext.set(domain)（ThreadLocal）
            → DomainRoutingDataSource 按 ThreadLocal 选池
            → DomainPoolManager 提供该域 DataSource
```

`DomainPoolManager`（`domainpack/DomainPoolManager.java`）：
- 每域按其内联 `DatabaseConfig` 懒建专属 HikariCP 池（`hikari-<domain>`，默认 min=2/max=10/连接超时 5s）；无可用 DB 配置则复用默认 DataSource。
- 建池时 `conn.isValid(3)` 探活，失败抛 `IllegalStateException("domain_database_unavailable")`。
- **`invalidate()` 按签名增量重建**：reload 后只关闭/丢弃 DB 签名变化或被移除的域池，未变域池不动，避免全量重连抖动。
- `@PreDestroy` 统一关闭自有池。

---

## 8. 配置热重载架构

目标：配置改动**不重启 JVM** 生效（非代码热更新）。

```
kb-ui 改配置 → main_control_service(8910, 配置单一事实源) → 点「配置热重载」
  → main_control POST /api/v1/admin/reload-serving 向各 enabled 域 serving_url 扇出
  → serving(8081) AdminController.reloadConfig()
  → ConfigReloadService.reload()：MainControlClient.fetchServingConfig() 回拉聚合配置
  → DomainRegistry.apply(snapshot) → DomainPackReader.apply(snapshot) → DomainPoolManager.invalidate()
  → 内存快照 volatile 原子替换，读路径无锁
```

关键设计（`domainpack/ConfigReloadService.java`）：
- **配置源解耦**：serving 不再直接读本地 `domain_registry.yaml` / `scenario_packs`，改走 `MainControlClient` HTTP 拉取；database 配置**内联下发**（不再引用环境变量名），彻底解耦。
- **原子替换**：registry/packReader 以 `apply(snapshot)` 整体替换 volatile 引用；顺序固定为 registry → packs → invalidate（pool manager 读 registry）。
- **启动不阻断**：`@PostConstruct` 调 reload，失败 try/catch 降级为空配置（lenient），靠 reload 端点恢复。
- **本地回退**：main_control 不可达时回退读本地 `domain_registry.yaml` + `scenario_packs/<pack>/domain.yaml`（IntelliJ/测试场景），解析 legacy schema（`database_url_env` → env → JDBC URL）。

> 配套计划文档：`docs/2026-06-11-serving-config-hot-reload-plan.md`（main_control M1–M3、serving S1–S13 文件级清单）。

---

## 9. 对外 API

基路径 `/api/v1`。

### 9.1 `POST /api/v1/search`（`api/SearchController`）

请求体（`SearchRequest`）：

| 字段 | 类型 | 说明 |
|------|------|------|
| `query` | string | **必填**，空白报 `query_required` |
| `domain` | string | 知识域，如 `cloud_core_network`；空用默认域 |
| `channel` | string | 发布通道（prod/staging）；null 用 registry 默认 |
| `scope` | object | 范围约束（product/version 等） |
| `mode` | string | 检索模式，默认 `evidence` |
| `sessionId` | string | 多轮上下文累积；null 即无状态 |
| `complexityHint` | string | 强制路由档位 `simple\|medium\|complex`；非法报错；null 自动推断 |
| `debug` | bool | true 时响应附 `debug`（trace/route_traces/understanding/route_plan...） |

响应：`{ query, items, relations, sources, evidence_groups, issues, suggestions[, debug] }`。

### 9.2 `POST /api/v1/admin/reload-config` / `GET /api/v1/admin/config-status`（`api/AdminController`）
热重载触发与配置加载状态查询。

### 9.3 `GET /actuator/health`（`api/HealthController`）+ `GET /actuator/prometheus`
健康检查（自定义 Controller）+ Prometheus 抓取端点。

> `application.yml` 中 actuator **只暴露 prometheus**，health 故意不进暴露集，避免与自定义 `HealthController` 的 handler-mapping 冲突。

### 9.4 异常翻译
`GlobalExceptionHandler` 把领域异常翻译为 HTTP（如 `query_required` → 400、`domain_database_unavailable` → 503/相应码）。

---

## 10. 持久化与数据契约

- **MyBatis**：`mapper-locations: classpath:mapper/*.xml`，9 个 Mapper（Asset* + SemanticCache + ServingQueryLog）。
- **核心读表**：`asset_publish_releases`（解析 active release/build/snapshot）、`asset_retrieval_units`（种子单元）、`asset_retrieval_embeddings`（向量）、`asset_raw_segments`(+relations)（段落与 RST 关系）、`asset_documents`（源文档）。
- **scope 解析**：domain+channel → active release → build → snapshotIds，所有检索限定在 snapshot 集合内。

### 10.1 ⚠️ 已知风险（dense 检索可能用不上 HNSW 索引）

`AssetRetrievalEmbeddingMapper.xml` 的 `selectTopKByVector` 查询：
```sql
ORDER BY re.embedding_vector <=> #{queryVector}::vector
```
查的是 `embedding_vector`（TEXT 列）并在查询时强转 `::vector`。若生产库 `asset_core` 的 pgvector 列 + HNSW 索引建在另一列（如 `embedding_vector_vec`，由触发器从 JSON 填充），则该查询**不会命中 HNSW 索引**，可能退化为精确扫描。叠加的强前置过滤（`embedding_dim=`、`facets_json @>`、`section_path` 的 `EXISTS` 子查询每行解析 JSONB）会进一步降低 ANN 友好度。**需核实生产库实际列与索引，必要时改查向量列并调 `hnsw.ef_search`。**

---

## 11. 可观测性

- **指标**（`observability/SearchMetrics`，Micrometer→Prometheus）：意图分布、每路由候选数（`recordRouteCandidates`）、rerank 耗时与 fallback 命中级、空 scope 无结果计数。
- **链路 trace**（`TraceCollector`）：逐阶段 start/end + 输出摘要，debug=true 时随响应返回。
- **查询日志落库**（`QueryLogAspect` AOP + `QueryLogService`）：无侵入记录查询到 `serving_query_logs`。

> 优化评审（`docs/optimization-notes.md`）建议补：缓存命中率 gauge、LLM 调用分类直方图（hyde/embed/rerank）、Hikari 池饱和度。

---

## 12. 配置与部署

### 12.1 关键配置（`application.yml` + `.env`）

| 配置 | 默认 | 说明 |
|------|------|------|
| `server.port` | `${SERVER_PORT:8081}` | 集成部署端口 8081 |
| `serving.main-control.base-url` | `:8910` | 配置单一事实源 |
| `serving.llm.base-url` | `:8900` | llm_service（embedding/rerank/generate） |
| `serving.embedding.{model,dimensions}` | embedding-3 / 1024 | embedding 契约（维度换则历史向量失效） |
| `spring.datasource` + Hikari | min 2 / max 10 | 默认 DataSource + 本地回退 |

> ⚠️ embedding 契约最脆弱：mining 与 serving 都调 llm_service 的 `/api/v1/models/embeddings`，模型+维度由 llm_service 单一 active model 决定；dense 查询带 `AND embedding_dim=?`，一旦换不同维度模型历史向量全部查不到，须重挖。

### 12.2 部署
- 独立镜像：`agent_serving_zdy/Dockerfile`（注意其 `EXPOSE 8082` 为遗留值，集成部署以 8081 为准）。
- 集成部署：纳入仓库根 docker-compose + supervisord 单容器 All-in-One（6 服务统一编排），supervisord 给 serving 注入 `SERVER_PORT=8081` 与 `SERVING_MAIN_CONTROL_BASEURL`。

---

## 13. 测试策略

三级分层（`pom.xml` surefire/failsafe + `e2e` profile）：
- **L1 单测**（surefire，排除 `pg-integration,e2e`）：domain record、各策略、router、rerank pipeline、fusion、JsonUtils 等。
- **L2 集成**（failsafe，`pg-integration`）：Mapper IT、Retriever IT、Repository IT、DomainRoutingIT（用 H2/真 PG）。
- **L3 E2E**（`e2e` profile）：`system/*E2ETest`（Search/Health/ErrorHandling 端到端）。

约 39 个测试类，与主代码接近 1:1，按层覆盖。

---

## 14. 关键设计取舍汇总

| 决策 | 取舍 |
|------|------|
| 召回三路 vs 图扩展放组装 | 图扩展是邻域补全非独立打分，归组装层职责更清晰 |
| 重排 `null 即降级` | 把外部 LLM 不稳定内建进接口契约，调用方零降级代码 |
| MyBatis 手写 SQL vs ORM | pgvector ANN / FTS / JSONB 过滤需精细控制，放弃 ORM 抽象 |
| 配置内联下发 vs 引用环境变量 | 内联彻底解耦 serving 与文件/环境，支撑热重载原子替换 |
| 连接池按签名增量重建 vs 全量 | 增量避免未变域无谓抖动 |
| 两层路由（复杂度主 + 意图覆盖） | 复杂度决定召回深度，意图微调权重/重排/扩展，兼顾通用与定制 |
| embedding future 乐观前置启动 | 与 QU 并行，命中缓存路径几乎零额外延迟 |

---

## 15. UML 图集

模型设计以 Mermaid UML 图呈现于 **`docs/uml-diagrams.md`**，含 7 张图：

| 图 | 类型 | 说明 |
|----|------|------|
| ① 组件/分层依赖图 | Component | 10 包单向向内依赖 + 外部系统（main_control/llm_service/PG/kb-ui） |
| ② 领域模型类图 | Class | SearchRequest→QueryUnderstanding→RoutePlan→Candidate(ScoreChain)→ContextPack |
| ③ 策略模式类图 | Class | Retriever / FusionStrategy / Reranker 三族实现 + RerankPipeline 级联 |
| ④ 检索主链路时序图 | Sequence | `POST /search` 全阶段（含 embedding 并行、缓存前置、异常隔离、级联重排） |
| ⑤ 配置热重载时序图 | Sequence | kb-ui→main_control 扇出→serving 回拉→volatile 原子替换 |
| ⑥ 多域连接池路由类图 | Class | DomainContext / DomainRoutingDataSource / DomainPoolManager / DatabaseConfig |
| ⑦ 部署图 | Deployment | supervisord 单容器 All-in-One + 外部 PG/Prometheus |

> 渲染：GitHub/IDE 直接预览；导出 PNG 用 `mmdc` 或 mermaid.live。

---
