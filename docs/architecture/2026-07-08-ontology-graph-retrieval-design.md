# 本体图谱召回（entity_graph 检索通道）设计

> 日期：2026-07-08
> 状态：方案设计（未进入实现）
> 目标服务：`agent_serving_java`（基于 v5 检索侧领先版）
> 范围：serving 检索侧新增一路本体图谱召回；依赖挖掘侧已落地的本体子系统（`ontology_*` 表）

---

## 0. 背景与现状

挖掘侧（`knowledge_mining`）已经建起完整的本体/实体知识图谱：`ontology_entities`（canonical 实体）、
`ontology_entity_relations`（事实边）、`ontology_evidence_nodes`（出处）、`asset_segment_entity_mentions`
（文章级 mention），并支持人审进化（Gate1/Gate2）。

**但检索侧（`agent_serving_java`）目前完全没有消费这张图谱。** 经代码核查（两版 serving 均）：

- 全 serving 源码对 `ontology_entities` / `ontology_entity_relations` / `ontology_node_types` /
  `asset_segment_entity_mentions` 的引用数为 **0**。
- 现有 `graph_expand`（`GraphExpander`）遍历的是 `asset_raw_segment_relations`——**段落间 RST 修辞关系**，
  不是实体图谱。
- 现有 `entity_exact`（`EntityExactRetriever`）匹配的是 `asset_retrieval_units.entity_refs_json`——
  单元上挂的**原始实体串字面匹配**，既不走消歧后的 canonical 实体，也不沿实体关系多跳。

因此设计文档所说的"本体带来的新检索角度（实体邻域、沿关系多跳召回）"目前是**设计有、实现无**。
本方案填补这个缺口。

---

## 1. 目标与定位

新增**第 5 路检索通道** `entity_graph`，与 `fts` / `dense_vector` / `entity_exact` / `graph_expand`
并行，补充**实体维度的召回**：查询命中实体后，沿"实体—关系"边多跳，把邻域实体的证据段一并召回。

典型收益场景（云核网域）：

- 查「SMF 会话建立」→ 沿 `SMF —connects_to→ N4 —uses_protocol→ PFCP` 把 N4、PFCP 的相关片段带出；
- 查「UPF 故障」→ 沿关系带出与 UPF 直接相连的网元/接口的排障片段。

**定位**：一路独立召回（recall route），不是重排、不是段落扩展。与 `entity_exact` 的本质区别——
`entity_exact` 是"实体名字面匹配单元"，本方案是"**消歧到 canonical 实体 → 图上多跳 → 经出处回到证据段**"。

---

## 2. 核心难点与破解

| 难点 | 破解 |
|------|------|
| 图是「实体→(出处)→段落」，候选模型（`RetrievalCandidate`）以 **retrieval_unit** 为主键 | 本体表外键指向 `asset_document_snapshots/asset_raw_segments`，与 `asset_retrieval_units` **同库**；一条 SQL 从 `ontology_evidence_nodes.segment_id` JOIN 回 `asset_retrieval_units.source_segment_id` 直接产 unit 候选 |
| 多跳邻域可能爆炸 | 递归 CTE **限深（默认 1–2 跳）+ 限每跳出度 + 按关系 confidence 剪枝** |
| 无本体 / 查询没链到实体，不能拖慢主链路 | 编排器已有 auto-skip 机制（仿 `dense_vector` 无 embedding 即跳）；无 active 本体或链不到实体就返回空并记 trace |
| 多租户/按域 | 本体表都是 `domain_id` 列，serving 已按域路由数据源；查询再带 `domain_id` 兜底 |

**最大工程红利**：本体表与 serving 读表同库，召回全程可在一次 DB 往返内以 JOIN 完成，无需跨服务/跨库。

---

## 3. 召回流程（四步）

```
查询实体 (QueryUnderstanding.entities)
  │  ① 实体链接 (entity linking)
  ▼
canonical 实体 id  ── ontology_alias_dictionary / ontology_entities 归一
  │  ② 图遍历 (bounded multi-hop)
  ▼
种子实体 + 邻域实体 (+ 命中的边、跳数、confidence)
  │  ③ 出处回证 (evidence → segment)
  ▼
证据段 segment_id  ── ontology_evidence_nodes (entity/relation)
  │  ④ 段 → 单元 + 打分
  ▼
RetrievalCandidate(retrievalUnitId, score, source='entity_graph', metadata{hop, path, relation})
```

**① 实体链接**：把 `query.entities()`（+ keywords 兜底）归一，命中 `ontology_alias_dictionary.alias_normalized`
或 `ontology_entities` 规范名 → 种子 canonical 实体 id + node_type。

**② 图遍历**：递归 CTE 沿 `ontology_entity_relations` 扩 N 跳，记录 `hop` 与路径上边的 `relation_type/confidence`。

**③ 出处回证**：种子 + 邻域实体 → `ontology_evidence_nodes`（`target_kind='entity'`）取 `segment_id`；
命中的边（`target_kind='relation'`）也回其证据段。

**④ 段→单元 + 打分**：`segment_id` JOIN `asset_retrieval_units.source_segment_id`（过 `snapshotIds` scope），
产出 unit 候选。

---

## 4. 打分设计

图召回分数体现「离查询实体越近越可信」：

```
score(unit) = BASE
            × decay^hop                      // 跳数衰减，decay ≈ 0.6
            × relPathConfidence              // 路径上边 confidence 之积（种子 hop0 = 1.0）
            × evidenceBoost(node_type)       // strong 类型 / entity_card 单元加权
```

- `BASE ≈ 0.85`（略低于 entity_exact 的 0.95——图召回精度天然低于字面精确）；
- 同一 unit 被多路径命中 → 取 **max**（或 top-2 之和封顶），避免重复累加虚高；
- 分数写进 `ScoreChain.rawScore`，`source='entity_graph'`，交下游 **Weighted RRF 融合 + 级联重排**，
  不单独截断。

---

## 5. 数据层（新增 Mapper + SQL）

新增 `OntologyGraphMapper.java` + `resources/mapper/OntologyGraphMapper.xml`，核心三段（可合成 1–2 次往返）：

### A. 实体链接

```sql
SELECT e.id, e.canonical_name, e.node_type
FROM ontology_entities e
WHERE e.domain_id = #{domain}
  AND ( lower(e.canonical_name) IN (<names>)
        OR e.id IN (
          SELECT en.id FROM ontology_alias_dictionary a
          JOIN ontology_entities en
            ON en.domain_id = a.domain_id
           AND en.canonical_name = a.canonical_name
          WHERE a.domain_id = #{domain} AND a.alias_normalized IN (<names>) ) )
```

### B. 多跳邻域（递归 CTE，限深限出度）

```sql
WITH RECURSIVE nb(entity_id, hop, conf) AS (
    SELECT id, 0, 1.0 FROM ontology_entities WHERE id IN (<seedIds>)
  UNION ALL
    SELECT CASE WHEN r.head_entity_id = nb.entity_id THEN r.tail_entity_id
                ELSE r.head_entity_id END,
           nb.hop + 1, nb.conf * r.confidence
    FROM nb JOIN ontology_entity_relations r
      ON (r.head_entity_id = nb.entity_id OR r.tail_entity_id = nb.entity_id)
    WHERE nb.hop < #{maxHop} AND r.confidence >= #{minRelConf}
)
SELECT entity_id, min(hop) AS hop, max(conf) AS conf
FROM nb GROUP BY entity_id
```

### C. 实体 → 出处段 → 检索单元（同库一次 JOIN 打通）

```sql
SELECT ru.id, ru.text, ru.title, ru.document_snapshot_id, ru.unit_type,
       ru.source_segment_id, nb.hop, nb.conf
FROM ontology_evidence_nodes ev
JOIN asset_retrieval_units ru ON ru.source_segment_id = ev.segment_id
JOIN (<nb 结果>) nb ON nb.entity_id = ev.target_id
WHERE ev.domain_id = #{domain} AND ev.target_kind = 'entity'
  AND ru.document_snapshot_id IN (<snapshotIds>)
```

复用现成 `FtsResultRow` 承载行（已有 `source_segment_id / unit_type / document_snapshot_id` 等字段）。

---

## 6. 接线（改动点清单）

| 位置 | 改动 |
|------|------|
| `retrieval/EntityGraphRetriever.java` | **新增**，`implements Retriever`，仿 `EntityExactRetriever`，注入 `OntologyGraphMapper` |
| `domain/ServingConstants.java` | 加 `ROUTE_ENTITY_GRAPH = "entity_graph"` |
| `config/ServingBeans.java` | 把 `EntityGraphRetriever` 以 `"entity_graph"` 注册进 orchestrator 的 `Map<String,Retriever>` |
| `pipeline/RetrievalOrchestrator.java` | auto-skip：该路无种子实体链接时记 `no_entity_link` 跳过（仿 `dense_vector` 无 embedding） |
| `application/RetrievalRouter.java` | route plan 支持 `entity_graph`（读 domain.yaml 权重/top_k/max_hop） |
| `application/ContextAssembler.java` | 把命中的边写进 `ContextPack.relations`（`from_id/to_id/type=relation_type`）；item 标 `routeSources += entity_graph`、`relationToSeed` |
| `scenario_packs/*/domain.yaml` | `serving.route_policy` 各 intent 加 `entity_graph` 权重/top_k |

### `EntityGraphRetriever` 骨架

```java
public class EntityGraphRetriever implements Retriever {
    private static final String SOURCE_NAME = "entity_graph";
    private static final double BASE = 0.85, DECAY = 0.6, MIN_REL_CONF = 0.5;
    private final OntologyGraphMapper mapper;

    @Override
    public List<RetrievalCandidate> retrieve(RetrievalQuery q, List<String> snapshotIds, int topK) {
        if (snapshotIds.isEmpty()) return List.of();
        List<String> names = normalizedEntityNames(q);           // 实体名 + normalized + keyword 兜底
        if (names.isEmpty()) return List.of();
        List<String> seedIds = mapper.linkEntities(domain(), names);
        if (seedIds.isEmpty()) return List.of();                 // → orchestrator 记 no_entity_link
        var rows = mapper.graphRecall(domain(), seedIds, snapshotIds, maxHop, MIN_REL_CONF, topK);
        return rows.stream().map(this::toCandidate).toList();     // score = BASE*DECAY^hop*conf
    }
}
```

---

## 7. 领域配置（按 intent 配权重）

`domain.yaml` 的 `serving.route_policy` 里给**受益 intent** 配较高权重，其余关掉：

```yaml
route_policy:
  troubleshooting:      # 排障最受益：沿相连网元/接口带出关联证据
    entity_graph: { weight: 1.2, top_k: 20, max_hop: 2 }
  concept_lookup:       # 概念查询次之：带出相关概念邻域
    entity_graph: { weight: 0.8, top_k: 15, max_hop: 1 }
  command_usage:        # 命令用法：实体精确已够，图召回关掉/低权
    entity_graph: { weight: 0.0 }
```

---

## 8. 边界与降级（不拖累主链路）

- **无 active 本体版本** → 整路跳过（`OntologyStore.active_version == null`），trace `no_ontology`；
- **查询链不到任何种子实体** → 跳过，trace `no_entity_link`；
- **遍历限额**：`max_hop`（默认 2）、每跳出度上限、`min_rel_conf`、总候选 `top_k` 封顶；
- **异常隔离**：编排器已对每路 try/catch，图召回失败不影响其余四路；
- **出处强约束一致**：只用有 `ontology_evidence_nodes` 出处的实体/边（挖掘侧已保证无出处不落库）。

---

## 9. 可观测性与评测

- **Trace**：`RouteTrace(entity_graph, attempted, candidateCount, reason, latencyMs)`；
  debug 模式把命中的种子实体、路径、跳数放进 `ContextPack.debug`；
- **评测**：用 `runtime_eval` 检索层指标（HitRate@K / NDCG / ContextRecall）做**开关对比**——
  同一批 golden query 跑「开/关 entity_graph」两组，看多跳类问题召回提升；
  `domain.yaml` 的 `eval_questions` 里已有"跨文档"类问题正好覆盖。

---

## 10. 分期落地

| 阶段 | 范围 |
|------|------|
| **MVP** | 单跳（max_hop=1）+ 仅种子实体证据 + 固定衰减打分；只在 `troubleshooting` intent 开；先跑通"链接→出证→单元" |
| **P1** | 递归 CTE 多跳 + 边 confidence 剪枝 + 边写入 `ContextPack.relations` |
| **P2** | 与向量召回互补调权、按 intent 精调、加语义缓存（复用 v5 已有 `SemanticCacheService`）；接 eval 回归 |

---

## 11. 一句话总结

新增一路 `entity_graph` 检索器——把查询实体消歧到 canonical 实体、沿 `ontology_entity_relations`
限深多跳、经 `ontology_evidence_nodes` 回到证据段并 JOIN 成 retrieval_unit 候选，按「跳数衰减 × 边置信」
打分，并入现有 RRF 融合 + 级联重排。落点小、隔离好、可按 intent 开关，**同库 JOIN** 是最大工程红利。

## 附：涉及的关键表/类

- 本体表：`ontology_entities` / `ontology_entity_relations` / `ontology_alias_dictionary` /
  `ontology_evidence_nodes` / `ontology_versions`（DDL：`databases/ontology/schemas/001_ontology_concept_postgresql.sql`）
- serving 读表：`asset_retrieval_units`（`source_segment_id` 是回表关键）
- 现有可复用类：`Retriever` 接口 / `RetrievalCandidate` / `ScoreChain` / `RetrievalOrchestrator` /
  `RouteConfig` / `EntityExactRetriever`（模板）/ `SemanticCacheService`（P2）
