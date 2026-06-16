# Python → Java 重构文档 · agent_serving → agent_serving_zdy

> 评价人：张大勇（z30031510）　团队：AI 开发团队
> 范围：将旧 Python 检索服务 `agent_serving` 重写为 Java 版 `agent_serving_zdy`（Java 21 / Spring Boot 3.2.5 / MyBatis / Postgres+pgvector，端口 8081）
> 整理日期：2026-06-16

本文记录检索服务从 Python 到 Java 的**重构（重写）**全过程：重构动机与原则、语言/运行时映射、模块到 Java 包的映射、**行为对齐契约**、重写中顺带完成的结构性重构与缺陷修复、以及行为差异与已知风险。

> 说明：Python 原版 `agent_serving` 已不在当前仓库（被 Java 版取代）。本文的对齐基线来自两处可核验来源：① Java 源码中显式标注的 `Matches Python's ... behavior` / `ported from Python ...` Javadoc 契约；② 演进记录 `docs/2026-06-03-agent-serving-zdy-evolution.md`。

---

## 1. 重构动机与目标

| 动机 | 说明 |
|------|------|
| 运行时统一 | 团队后端检索服务统一到 JVM 技术栈，便于与既有 Java 体系的部署/监控/连接池治理集成 |
| 性能 | 用 Java 21 虚拟线程替代 Python 的 asyncio/GIL 受限并发，压低 embedding/HyDE 等 IO 密集调用的尾延迟 |
| 工程化 | 借强类型 + DI 容器把 Python 中靠约定维系的策略装配、配置加载显式化、可测试化 |
| 可维护性 | 把检索打分链、路由策略、降级逻辑用接口 + 不可变模型固化，降低后续演进风险 |

**首要约束 —— 行为等价优先**：重写以"对齐 Python 既有检索行为"为第一原则，再在不破坏对齐的前提下做结构性改进。关键算法（意图词表、路由权重、RST 关系、组装规则）逐一对齐，并以单测锁定。

---

## 2. 重构策略与原则

1. **对齐基线显式化**：凡与 Python 行为对齐的类，在 Javadoc 标注 `Matches Python's X behavior`，作为重构契约（见 §5）。
2. **行为先于美化**：先做到等价（含 Python 的常量集、关键词集、阈值），再重构结构；不在对齐阶段引入行为漂移。
3. **分层重构**：按 DDD 把 Python 的扁平模块拆成 10 个 Java 包（`api/application/domain/pipeline/retrieval/rerank/domainpack/evidence/observability/infrastructure`），单向向内依赖。
4. **以测试锁定等价**：39 个测试类 / 214 个 `@Test`，对路由权重、融合、级联降级、组装顺序逐一断言（`mvn test` 全绿，演进记录中一轮为 176 通过/0 失败）。
5. **重写中识别并修复缺陷**：阅读 Python 逻辑时发现的死代码/隐患在 Java 侧顺手修正或标注（见 §6 / §8）。

---

## 3. 语言与运行时映射

| 关注点 | Python `agent_serving` | Java `agent_serving_zdy` | 重构收益 |
|--------|------------------------|--------------------------|---------|
| Web 框架 | FastAPI（`search()` 端点） | Spring Boot Web（`SearchController`，薄编解码层） | DI 装配、统一异常翻译 |
| 数据模型 | `dataclass`（部分 frozen，如 `RawSegmentData`） | **不可变 `record`** + 紧凑构造器校验 + `withXxx()` 派生 | 编译期不可变保证，消除可变状态共享 |
| 入参校验 | 运行时/pydantic 式 | `record` 紧凑构造器抛 `IllegalArgumentException`（`SearchRequest.java:32-41`） | 构造即合法 |
| 并发 | asyncio（受 GIL 限制） | **Java 21 虚拟线程**（`Executors.newVirtualThreadPerTaskExecutor`，`SearchService.java:54`） | embedding/HyDE fan-out，墙钟取最大而非求和 |
| 数据访问 | 手写 SQL（DB-API/驱动） | **MyBatis**（9 个 Mapper XML，手写 pgvector ANN/FTS/JSONB SQL） | 保留 SQL 精细控制，去掉胶水代码 |
| 多态/策略 | duck typing + 函数注册 | **接口 + 策略模式 + DI Bean**（`Retriever`/`FusionStrategy`/`Reranker`，共 12 接口） | 扩展点显式、可单测、可替换 |
| 配置加载 | 直接读 YAML 文件 | `ConfigReloadService` HTTP 拉取 + volatile 原子替换（见 §7） | 不停机热重载 |
| LLM/Embedding 客户端 | requests/httpx | `EmbeddingClient`/`LlmClient`/`LlmServiceReranker`（RestClient） | 收敛在 `infrastructure` |
| 分词 | Python jieba（写侧） | `com.huaban:jieba-analysis`（`FtsRetriever`，对齐写侧分词） | 读写分词一致 |
| Prompt 模板 | `SERVING_TEMPLATES` 常量 | `infrastructure/ServingTemplates.java`（ported） | 启动自动注册 serving-* 模板 |

---

## 4. 模块 → Java 包/类映射

| Python 组件（逻辑） | Java 落点 | 对齐说明 |
|---------------------|-----------|---------|
| `search()` 端点编排 | `application/SearchService.search()` | `Matches Python's search() endpoint behavior` |
| QueryUnderstandingEngine | `application/QueryUnderstandingEngine` | 7 种意图、意图关键词集、中英停用词集**与 Python 一致** |
| RetrievalRouter | `application/RetrievalRouter` | `_BUILTIN_ROUTES` / `_DEFAULT_ROUTE_POLICY` 对齐 |
| 多路检索编排 | `pipeline/RetrievalOrchestrator` | 注册 `lexical_bm25/dense_vector/entity_exact` 三路 |
| 召回器 | `retrieval/{Fts,DenseVector,EntityExact}Retriever` | FtsRetriever 分词对齐写侧 Python jieba |
| 融合 | `pipeline/{RRF,WeightedRRF,Identity}Fusion` | RRF k=60 |
| 重排 | `rerank/RerankPipeline` + `LlmServiceReranker`（ports `LLMServiceReranker`） | 级联 model→llm→score |
| ContextAssembler | `application/ContextAssembler` | `Matches Python's ContextAssembler behavior`；Issue 类型常量 match Python |
| EvidenceRoleClassifier | `evidence/EvidenceRoleClassifier` | `Aligned with Python evidence/role_classifier.py`（注：主链路尚未集成，见 §8） |
| 域配置/画像 | `domainpack/ServingDomainProfile` | route policy 对齐 Python `_DEFAULT_ROUTE_POLICY` |
| Prompt 模板 | `infrastructure/ServingTemplates` | ported from Python `SERVING_TEMPLATES` |
| GraphExpander | `retrieval/GraphExpander` | 组装阶段邻域扩展（非检索通道） |

---

## 5. 行为对齐契约（重构验收基线）

以下是 Java 源码中显式声明的 Python 行为对齐点，**任何后续改动需保持或显式声明偏离**：

| 文件:行 | 契约 |
|---------|------|
| `application/SearchService.java:31` | `Matches Python's search() endpoint behavior` |
| `application/QueryUnderstandingEngine.java:19` | 对齐 Python QU：7 意图 / 实体抽取 / jieba / scope / 子查询 / EvidenceNeed / 歧义检测 |
| `application/QueryUnderstandingEngine.java:37,74,415` | 意图关键词集、中英停用词集、关键词优先级匹配 **same as Python** |
| `application/RetrievalRouter.java:16,47` | `Matches Python's RetrievalRouter behavior`；`_BUILTIN_ROUTES` 对齐 |
| `application/ContextAssembler.java:25,37` | `Matches Python's ContextAssembler behavior`；Issue 类型常量 match Python |
| `domainpack/ServingDomainProfile.java:40` | route policy 对齐 Python `_DEFAULT_ROUTE_POLICY` |
| `evidence/EvidenceRoleClassifier.java:11` | `Aligned with Python evidence/role_classifier.py` |
| `infrastructure/ServingTemplates.java:6` | ported from Python `SERVING_TEMPLATES` |
| `rerank/LlmServiceReranker.java:14` | ports Python `LLMServiceReranker` |
| `retrieval/FtsRetriever.java:218` | jieba 分词 matches write-side Python jieba |

---

## 6. 重写中完成的结构性重构

重写不是逐行翻译，同时对 Python 实现做了如下结构性改进（不改变外部行为）：

1. **打分链显式建模**：新增 `ScoreChain`（rawScore→fusionScore→rerankScore + routeSources）随候选透传（`RetrievalCandidate.withScoreChain`），把 Python 中隐式的多段打分变为可解释的一等对象。
2. **可插拔点接口化**：将 Python 的函数/注册式多态升级为 `Retriever`/`FusionStrategy`/`Reranker` 接口 + 策略模式，新增实现对扩展开放、对修改封闭。
3. **降级契约内建类型**：`Reranker.rerank()` 约定"返回 `null` 即降级"，`RerankPipeline` 级联 model→llm→score，把"外部 LLM 不稳定"内建进接口语义，调用方零降级分支。
4. **召回路异常隔离**：`RetrievalOrchestrator` 每路独立 try/catch + `RouteTrace` 留痕，单路失败不拖垮整体（`RetrievalOrchestrator.java:108-116`）。
5. **不可变领域模型**：Python frozen dataclass → Java `record` + `withXxx()`，全链路无可变共享态。
6. **分层归位**：明确 `graph_expand` 是**组装阶段邻域扩展**而非检索通道（Python/早期文档曾混淆），落为 per-intent `AssemblyConfig`。

### 重写中发现并修复的 Python 缺陷
| 缺陷 | 处理 |
|------|------|
| `EvidenceRoleClassifier` seed 分支为死代码（判断 `relationToSeed=="seed"` 恒 false） | Java 侧改判 `role=="seed"` 修复 |
| `RetrievalRouter.BUILTIN_ROUTES` 实为死代码（per-intent 权重真实来源是域 route policy） | 保留以对齐，但澄清复杂度档位 `COMPLEXITY_ROUTES` 才是主选择器 |

---

## 7. 重写后新增的能力（Python 版没有）

这些是借 Java 重写契机新建、Python 原版不具备的工程能力（详见各专题文档）：

- **多域连接池隔离**：`DomainPoolManager` 按域建专属 HikariCP 池，`DomainRoutingDataSource` + `DomainContext`(ThreadLocal) 按域路由。
- **配置热重载**：`ConfigReloadService` 以 main_control 为单一事实源、HTTP 拉取 + volatile 原子替换 + 连接池按签名增量重建，不重启 JVM（见 `software-engineering-evidence.md`）。
- **Prometheus 可观测**：6 个 Micrometer 指标 + AOP 查询日志落库 + 链路 TraceCollector（见 `2026-06-03-...-evolution.md` 特性 1）。
- **意图感知策略增强 / 树索引导航**：`RetrievalRouter` 意图→关系链/rerank、`TreeNavigator` 章节软加权（演进记录特性 3/4）。

---

## 8. 行为差异与已知风险（重构遗留，待核实/跟踪）

| 项 | 状态 |
|----|------|
| **端口**：早期 Java 镜像 `Dockerfile EXPOSE 8082`，集成部署实际 8081 | 以 8081 为准；独立镜像遗留值 |
| **dense 向量可能打错列**：`AssetRetrievalEmbeddingMapper.xml` 用 `embedding_vector`(TEXT) 做 `<=> ::vector`，生产库 pgvector 列+HNSW 索引为 `embedding_vector_vec` | **待核实**：可能用不上 HNSW，dense 召回退化 |
| **QU 意图词表分裂**：注册 llm_service 的 schema 用 `factoid/conceptual/...`，遗留 `prompts/query-understanding-system.txt`（src 未引用）用 `command_usage/...`；`navigational` 被 normalize 成 `general`（致 `deriveComplexity` 的 navigational→simple 为死分支） | 未处理（不影响主链路） |
| **EvidenceRoleClassifier 尚未接入主链路**：已对齐 Python `role_classifier.py` 但 `NOT integrated in main pipeline yet` | 跟踪：接入前不影响输出 |

---

## 9. 验证

- **单测对齐**：`cd agent_serving_zdy && mvn -o test` 全绿（演进记录一轮为 `Tests run: 176, Failures: 0`）。当前仓库 39 测试类 / 214 `@Test`，对路由权重、融合、级联降级、组装顺序逐一锁定等价。
- **三级测试**：L1 单测（surefire）/ L2 集成（failsafe `pg-integration`）/ L3 E2E（`-Pe2e`）。
- **对齐回归**：`RetrievalRouterTest`（command_usage/concept_lookup 权重）、`ContextAssemblerTest`（组装/排序）、`RerankPipelineTest`（级联降级）是行为等价的主要守门测试。

---

## 关联文档

| 文件 | 内容 |
|------|------|
| `docs/2026-06-03-agent-serving-zdy-evolution.md`（仓库根） | 重写后单轮特性演进（可观测/discourse/意图策略/树导航） |
| `agent_serving_zdy/docs/detailed-design.md` | 重写后的完整实现设计 |
| `agent_serving_zdy/docs/uml-diagrams.md` | 重写后架构/类/时序 UML |
| `agent_serving_zdy/docs/code-development-evidence.md` | 代码开发举证（含工作量与测试数据） |
