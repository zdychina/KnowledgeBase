# 软件实现设计文档 · agent_serving_zdy 检索服务

> 评价人：张大勇（z30031510）　团队：AI 开发团队
> 模块：CoreMasterKB 检索服务 `agent_serving_zdy`（Java 21 / Spring Boot 3.2.5 / MyBatis / Postgres+pgvector，端口 8081）
> 用途：青鸟「代码白盒评价 · 软件设计」评分项手工举证（软件实现设计文档）
> 整理日期：2026-06-15

本文是检索服务编码前/演进中的组件级软件实现设计，覆盖分层架构、关键数据模型、核心接口与设计模式、交互流程、配置热重载架构与关键设计取舍。对应软件设计评分规则 1.1（技术选型）、1.2（代码设计）、1.3（设计工具/UML）、1.4（AI 辅助设计）。

---

## 一、设计目标与技术选型（规则 1.1）

将旧 Python `agent_serving` 重写为 Java 检索服务，设计目标：

1. **可扩展**：召回通道、融合算法、重排策略均可插拔，新增不改动主链路。
2. **高可用**：单路异常隔离、重排级联降级，保证部分可用而非整体失败。
3. **多域**：同一服务支撑多个知识域，配置与连接池按域隔离。
4. **可热更新**：配置改动不重启 JVM。
5. **可观测**：检索链路全程 trace + 指标。

技术选型理由：

| 选型 | 理由 |
|------|------|
| Java 21 虚拟线程 | embedding/HyDE 等 IO 密集调用并行化，低成本压低尾延迟 |
| Spring Boot 3.2.5 | 依赖注入装配可插拔策略 Bean；actuator 直出 Prometheus 指标 |
| MyBatis | 检索 SQL（pgvector ANN、FTS、JSONB 过滤）需精细手写，ORM 不合适 |
| Postgres + pgvector | 一库内同时支撑关系/全文/向量检索，避免引入独立向量库 |

---

## 二、分层架构（规则 1.2）

按 DDD 分层划分，依赖单向向内，10 个职责清晰的包：

```
api/            薄控制器层：SearchController / AdminController / HealthController / GlobalExceptionHandler
  │（只做 IO 编解码与异常翻译，零业务逻辑）
application/    应用编排层：SearchService（主用例）/ ContextAssembler / QueryUnderstandingEngine
  │            MultiQueryExpander / RetrievalRouter / SemanticCacheService / SessionStore / TreeNavigator
pipeline/       检索编排：RetrievalOrchestrator + 融合策略（FusionStrategy 及实现）
retrieval/      召回策略：Retriever 接口 + Dense/FTS/Entity 实现 + GraphExpander
rerank/         重排策略：Reranker 接口 + Llm/Score/Service 实现 + RerankPipeline（级联）
domain/         领域模型：充血值对象/record（RetrievalCandidate / ContextPack / QueryUnderstanding ...）
domainpack/     多域配置与路由：DomainRegistry / DomainPoolManager / DomainRoutingDataSource / ConfigReloadService
evidence/       证据角色：EvidenceRoleClassifier
observability/  可观测：SearchMetrics / QueryLogAspect / TraceCollector / QueryLogService
infrastructure/ 外部出口：EmbeddingClient / LlmClient / MainControlClient / PgConfig
```

**分层原则**：`api` 极薄（只编解码），业务全在 `application`；`domain` 不依赖任何框架；外部依赖（LLM、DB、main_control）全部收敛在 `infrastructure` 与 `domainpack`，便于替换与测试 mock。

---

## 三、关键数据模型（规则 1.2）

核心领域对象（均为不可变 record，带 `withXxx()` 派生）：

| 模型 | 角色 |
|------|------|
| `SearchRequest` | 入参：query、domain、session、debug 开关 |
| `QueryUnderstanding` | 查询理解结果：intent、复杂度、实体、关键词、子查询 |
| `RetrievalQuery` | 单次检索输入：关键词 / 实体 / embedding |
| `RetrievalCandidate` | 候选：score + `ScoreChain`（rawScore→fusionScore→rerankScore）+ source + metadata |
| `RetrievalRoutePlan` | 路由计划：各路 `RouteConfig` + `FusionConfig` + `RerankConfig` + `AssemblyConfig` |
| `ContextPack` | 出参：items / relations / sources / evidence_groups / issues / suggestions |
| `Trace` / `RouteTrace` / `RerankTraceStep` | 可观测：逐阶段决策留痕 |

**设计要点**：`ScoreChain` 把"原始分→融合分→重排分"三段打分链显式建模并随候选透传，使最终排序对调试可解释——这是检索系统可维护性的关键设计。

**检索对象约定**：种子结果来自 `asset_retrieval_units`；段落级信息（section_path、metadata_json、entity_refs_json）在 `asset_raw_segments` 上，二者通过 `source_segment_id` 关联。

---

## 四、核心接口与设计模式（规则 1.2）

三处可插拔点均以策略模式 + 接口隔离设计，对扩展开放、对修改封闭：

### 1. 召回策略 `Retriever`（策略模式）
```java
public interface Retriever {
    List<RetrievalCandidate> retrieve(RetrievalQuery query, List<String> snapshotIds, int topK);
}
```
实现：`DenseVectorRetriever`（pgvector ANN）、`FtsRetriever`（全文 BM25）、`EntityExactRetriever`（实体精确）。
`RetrievalOrchestrator` 注册 `lexical_bm25 / dense_vector / entity_exact` 三路，按 route plan 启用，缺输入（如无 embedding）自动跳过，单路异常隔离不影响其余路。

### 2. 融合策略 `FusionStrategy`（策略模式）
```java
public interface FusionStrategy {
    List<RetrievalCandidate> fuse(List<RetrievalCandidate> candidates, RetrievalRoutePlan routePlan);
}
```
实现：`RRFFusion`、`WeightedRRFFusion`、`IdentityFusion`，由 `FusionConfig.method()` 选择。

### 3. 重排策略 `Reranker` + `RerankPipeline`（策略模式 + 责任链/级联降级）
```java
public interface Reranker {
    // 返回 null 表示本级无法产出，触发下一级降级
    List<RetrievalCandidate> rerank(List<RetrievalCandidate> candidates, QueryUnderstanding understanding);
}
```
`RerankPipeline` 级联：**model → llm → score**，前一级返回 null 或异常时降级到下一级，`score` 兜底必成功。级联后统一后处理 6 步：按 segment 去重 → 低价值类型（heading/toc/link）降权 → 文本相似度去重（字符 bigram Jaccard>0.9）→ 回填 ScoreChain → 最低分阈值过滤 → 截断到 maxItems。每级留 `RerankTraceStep`。

> 设计价值：`null 即降级` 的契约把"外部 LLM 不稳定"这一现实约束内建进类型语义，无需调用方写降级分支。

### 4. 图扩展的位置选择
`graph_expand` 不作为召回通道，而置于**组装阶段**（`ContextAssembler` + `GraphExpander`），由 `AssemblyConfig.relationExpansion / relationTypes / maxRelationDepth` 控制——因为它是对已选种子的邻域补全，而非独立打分召回。这是一处经过权衡的分层归属决策。

---

## 五、检索主链路交互流程（规则 1.2）

```
SearchController（薄）
  └─> SearchService.search()
        1. QueryUnderstandingEngine：意图/复杂度/实体/关键词
        2. MultiQueryExpander：原始 query → 多 variant + 子查询（问题"放大"）
        3. EmbeddingClient：variant/子查询 embedding（虚拟线程并行；可选 HyDE）
        4. SemanticCacheService：pgvector 语义缓存查找（命中即返回）
        5. RetrievalRouter：按 intent 取域 route_policy → RetrievalRoutePlan
        6. RetrievalOrchestrator.execute()：多 query × 三路召回 → FusionStrategy 融合
        7. RerankPipeline：model→llm→score 级联重排 + 后处理
        8. ContextAssembler（+ GraphExpander）：邻域扩展 + 组装 ContextPack
        9. EvidenceRoleClassifier：证据角色标注
  <── ContextPack（items/relations/sources/evidence_groups/issues/suggestions）
```

**核心设计思想**：不是"拿原始问题查一次"，而是"一个问题 → 多个查询 × 多路检索器 → 海量候选融合收敛"。per-intent 路由权重来自域 `route_policy`，内置默认按 queryComplexity（simple/medium/complex）决定。

---

## 六、配置热重载架构设计（规则 1.1 / 1.2）

让 serving 支持配置热重载（非代码热更新），目标架构：

```
kb-ui 改配置 → main_control_service(8910，配置单一事实源) → 点「配置热重载」
  → main_control 向各 enabled 域 serving_url 扇出 POST /api/v1/admin/reload-config
  → serving(8081) 回拉 GET /api/v1/serving-config 聚合配置
  → 内存快照 volatile 原子替换，不重启 JVM
```

关键设计：
- **配置源解耦**：serving 不再读本地 `domain_registry.yaml` / `scenario_packs`，改走 `MainControlClient` HTTP 拉取；database 配置内联下发，彻底解耦。
- **原子替换**：`DomainRegistry` / `DomainPackReader` 以 `apply(snapshot)` 对 volatile 引用整体替换，读路径无锁。
- **增量重建连接池**：`DomainPoolManager.invalidate(snapshot)` 按配置签名**只重建发生变化/被移除的域池**，未变域连接池不动，避免全量抖动。
- **启动降级**：serving 启动依赖 main_control，失败时 try/catch 降级 + 本地回退，重载端点兜底。

详见配套文档 `docs/2026-06-11-serving-config-hot-reload-plan.md`（含 main_control M1–M3、serving S1–S13 文件级改动清单）。

---

## 七、关键设计取舍（规则 1.2）

| 决策 | 取舍 |
|------|------|
| 召回三路 vs 图扩展放组装 | 图扩展是邻域补全非独立打分，归组装层而非召回层，职责更清晰 |
| 重排 `null 即降级` | 把外部 LLM 不稳定内建进接口契约，调用方零降级代码 |
| MyBatis 手写 SQL vs ORM | pgvector ANN / FTS / JSONB 过滤需精细控制，放弃 ORM 抽象 |
| 配置内联下发 vs 引用环境变量 | 内联下发彻底解耦 serving 与文件/环境，支撑热重载原子替换 |
| 连接池按签名增量重建 vs 全量重建 | 增量避免未变域无谓抖动 |

---

## 八、设计工具与 AI 辅助（规则 1.3 / 1.4）

- **架构可视化**：`docs/architecture/coremasterkb-v1.3-architecture.html` 架构说明。
- **链路/算法设计文档**：`docs/2026-06-10-search-endpoint-retrieval-flow.md`、`docs/2026-05-28-pipeline-algorithm-details.md`、`docs/serving-search-api-output-spec.md`。
- **AI 辅助设计（1.4）**：借助 AI 工具完成 Python→Java 架构映射、设计取舍评审、设计文档与优化笔记沉淀（见 `agent_serving_zdy/docs/optimization-notes.md`）。

---

## 关联举证文件清单

| 文件 | 对应规则 |
|------|----------|
| `agent_serving_zdy/docs/software-design-spec.md`（本文） | 1.1 / 1.2 / 1.3 / 1.4 总设计 |
| `docs/2026-06-10-search-endpoint-retrieval-flow.md` | 1.2 检索链路交互设计 |
| `docs/2026-05-28-pipeline-algorithm-details.md` | 1.2 pipeline 算法设计 |
| `docs/architecture/coremasterkb-v1.3-architecture.html` | 1.3 架构可视化 |
| `docs/2026-06-11-serving-config-hot-reload-plan.md` | 1.2 热重载架构设计 |
| `agent_serving_zdy/docs/optimization-notes.md` | 1.4 AI 辅助设计评审 |
