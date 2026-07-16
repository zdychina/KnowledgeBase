# 可插拔检索算子系统 — 实施计划（后端 + DB）

> **对应 PRD**：`2026-06-22-pluggable-retrieval-operator-system-prd.md`
> **范围**：后端 `com.coremasterkb.serving.operator` 全 package + 两张 DB 表 + 算子开发文档。**不含前端**（前端后续落 kb-ui）。
> **分支**：`v5`
> **状态**：后端全量交付（2026-06-22）—— WP-0~4（引擎+核心算子）+ WP-5（**全 17 个算子**）+ WP-6（范式持久化）。**前端 kb-ui 画布待续**。
>
> **算子目录已全实现（17 个）**：query_embed / query_understanding / hyde / multi_query / scope_resolve / dense_vector(textKind) / fts / entity_exact / graph_expand / rrf / weighted_rrf / identity / model_rerank / llm_rerank / score_rerank / collect / **assemble**（终点产 ContextPack）。WP-5 的 query_understanding/assemble/entity_exact/graph_expand/llm_rerank/hyde/multi_query 按决策 6 **直接注入复用**现有 `QueryUnderstandingEngine`/`ContextAssembler`/`EntityExactRetriever`/`GraphExpander`/`LlmReranker`/`EmbeddingClient`/`MultiQueryExpander`（均未改原类）。
>
> **决策确认（2026-06-22）**：D-1 范式表非路由存储 ✓；D-2 允许加 `json-schema-validator` ✓；D-3 `textKind=both`=`raw_text+question` ✓；D-6 允许直接注入复用现有 @Component 但**不得修改原有代码** ✓；交付节奏：先 WP-0~4 跑通三类范例 ✓。
>
> **联调冒烟结论（2026-06-22，真实库+llm_service）**：create→publish→`/{id}/search` 全链路跑通；`model_rerank` 复用 BigModel rerank 返回真实重排分；同一 `id+version` 重复调用结果一致（可复现）。**textKind 三值已验证**：raw_text / question 返回**不相交**的候选集、both 为二者合并——但发现 **PRD §2.2 的数据假设有误**：实际 `asset_retrieval_embeddings.text_kind` 全部是 `'full'`，raw_text vs question 的区分在 **`asset_retrieval_units.unit_type`**（`raw_text` / `generated_question`）。已据此修正 `OperatorEmbeddingMapper.xml`（过滤 `ru.unit_type`）和 `DenseVectorOperator`（`question`→`generated_question`）。⚠️ 运行中的 8081 实例是修正前构建，需重启才能生效。
>
> **D-1 实现说明（与原计划的偏差，需知悉）**：原计划给范式表单独挂一个**独立 SqlSessionFactory**。落地时发现：mybatis-spring-boot-starter 的自动配置带 `@ConditionalOnMissingBean(SqlSessionFactory)`——一旦我新增任何 `SqlSessionFactory` bean，自动配置会**整体退避**，导致现有路由 mapper 失去默认 factory 而损坏现有功能。为遵守"不破坏现有"，改为：范式 mapper 复用默认（路由）factory，但范式 CRUD/读取**在 `DomainContext` 未设置时调用**，路由 DataSource 回退到 `defaultDataSource`（共享/控制库）。**数据落点与原方案完全一致**（都在 `defaultDataSource` 指向的库，即 `PG_DBNAME`，默认 `test_db`），同样保证范式不被路由到领域库——D-1 的意图达成。范式表由 `ParadigmSchemaInitializer` 启动时幂等建表（`CREATE TABLE IF NOT EXISTS`，best-effort）。
> **约束复述**：现有 pipeline 文件**一行不改**（验收标准 6/7）；复用现有 mapper，不够用就新建 operator 专用 mapper（决策 8）。

---

## 0. 计划阶段已核实的现有契约（落地依据）

| 契约 | 确认结果 | 对计划的影响 |
|---|---|---|
| `RetrievalCandidate` | `record(retrievalUnitId, score, source, metadata:Map, scoreChain)` + `withScore/withSource/withScoreChain` | 算子间主流转类型 `CANDIDATE_LIST` = `List<RetrievalCandidate>`，直接复用 |
| `Retriever` 接口 | `List<RetrievalCandidate> retrieve(RetrievalQuery, List<String> snapshotIds, int topK)` | 算子**不实现**该接口（决策 1 要求新文件重写逻辑），但可参考其调用形态 |
| `EmbeddingClient` | `embed(String)→float[]`、`embedBatch(List)→List<float[]>`、`embedHyDE(String)→float[]`，`isConfigured()` | `query_embed`/`hyde` 算子直接注入复用 |
| `AssetRepository.resolveActiveScope(domain,channel)` | 返回 `ActiveScope(releaseId, buildId, snapshotIds, documentMap)`，抛 `no_active_release`/`multiple_active_releases` | `scope_resolve` 算子复用它（只读、非 SearchService 内部，符合决策 8 边界） |
| `ServingBeans` 装配模式 | 纯 Java 类用显式 `@Bean`；`@Component` 扫描的不在此重复声明 | 算子用 `@Component`（无状态单例，被 registry 扫描）；引擎/registry 视情况 `@Bean` 或 `@Component` |
| `DomainContext` | ThreadLocal + `wrapRunnable(Runnable)` 跨线程传播 | 执行器并行节点必须用 `wrapRunnable` 包裹，并显式 `llmClient.setKnowledgeDomain` |
| `AssetRetrievalEmbeddingMapper.selectTopKByVector` | **不含 text_kind**；用 `embedding_vector_vec`（真 vector 列，非 init.sql 里的 `embedding_vector TEXT`）；假设 unit:embedding=1:1 | textKind 过滤须**新建** `OperatorEmbeddingMapper`，SQL 用 `embedding_vector_vec` + `text_kind` 条件 + 按 unit 去重 |

---

## 1. 待你拍板的设计决策（动手前确认）

> 这些是 PRD 标 💡/未覆盖、但影响骨架的点。给出我的建议，确认后即按此实现。

### D-1：范式表的数据库归属 ⚠️ 重要
现有 `DomainRoutingDataSource` 把所有 JDBC 按 ThreadLocal domain 路由到领域库。范式是跨领域全局配置，不应被路由；且执行检索时已 `DomainContext.set(domain)`，此刻读范式表会被错误路由。

- **建议方案**：范式表挂在**独立、不路由的 SqlSessionFactory**（绑现有 `defaultDataSource`），通过 `@MapperScan(..., sqlSessionFactoryRef="paradigmSqlSessionFactory")` 隔离。范式 CRUD/读取走它；检索算子仍走路由 dataSource 的现有 mapper。
- 备选：范式表放各领域库（需调用方带 domain，且重复存储）——不推荐。
- **影响**：`operator/paradigm/` 下的 mapper 用独立 SqlSessionFactory；执行流程里"先用非路由会话读出范式 graph_json，再 set domain 跑检索"。

### D-2：`params` / `paramSchema` 的 Java 表示
PRD 写 `JsonObject params` / `JsonSchema paramSchema`，非标准 Java 类型。
- **建议**：用 Jackson。`params` = `com.fasterxml.jackson.databind.JsonNode`（实为 `ObjectNode`）；提供轻量 `Params` 包装类（`getString(k,def)/getInt(k,def)/getBool(k,def)/getDouble/getStringList/getMap`）。`paramSchema` 存为 JSON 字符串（catalog 接口原样下发给前端），编译期用 networknt `json-schema-validator` 校验 params。
- **新增依赖**：`com.networknt:json-schema-validator`（pom 加一项；它依赖已有的 jackson）。若不想加依赖，退化为手写最小校验（type/required/enum/min/max），但不推荐。→ **需你确认是否可加该依赖。**

### D-3：`textKind="both"` 的语义
DB `text_kind` 实际值有 `raw_text / question / entity_card / table_row`（PRD 2.3）。PRD 枚举只给 `raw_text / question / both`。
- **建议**：`raw_text`→`text_kind='raw_text'`；`question`→`text_kind='question'`；`both`→`text_kind IN ('raw_text','question')`（不含 entity_card/table_row）。后续要纳入其余两种再扩枚举。**需你确认 both 的含义。**

### D-4：一个 unit 多条 embedding 的去重
按 textKind 拆分后，同一 `retrieval_unit_id` 可能命中多条（raw_text 一条、question 一条）。
- **建议**：新 SQL 用 `DISTINCT ON (re.retrieval_unit_id)` 取每个 unit 在所选 textKind 内余弦最高的一条；`both` 时也保证每 unit 最多一条候选，避免 fusion 前重复。

### D-5：`scope_resolve` 的复用边界
- **建议**：复用 `AssetRepository.resolveActiveScope`（@Repository，只读，非 SearchService 内部，符合决策 8）。`ExecContext.attributes` 存 `releaseId/buildId` 供 `assemble`/可观测使用。

---

## 2. 交付物总览（文件清单）

```
operator/
├── core/
│   ├── Operator.java                 接口：definition() + execute()
│   ├── SlotType.java                 枚举（PRD 6.2，10 种）
│   ├── SlotDecl.java                 record(name,type,required,description)
│   ├── SlotValues.java               类型化值容器 + 运行时校验
│   ├── OperatorDef.java              record(type,category,displayName,desc,in,out,paramSchema,errorPolicy)
│   ├── ErrorPolicy.java              枚举 FAIL_FAST/SKIP_WITH_EMPTY/FALLBACK
│   ├── ExecContext.java              requestId/domain/channel/debug/trace/attributes
│   ├── Params.java                   JsonNode 包装（getString/getInt/...）
│   └── exceptions/
│       ├── OperatorException.java
│       ├── SlotTypeMismatchException.java
│       └── ParadigmCompileException.java   含结构化错误列表
├── engine/
│   ├── ParadigmGraph.java            record(nodes,edges,outputNodeId,outputSlot)
│   ├── NodeDef.java / EdgeDef.java
│   ├── ParadigmCompiler.java         JSON→图 + 7 项编译期校验（PRD 8.2）
│   ├── ParadigmExecutor.java         拓扑 + 虚拟线程并行（PRD 8.3）
│   ├── SlotBinder.java               入口 slot 绑定 + variadic 合并 + 运行时校验
│   └── CompileError.java             record(kind,nodeId,edge,message) 供前端高亮
├── registry/
│   └── OperatorRegistry.java         扫描 Operator bean → Map<type,Operator>/Map<type,OperatorDef>
├── operators/
│   ├── query/    QueryEmbedOperator, QueryUnderstandingOperator, HydeOperator, MultiQueryOperator
│   ├── retrieve/ DenseVectorOperator, FtsOperator, EntityExactOperator, GraphExpandOperator
│   ├── fuse/     RrfOperator, WeightedRrfOperator, IdentityOperator
│   ├── rerank/   ModelRerankOperator, LlmRerankOperator, ScoreRerankOperator
│   └── output/   ScopeResolveOperator, CollectOperator, AssembleOperator
├── mapper/
│   ├── OperatorEmbeddingMapper.java          textKind 过滤的向量检索（新 SQL）
│   └── (按需) OperatorFtsMapper / OperatorEntityMapper 仅当现有 mapper 不够用
├── paradigm/
│   ├── ParadigmService.java          CRUD/发布/版本/回滚
│   ├── ParadigmEntity.java / ParadigmVersionEntity.java
│   ├── ParadigmMapper.java + ParadigmVersionMapper.java   （独立 SqlSessionFactory，见 D-1）
│   └── ParadigmExecutionService.java 编排：读范式→编译→执行→输出
├── api/
│   ├── ParadigmController.java       PRD 11 全部端点
│   ├── OperatorCatalogController.java GET /operator/catalog
│   └── dto/                          请求/响应 DTO
└── config/
    ├── OperatorBeans.java            引擎/registry/executor 显式装配
    └── ParadigmPersistenceConfig.java 独立 SqlSessionFactory + @MapperScan（D-1）

src/main/resources/
├── mapper/operator/OperatorEmbeddingMapper.xml
├── mapper/operator/ParadigmMapper.xml
├── mapper/operator/ParadigmVersionMapper.xml
└── db/operator/001_operator_paradigm.sql        两张表 DDL

docs/
└── operator-development-guide.md     如何新增一个算子
```

> 全程不出现对现有 `application/ pipeline/ retrieval/ rerank/ domain/` 文件的修改；新代码**调用**现有 mapper / `EmbeddingClient` / `AssetRepository` / `DomainContext`。

---

## 3. 工作包拆解（建议执行顺序）

> 对应 PRD 迁移步骤 1（框架）+ 步骤 2（全算子）。每个 WP 末尾给验收点。

### WP-0：脚手架 + DB（半天）
- 建 `operator/` package 骨架与 `OperatorBeans`。
- `001_operator_paradigm.sql`：`operator_paradigm` + `operator_paradigm_version`（PRD 10.1，含草稿列 `draft_graph_json JSONB`，省一张表）。
- `ParadigmPersistenceConfig`：独立 `paradigmDataSource`（= defaultDataSource 引用）+ `paradigmSqlSessionFactory` + `@MapperScan(basePackages="...paradigm", sqlSessionFactoryRef=...)`。
- **验收**：服务启动不报错；两表创建；现有测试全绿。

### WP-1：核心抽象（core 包）（1 天）
- `SlotType`、`SlotDecl`、`OperatorDef`、`Operator`、`ErrorPolicy`、`ExecContext`、`Params`、`SlotValues`（含 `get(name,Class)` 运行时校验 → `SlotTypeMismatchException`）、exceptions。
- `SlotType ↔ Java 类`映射表（VECTOR→`float[]`，CANDIDATE_LIST→`List<RetrievalCandidate>`，SCOPE→`ActiveScope`，QUERY_UNDERSTANDING→`QueryUnderstanding`，CONTEXT_PACK→`ContextPack`，STRING_LIST→`List<String>` …）。
- **验收**：SlotValues 单测（类型匹配/不匹配/缺失）。

### WP-2：DAG 引擎（engine + registry）（2 天）
- `OperatorRegistry`：`@PostConstruct` 扫描所有 `Operator` bean 建索引；type 重复 → 启动失败。
- `ParadigmCompiler`：JSON→`ParadigmGraph`，7 项校验（节点存在/params 符合 schema/连线类型一致/非 variadic 单入/无环/终点合法/required 输入齐全），失败抛 `ParadigmCompileException(List<CompileError>)`。
- `SlotBinder`：隐式入口 slot（`query`←request，`scope` 来自 scope_resolve 或 request）、variadic（`CANDIDATE_LIST_MULTI`）多上游合并、运行时输出类型校验。
- `ParadigmExecutor`：拓扑分层 → `newVirtualThreadPerTaskExecutor` 并行 → 节点用 `DomainContext.wrapRunnable` 包裹 + 设 LLM domain → 按 `ErrorPolicy` 隔离异常 → 收集终点输出 → 写 `Trace`。
- **验收**：引擎单测——拓扑顺序、并行、SKIP_WITH_EMPTY 不阻断、各类编译错误、环检测。用 2~3 个 mock 算子跑通。

### WP-3：检索 + 输出算子（最小可跑通集）（2 天）
先实现跑通三类范例所必需的算子：
- `query_embed`（复用 EmbeddingClient.embed）、`scope_resolve`（复用 AssetRepository）、`dense_vector`（**新 `OperatorEmbeddingMapper`** + textKind）、`fts`（复用 `AssetRetrievalUnitMapper` 的 FTS SQL，逻辑在算子内重写三级降级）、`collect`。
- `OperatorEmbeddingMapper.xml`：`DISTINCT ON (retrieval_unit_id)` + `text_kind` 过滤 + `embedding_vector_vec <=> ::vector` + scope JSONB 下推（参考现有 SQL，新文件）。
- **验收**：范例①embedding-only 三种 textKind 跑通且结果不同（验收标准 4/5）。

### WP-4：融合 + 重排算子（1.5 天）
- `rrf`/`weighted_rrf`（variadic 多入）/`identity`；`model_rerank`（复用 LlmClient.rerank 逻辑，新写）/`llm_rerank`/`score_rerank`。
- **验收**：范例②embedding+rerank、范例③多路+加权融合跑通（验收标准 4）。

### WP-5：补全算子目录剩余项（1.5 天）
- `query_understanding`（复用 QueryUnderstandingEngine？→ 决策 1 要求新写；可注入复用其 LLM 调用，规则逻辑在算子内重写）、`hyde`、`multi_query`、`entity_exact`、`graph_expand`、`assemble`（复用 ContextAssembler？同样新写，但可复用其 RST 权重表与 repo 调用）。
- **验收**：PRD 7.1 全算子在 `/operator/catalog` 可见；assemble 终点产出 ContextPack（决策 5）。

> ⚠️ `query_understanding`/`assemble` 的"复用 vs 重写"：决策 1 明确"新算子在新文件里基于现有逻辑重新实现，可优化重构"。计划按**新写、可注入复用稳定依赖（mapper/EmbeddingClient/AssetRepository）**，**不直接调用** `QueryUnderstandingEngine`/`ContextAssembler` 实例（它们是现有 pipeline 内部编排件）。这点请你确认是否同意（也可放宽为"允许直接注入复用这两个 @Component"，能省不少重复代码）。→ **待确认 D-6。**

### WP-6：范式持久化 + API（2 天）
- `ParadigmEntity`/`VersionEntity` + 两 mapper（独立 SqlSessionFactory）。
- `ParadigmService`：CRUD、`publish`（编译校验通过→`version=current+1`，graph_json 落不可变版本）、`rollback`、版本解析规则（PRD 10.3）。
- `ParadigmExecutionService` + `ParadigmController`（PRD 11 全端点）+ `OperatorCatalogController`。
- 执行流程严格遵守 D-1：**先用非路由会话读范式**，再 `DomainContext.set` 跑检索。
- **验收**：验收标准 1~3、8（按 id+version 调用、版本不可变可复现、catalog 可渲染）。

### WP-7：测试 + 文档（1.5 天）
- 算子单测（PRD 14.1）、引擎测试（14.2）、范式 E2E（14.3，标 `pg-integration`/`e2e` 分组，沿用现有三级测试体系）。
- **兼容性回归（14.4，关键）**：跑现有全部测试，`git diff` 确认现有文件零改动（验收标准 6/7）。
- `operator-development-guide.md`。

**总估**：约 13~14 人日（不含前端）。

---

## 4. 关键技术点定稿

### 4.1 算子无状态 + 并发
算子 `@Component` 单例，只持 mapper/client 等无状态依赖；所有请求态进 `ExecContext`/`SlotValues`。执行器节点跑在虚拟线程，**必须** `DomainContext.wrapRunnable` + `llmClient.setKnowledgeDomain(ctx.domain)`（finally clear）——照搬现有 `SearchService`/`RetrievalOrchestrator` 的成熟做法。

### 4.2 textKind 向量检索新 SQL（核心增量）
```sql
-- OperatorEmbeddingMapper.selectTopKByVectorAndTextKind
SELECT DISTINCT ON (re.retrieval_unit_id)
       re.retrieval_unit_id,
       (1 - (re.embedding_vector_vec <=> #{queryVector}::vector)) AS cosine_score,
       ru.document_snapshot_id, ru.title, ru.block_type, ru.semantic_role,
       ru.facets_json, ru.target_type, ru.unit_type, ru.source_segment_id
FROM asset_retrieval_embeddings re
JOIN asset_retrieval_units ru ON re.retrieval_unit_id = ru.id
WHERE ru.document_snapshot_id IN (...snapshotIds...)
  AND re.embedding_dim = #{dim}
  AND re.text_kind IN (...textKinds...)         -- ← 新增（D-3/D-4）
  <scope: AND ru.facets_json @> #{p}::jsonb>
ORDER BY re.retrieval_unit_id, re.embedding_vector_vec <=> #{queryVector}::vector
-- 外层再按 cosine_score desc + LIMIT topK（DISTINCT ON 要求 unit_id 先排序，故外包一层子查询）
```
重列（text/source_refs_json/target_ref_json）沿用现有"检索时 NULL、后置 hydrate"策略——但算子系统是否做 hydrate 取决于终点：`collect` 可不 hydrate（测试只看 id/score），`assemble` 需要文本→在 assemble 算子内补全或加 `hydrate` 辅助算子（后续按需，不在最小集）。

### 4.3 范式入口 slot
请求体 `{query,domain,channel,scope?,debug}`。引擎注入隐式入口：`query`(STRING)、可选 `scope`(SCOPE，若 request 直传则跳过 `scope_resolve`)；`domain/channel/debug` 进 `ExecContext`。无上游的起点算子 `query` slot 自动绑 request.query（PRD 8.4）。前端后续画显式 Input 节点，后端两种都支持。

### 4.4 输出契约（决策 5）
- `collect` 终点 → `{candidates:[{id,score,scoreChain,source,metadata}], debug?}`
- `assemble` 终点 → `ContextPack`（复用现有 record，与 `/api/v1/search` 同构）

---

## 5. 风险与对应（在 PRD 风险表基础上补充）

| 风险 | 对应 |
|---|---|
| 范式表被 domain 路由错库（D-1） | 独立非路由 SqlSessionFactory；执行时先读范式后 set domain |
| 一 unit 多 embedding 致候选重复（D-4） | `DISTINCT ON` 每 unit 取最高分 |
| `embedding_vector_vec` 列不在 init.sql | 新 SQL 用该列；测试库需有此列（确认 migrate 脚本已建）→ WP-3 起测前核实 |
| 决策 1 "重写"与"复用"边界（D-6） | 默认新写、注入复用稳定依赖；待你确认是否允许直接复用 @Component |
| 新增 json-schema 依赖（D-2） | 待确认；不允许则退化手写最小校验 |

---

## 6. 需你确认清单（开写前）

1. **D-1** 范式表挂独立非路由 DataSource —— 同意？
2. **D-2** 允许加 `json-schema-validator` 依赖做 params 校验？（否则手写最小校验）
3. **D-3** `textKind=both` = `raw_text + question` 两种 —— 确认？
4. **D-6** 算子允许"直接注入复用现有 `QueryUnderstandingEngine`/`ContextAssembler` 等 @Component"，还是严格"新文件重写、只复用 mapper/client/repository"？
5. 执行顺序（WP-0→7）与 13~14 人日估算，是否接受？是否要先交付"最小可跑通"（WP-0~4，跑通三类范例）再继续补全？

确认后我从 WP-0 开始，按工作包提交、每包自带验收。
