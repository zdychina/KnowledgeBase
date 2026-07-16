# 本体图谱检索（entity_graph）逻辑文档

> 依据：`operator/operators/retrieve/EntityGraphOperator.java`、`retrieval/EntityGraphRetriever.java`、`mapper/OntologyGraphMapper.java`、`resources/mapper/OntologyGraphMapper.xml`、`mapper/result/OntologyGraphRow.java`（以当前真实代码为准）。
> 定位：`retrieve` 类检索算子，与 `fts` / `dense_vector` / `entity_exact` / `graph_expand` 同构并列，产出候选喂给融合节点。

---

## 1. 概述

`entity_graph` 是检索侧消费本体知识图谱的算子。它把查询理解出的实体消歧到 canonical（规范）实体，沿本体的"实体—关系"图做有界多跳遍历，再经出处（evidence）回到证据段落，最终召回这些段落对应的检索单元（retrieval unit），并按"跳数衰减 × 路径置信"打分。

与其它检索算子的分工：

- `entity_exact`：实体名字面匹配检索单元，不做图遍历。
- `graph_expand`：在**段落**间的 RST 语篇/结构关系图（`asset_raw_segment_relations`）上 BFS。
- `entity_graph`：在**实体**本体关系图（`ontology_entity_relations`）上多跳，再回落到证据段落。

三者互补，可在同一检索范式里并列启用。

---

## 2. 组件结构

| 组件 | 类型 | 职责 |
|------|------|------|
| `EntityGraphOperator` | `@Component` 算子 | 声明槽/参数契约，读输入槽 → 调 retriever → 输出候选 |
| `EntityGraphRetriever` | `@Component` 检索器 | 核心逻辑：收名字 → 实体链接 → 图遍历回证 → 打分组装 |
| `OntologyGraphMapper` | MyBatis 接口 | 两个查询方法 `linkEntities` / `graphRecall` |
| `OntologyGraphMapper.xml` | SQL 映射 | 实体链接 SQL + 递归 CTE 多跳 SQL |
| `OntologyGraphRow` | 结果行 | 承载单元字段 + 图专有量 `hop` / `conf` |

调用关系：`EntityGraphOperator.execute()` → `EntityGraphRetriever.retrieve()` → `OntologyGraphMapper.linkEntities()` / `graphRecall()`。

算子标 `@Component`，启动时由 `OperatorRegistry` 按 `type="entity_graph"` 自动收集，无需手动登记；`EntityGraphRetriever` 同样 `@Component` 自注册，注入的 Mapper 随请求的按域路由 DataSource 命中对应域库。

---

## 3. 算子契约

### 3.1 槽签名

与其它四个检索算子完全一致，因此可直接接入任意范式的融合节点：

| 方向 | 槽名 | 类型 | 来源 / 去向 |
|------|------|------|-----------|
| 输入（必填） | `understanding` | `QUERY_UNDERSTANDING` | ← `query_understanding` 节点 |
| 输入（必填） | `scope` | `SCOPE` | ← `scope_resolve` 节点（提供 `snapshotIds`） |
| 输出（必填） | `candidates` | `CANDIDATE_LIST` | → 融合算子的 `CANDIDATE_LIST_MULTI` 入口 |

`domain` 不经过槽传递，来自 `ExecContext.domain()`；请求进入时 DB 已按域路由，`domain` 仅用于 SQL 里的 `domain_id` 列过滤。

### 3.2 参数（paramSchema，draft-07）

前端 `/operator/catalog` 依据此 schema 自动渲染配置表单。

| 参数 | 类型 | 默认 | 范围 | 含义 |
|------|------|------|------|------|
| `topK` | integer | 20 | 1–200 | 返回候选数上限（SQL `LIMIT`） |
| `maxHop` | integer | 2 | 1–3 | 图遍历最大跳数 |
| `minRelConf` | number | 0.5 | 0–1 | 关系置信下限，低于此值的边不遍历 |
| `decay` | number | 0.6 | 0–1 | 跳数衰减系数，用于打分 |

> **算子路径 vs legacy 路径**：以上 4 参数在**算子路径**（`EntityGraphOperator.execute`）经节点 `params` 全量生效，构造 `Options(topK, maxHop, minRelConf, decay)`。而 legacy `/api/v1/search` 路由路径（`EntityGraphRouteRetriever`）因 `Retriever` 接口签名带不了图参数，`maxHop / minRelConf / decay` 用**写死的默认值**（与本 schema 默认一致），仅 `topK` 来自路由的 `top_k`——即该路径下实际只有 `topK` 可配。

参数速查（作用阶段 / 性质 / 调整效果）：

| 参数 | 作用阶段 | 性质 | 调大 | 调小 |
|------|---------|------|------|------|
| `topK` | 结果输出 | 数量上限 | 召回更多候选 | 只留最优少数 |
| `maxHop` | 遍历 | 深度上限 | 扩得更远更全，噪声/耗时增 | 只看近邻，精准保守 |
| `minRelConf` | 遍历 | 硬门槛（剪边） | 更精准、覆盖窄 | 覆盖广、噪声多 |
| `decay` | 打分 | 软衰减 | 远处实体也能冒头 | 强压远跳，突出近邻 |

### 3.3 错误策略

`ErrorPolicy.SKIP_WITH_EMPTY`：无本体、链不到实体、遍历无果或异常时返回空候选，不影响同范式其它检索路。

### 3.4 早退

`EntityGraphOperator.execute` 在进入 retriever 前先判空：`understanding` 为 null、`scope` 为 null、或 `scope.snapshotIds()` 为空，任一成立即返回空 `candidates`。否则用 `params` 构造 `EntityGraphRetriever.Options(topK, maxHop, minRelConf, decay)` 并调用 `retriever.retrieve(u, scope.snapshotIds(), ctx.domain(), opts)`。

---

## 4. 数据库表

本算子读取 4 张本体表（`ontology_*`，挖掘期写入，DDL 见 `databases/ontology/schemas/001_ontology_concept_postgresql.sql`）加 1 张 serving 侧检索单元表。5 张表全部位于**按域路由的同一个 asset 库**，因此整条召回在一次 DB 往返内以 JOIN 完成，无跨库/跨服务调用。表之间的连接链即算子的召回路径：

```
查询实体名
  │ linkEntities:  lower(canonical_name) 命中，或 alias_dictionary 别名 → canonical_name
  ▼
ontology_entities ──(head/tail 双向多跳)── ontology_entity_relations
  │ 邻域实体 id
  ▼
ontology_evidence_nodes  (target_kind='entity', target_id=实体 id → segment_id)
  │ segment_id
  ▼
asset_retrieval_units    (source_segment_id = segment_id, 按 snapshotIds 过滤) → 候选
```

### 4.1 `ontology_entities` — canonical 实体档案

消歧后的领域实体，一个真实对象一条。是实体链接的目标与图遍历的节点。

| 列 | 说明 | 本算子用途 |
|----|------|-----------|
| `id` (PK) | 实体唯一 id | 种子 id、遍历节点、`evidence_nodes.target_id` 关联键 |
| `domain_id` | 所属域 | `domain_id = #{domain}` 过滤 |
| `canonical_name` | 规范名 | `lower(canonical_name)` 参与实体链接 |
| `node_type` | 节点类型（如 product / network_element） | 未直接使用（保留） |

唯一约束 `(domain_id, node_type, canonical_name)`。

### 4.2 `ontology_entity_relations` — 实体事实边

实体间的领域事实关系，有向存储但检索按无向遍历。多跳的边来源。

| 列 | 说明 | 本算子用途 |
|----|------|-----------|
| `head_entity_id` / `tail_entity_id` | 边两端实体（各有索引 `idx_der_head` / `idx_der_tail`） | `ON (head=cur OR tail=cur)` 双向匹配，取对端为下一跳 |
| `relation_type` | 关系类型 | 未过滤（保留） |
| `confidence` | 边置信（默认 0.7） | `>= minRelConf` 剪枝；路径置信为沿途 `confidence` 连乘 |
| `domain_id` | 所属域 | `domain_id = #{domain}` 过滤 |

约束：出处强制非空（`source_refs_json` 长度 > 0）、禁自环（head ≠ tail）、`(domain_id, head, tail, relation_type)` 唯一。

### 4.3 `ontology_alias_dictionary` — 别名词典

别名（归一化形态）到规范名的映射，为实体链接提供别名入口。

| 列 | 说明 | 本算子用途 |
|----|------|-----------|
| `alias_normalized` | 归一化别名 | 与查询名等值匹配（`IN (<names>)`） |
| `canonical_name` | 对应规范名 | 关联回 `ontology_entities.canonical_name` |
| `domain_id` | 所属域 | 与实体表 `domain_id` 对齐 |

唯一约束 `(domain_id, alias_normalized)`。

### 4.4 `ontology_evidence_nodes` — 出处

把实体/关系/mention 挂回它被佐证的段落，是"图 → 文本"的桥。挖掘侧"无出处不落库"，故每个被召回实体必有出处。

| 列 | 说明 | 本算子用途 |
|----|------|-----------|
| `target_kind` | 出处对象类型：`entity` / `relation` / `mention` | 固定取 `= 'entity'` |
| `target_id` | 出处对象 id | `= 实体 id`（关联 `entities.id`，索引 `idx_ev_target`） |
| `segment_id` | 证据段落 id（索引 `idx_ev_segment`） | 关联 `asset_retrieval_units.source_segment_id` |
| `domain_id` | 所属域 | `domain_id = #{domain}` 过滤 |

### 4.5 `asset_retrieval_units` — 检索单元（召回产物）

serving 侧的检索单元表，是本算子最终产出的候选实体。

| 列 | 说明 | 本算子用途 |
|----|------|-----------|
| `id` | 单元 id | 候选键 `retrievalUnitId`，`GROUP BY` 收敛键 |
| `source_segment_id` | 源段落 id（**可空**） | `= evidence_nodes.segment_id` 回表 |
| `document_snapshot_id` | 所属快照 | `IN (<snapshotIds>)` 做 scope 过滤 |
| `text` / `title` / `block_type` / `semantic_role` / `unit_type` | 单元内容与元数据 | 写入候选 metadata；`unit_type='entity_card'` 触发打分加权 |

> `source_segment_id` 可空：无源段的跨段/纯生成单元 JOIN 不上，不会被图召回。

`unit_type` 是**表中实存的 `TEXT` 列**（非计算值），DDL 带 `CHECK` 约束，取值限定为 7 种枚举之一（`databases/asset_core/schemas/002_asset_core_postgresql.sql`）：

```sql
unit_type TEXT NOT NULL CHECK (
    unit_type IN (
        'raw_text', 'contextual_text', 'summary', 'generated_question',
        'entity_card', 'table_row', 'other'
    )
),
```

且建有索引 `idx_asset_retrieval_units_unit_type`。数据流：挖掘期 retrieval_units 阶段写库时定死 `unit_type`（构建实体卡片写 `'entity_card'`）→ `graphRecall` 直接 `SELECT ru.unit_type` 读出 → 映射到 `OntologyGraphRow.unitType` → 打分时 `"entity_card".equals(...)` 判定加权（§7 的 `entityCardBoost`）。即：一条单元是不是 `entity_card` 在写库时就确定，检索仅读取该真实存储值作为加权依据。

---

## 5. 执行流程

`EntityGraphRetriever.retrieve(u, snapshotIds, domain, opts)` 分四步。

### 5.1 收集实体名（collectNames）

1. 遍历 `understanding.entities`，每个 `EntityRef` 取 `name` 与 `normalizedName`。
2. 每个名字 `trim()` + `toLowerCase()` 后放入 `LinkedHashSet`（去重且保序）。
3. 若一个实体名都未收到，退化用 `keywords` 兜底：长度 ≥ 2 的关键词同样归一后加入。

归一化必须在 Java 侧完成——SQL 侧 `alias_normalized` 做等值匹配、`canonical_name` 仅做 `lower()`。`entities` 非空时不看 keywords。

### 5.2 实体链接（linkEntities）

将归一后的名字解析为种子 canonical 实体 id。命中两条路径：规范名直接命中，或通过别名字典命中（见 §6.1）。返回去重后的 `seedIds`；若为空，直接返回空候选（对应 `no_entity_link`）。

### 5.3 图遍历 + 回证 + 回表（graphRecall）

一条递归 CTE SQL 完成：从 `seedIds` 沿 `ontology_entity_relations` 有界多跳（记录 hop、路径置信、防环），邻域实体经 `ontology_evidence_nodes` 回到 `segment_id`，再 JOIN `asset_retrieval_units`（按 `source_segment_id` 对齐，按 `snapshotIds` 过滤），每检索单元收敛为一行（见 §6.2）。返回 `List<OntologyGraphRow>`。

### 5.4 打分组装（toCandidate）

对每行按 §7 公式计算分数，组装 `RetrievalCandidate`（含 metadata 与 `ScoreChain`）。

### 5.5 返回空候选的情形

以下均为正常业务态而非错误，统一返回 `List.of()`：

- `u` / `snapshotIds` / `domain` 为空或 `domain` 空白；
- `collectNames` 收不到任何名字；
- `linkEntities` 未链到种子实体；
- `graphRecall` 遍历无果（scope 内无对应证据单元）。

---

## 6. SQL 细节

### 6.1 实体链接 linkEntities

```sql
SELECT DISTINCT e.id
FROM ontology_entities e
WHERE e.domain_id = #{domain}
  AND (
      lower(e.canonical_name) IN (<names>)
      OR EXISTS (
          SELECT 1 FROM ontology_alias_dictionary a
          WHERE a.domain_id = e.domain_id
            AND a.canonical_name = e.canonical_name
            AND a.alias_normalized IN (<names>) )
  )
```

- 规范名匹配对 `canonical_name` 做 `lower()`；别名匹配对 `alias_normalized` 直接等值（该列本身即归一化形态）。
- 别名子查询通过 `canonical_name` 关联回实体，即"别名 → 规范名 → 实体"。
- `DISTINCT` 去重：一个名字可能既是规范名又是别名，或多名字命中同一实体。

### 6.2 多跳召回 graphRecall

单条 SQL，三段 CTE + 主查询。

**① 递归 CTE `nb`：从种子沿边扩展**

```sql
WITH RECURSIVE nb(entity_id, hop, conf, path) AS (
    SELECT e.id, 0, CAST(1.0 AS double precision), ARRAY[e.id]
    FROM ontology_entities e
    WHERE e.domain_id = #{domain} AND e.id IN (<seedIds>)
  UNION ALL
    SELECT nxt.next_id,
           nb.hop + 1,
           nb.conf * r.confidence,
           nb.path || nxt.next_id
    FROM nb
    JOIN ontology_entity_relations r
      ON r.domain_id = #{domain}
     AND (r.head_entity_id = nb.entity_id OR r.tail_entity_id = nb.entity_id)
    CROSS JOIN LATERAL (
      SELECT CASE WHEN r.head_entity_id = nb.entity_id
                  THEN r.tail_entity_id ELSE r.head_entity_id END AS next_id
    ) nxt
    WHERE nb.hop < #{maxHop}
      AND r.confidence >= #{minRelConf}
      AND NOT nxt.next_id = ANY(nb.path)
)
```

- **锚**：种子实体，`hop=0`、`conf=1.0`、`path=ARRAY[id]`。
- **双向遍历**：边有向存储，但 `ON (head = cur OR tail = cur)` 两方向都匹配，`LATERAL` 里的 `CASE` 取对端实体作为下一跳，等价于无向图遍历。
- **路径置信**：`conf = nb.conf * r.confidence`，即沿途各边置信之积；跳得越远、经过的边越不确定，`conf` 越小。
- **限深与剪枝**：`nb.hop < maxHop` 限制跳数，`r.confidence >= minRelConf` 剪掉低置信边——这是**遍历阶段的硬门槛**（布尔筛选），置信低于门槛的边彻底不走，对端实体这条路就到不了。例：`发动机—包含—活塞`(0.92) 与 `发动机—可能导致—噪音`(0.35)，`minRelConf=0.5` 时前者走通、后者被剪，「噪音」相关证据段不由此路径召回。注意它与路径置信 `conf` 的分工——`minRelConf` 卡**单条边**是否可走，`conf` 是**整条路径**各边置信的连乘积（软权重，参与打分排序）；一条路径即便每条边都过门槛，多跳连乘后整体 `conf` 仍明显衰减、排序靠后。调高 `minRelConf` → 精准但覆盖窄，调低 → 覆盖广但噪声多（多跳时噪声顺链放大）。
- **防环**：每行携带已访问实体的 `path` 数组，`NOT next_id = ANY(nb.path)` 排除路径上已出现的实体，避免稠密无向图上环导致的行数膨胀。

**② 聚合 `nb_agg`：每实体收敛为最短跳 / 最优置信**

```sql
nb_agg AS (
    SELECT entity_id, MIN(hop) AS hop, MAX(conf) AS conf
    FROM nb GROUP BY entity_id
)
```

同一实体可能被多条路径以不同跳数到达，取 `MIN(hop)` / `MAX(conf)`，多路径命中不累加。

**③ 回证 + 回表 + 收敛到单元**

```sql
SELECT ru.id, ru.text, ru.title, ru.document_snapshot_id,
       ru.block_type, ru.semantic_role, ru.unit_type, ru.source_segment_id,
       MIN(nb_agg.hop)  AS hop,
       MAX(nb_agg.conf) AS conf
FROM nb_agg
JOIN ontology_evidence_nodes ev
  ON ev.domain_id = #{domain}
 AND ev.target_kind = 'entity'
 AND ev.target_id = nb_agg.entity_id
JOIN asset_retrieval_units ru
  ON ru.source_segment_id = ev.segment_id
 AND ru.document_snapshot_id IN (<snapshotIds>)
GROUP BY ru.id, ru.text, ru.title, ru.document_snapshot_id,
         ru.block_type, ru.semantic_role, ru.unit_type, ru.source_segment_id
ORDER BY MIN(nb_agg.hop) ASC, MAX(nb_agg.conf) DESC
LIMIT #{limit}
```

- **回证**：邻域实体经 `ontology_evidence_nodes`（`target_kind='entity'`）挂回证据 `segment_id`。
- **回表**：`segment_id` 对齐 `asset_retrieval_units.source_segment_id`，并按 `snapshotIds` 做 scope 过滤，只召回范围内单元。
- **收敛到单元**：`GROUP BY ru.id` 把"一段多单元 / 一单元多实体证据"的扇出收敛为一行/单元，取 `MIN(hop)` / `MAX(conf)`。
- **排序**：`hop` 升序优先、`conf` 降序次之，再 `LIMIT topK`。

落地约束：一个 `source_segment_id` 常对应多个单元（`raw_text` / `entity_card` / `generated_question` 共享源段），且一个单元可能是多个实体的证据，故 `GROUP BY ru.id` 收敛此扇出（`source_segment_id` 可空导致的漏召回见 §4.5）。

### 6.3 结果行 OntologyGraphRow

映射标准单元字段（`id/text/title/documentSnapshotId/blockType/semanticRole/unitType/sourceSegmentId`）加两个图专有量：`hop`（0=种子自身证据，越大越远）、`conf`（路径置信 ∈ [0,1]，多路径取最大）。

---

## 7. 打分

```
score = BASE × decay^hop × conf × entityCardBoost
```

`EntityGraphRetriever.toCandidate` 中的常量与钳制：

| 因子 | 规则 | 说明 |
|------|------|------|
| `BASE` | `0.85` | hop=0、满置信单元的基分，略低于 `entity_exact` 的 0.95（图召回精度天然较低） |
| `decay^hop` | `decay` 默认 0.6，指数取 `max(0, hop)` | 每远一跳打折：hop0=1、hop1=0.6、hop2=0.36 |
| `conf` | `conf<=0 → 0.01`，否则 `min(1.0, conf)` | 钳到 (0,1] |
| `entityCardBoost` | `unit_type == "entity_card"` → 1.1，否则 1.0 | 实体卡片轻微加权；公式里唯一可能超过 BASE 的因子 |
| `decay` 兜底 | `decay<=0 或 >1 → 0.6` | 参数越界回退默认 |

各因子含义：`decay^hop` 按最短跳距指数衰减（decay=0.6 时 hop0=1、hop1=0.6、hop2=0.36），越远越弱；`conf` 是路径各边置信连乘积（多路径取 MAX），越可靠越短越接近 1。`entity_card` 命中时 hop=0、conf=1 的上界为 `0.85×1×1×1.1=0.935`，仍压在 `entity_exact` 的 0.95 之下。

数值示例：

- `entity_card`，hop=1，单边置信 0.8：`0.85 × 0.6^1 × 0.8 × 1.1 ≈ 0.449`
- 普通段落单元，hop=2，路径置信 0.5×0.9=0.45：`0.85 × 0.6^2 × 0.45 × 1.0 ≈ 0.138`

跳得越远、路径越弱、单元质量越低，三重折扣叠乘拉开层次。分数经 `source="entity_graph"` 的候选进入多路融合，与 `fts`/`dense_vector`/`entity_exact` 通道一起排序去重——BASE 压在 0.95 之下正是为让各通道分数量纲可比。

产出 `RetrievalCandidate`：

- `retrievalUnitId` = `row.id`，`score` 如上，`source = "entity_graph"`；
- `scoreChain = ScoreChain(score, 0.0, 0.0, ["entity_graph"])`，分数写入 `rawScore`，`fusionScore` / `rerankScore` 留给下游；
- `metadata` 非空才放入：`text`、`title`、`document_snapshot_id`、`block_type`、`semantic_role`、`unit_type`、`source_segment_id`，另加固定写入的 `graph_hop`、`graph_conf`（供下游解释召回来源与跳距）。

---

## 8. 范式接入

`entity_graph` 作为普通 `retrieve` 节点接入 DAG，与其它检索路并列喂进融合。

```
request_input → query_understanding → scope_resolve
     ├─ fts ─────────────┐
     ├─ dense_vector ────┤
     ├─ entity_exact ────┼─→ weighted_rrf → score_rerank → assemble
     └─ entity_graph ────┘        (CANDIDATE_LIST_MULTI)
```

接线（见 `resources/paradigm/examples/hybrid_with_entity_graph.json`）：

- `understanding` 槽 ← `query_understanding` 的 `understanding` 输出；
- `scope` 槽 ← `scope_resolve` 的 `scope` 输出；
- `candidates` 输出 → 融合算子（`weighted_rrf` / `rrf`）的变长 `CANDIDATE_LIST_MULTI` 入口；
- `maxHop/topK/minRelConf/decay` 在范式编辑器表单填写，存入 paradigm 版本，无需改代码或重启。

单算子冒烟范式见 `resources/paradigm/examples/entity_graph_test.json`：`query_understanding + scope_resolve → entity_graph → collect`，用于单独验证链接→回证→候选链路。

---

## 9. 边界、降级与运行约束

- 无 active 本体 / 链不到种子 / 遍历无果 → 空候选；debug 下 `NodeTrace` 记 `no_ontology` / `no_entity_link`。
- 遍历限额：`maxHop`（默认 2，上限 3）、`minRelConf` 剪枝、`topK` 封顶、`path` 防环，共同控住稠密图爆炸。
- 异常隔离：`SKIP_WITH_EMPTY` 保证单算子异常不影响整张范式。
- 无状态：per-request 态全走 `inputs/params/ctx`，算子与 retriever 均为线程安全单例，可并行。
- DB 路由：`DomainContext` 由范式执行入口设好，MyBatis 走 `DomainRoutingDataSource` 命中对应域库；SQL 再以 `#{domain}` 做 `domain_id` 列过滤。

---

## 10. 可观测性与评测

- NodeTrace：debug 下记录本节点耗时与摘要（种子实体数、候选数、跳数分布）；单条候选的 `graph_hop` / `graph_conf` 可解释召回来源。
- 评测：用 `runtime_eval` 检索层指标（HitRate@K / NDCG / ContextRecall），对比"含 / 不含 `entity_graph`"两张范式在同一批 golden query（`domain.yaml` 的 `eval_questions`，含跨文档类）上的召回差异。

---

## 11. 已知局限

1. 召回质量受本体覆盖与准确度约束；实体未链上（别名字典缺失）则整条哑火。
2. 无内容级质量剪枝：`minRelConf` 只判断边可信度，不判断扩到的实体证据与 query 内容相关性，可能扩进"关系对但内容不相关"的段落。
3. 置信连乘随跳数快速衰减，叠加 `decay^hop`，深层实体分难以冒头（刻意保守）。
4. `entity_card` 加权固定 1.1，仅按 `unit_type` 判定，不区分卡片质量。
5. `source_segment_id` 为空的跨段/生成单元不进图召回（设计如此）。

---

## 附：文件 / 表 / 类

| 文件 | 职责 |
|------|------|
| `operator/operators/retrieve/EntityGraphOperator.java` | 算子封装：槽/参数契约，读槽→调 retriever→出候选 |
| `retrieval/EntityGraphRetriever.java` | 核心逻辑：collectNames → linkEntities → graphRecall → toCandidate |
| `mapper/OntologyGraphMapper.java` | MyBatis 接口（linkEntities / graphRecall） |
| `resources/mapper/OntologyGraphMapper.xml` | 实体链接 SQL + 递归 CTE 多跳 SQL |
| `mapper/result/OntologyGraphRow.java` | 结果行：单元字段 + hop / conf |
| `resources/paradigm/examples/hybrid_with_entity_graph.json` | 四路召回混合范式示例 |
| `resources/paradigm/examples/entity_graph_test.json` | 单算子冒烟范式示例 |

- 本体表 DDL：`databases/ontology/schemas/001_ontology_concept_postgresql.sql`
- 算子系统类：`Operator` / `OperatorDef` / `SlotDecl` / `SlotType` / `ErrorPolicy` / `OperatorRegistry` / `ExecContext` / `ParadigmExecutor` / `OperatorCatalogController`
- 产物 domain 类：`RetrievalCandidate` / `ScoreChain` / `QueryUnderstanding` / `EntityRef`
