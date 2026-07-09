# 本体图谱召回算子（entity_graph operator）设计

> 日期：2026-07-08
> 状态：方案设计（未进入实现）
> 目标服务：`agent_serving_java`（v5 检索侧，已算子化）
> 接入方式：**只接可插拔算子系统**（新增一个检索算子）；**不改老的 `POST /api/v1/search`**
> 依赖：挖掘侧已落地的本体子系统（`ontology_*` 表）

---

## 0. 背景与现状

1. **挖掘侧**已建起完整的实体知识图谱：`ontology_entities`（canonical 实体）、
   `ontology_entity_relations`（事实边）、`ontology_evidence_nodes`（出处）、
   `asset_segment_entity_mentions`（mention），并支持人审进化。

2. **检索侧目前完全没消费这张图谱**（经代码核查，serving 对 `ontology_*` 表引用数为 0）。
   现有 `graph_expand` 走 `asset_raw_segment_relations`（**段落**间 RST 关系）、`entity_exact` 走
   `entity_refs_json` 字面匹配，均非本体图谱召回。

3. **serving 已算子化**：v5 把检索管线重构为**可插拔算子 DAG（检索范式 paradigm）**。
   `operator/operators/retrieve/` 下已有 `FtsOperator` / `DenseVectorOperator` /
   `EntityExactOperator` / `GraphExpandOperator` 四个检索算子。算子标 `@Component` 由
   `OperatorRegistry` 启动时自动收集；`ParadigmCompiler`/`ParadigmExecutor` 按 DAG 编排执行；
   范式可持久化、可在前端拖拽编排调参。

**结论**：本体图谱召回应当做成**一个新的检索算子**接进这套系统，而不是硬编码进老编排器。

---

## 1. 目标与定位

新增检索算子 **`entity_graph`（本体图谱检索）**，与 `fts`/`dense_vector`/`entity_exact`/`graph_expand`
**同构并列**。它补充"实体维度"的召回：查询命中实体后，消歧到 canonical 实体、沿"实体—关系"边
多跳、经出处回到证据段召回。

**范围约束（本方案的硬边界）**：
- **只接算子系统**——新算子自动出现在算子目录，可在任意检索范式里使用；
- **不动 `POST /api/v1/search`（老 `SearchService` 硬编码管线）**——零回归风险。

与 `entity_exact` 的本质区别：后者是"实体名字面匹配单元"；本算子是"**消歧到 canonical 实体 →
图上多跳 → 经出处回证据段**"。与 `graph_expand` 的区别：后者扩的是**段落** RST 关系图，本算子扩的是
**实体**本体关系图。

---

## 2. 与算子系统的契合点（为什么天然合身）

| 契约 | 本算子如何满足 |
|------|---------------|
| `Operator` 接口：无状态单例，`definition()` + `execute(inputs, params, ctx)` | 同 `EntityExactOperator`：注入 retriever，execute 读槽→调 retriever→出候选 |
| 槽类型系统（`SlotType`） | 输入 `QUERY_UNDERSTANDING` + `SCOPE`，输出 `CANDIDATE_LIST`——与 4 个现有检索算子**完全一致**，可直接接进融合算子（`RrfOperator`/`WeightedRrfOperator` 的 `CANDIDATE_LIST_MULTI` 入口） |
| 注册（`OperatorRegistry`） | 标 `@Component` 即被构造注入、按 `type="entity_graph"` 建索引——**零编排改动**；重复 type 启动即报错 |
| 参数 Schema（`paramSchemaJson`，draft-07） | 声明 `topK/maxHop/minRelConf/decay`，前端 `/operator/catalog` 自动渲染成配置表单 |
| 错误策略（`ErrorPolicy`） | `SKIP_WITH_EMPTY`——无本体/无实体链接/异常时返回空候选，不拖垮整张范式 |
| 执行上下文（`ExecContext`） | 从 `ctx.domain()` 拿域做 `domain_id` 过滤；`debug` 时写 `NodeTrace` |

**前端零改动**：`OperatorCatalogController` 暴露算子目录，新算子带 paramSchema **自动出现在范式编辑器**
（`kb-ui` 的 operator/paradigm 页面），用户拖拽即用、表单调参，无需改前端。

---

## 3. 算子契约与骨架

```java
package com.coremasterkb.serving.operator.operators.retrieve;

@Component
public class EntityGraphOperator implements Operator {

    private static final String SOURCE = "entity_graph";
    private static final String PARAM_SCHEMA = """
        {"type":"object","properties":{
          "topK":      {"type":"integer","minimum":1,"maximum":200,"default":20,"title":"返回数量"},
          "maxHop":    {"type":"integer","minimum":1,"maximum":3,"default":2,"title":"最大跳数"},
          "minRelConf":{"type":"number","minimum":0,"maximum":1,"default":0.5,"title":"关系置信下限"},
          "decay":     {"type":"number","minimum":0,"maximum":1,"default":0.6,"title":"跳数衰减"}
        }}""";

    private final EntityGraphRetriever retriever;
    public EntityGraphOperator(EntityGraphRetriever retriever) { this.retriever = retriever; }

    @Override public OperatorDef definition() {
        return new OperatorDef(
            "entity_graph", "retrieve", "本体图谱检索",
            "查询实体消歧到 canonical 实体，沿本体关系多跳，经出处回证据段召回",
            List.of(SlotDecl.required("understanding", SlotType.QUERY_UNDERSTANDING, "查询理解(实体)"),
                    SlotDecl.required("scope", SlotType.SCOPE, "检索范围(snapshotIds)")),
            List.of(SlotDecl.required("candidates", SlotType.CANDIDATE_LIST, "检索候选")),
            PARAM_SCHEMA, ErrorPolicy.SKIP_WITH_EMPTY);
    }

    @Override public SlotValues execute(SlotValues inputs, Params params, ExecContext ctx) {
        var u = inputs.getUnderstanding("understanding");
        var scope = inputs.getScope("scope");
        if (u == null || scope == null || scope.snapshotIds().isEmpty())
            return SlotValues.of("candidates", List.of());
        var opts = new EntityGraphRetriever.Options(
            params.getInt("topK", 20), params.getInt("maxHop", 2),
            params.getDouble("minRelConf", 0.5), params.getDouble("decay", 0.6));
        var candidates = retriever.retrieve(u, scope.snapshotIds(), ctx.domain(), opts);
        return SlotValues.of("candidates", candidates);
    }
}
```

> 注：现有 `Retriever` 接口签名 `(RetrievalQuery, snapshotIds, topK)` 装不下 `domain/maxHop/decay`，
> 故 `EntityGraphRetriever` 用**自有 `retrieve(understanding, snapshotIds, domain, Options)`** 方法
> （不强套 `Retriever` 接口，与 `GraphExpander` 一样是被算子包裹的专用检索器）。

---

## 4. 核心检索逻辑（EntityGraphRetriever + OntologyGraphMapper）

四步，全程一次 DB 往返内以 JOIN 完成（本体表与 `asset_retrieval_units` **同库**是最大红利）：

```
QueryUnderstanding.entities
  │  ① 实体链接：归一 → ontology_alias_dictionary / ontology_entities → 种子 canonical 实体 id
  ▼
  │  ② 图遍历：递归 CTE 沿 ontology_entity_relations 扩 ≤maxHop 跳（记 hop、路径 conf 之积）
  ▼
  │  ③ 出处回证：种子+邻域实体 → ontology_evidence_nodes(target_kind='entity') → segment_id
  ▼
  │  ④ 段→单元 + 打分：segment_id JOIN asset_retrieval_units.source_segment_id（过 snapshotIds）
  ▼
List<RetrievalCandidate>(retrievalUnitId, score, source='entity_graph', meta{hop,conf,relation})
```

### 4.1 三段 SQL（`OntologyGraphMapper.xml`）

**A. 实体链接**
```sql
SELECT e.id, e.canonical_name, e.node_type
FROM ontology_entities e
WHERE e.domain_id = #{domain}
  AND ( lower(e.canonical_name) IN (<names>)
        OR e.id IN (
          SELECT en.id FROM ontology_alias_dictionary a
          JOIN ontology_entities en
            ON en.domain_id = a.domain_id AND en.canonical_name = a.canonical_name
          WHERE a.domain_id = #{domain} AND a.alias_normalized IN (<names>) ) )
```

**B. 多跳邻域（递归 CTE，限深 + 置信剪枝 + 防环）**
```sql
WITH RECURSIVE nb(entity_id, hop, conf, path) AS (
    SELECT id, 0, 1.0, ARRAY[id] FROM ontology_entities WHERE id IN (<seedIds>)
  UNION ALL
    SELECT nxt.next_id, nb.hop + 1, nb.conf * r.confidence, nb.path || nxt.next_id
    FROM nb
    JOIN ontology_entity_relations r
      ON (r.head_entity_id = nb.entity_id OR r.tail_entity_id = nb.entity_id)
    CROSS JOIN LATERAL (
      SELECT CASE WHEN r.head_entity_id = nb.entity_id
                  THEN r.tail_entity_id ELSE r.head_entity_id END AS next_id) nxt
    WHERE nb.hop < #{maxHop}
      AND r.confidence >= #{minRelConf}
      AND NOT nxt.next_id = ANY(nb.path)          -- 防环：不重访路径上已出现的实体
)
SELECT entity_id, min(hop) AS hop, max(conf) AS conf FROM nb GROUP BY entity_id
```
> **防环**：本体关系按 head/tail 双向扩展，`A↔B` 类环若用朴素 `UNION ALL` 会在 hop 上限内反复绕、
> 稠密图上行数膨胀。故 CTE 携带 `path` 数组，用 `NOT next_id = ANY(path)` 排除已访问实体。`maxHop`
> 建议 ≤ 3；若需进一步控爆炸，可在 `LATERAL` 内对每个实体的扩展出度设上限
> （`ORDER BY r.confidence DESC LIMIT k`）。

**C. 实体 → 出处段 → 检索单元（同库一次 JOIN）**
```sql
SELECT ru.id, ru.text, ru.title, ru.document_snapshot_id, ru.unit_type,
       ru.source_segment_id, nb.hop, nb.conf
FROM ontology_evidence_nodes ev
JOIN asset_retrieval_units ru ON ru.source_segment_id = ev.segment_id
JOIN (<nb 结果>) nb ON nb.entity_id = ev.target_id
WHERE ev.domain_id = #{domain} AND ev.target_kind = 'entity'
  AND ru.document_snapshot_id IN (<snapshotIds>)
```
复用现成 `FtsResultRow` 承载行（已含 `source_segment_id/unit_type/document_snapshot_id`）。

> **两个已核验的落地细节**：
> 1. `asset_retrieval_units.source_segment_id` 是**可空**列（`init.sql:151`，非 NOT NULL）——
>    没有源段的单元（如跨段/纯生成单元）join 不上、自然不被图召回，可接受；
> 2. **一段多单元的扇出**：一个 `source_segment_id` 通常对应**多个单元**（`raw_text` / `entity_card` /
>    `generated_question` 共享同一源段），且一个单元可能是多个实体的证据 → SQL-C 会产生多行。
>    需在 Java 侧**按 `ru.id` 聚合、取 max 分**（见 §4.2 打分），可选按 `unit_type` 偏好
>    （如优先 `entity_card` / `raw_text`）以控每段候选数。

### 4.2 打分

```
score = BASE × decay^hop × relPathConfidence × evidenceBoost(node_type)
```
- `BASE ≈ 0.85`（略低于 entity_exact 的 0.95——图召回精度天然较低）；
- 同一 unit 被多路径命中取 **max**（避免累加虚高）；
- 分数写 `ScoreChain.rawScore`，`source='entity_graph'`，交下游融合 + 级联重排。

### 4.3 候选产出形态

**主：retrieval-unit 候选**（上文 SQL-C，join 回单元）——与 fts/dense/entity_exact 同构，融合最顺。
**备选：段落候选**（不 join 单元，id=segment_id，仿 `GraphExpandOperator` 的做法）——MVP 更简单，
`graph_expand` 已证明段落粒度候选可被 collect/assemble 正常处理。P1 前可先用段落粒度跑通链路。

---

## 5. 数据层与 DB 路由

- 新增 `mapper/OntologyGraphMapper.java` + `resources/mapper/OntologyGraphMapper.xml`（MyBatis）。
- **DB 路由**：本体表在**按域路由的同一个 asset 库**里。算子执行时 `DomainContext` 已由范式执行入口
  设好（现有检索算子同此机制），MyBatis 走 `DomainRoutingDataSource` 命中对应域库；SQL 再以
  `#{domain}`（来自 `ctx.domain()`）做 `domain_id` 列过滤，双保险。
- 强约束一致：只用有 `ontology_evidence_nodes` 出处的实体/边（挖掘侧保证无出处不落库）。

---

## 6. 在检索范式（paradigm）里怎么用

`entity_graph` 作为一个 `retrieve` 类算子节点，接进 DAG（与其它检索路并列，喂进融合）：

```
request_input → query_understanding → scope_resolve
     ├─ fts ─────────────┐
     ├─ dense_vector ────┤
     ├─ entity_exact ────┼─→ weighted_rrf → model_rerank → assemble → collect
     └─ entity_graph ────┘        (CANDIDATE_LIST_MULTI)
```
- 节点 `understanding` 槽 ← `query_understanding` 输出；`scope` 槽 ← `scope_resolve` 输出；
- 节点 `candidates` 输出 → 融合算子的变长 `CANDIDATE_LIST_MULTI` 入口；
- 用户在范式编辑器里给该节点设 `maxHop/topK/minRelConf/decay`，存进 paradigm 版本，无需改代码/重启。

**按需启用**：某个范式想用就拖进去，不想用就不放——比排"按 intent 配权"更灵活（范式即配置）。

---

## 7. 边界与降级

- 无 active 本体 / 查询链不到种子实体 / 遍历无果 → 返回空候选（`ErrorPolicy.SKIP_WITH_EMPTY`），
  `debug` 下 `NodeTrace` 记 `no_ontology` / `no_entity_link`；
- 遍历限额：`maxHop`（默认2）、`minRelConf` 剪枝、`topK` 封顶；
- 异常隔离：`SKIP_WITH_EMPTY` 保证单算子异常不炸整张范式；
- 无状态：所有 per-request 态走 inputs/params/ctx，算子 bean 线程安全、可并行。

---

## 8. 可观测性与评测

- **NodeTrace**：`ParadigmExecutor` 在 debug 下记录本节点耗时/摘要（命中种子实体数、候选数、跳数分布）；
- **评测**：用 `runtime_eval` 检索层指标（HitRate@K / NDCG / ContextRecall），做**含/不含
  entity_graph 两张范式**的对比——同一批 golden query（`domain.yaml` 的 `eval_questions` 已含"跨文档"类）
  跑两版范式看多跳类问题召回提升。

---

## 9. 落地清单与分期

**新增文件（4 个，零编排改动）**：
| 文件 | 作用 |
|------|------|
| `operator/operators/retrieve/EntityGraphOperator.java` | `@Component` 算子封装，自动注册 |
| `retrieval/EntityGraphRetriever.java` | 核心逻辑：实体链接→多跳→回证→打分 |
| `mapper/OntologyGraphMapper.java` | MyBatis 接口 |
| `resources/mapper/OntologyGraphMapper.xml` | 三段 SQL |

**不改**：`SearchService` / 老 `RetrievalOrchestrator` / `RetrievalRouter` / `ServingBeans`（`@Component`
自动注册，无需手动登记）/ 前端（算子目录自动带出）。

| 阶段 | 范围 |
|------|------|
| **MVP** | 单跳（maxHop=1）+ **段落粒度候选**（仿 graph_expand，免回表）+ 固定衰减打分；跑通"链接→出证→候选"，在测试范式里接上融合 |
| **P1** | 递归 CTE 多跳 + 置信剪枝 + **回表到 retrieval-unit 候选** + 命中边写入 `ContextPack.relations` |
| **P2** | 与向量召回互补调参、eval 回归、（可选）复用 v5 已有 `SemanticCacheService` 做语义缓存 |

---

## 10. 与旧方案的取舍（为什么改成算子）

初版设计把本体召回做成老 `RetrievalOrchestrator` 的"硬编码第 5 路 route"。在 v5 已算子化的前提下，
改为算子更优：

| | 硬编码 route | 算子（本方案） |
|---|---|---|
| 注册 | 改 `ServingBeans` 手动登记 | `@Component` 自动进 registry，**零编排改动** |
| 配置 | 只能在 `domain.yaml` 按 intent 配权 | 前端范式编辑器拖拽 + 表单调参，**无需改代码/重启** |
| 组合 | 固定并入 5 路 | 任意范式按需组合（喂进任意融合/重排） |
| 一致性 | 与 v5 演进方向脱节 | 与四个现有检索算子完全同构 |
| 入口影响 | 动了老 `/api/v1/search` | **只接算子系统，老入口零回归** |

---

## 11. 一句话总结

新增 `EntityGraphOperator`（`@Component` 自动注册）+ 其包裹的 `EntityGraphRetriever` + `OntologyGraphMapper`：
把查询实体消歧到 canonical 实体、沿 `ontology_entity_relations` 限深多跳、经 `ontology_evidence_nodes`
回证据段（**同库 JOIN**）产候选，按「跳数衰减 × 边置信」打分。它与现有检索算子同构，自动出现在算子
目录、可在任意检索范式里拖拽编排调参；**不触碰老 `/api/v1/search`**，零回归。

## 附：涉及的关键表/类

- 本体表：`ontology_entities` / `ontology_entity_relations` / `ontology_alias_dictionary` /
  `ontology_evidence_nodes`（DDL：`databases/ontology/schemas/001_ontology_concept_postgresql.sql`）
- serving 读表：`asset_retrieval_units`（`source_segment_id` 回表关键）
- 算子系统：`Operator` / `OperatorDef` / `SlotType`(QUERY_UNDERSTANDING/SCOPE/CANDIDATE_LIST) /
  `SlotDecl` / `ErrorPolicy.SKIP_WITH_EMPTY` / `OperatorRegistry` / `ExecContext.domain()` /
  `ParadigmExecutor` / `OperatorCatalogController`
- 模板算子：`EntityExactOperator`（同槽签名）、`GraphExpandOperator`（段落粒度候选先例）
