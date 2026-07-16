# 可插拔检索算子系统 PRD

> **文档类型**：产品需求文档（PRD），用于交接开发
> **日期**：2026-06-22
> **状态**：已确认核心决策，待开发
> **作者**：Claude（基于与产品负责人的需求澄清）
> **范围**：`agent_serving_java` 检索服务的算子化重构（新增子系统，不改动现有 pipeline）

---

## 0. 阅读指引

- **开发者**：从第 3 章决策记录读起（理解为什么这样选），再读第 5–13 章落地设计。
- **决策不可推翻**：第 3 章的每条决策都经过产品负责人确认，实现时**必须遵守**，如需变更需回到产品负责人重新确认。
- **标注约定**：🟢 = 已确认决策；💡 = 建议方案（开发时可调整，但需与建议方对齐）；⚠️ = 已知风险点。

---

## 1. 背景与目标

### 1.1 背景

现有检索服务（`agent_serving_java`）的 serving pipeline 是一条**固定 11 阶段、硬编码顺序**的链：

```
SearchRequest → 解析Domain → 加载Profile → 查询理解+Embedding(并行)
  → 路由Router → 解析Scope → 多路Retrieve(并行) → Fuse → Rerank(级联) → Assemble → ContextPack
```

编排逻辑全部硬编码在 `SearchService.search()` 中。虽然已有一定配置化基础（`RetrievalRoutePlan`：`routes` 的 `enabled/topK/weight` + `fusion.method` + `rerank.method` + `assembly.*`，来自 Domain Profile YAML 的 `retrieval_policy`），但存在三个核心痛点：

1. **不可插拔**：流程阶段固定，不能跳过（如"只要 embedding 不要查询理解"做不到）、不能自由组合、不能在前端拖拽编排。
2. **无法做增益实验**：各个检索组件（多路检索、融合、重排）的**单独增益不清楚**。无法快速搭建"只有 embedding"、"embedding+rerank"、"多路+融合"等不同检索范式做 A/B 对比。
3. **不能被测试系统按范式调用**：现有 `/api/v1/search` 是单一固定行为，测试系统无法选择"用哪一套检索范式"来评测检索效果。

### 1.2 目标

构建一套**可热插拔的检索算子系统**，与现有 pipeline **并存**，实现：

1. **算子化解耦**：把检索拆成细粒度算子，每个算子有明确的**类型化输入输出（slot）**和**可调参数**。
2. **JSON 驱动编排**：前端拖拽算子 + 配置参数 → 生成一份范式 JSON → 后端据此刻实例化 DAG 执行检索。
3. **范式可发布、可版本化、可被测试系统调用**：配好的范式发布后获得稳定 ID + 版本，测试系统按 ID+版本调用，得到检索结果算指标。
4. **逐步替换现有 pipeline**：新系统成熟后，逐步用算子链取代现有固定链；**替换分多个步骤进行，不能一蹴而就**，因为现有 pipeline 仍有其他使用者在用。

### 1.3 核心用户场景

| 场景 | 范例范式 | 用途 |
|---|---|---|
| 单路基线 | `QueryEmbed → DenseVector(textKind=raw_text) → Collect` | 测纯向量检索的召回上限 |
| 检索范围实验 | 同上，`textKind` 分别取 `raw_text` / `question` / `both` 各发一版 | 测检索范围对效果的影响 |
| 加重排 | `QueryEmbed → DenseVector → ModelRerank → Collect` | 测重排的增益 |
| 多路+融合 | `DenseVector ‖ Fts → WeightedRRF → Collect` | 复刻并调参现有多路融合 |
| 完整生产链 | 上述 + `Assemble` 结尾 | 输出 ContextPack 喂给 LLM |

---

## 2. 现状分析（开发必读，理解复用基础）

### 2.1 现有 serving pipeline 的关键资产（新系统将复用）

**11 个阶段及其参数来源**：

| 阶段 | 类:方法 | 输入 → 输出 | 关键参数 | 参数来源 |
|---|---|---|---|---|
| 查询理解 QU | `QueryUnderstandingEngine:understand` | `String,ServingDomainProfile` → `QueryUnderstanding` | — | Domain Pack extractor_rules |
| 路由 | `RetrievalRouter:route` | `QueryUnderstanding,ServingDomainProfile` → `RetrievalRoutePlan` | 复杂度分层 | **硬编码** `COMPLEXITY_ROUTES` |
| 解析 Scope | `SearchService:resolveActiveScope` | `domain,channel` → `ActiveScope` | — | DB 查询 |
| TreeNav | `TreeNavigator:inferSections` | `entities,snapshotIds` → `TreeNavigation` | `DOMINANCE_THRESHOLD=0.15` | **硬编码** |
| MultiQuery | `MultiQueryExpander:expand` | `query` → `List<String>` | `MAX_EXTRA_VARIANTS=2` | **硬编码** |
| 检索 | `RetrievalOrchestrator:execute` | `RetrievalQuery,RoutePlan,float[]` → `OrchestratorResult` | 各路 `topK` | `RoutePlan.routes()` |
| 融合 | `WeightedRRFFusion:fuse` | `List<Candidate>,RoutePlan` → `List<Candidate>` | `k=60` | `FusionConfig.k()` |
| 重排 | `RerankPipeline:rerank` | `List<Candidate>,RoutePlan,QU` → `RerankResult` | `MIN_RERANK_SCORE=0.01` | **硬编码** |
| 组装 | `ContextAssembler:assemble` | `query,QU,scope,candidates,RoutePlan` → `ContextPack` | `MAX_TOTAL_TOKENS=3000` | **硬编码** |

**现有三个干净接口（新算子的包装/复用对象）**：
```
Retriever:        List<RetrievalCandidate> retrieve(RetrievalQuery, List<String> snapshotIds, int topK)
FusionStrategy:   List<RetrievalCandidate> fuse(List<RetrievalCandidate>, RetrievalRoutePlan)
Reranker:         List<RetrievalCandidate> rerank(List<RetrievalCandidate>, QueryUnderstanding)
```

**4 个 Retriever 实现**：
- `DenseVectorRetriever`：pgvector `<=>` 余弦检索，scope 三级降级
- `FtsRetriever`：PostgreSQL FTS 三级降级（tsvector → trigram → LIKE），jieba 分词
- `EntityExactRetriever`：JSONB `@>` 实体匹配，固定分 0.95
- `GraphExpander`：BFS 图扩展

**3 种 Fusion**：`RRFFusion` / `WeightedRRFFusion`（默认）/ `IdentityFusion`

**级联 Rerank**：`Model(Zhipu/LLMService)` → `LLM` → `Score`（兜底）

### 2.2 关键发现：`textKind` 字段已存在但未被使用 🟢

`asset_retrieval_embeddings` 表已有一个 `textKind` 字段（设计意图：区分 embedding 来自哪种文本——raw_text / generated_question / entity_card 等），但当前 `DenseVectorRetriever.retrieve()` **检索时完全没按 textKind 过滤**。

**这意味着**："检索范围 raw_text / question / both" 这个参数的**数据层基础已经具备**，只是检索器没暴露。新算子把 `textKind` 作为 DenseVector 算子的可调参数即可——**零数据迁移**。

### 2.3 检索单元的 4 种类型（"检索范围"参数的物理基础）

| 类型 | weight | 文本来源 | 对应 textKind |
|---|---|---|---|
| `raw_text` | 1.0 | section标题链 + LLM上下文描述 + 原始 raw_text | `raw_text` |
| `entity_card` | 0.5 | `{entity_name}（{entity_type}） {上下文}` | `entity_card` |
| `table_row` | 0.8 | `{col1}为{val1}，{col2}为{val2}。` | `table_row` |
| `generated_question` | 0.7 | LLM 生成的问题 | `question` |

### 2.4 技术栈

Java 21（虚拟线程）+ Spring Boot 3.2.5 + MyBatis 3.0.3 + PostgreSQL + pgvector + jieba-analysis + httpclient5。

---

## 3. 核心决策记录（🟢 已确认，不可推翻）

> 以下 7 个核心决策 + 1 个复用边界，均经产品负责人逐条确认。实现时必须遵守。

### 决策 1：代码边界 —— 纯新增，现有文件零改动 🟢

**选项**：
- (A) 纯新增，现有 pipeline 文件零改动 ✅ **选定**
- (B) 混合：包装为主 + 必要时抽取共享逻辑，现有文件做最小改动
- (C) 允许自由重构现有代码

**决策**：(A) 现有 pipeline 源码文件（`SearchService` 编排链、现有 `Retriever`/`Fusion`/`Reranker` 实现类）**一行不改**，继续线上服务。新算子基于现有算法逻辑重新实现，全部写在**全新 package 的新文件**里，可在新代码内对这些逻辑做优化重构。两套系统并存，新系统成熟后再逐步删旧。

**理由**：现有 pipeline 别人还在用，零改动最安全；"纯新增"与"基于已有代码复用、优化、重构"不矛盾——复用和重构都发生在新代码里。

### 决策 2：编排模型 —— 有向图 DAG 🟢

**选项**：
- (A) 有向图 DAG（可分支/并行/合并）✅ **选定**
- (B) 线性链
- (C) 线性链 + 可选并行组

**决策**：(A) 算子可分支、并行、合并。引擎做拓扑排序 + Java 21 虚拟线程并行执行。能完整表达现有 pipeline 的"多路并行检索 → 融合"模式。

**理由**：现有 pipeline 本身就是多路并行 + 融合；要逐步取代现有 pipeline，DAG 才能完整复刻；"测试不同组合的增益"需要最大灵活性。Haystack 2.x / Dify / n8n 均为 DAG。

### 决策 3：算子粒度 —— 细粒度，每种方法独立算子 🟢

**选项**：
- (A) 细粒度：每种方法独立算子 ✅ **选定**
- (B) 粗粒度：一个算子内用参数选方法
- (C) 分层：基础算子 + 预设组合算子

**决策**：(A) DenseVector / Fts / Entity / Graph 各为独立检索算子；RRF / WeightedRRF / Identity 各为独立融合算子；Model / LLM / Score 各为独立重排算子。DAG 里靠连线自由组合。

**理由**：最契合"可热插拔"，职责单一，DAG 配合细粒度才能发挥表达力。（后续可叠加 (C) 的"预设组合算子"作为便捷入口，但底层仍是细粒度。）

### 决策 4：引擎归属 —— `agent_serving_java` 内新建 Java package 🟢

**选项**：
- (A) `agent_serving_java` 内新建 package ✅ **选定**
- (B) 独立新服务

**决策**：(A) 引擎和算子用 Java 写在新 package（`com.coremasterkb.serving.operator`）。直接复用现有 MyBatis mapper、pgvector、`EmbeddingClient`、`DomainContext`、Java 21 虚拟线程。与现有 `/api/v1/search` 并存，新增范式调用 API。前端编辑器接入 unified-frontend (Vue)。

**理由**：零跨服务开销；直接复用经过验证的数据访问层和 LLM 客户端；与现有检索同语言、同 DB。

### 决策 5：输出契约 —— 由范式终点算子决定 🟢

**选项**：
- (A) 由范式终点算子决定 ✅ **选定**
- (B) 固定候选列表
- (C) 固定 ContextPack

**决策**：(A) 范式 DAG 最后一个算子决定输出：
- `Collect` 算子 → 候选列表（`id/score/scoreChain/source/metadata`，测试友好，可直接算 recall/precision/MRR/NDCG）
- `Assemble` 算子 → ContextPack（给 LLM/前端用，与现有 `/api/v1/search` 一致）

**理由**：测试范式用 `Collect`、生产范式用 `Assemble`，一个范式定义自己的输出类型，最灵活。

### 决策 6：范式存储 —— DB 表 + 不可变版本 🟢

**选项**：
- (A) DB 表 + 不可变版本 ✅ **选定**
- (B) DB 表 + 单一当前版本
- (C) 文件 + git 版本控制

**决策**：(A) 范式存 DB 表（`operator_paradigm` + `operator_paradigm_version`）。范式有 `草稿/已发布` 状态；每次发布生成新版本，**版本内容不可变**（可回滚、可 diff 对比）。测试系统按 `paradigmId + version` 调用，不指定版本用 latest。

**理由**：支持并发查询、审计、实验复现；不可变版本保证同一范式版本的结果可复现。

### 决策 7：数据流模型 —— 强类型 slot 🟢

**选项**：
- (A) 强类型 slot（Haystack 风格）✅ **选定**
- (B) 共享 Context 黑板
- (C) 混合：slot + Context 兜底

**决策**：(A) 每个算子声明**类型化输入输出 slot**（名称 + `SlotType` + 方向）。连线时校验 slot 类型匹配，数据沿连线定向流转。类型校验两道关：编译期（JSON→图，画布报红）+ 运行时（slot 绑定）。

**理由**：最契合"定义好每个算子的输入输出"；前端连线可自动校验（连错报红）；算子自文档化；长期可维护性最好。Haystack 2.x 验证过的成熟模式。

### 决策 8：数据访问复用边界 —— 复用现有 mapper，不改 SearchService 🟢

**选项**：
- (A) 复用现有 mapper（新算子注入并调用现有 mapper 方法，复用 SQL）✅ **选定**
- (B) 完全独立重写一套 mapper

**决策**：(A) 新算子**注入并调用**现有 MyBatis mapper（如 `AssetRetrievalEmbeddingMapper`）复用经过验证的 SQL（pgvector 检索、scope JSONB 下推、FTS 三级降级等）。现有 mapper 文件**不被修改**，只是被新代码调用。现有 `SearchService` 编排链**一行不改**。

**边界细节（重要）⚠️**：当现有 mapper 的 SQL **不满足新算子参数需求**时（典型：`textKind` 过滤需要 SQL 加条件），**新建一个 operator 专用 mapper（新文件，新 SQL），不改现有 mapper**。即：
- 默认：新算子调用现有 mapper 复用 SQL
- 现有 SQL 不够用：新建 `operator/mapper/OperatorXxxMapper.java`（全新文件）写新 SQL
- 两种情况都不触碰现有文件

**理由**：复用经过调优的复杂 SQL，避免重写出错和重复；mapper 是稳定的数据访问接口，新代码调用它属于正常依赖。

---

## 4. 非目标（不在本需求范围内）

1. ❌ **不修改、不下线现有 pipeline**：`SearchService` 及现有 `/api/v1/search` 行为保持完全不变。
2. ❌ **不强制把现有 pipeline 的所有阶段都建模为算子**：本需求实现第 7 章列出的完整算子目录。TreeNav（章节树导航）、EvidenceRole（证据角色分类）等现有 pipeline 的辅助能力不在本需求算子目录内，如需可作为新算子扩展（这是算子目录的自然扩展，不是分期交付）。
3. ❌ **不做算子的热加载/动态注册**：算子通过 Spring Bean 静态注册，新增算子需要重启服务。
4. ❌ **不做范式编辑的协同/权限**：范式管理为单用户，不做多人协同编辑和细粒度权限。
5. ❌ **不做范式执行的分布式调度**：单实例执行，虚拟线程并行即可。
6. ❌ **不在本需求中取代现有 `/api/v1/search`**：现有 pipeline 的切换下线是多步骤工作（见第 13 章），本需求只做到并存。

---

## 5. 系统架构

### 5.1 包结构（全新，现有代码零改动）

```
agent_serving_java/src/main/java/com/coremasterkb/serving/
├── (现有 pipeline，全部保持原样：application/ pipeline/ retrieval/ domain/ ...)
│
└── operator/                              ← 全新 package，本次新增
    ├── core/          算子核心抽象
    │   ├── Operator.java                  算子执行接口
    │   ├── SlotDecl.java                  slot 声明(名/类型/方向)
    │   ├── SlotType.java                  类型系统枚举
    │   ├── SlotValues.java                slot 值容器(带运行时类型校验)
    │   ├── OperatorDef.java               算子元数据(type + slots + 参数schema)
    │   ├── ExecContext.java               执行上下文(domain/trace/debug)
    │   └── exceptions/                     OperatorException、SlotTypeMismatch 等
    ├── engine/        DAG 引擎
    │   ├── ParadigmGraph.java             图模型(nodes + edges)
    │   ├── ParadigmCompiler.java          范式JSON → 图(含编译期类型校验)
    │   ├── ParadigmExecutor.java          拓扑执行 + 虚拟线程并行
    │   └── SlotBinder.java                slot 绑定 + 运行时类型校验
    ├── registry/
    │   └── OperatorRegistry.java          算子目录(type → OperatorDef)，Spring 启动时扫描注册
    ├── operators/     算子实现(按类别)
    │   ├── query/     QueryEmbed, QueryUnderstanding, HyDE, MultiQuery
    │   ├── retrieve/  DenseVector, Fts, EntityExact, GraphExpand
    │   ├── fuse/      RRF, WeightedRRF, Identity
    │   ├── rerank/    Model, LLM, Score
    │   └── output/    ScopeResolve, Collect, Assemble
    ├── mapper/        operator 专用 mapper（仅当现有 mapper 不满足时新建，见决策8）
    ├── paradigm/      范式管理
    │   ├── ParadigmService.java           CRUD + 发布 + 版本
    │   ├── ParadigmEntity.java            DB 实体
    │   ├── ParadigmVersionEntity.java     版本实体
    │   └── ParadigmRepository.java
    └── api/
        └── ParadigmController.java        新 API 端点
```

### 5.2 运行时并存（两套互不干扰）

```
现有:  SearchController → SearchService(固定11阶段) → ContextPack      ← 一行不改
新增:  ParadigmController → ParadigmService → ParadigmExecutor → 结果   ← 全新
                                                    │
                                    复用(只读调用,不改): 现有 MyBatis mapper
                                    (AssetRetrievalEmbeddingMapper 等)、
                                    EmbeddingClient、DomainContext
```

### 5.3 一次范式执行的端到端流程

```
①前端画布拖拽算子 + 配参数 → 生成范式 JSON
②POST /api/v1/paradigm          → 存草稿
③发布                           → 生成不可变 paradigm_version
                                    │
④测试系统 POST /api/v1/paradigm/{id}/search  body={query,domain?,channel?}
                                    │
⑤ParadigmCompiler: 范式JSON → ParadigmGraph   (编译期类型校验，连错报错)
⑥ParadigmExecutor: 拓扑排序 → 虚拟线程并行执行
     • 从 OperatorRegistry 按 type 取 OperatorDef
     • 按 OperatorDef 的参数 schema 校验并注入 params
     • slot 绑定：上游 out → 下游 in，运行时再校验一次类型
     • 依赖满足即执行，多路并行(如 DenseVector ‖ Fts)
⑦终点算子输出: Collect → 候选列表 / Assemble → ContextPack
```

### 5.4 三条关键设计原则

1. **算子无状态**：所有可变状态进 `ExecContext`，算子只持有 config 参数 → 实例可缓存、线程安全、可并行。
2. **引擎不懂检索**：`ParadigmExecutor` 只懂"图执行 + slot 绑定"，检索知识全在算子里 → 引擎稳定，算子可任意扩展。
3. **类型校验两道关**：编译期（JSON→图，画布连线报红）+ 运行时（slot 绑定），尽量早暴露错误。

---

## 6. 核心抽象

### 6.1 `Operator` 接口

```java
public interface Operator {
    /** 声明：算子类型、slot、参数 schema。启动时由 registry 收集。 */
    OperatorDef definition();

    /** 执行：上游 slot 值 + 范式参数 + 执行上下文 → 输出 slot 值。算子必须无状态。 */
    SlotValues execute(SlotValues inputs, JsonObject params, ExecContext ctx);
}
```

算子是**无状态 Spring Bean（单例）**，参数每次执行时通过 `params` 传入。

### 6.2 Slot 声明 + 类型系统（强类型 slot 的基础）

```java
public record SlotDecl(String name, SlotType type, boolean required, String description) {}

public enum SlotType {
    STRING,                // 原始 query 等
    INT, DOUBLE, BOOL,
    VECTOR,                // float[] query embedding
    STRING_LIST,           // snapshotIds、keywords、multi_query 变体
    CANDIDATE_LIST,        // List<RetrievalCandidate> —— 检索/融合/重排之间的主流转类型
    CANDIDATE_LIST_MULTI,  // variadic：融合算子接收多路 candidates（允许多个上游连入）
    SCOPE,                 // ActiveScope(snapshotIds + documentMap)
    QUERY_UNDERSTANDING,   // QueryUnderstanding 对象
    CONTEXT_PACK           // Assemble 算子输出
}
```

> 💡 **variadic slot（`CANDIDATE_LIST_MULTI`）**：融合算子（RRF/WeightedRRF）的 `candidates` 输入 slot 允许多个上游连入，引擎将所有连入的候选列表收集合并后再传给算子。这是 DAG "多入"的标准处理。

### 6.3 `OperatorDef`（算子元数据）

```java
public record OperatorDef(
    String type,                   // "dense_vector"（唯一标识，范式JSON用它引用算子）
    String category,               // "retrieve"（前端按类别分组显示）
    String displayName,            // "向量检索"（画布节点显示名）
    String description,            // 算子说明
    List<SlotDecl> inputSlots,     // 输入 slot 列表
    List<SlotDecl> outputSlots,    // 输出 slot 列表
    JsonSchema paramSchema         // 参数 schema（JSON Schema，见 6.4）
) {}
```

### 6.4 参数 schema（JSON Schema，前端据此自动渲染配置面板）

```json
{
  "type": "object",
  "properties": {
    "textKind":    {"type": "string",  "enum": ["raw_text", "question", "both"], "default": "raw_text", "title": "检索范围"},
    "topK":        {"type": "integer", "minimum": 1, "maximum": 100, "default": 20, "title": "返回数量"},
    "scopeFilter": {"type": "boolean", "default": true, "title": "启用 scope 过滤"}
  }
}
```

前端拿到 schema → 自动生成下拉框(textKind) / 数字框(topK) / 开关(scopeFilter)。**加参数只改算子的 schema，前端零改动**。

### 6.5 `ExecContext`（跨算子共享，算子无状态的关键）

```java
public class ExecContext {
    String requestId;
    String domain;
    String channel;
    boolean debug;
    Trace trace;                      // 每个算子的耗时/输入输出摘要（复用现有 Trace 体系）
    Map<String, Object> attributes;   // 跨算子辅助数据（如 releaseId、buildId）
}
```

### 6.6 `SlotValues`（slot 值容器，带运行时类型校验）

```java
public class SlotValues {
    /** 取值时按声明的 SlotType 做类型校验，不匹配抛 SlotTypeMismatchException */
    public <T> T get(String slotName, Class<T> type);
    public void put(String slotName, Object value);
    public static SlotValues of(String slotName, Object value);
}
```

### 6.7 完整示例：DenseVector 算子

```java
@Component
public class DenseVectorOperator implements Operator {
    private final AssetRetrievalEmbeddingMapper mapper;  // 复用现有 mapper（决策8）

    public OperatorDef definition() {
        return new OperatorDef(
            "dense_vector", "retrieve", "向量检索", "pgvector 余弦相似度检索",
            List.of(
                new SlotDecl("queryEmbedding", VECTOR, true, "查询向量"),
                new SlotDecl("scope", SCOPE, true, "检索范围(snapshotIds)")),
            List.of(
                new SlotDecl("candidates", CANDIDATE_LIST, "检索候选")),
            PARAM_SCHEMA  // 6.4 里的 JSON Schema
        );
    }

    public SlotValues execute(SlotValues in, JsonObject params, ExecContext ctx) {
        float[] vec = in.get("queryEmbedding", float[].class);
        ActiveScope scope = in.get("scope", ActiveScope.class);
        String textKind = params.getString("textKind", "raw_text");
        int topK = params.getInt("topK", 20);
        // 复用现有 mapper SQL；textKind 过滤是新增逻辑（现有 DenseVectorRetriever 没有）
        var rows = mapper.selectTopKByVector(scope.snapshotIds(), vec, ...);
        var candidates = rows.stream()
            .filter(r -> textKindMatch(r.getTextKind(), textKind))  // 新增检索范围过滤
            .limit(topK).map(toCandidate).toList();
        return SlotValues.of("candidates", candidates);
    }
}
```

> ⚠️ **textKind 过滤的实现选择**：如果现有 `selectTopKByVector` SQL 不支持 textKind 条件下推，优先**新建** `operator/mapper/OperatorEmbeddingMapper.java`（新文件，新 SQL，带 textKind 条件）而非改现有 mapper。性能上 SQL 下推优于 Java 层过滤，建议新建专用 mapper。具体由开发阶段评估。

---

## 7. 算子目录

### 7.1 算子清单

| 类别 | 算子 type | 显示名 | 输入 slot | 输出 slot | 关键参数 |
|---|---|---|---|---|---|
| **查询变换** | `query_embed` | 查询向量化 | `query`(STRING) | `queryEmbedding`(VECTOR) | model |
| | `query_understanding` | 查询理解 | `query`(STRING) | `understanding`(QUERY_UNDERSTANDING) | useLlm(BOOL) |
| | `hyde` | HyDE | `query`(STRING) | `queryEmbedding`(VECTOR) | — |
| | `multi_query` | 多查询扩展 | `query`(STRING) | `variants`(STRING_LIST) | maxVariants(INT) |
| **范围** | `scope_resolve` | 范围解析 | *(从 request 的 domain/channel)* | `scope`(SCOPE) | — |
| **检索** | `dense_vector` | 向量检索 | `queryEmbedding`(VECTOR), `scope`(SCOPE) | `candidates`(CANDIDATE_LIST) | textKind(ENUM), topK(INT), scopeFilter(BOOL) |
| | `fts` | 全文检索 | `query`(STRING), `scope`(SCOPE) | `candidates` | topK, fallbackLevel(ENUM) |
| | `entity_exact` | 实体检索 | `understanding`(QUERY_UNDERSTANDING), `scope`(SCOPE) | `candidates` | topK |
| | `graph_expand` | 图扩展 | `seeds`(CANDIDATE_LIST), `scope`(SCOPE) | `candidates` | maxDepth, maxResults, relationTypes(LIST) |
| **融合** | `rrf` | RRF 融合 | `candidates`(CANDIDATE_LIST_MULTI) | `candidates` | k(INT) |
| | `weighted_rrf` | 加权 RRF | `candidates`(CANDIDATE_LIST_MULTI) | `candidates` | k(INT), weights(MAP) |
| | `identity` | 直通 | `candidates` | `candidates` | — |
| **重排** | `model_rerank` | 模型重排 | `candidates`, `query`(STRING) | `candidates` | topK, threshold(DOUBLE) |
| | `llm_rerank` | LLM 重排 | `candidates`, `query`(STRING) | `candidates` | topK |
| | `score_rerank` | 分数兜底 | `candidates` | `candidates` | threshold(DOUBLE) |
| **输出** | `collect` | 收集候选（测试用） | `candidates` | `candidates`(终点) | maxItems(INT) |
| | `assemble` | 组装上下文（生产用） | `candidates`, `understanding`, `scope` | `contextPack`(CONTEXT_PACK, 终点) | maxItems, maxExpanded |

> 💡 **实现顺序建议**（非分期，上表全部算子都在本需求范围内）：建议先搭建核心抽象与 DAG 引擎，再按「查询变换 → 检索 → 融合 → 重排 → 输出」的类别顺序实现算子。**上表全部算子均需实现**。验收时必须能跑通「embedding-only」「embedding+rerank」「多路+融合」三类范式。

### 7.2 算子注册机制 💡

- 每个算子是 `@Component`，实现 `Operator` 接口。
- `OperatorRegistry` 在 Spring 启动时扫描所有 `Operator` bean，按 `definition().type()` 建立索引（`Map<String, Operator>` + `Map<String, OperatorDef>`）。
- `GET /api/v1/operator/catalog` 返回所有 `OperatorDef`，供前端画布渲染算子面板。

---

## 8. DAG 编排引擎

### 8.1 图模型（`ParadigmGraph`）

```java
public record ParadigmGraph(
    Map<String, NodeDef> nodes,     // nodeId → 节点定义
    List<EdgeDef> edges,            // 连线
    String outputNodeId,            // 终点节点（其输出作为范式结果）
    String outputSlot               // 终点节点的哪个输出 slot
) {}

public record NodeDef(
    String nodeId,                  // 画布上的唯一节点 ID（如 "dv1"）
    String operatorType,            // 算子 type（如 "dense_vector"）
    JsonObject params               // 该节点的参数值
) {}

public record EdgeDef(
    String fromNode, String fromSlot,   // 上游节点 + 其输出 slot
    String toNode, String toSlot        // 下游节点 + 其输入 slot
) {}
```

### 8.2 范式编译（`ParadigmCompiler`：JSON → 图 + 编译期类型校验）

编译期校验（不执行算子，只看图结构）：
1. **节点合法性**：每个 `operatorType` 在 registry 中存在。
2. **参数合法性**：每个节点 `params` 符合其 `paramSchema`（JSON Schema 校验，必填项、类型、范围）。
3. **连线类型校验**：每条边的 `fromSlot` 类型 == `toSlot` 类型（`VECTOR→VECTOR` ✓，`VECTOR→STRING_LIST` ✗ 报错）。
4. **slot 占用校验**：非 variadic 的输入 slot 只能有一个上游连入；输出 slot 可连多个下游。
5. **无环校验**：DAG 不能有环（拓扑排序检测）。
6. **终点合法**：`outputNodeId` 的 `outputSlot` 必须存在且类型明确。
7. **输入完整性**：每个 `required=true` 的输入 slot 都有上游连入（或来自范式入口）。

校验失败 → 返回结构化错误（节点/边/原因），前端据此高亮。

### 8.3 执行（`ParadigmExecutor`：拓扑 + 虚拟线程并行）

```
1. 拓扑排序得到执行层级
2. 用 Executors.newVirtualThreadPerTaskExecutor()（复用现有并发模型）
3. 同层级无依赖的节点并行执行；跨层级按依赖等待
4. 每个节点执行：
   a. 从 registry 取 Operator bean（单例）
   b. 收集上游节点的输出 slot 值 → SlotValues
   c. 调用 operator.execute(inputs, node.params, ctx)
   d. SlotBinder 运行时校验输出 slot 类型
   e. 记录 Trace（耗时、输入输出摘要）
5. 异常隔离：单节点失败按算子声明的错误策略处理（见 8.5），不直接炸掉整图
6. 收集终点节点输出 → 返回
```

### 8.4 范式入口（request → 起点算子的 slot 绑定）

范式执行的标准输入（来自 HTTP request body）：
```json
{ "query": "...", "domain": "...", "channel": "...", "scope": {...}, "debug": false }
```

引擎把这些封装为**隐式入口 slot**，供没有上游的起点算子消费：
- `query`(STRING) ← request.query
- `scope`(SCOPE) ← 由 `scope_resolve` 算子产出（或 request 直接传入）
- `domain`/`channel`/`debug` ← 进 `ExecContext`

> 起点算子（如 `query_embed`）的 `query` 输入 slot 若无上游连线，自动绑定到 request 的 `query`。这是约定，前端画布上这类"入口边"可隐式处理或显式画一个"Input"伪节点（💡 建议显式画 Input 节点，更清晰）。

### 8.5 错误处理与降级策略 💡

每个算子在 `OperatorDef` 中可声明错误策略（建议字段）：
- `FAIL_FAST`：节点失败 → 整个范式执行失败，返回错误（默认）。
- `SKIP_WITH_EMPTY`：节点失败 → 该节点输出空候选，下游继续（如某路检索失败不影响其他路）。
- `FALLBACK`：节点失败 → 走降级逻辑（如 Fts 的 tsvector→trigram→LIKE 三级降级，在算子内部实现）。

检索类算子建议默认 `SKIP_WITH_EMPTY`（单路失败不阻断多路融合）；重排/组装类建议 `FAIL_FAST`。

---

## 9. 范式 JSON Schema（前端画布 ↔ 后端的契约）

### 9.1 JSON 结构

```json
{
  "schemaVersion": "1.0",
  "nodes": [
    {"nodeId": "qe1", "operatorType": "query_embed", "params": {}},
    {"nodeId": "scope1", "operatorType": "scope_resolve", "params": {}},
    {"nodeId": "dv1", "operatorType": "dense_vector",
     "params": {"textKind": "raw_text", "topK": 20}},
    {"nodeId": "out1", "operatorType": "collect", "params": {"maxItems": 20}}
  ],
  "edges": [
    {"fromNode": "qe1",    "fromSlot": "queryEmbedding", "toNode": "dv1", "toSlot": "queryEmbedding"},
    {"fromNode": "scope1", "fromSlot": "scope",          "toNode": "dv1", "toSlot": "scope"},
    {"fromNode": "dv1",    "fromSlot": "candidates",     "toNode": "out1", "toSlot": "candidates"}
  ],
  "output": {"nodeId": "out1", "slot": "candidates"}
}
```

> 前端画布的位置坐标（x/y）等纯展示信息可放在 `nodes[].ui` 子对象里，后端编译时忽略，仅原样存档。

### 9.2 三个范例范式

**① embedding-only（textKind=raw_text）**
```json
{"nodes":[
  {"nodeId":"qe","operatorType":"query_embed"},
  {"nodeId":"scope","operatorType":"scope_resolve"},
  {"nodeId":"dv","operatorType":"dense_vector","params":{"textKind":"raw_text","topK":20}},
  {"nodeId":"out","operatorType":"collect","params":{"maxItems":20}}],
 "edges":[
  {"fromNode":"qe","fromSlot":"queryEmbedding","toNode":"dv","toSlot":"queryEmbedding"},
  {"fromNode":"scope","fromSlot":"scope","toNode":"dv","toSlot":"scope"},
  {"fromNode":"dv","fromSlot":"candidates","toNode":"out","toSlot":"candidates"}],
 "output":{"nodeId":"out","slot":"candidates"}}
```

**② embedding + rerank**
在 ① 的 `dv` 与 `out` 之间插入：
```json
{"nodeId":"rr","operatorType":"model_rerank","params":{"topK":10}}
```
边：`dv.candidates → rr.candidates`、`qe.query → rr.query`(经入口)、`rr.candidates → out.candidates`

**③ 多路 + 加权融合**
```json
{"nodes":[
  {"nodeId":"qe","operatorType":"query_embed"},
  {"nodeId":"scope","operatorType":"scope_resolve"},
  {"nodeId":"dv","operatorType":"dense_vector","params":{"topK":20}},
  {"nodeId":"fts","operatorType":"fts","params":{"topK":20}},
  {"nodeId":"fuse","operatorType":"weighted_rrf","params":{"k":60,"weights":{"dv":1.2,"fts":1.0}}},
  {"nodeId":"out","operatorType":"collect","params":{"maxItems":20}}],
 "edges":[
  {"fromNode":"qe","fromSlot":"queryEmbedding","toNode":"dv","toSlot":"queryEmbedding"},
  {"fromNode":"scope","fromSlot":"scope","toNode":"dv","toSlot":"scope"},
  {"fromNode":"scope","fromSlot":"scope","toNode":"fts","toSlot":"scope"},
  {"fromNode":"dv","fromSlot":"candidates","toNode":"fuse","toSlot":"candidates"},
  {"fromNode":"fts","fromSlot":"candidates","toNode":"fuse","toSlot":"candidates"},
  {"fromNode":"fuse","fromSlot":"candidates","toNode":"out","toSlot":"candidates"}],
 "output":{"nodeId":"out","slot":"candidates"}}
```

---

## 10. 持久化与版本管理

### 10.1 DB 表设计 💡

```sql
-- 范式定义（可变，存元数据）
CREATE TABLE operator_paradigm (
    id              VARCHAR(64)  PRIMARY KEY,          -- 如 "pd-xxxx"（可由 name slug 生成）
    name            VARCHAR(200) NOT NULL UNIQUE,       -- 范式名
    description     TEXT,
    current_version INT          DEFAULT 0,             -- 当前发布版本号
    status          VARCHAR(20)  DEFAULT 'draft',       -- draft / active / archived
    created_at      TIMESTAMP    DEFAULT NOW(),
    updated_at      TIMESTAMP    DEFAULT NOW()
);

-- 范式版本（不可变，每次发布一条）
CREATE TABLE operator_paradigm_version (
    id              VARCHAR(64)  PRIMARY KEY,           -- 如 "pdv-xxxx"
    paradigm_id     VARCHAR(64)  NOT NULL REFERENCES operator_paradigm(id),
    version         INT          NOT NULL,              -- 自增版本号（从 1 开始）
    graph_json      JSONB        NOT NULL,              -- 第9章的范式 DAG JSON（不可变）
    schema_version  VARCHAR(20)  DEFAULT '1.0',         -- JSON schema 版本
    created_at      TIMESTAMP    DEFAULT NOW(),
    created_by      VARCHAR(100),
    UNIQUE(paradigm_id, version)
);
CREATE INDEX idx_op_paradigm_version ON operator_paradigm_version(paradigm_id, version);
```

> 💡 建议同时建一张 `operator_paradigm_draft`（或在 `operator_paradigm` 加 `draft_graph_json` 列）存草稿，草稿可随意改，发布时把草稿快照写入 `operator_paradigm_version`（不可变）。开发阶段定具体方案。

### 10.2 范式生命周期

```
[新建] → draft(草稿,可任意编辑) → [发布] → version N(不可变) → active
                                       ↑                         ↓
                                   [回滚到旧版本]            [归档] → archived
```

- **草稿**：可反复编辑、试运行（试运行用 `?dryRun=true`，不落库结果）。
- **发布**：校验范式 JSON 编译通过 → 生成新版本（`version = current_version + 1`），`graph_json` 写入后不可变。
- **调用**：测试系统按 `paradigmId + version` 调用；不指定 version 用 `current_version`（latest active）。
- **回滚**：把 `current_version` 指回历史版本（版本本身不变）。

### 10.3 版本解析规则

调用 `POST /api/v1/paradigm/{id}/search?version=N`：
- 指定 version → 用该版本
- 不指定 → 用 `operator_paradigm.current_version`
- 版本不存在 → 404

---

## 11. API 端点 💡

> 所有新 API 在 `ParadigmController`，挂在 `/api/v1/` 下，与现有 `/api/v1/search` 并存。

### 11.1 算子目录
```
GET /api/v1/operator/catalog
→ { operators: [OperatorDef...] }   // 前端画布据此渲染算子面板和参数表单
```

### 11.2 范式管理（CRUD + 发布）
```
POST   /api/v1/paradigm                       创建范式（草稿）→ 返回 paradigmId
GET    /api/v1/paradigm/{id}                  查询范式（含草稿 + current_version 信息）
PUT    /api/v1/paradigm/{id}                  更新草稿 graph_json
GET    /api/v1/paradigm/{id}/versions         版本列表
GET    /api/v1/paradigm/{id}/versions/{v}     查看某版本 graph_json（不可变）
POST   /api/v1/paradigm/{id}/publish          发布 → 生成新版本（先编译校验）
POST   /api/v1/paradigm/{id}/rollback?version=N   回滚 current_version
```

### 11.3 范式执行（测试系统调用入口）
```
POST /api/v1/paradigm/{id}/search?version={N?}
body: {
  "query": "...",                // 必填
  "domain": "...",               // 可选，默认 defaultDomain
  "channel": "...",              // 可选
  "scope": {...},                // 可选
  "debug": false                 // 可选
}
→ 终点算子输出：
   • Collect 结尾  → { candidates: [{id, score, scoreChain, source, metadata}...] , debug? }
   • Assemble 结尾 → ContextPack（与现有 /api/v1/search 同结构）

POST /api/v1/paradigm/{id}/validate           编译校验草稿（不执行），返回错误列表
POST /api/v1/paradigm/{id}/dryrun             试运行草稿（执行但不落库），用于编辑时预览
```

---

## 12. 前端集成（unified-frontend，Vue）💡

### 12.1 画布编辑器
- 基于 **Vue Flow**（或同类 DAG 编辑库，React Flow 的 Vue 版）。
- **左侧算子面板**：按 category 分组列出 `GET /operator/catalog` 的算子，拖拽到画布生成节点。
- **画布节点**：显示 `displayName` + 关键参数摘要；节点按 category 配色。
- **连线**：从节点输出 slot 拖到下游输入 slot；**实时类型校验**（`SlotType` 不匹配 → 连线报红 + 提示）。
- **入口**：画布上有一个显式的 **Input 伪节点**（提供 `query` / `domain` / `channel` / `scope`），起点算子从它连线。

### 12.2 参数配置面板（右侧）
- 选中节点 → 右侧根据该算子 `paramSchema`（JSON Schema）自动渲染表单：
  - `enum` → 下拉框
  - `integer/double` → 数字框（含 min/max）
  - `boolean` → 开关
  - `string` → 文本框
- **加参数只改后端 schema，前端自动适配，零改动**。

### 12.3 范式管理界面
- 范式列表（按 status 分组：草稿/已发布/已归档）。
- 编辑器顶部：**保存草稿 / 校验 / 试运行 / 发布** 按钮。
- 发布时调 `/publish`，后端编译校验通过才生成版本；失败则提示错误并高亮问题节点/边。
- 版本切换：查看历史版本 graph（只读）、回滚。

---

## 13. 迁移策略（逐步替换现有 pipeline，不能一蹴而就）🟢

> **核心约束**：现有 `/api/v1/search` 及 `SearchService` 有其他使用者在用，**任何时候都不能中断现有服务**。新系统始终独立可用、可回退。

### 13.1 并存原则
- 现有 pipeline 和新算子系统是**两条独立的检索路径**，共享数据访问层（mapper）和基础设施（DB、pgvector、LLM client），但编排互不依赖。
- 现有 `/api/v1/search` 行为锁死不变。
- 新系统通过 `/api/v1/paradigm/{id}/search` 独立提供服务。

### 13.2 实现与迁移步骤

> 这是**一个完整需求**的工程拆分步骤，**不是能力分期**——第 7 章全部算子、全部能力都在本需求范围内，最终全部交付。拆分步骤的意义是"不中断现有服务"的工程节奏，而非"分批交付不同能力"。

**步骤 1：搭建算子框架**
- 实现核心抽象（第 6 章）+ DAG 引擎（第 8 章）+ 范式持久化（第 10 章）+ API（第 11 章）+ 前端画布编辑器（第 12 章）。
- **不碰现有 pipeline 任何代码**。

**步骤 2：实现完整算子目录**
- 实现第 7.1 章列出的**全部算子**（查询变换 / 检索 / 融合 / 重排 / 输出 全类别）。
- 新系统与现有 pipeline 并存，各自独立运行。

**步骤 3：对标验证**
- 用新算子系统搭一条"复刻范式"，完整复刻现有 pipeline 的行为。
- 用测试系统对新"复刻范式"与现有 `/api/v1/search` 做 A/B 对比，验证新系统 **效果 ≥ 现有**、**延迟可接受**。
- 仍不替换现有 `/api/v1/search`。

**步骤 4：逐步切换调用方**
- 现有 `/api/v1/search` 的**新**检索需求引导走算子范式。
- 评估让 `/api/v1/search` 内部**可选地**代理到某条范式（通过开关，在外层路由，不改现有 `SearchService` 逻辑）。
- 追踪现有 `/api/v1/search` 的调用方，逐个确认迁移。

**步骤 5：下线旧链**
- 当所有调用方都迁移到算子范式、且新系统稳定运行足够长时间后，才标记 `SearchService` 为 deprecated 并最终下线。
- 此步骤在本需求之后，仅记录后续路线。

### 13.3 切换与回退保障
- 任何时候，现有 `/api/v1/search` 的调用方**无需任何改动**即可继续使用。
- 新系统的范式版本不可变，调用方绑定具体 version 即可保证结果可复现、不受后续范式编辑影响。
- 新系统故障不影响现有 `/api/v1/search`（独立路径）。

---

## 14. 测试策略 💡

### 14.1 算子单元测试
- 每个算子独立测试：mock 上游 `SlotValues` + 参数 → 验证输出 slot 值。
- 覆盖参数边界（topK=0/极大、textKind 各枚举值、空候选等）。

### 14.2 引擎测试
- `ParadigmCompiler`：各类编译错误（类型不匹配、环、缺 required slot、参数 schema 违规）。
- `ParadigmExecutor`：拓扑顺序正确性、并行执行、异常隔离（SKIP_WITH_EMPTY 不阻断其他路）、终点输出。

### 14.3 范式端到端测试
- 预置几个范式（第 9.2 的三个范例），用真实 DB 数据跑通，验证候选列表 / ContextPack 输出结构正确。

### 14.4 兼容性回归
- **关键**：每次改动后，现有 `/api/v1/search` 的行为回归（用现有测试用例），确保新代码未意外影响现有 pipeline。

### 14.5 性能基准
- 对比同等工作量下，新算子范式 vs 现有 `/api/v1/search` 的延迟（应在一个量级，因为复用同样的 mapper SQL 和虚拟线程模型）。

---

## 15. 风险与依赖

| 风险 | 影响 | 缓解 |
|---|---|---|
| ⚠️ slot 类型系统设计不当，导致算子组合受限或频繁加类型 | 算子无法表达某些组合 | 类型表（6.2）先最小化、预留扩展；variadic 类型处理多入场景 |
| ⚠️ 现有 mapper SQL 不支持新参数（textKind 过滤等） | 新算子拿不到正确数据 | 按决策 8：新建 operator 专用 mapper（新文件），不改现有 |
| ⚠️ 前端画布 + JSON Schema 表单的复杂度 | 前端工作量大 | 用成熟库（Vue Flow），参数渲染靠 JSON Schema 标准库 |
| ⚠️ 范式执行的 domain/scope 传播 | 跨算子的 ActiveScope/DomainContext 处理 | scope_resolve 算子统一产出 scope；DomainContext 在 ExecContext 注入 |
| ⚠️ 算子复用现有组件时的耦合 | 新算子依赖现有实现细节 | 复用 mapper（稳定接口）为主，避免依赖 SearchService 内部方法 |

**外部依赖**：现有 `agent_serving_java` 的 MyBatis mapper、`EmbeddingClient`、`DomainContext`、pgvector、LLM rerank 服务。

---

## 16. 验收标准

1. ✅ 前端能拖拽算子组成 DAG，连线时实时类型校验（连错报红），配置参数。
2. ✅ 范式能保存为草稿、编译校验、发布为不可变版本。
3. ✅ 测试系统能按 `paradigmId + version` 调用 `/api/v1/paradigm/{id}/search`，得到候选列表。
4. ✅ 三类范式可跑通：embedding-only（含 textKind 三种取值）、embedding+rerank、多路+融合。
5. ✅ `textKind` 参数能真正改变 DenseVector 算子的检索范围（验证 raw_text/question/both 结果不同）。
6. ✅ **新系统未修改任何现有 pipeline 文件**（git diff 可验证：现有文件零改动）。
7. ✅ 现有 `/api/v1/search` 行为回归测试全部通过，无任何影响。
8. ✅ 范式版本不可变：同一 `paradigmId+version` 多次调用结果一致（相同 query + 相同数据）。

---

## 17. 附录

### A. 交付物清单
- 后端：`com.coremasterkb.serving.operator` 全 package（core / engine / registry / operators 完整算子集 / paradigm / api / mapper）。
- DB：`operator_paradigm` + `operator_paradigm_version`（+ 草稿存储方案）两张表。
- 前端：unified-frontend 新增"检索范式"模块（画布编辑器 + 参数面板 + 范式管理）。
- 文档：算子开发指南（如何新增一个算子：实现 Operator + 写 definition + 注册）。

### B. SlotType 类型系统（速查）
见第 6.2 节。新增类型需评估对编译期校验和前端连线的影响。

### C. 工业级参考
- **Haystack 2.x**：typed-slot 有向图 + 组件序列化（YAML）+ 连接时类型校验 + SuperComponent 子图组合 + AsyncPipeline 并行。→ 本系统核心模式来源。
- **Dify workflow**：前端节点编辑器 + graph JSON（nodes/edges）+ 节点 type + 参数。→ 前端画布参考。
- **LlamaIndex QueryEngine + NodePostprocessor**：检索后处理链的线性组合思路。

### D. 名词表
| 术语 | 含义 |
|---|---|
| 算子 (Operator) | 检索流水线的最小可插拔单元，有类型化输入输出 slot + 参数 |
| slot | 算子的类型化输入/输出端口 |
| 范式 (Paradigm) | 一个完整的检索 DAG 配置（算子 + 连线 + 参数），可发布、可版本化 |
| 范式版本 (Paradigm Version) | 范式某次发布的不可变快照 |
| DAG | 有向无环图，算子编排的拓扑形态 |
| textKind | embedding 的检索范围标识（raw_text / question / entity_card / table_row） |

### E. 决策溯源
本文档第 3 章的 7 个核心决策 + 复用边界，源自 2026-06-22 与产品负责人的逐条澄清确认，原始讨论记录见会话上下文。任何决策变更需产品负责人重新确认。

---

> **开发交接说明**：本 PRD 已锁定核心决策（第 3 章）和核心抽象（第 6 章）。第 7–14 章的落地细节标 💡 的为建议方案，开发实现时如有更优解，可在不违背第 3 章决策的前提下调整，但需在实现计划中说明并回传对齐。
