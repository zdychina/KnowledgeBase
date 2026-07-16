# 图扩展（Graph Expansion）讲解

> 面向：给同事讲解上下文组装中的"图扩展"环节。
> 依据：实际源码 `retrieval/GraphExpander.java` + `mapper/AssetRawSegmentRelationMapper.xml` + `mapper/AssetRawSegmentMapper.xml`（非文档转述）。
> 关联：本环节是 `ContextAssembler` 组装流水线的第 3 步；产物喂给"RST 关系类型 → 证据角色映射"（见 `pipeline-08-context-assembly.md`）。

> ⚠️ **文档纠偏**：`pipeline-08-context-assembly.md` 说 "GraphExpander 无剪枝" 已过时——现在代码里有 **总预算 + 关系优先级** 两套控制。以本文为准。

---

## 1. 一句话定义 + 为什么要它

**图扩展**：从检索命中的"种子段落"出发，沿**段落之间的关系图**做 BFS（广度优先），把相邻的、语义/结构相关的段落也拉进上下文。

**为什么要**：向量/全文检索是"点状"命中，只找到最相关的几个片段；但回答一个问题往往还需要它的**前因后果、前提条件、上一步下一步、对比项**。这些相邻段落检索器不一定单独命中，靠关系图"顺藤摸瓜"补齐，让上下文更完整。属于业界的 **KG-augmented retrieval（知识图谱增强检索）**。

---

## 2. 数据基础（关系图从哪来）

一张表 `asset_raw_segment_relations`，每行是一条**段落间的边**：

| 列 | 含义 |
|----|------|
| `source_segment_id` / `target_segment_id` | 边的两端（有向） |
| `relation_type` | 关系类型（RST 语篇关系 + 结构关系） |
| `distance` | 原始距离 |
| `document_snapshot_id` | 所属快照（用于 scope） |

这些边在**挖掘阶段**建好：结构关系（`previous`/`next`/`same_section`/`section_header_of`…）+ RST 语篇关系（`elaborates`/`causes`/`results_in`/`contrasts_with`…）。**在线只读遍历，不建图。**

---

## 3. 输入 / 输出

**输入**（`GraphExpander.expand()`）：

| 参数 | 说明 |
|------|------|
| `seedIds` | 种子段落 id（来自检索候选的 `source_segment_id` / `source_refs_json`） |
| `maxDepth` | 最大 BFS 层数（默认 2） |
| `relationTypes` | 只走这些关系类型（null = 全部） |
| `maxResults` | 调用方想要的上限 |
| `snapshotIds` | 快照范围 |

**输出**：`List<ExpandedSegmentRow>`，每个扩展段落带 `segment`（全文+元数据）、`depth`（距种子几跳）、`rootSeed`（从哪个种子扩来）、`relationType`（靠哪种关系被拉进来）。
⚠️ **种子本身不在输出里**，只返回新扩展出来的。

### 3.1 种子 id（`seedIds`）从哪来 —— 扩展前的准备

**关键**：种子 id **不是检索候选本身**，而是每个候选"背后指向的原始段落（raw segment）id"。因为关系图 `asset_raw_segment_relations` 的边建在**段落**之间，而检索候选是"检索单元"（retrieval unit），粒度不同——扩展前必须先把候选**映射回它的源段落 id**。

**完整流程**（`ContextAssembler`）：

```
重排后的候选 candidates
   │  对每个候选 resolveCandidateSources(candidate) —— 三级优先级抽段落id
   ▼
allSourceSegmentIds(所有候选的段落id汇总)
   │  LinkedHashSet 去重(保留首次出现顺序)
   ▼
uniqueSegIds  ──────────────►  graphExpander.expand(uniqueSegIds, ...)  // 这就是 seedIds
```

**三级优先级抽取**（`resolveCandidateSources`，取到就返回、不再往下）：

| 优先级 | 字段 | 说明 |
|--------|------|------|
| **1** | `source_segment_id` | 候选直接标了源段落 id（最常见）→ 返回 `[segId]` |
| **2** | `source_refs_json` → `raw_segment_ids` | 单元跨多个段落（上下文增强/聚合单元）→ 返回这组 id |
| **3** | `target_ref_json`（且 `target_type` 非空）→ `raw_segment_ids` | 命令/实体类单元，源段落记在 target 引用里 |
| 都没有 | — | 返回空，该候选不贡献种子 |

三级正好对应不同的**检索单元类型**：多数单元带直接 `source_segment_id`；跨段单元用 `source_refs_json`；命令/实体卡片（`entity_card` 等）把段落引用放在 `target_ref_json`。

**要点**：

1. **为什么必须转换**：候选是 retrieval unit（`raw_text`/`generated_question`/`entity_card`/`table_row`），图的节点是 raw segment；一个 unit 可能由一个或多个 segment 派生，不转换就没法在段落关系图上走。
2. **所有候选都参与**：不是只取 top-N，重排后**每个候选**都抽段落 id（候选列表本身已被上游 rerank 的 topK 限过）。
3. **去重且保序**：`LinkedHashSet` 保留首次出现顺序 → 高分候选的段落排在前，影响 BFS 的 frontier 顺序与 `rootSeed`（每个扩展节点回溯到哪个种子）。
4. **同一份 `uniqueSegIds` 复用三处**：源文档下钻（取全文）、图扩展种子、直接关系获取。

**算子路径的差异**：`graph_expand` 算子（`GraphExpandOperator.collectSeedSegmentIds`）只用**两级**——`source_segment_id`，否则 `source_refs_json.raw_segment_ids`，**没有第 3 级 `target_ref_json`**，是组装器路径的子集。

---

## 4. 算法分步（BFS，可白板画）

```
visited  = {种子}          // 已访问,防重复
frontier = {种子}          // 当前层要扩的节点

for depth = 1 .. maxDepth:
    ① 一次 SQL:查 frontier 所有节点的"一跳邻居"   ← 每层只查一次,批量
    ② 把邻居按"关系优先级"排序                     ← 关键点(见 §5)
    ③ 逐个邻居:
        - 已访问 → 跳过
        - 新的   → 标记 visited、加入 nextFrontier、记录 (depth, relationType, rootSeed)
        - 每加一个就检查:达到预算 → 立即停,返回      ← 关键点(见 §5)
    ④ frontier = nextFrontier(进入下一层)

最后:resolveSegments —— 把扩展到的 id 批量查出全文+元数据
```

**走一个小例子**（maxDepth=2）：
```
种子 S ──elaborates──> A ──causes──> C
        └─next──────> B
```
- depth=1：查 S 的邻居 → A(elaborates)、B(next)。优先级 elaborates(1) 排在 next(13) 前，先收 A 再收 B。
- depth=2：查 {A,B} 的邻居 → C(causes, depth=2)。
- 输出：A(depth1)、B(depth1)、C(depth2)，各带 relationType 和 rootSeed=S。

---

## 5. 两个关键控制（重点）

### 5.1 总预算 `TOTAL_BUDGET = 20`（硬上限）

```java
int budget = Math.min(maxResults, TOTAL_BUDGET);   // TOTAL_BUDGET = 20
```

- **实际上限 = `min(maxResults, 20)`**：调用方传得比 20 小（如 `graph_expand` 算子默认 `maxResults=10`）→ 实际最多 10 条；传得比 20 大 → 压到 20。
- 预算是**跨所有层共享的一个总数**，不是每层 20。一旦扩展节点数达到预算，**立刻返回，可能停在 depth=1，depth=2 根本不执行**。

### 5.2 关系优先级（让"好关系"先占预算）

每层邻居**先按优先级排序再消费**，两种模式：

- **传了 `relationTypes`（意图感知）**：**列表顺序就是优先级**，index 0 最高。故障排查意图把 `causes`/`results_in` 放前面，对比类意图把 `contrasts_with` 放前面 → 各意图的"招牌关系"优先占预算。
- **没传（默认）**：用全局 RST 优先级表 `RELATION_PRIORITY`：
  ```
  entity_relation 0 → elaborates 1 → conditions/evidences 2 → backgrounds/exemplifies 3
  → enables 4 → results_in/purposes/justifies 5 → sequences/summarizes 6
  → contrasts_with/concedes 7 → causes 8 → parallels 9
  → 结构关系最后: section_header_of 10、same_section 11、previous 12、next 13、same_parent_section 14
  ```
  即**语义关系（详述/因果/条件）优先于结构关系（前后/同章节）**。

### 5.3 排序层级（同事最常问）

> **depth 是第一排序维度，关系优先级是第二维度。**

- BFS 一层层来：depth=1 的节点**总比** depth=2 先占预算。
- 关系优先级**只在同一层内部**决定谁先进（`sort` 在每层循环里对当前层邻居排）。
- 极端情况：depth=1 若有一堆低价值 `next` 且数量就超预算，可能先占满，depth=2 的高价值 `causes` 进不来——这正是"每层内优先级排序"要缓解的问题。

### 5.4 `RELATION_PRIORITY` 优先级表详解

`RELATION_PRIORITY` 是一张**静态优先级表**，给每种关系类型打一个优先级数字，用来在**预算有限（≤20）时决定哪种关系的邻居先被收进来**。规则：**数字越小 = 优先级越高 = 越先占预算。**

**源码原样：**

```java
Map<String,Integer> RELATION_PRIORITY = Map.ofEntries(
    entry("entity_relation",      0),   // 最高
    entry("elaborates",           1),
    entry("conditions",           2),   entry("evidences",     2),
    entry("backgrounds",          3),   entry("exemplifies",   3),
    entry("enables",              4),
    entry("results_in",           5),   entry("purposes", 5), entry("justifies", 5),
    entry("sequences",            6),   entry("summarizes",    6),
    entry("contrasts_with",       7),   entry("concedes",      7),
    entry("causes",               8),
    entry("parallels",            9),
    // ↓ 结构/位置关系,排最后
    entry("section_header_of",   10),
    entry("same_section",        11),
    entry("previous",            12),
    entry("next",                13),
    entry("same_parent_section", 14)
);
```

**分两大层看：**

| 层 | 优先级 | 关系类型 | 含义 |
|----|--------|----------|------|
| **语义/语篇关系**（有实质内容） | 0–9 | `entity_relation`(实体关系)、`elaborates`(详述)、`conditions`(条件)、`evidences`(佐证)、`backgrounds`(背景)、`exemplifies`(举例)、`enables`(使能)、`results_in`(导致)、`purposes`(目的)、`justifies`(论证)、`sequences`(顺序)、`summarizes`(总结)、`contrasts_with`(对比)、`concedes`(让步)、`causes`(起因)、`parallels`(并列) | RST 语篇关系 + 实体关系，真正在补充/支撑内容 |
| **结构/位置关系**（只是相邻） | 10–14 | `section_header_of`(章节标题)、`same_section`(同节)、`previous`(前)、`next`(后)、`same_parent_section`(同父节) | 仅位置/结构上挨着，证据价值弱 |

**设计意图**：预算就 20 个名额，当种子邻居很多时，让**"有内容的语义关系"先占坑**，别让一堆"只是同章节/前后相邻"的结构关系把名额占满——所以结构关系统一排在 10–14 最后。

**只在默认模式生效**（`resolvePriority()`）：

```java
if (relationTypes == null || relationTypes.isEmpty())
    return RELATION_PRIORITY;      // 默认:用这张全局表
// 否则:传入列表的"顺序"就是优先级(index 0 最高),本表让位
```

**几个易被追问的点：**

1. **表里没有的关系类型** → `getOrDefault(..., Integer.MAX_VALUE)` → 排到最后。
2. **数字有重复**（如 `conditions`=2 与 `evidences`=2）：允许并列，谁先由排序稳定性（原始顺序）决定。可见这张表是"核心 RST(0–9)+ 结构(10–14)"再补了一批（`evidences`/`exemplifies`/`purposes`/`justifies`/`summarizes`/`concedes`）复用 2–7 档位。
3. **`causes`=8 偏低有点反直觉**：因果排在 `elaborates`(1)、`results_in`(5) 之后。注释说它 "mirrors the RST weight scale in ContextAssembler(elaborates 1.5 最高…)"——对齐的是组装里那套 RST 权重，而非"因果最重要"。若某类查询就想让因果优先，应走**意图感知模式**传 `relationTypes` 覆盖。
4. **只影响"谁先占预算"，不影响"是否遍历"**：遍历哪些关系类型由 `selectNeighbors` 的 `relationTypes` 过滤决定；这张表只在拿到邻居后排序。

---

## 6. 输出完整性与顺序（满预算 20 条时）

满预算走 `resolveSegments`：

```java
segments = segmentMapper.selectWithMeta(expandedNodes.keySet(), snapshotIds);   // 查这 20 个 id
return segments.stream()
    .filter(seg -> expandedNodes.containsKey(seg.getId()))   // ← 恒真,空操作
    .map(...).toList();
```

- **正常路径（传了 snapshot）→ 完整包含 20 条，不多不少。** 因为这 20 个 id 来自 `selectNeighbors`，它已 JOIN 段落表并要求两端都在 scope 内，所以 `selectWithMeta` 必然全部命中；`LEFT JOIN` 不丢行；那个 `filter` 是空操作；id 是主键不会 >20。
- **可能 <20 的唯一现实情况**：悬空引用（关系边指向一个 `asset_raw_segments` 里不存在的 id），且只在**没传 snapshotIds** 时才可能发生 → 该条被 `selectWithMeta` 悄悄丢掉。
- ⚠️ **顺序会变**：`selectWithMeta` 的 SQL **没有 `ORDER BY`**，返回顺序是数据库顺序，**不再是 BFS 里按优先级排好的顺序**（内容都在，排序不保证）。

---

## 7. 几个易被问到的细节

- **有向边、双向遍历**：边有向，但 `selectNeighbors` 用 `UNION ALL` 把 source↔target 两个方向都查，遍历时当**无向图**走。
- **每层一次 SQL**：对整个 frontier 批量查邻居，depth=2 就 2 次查询，高效。
- **去重取最浅**：`visited` 保证每节点只收一次，记录**第一次（最浅）到达**的 depth 与关系。
- **快照隔离**：传 `snapshotIds` 时 JOIN 段落表，要求**边两端都在 scope 内**，不扩到范围外文档。

---

## 8. 下游怎么用（承接组装）

`ContextAssembler` 里，图扩展产物：
- 变成 `ContextItem`，结构角色 `role = "support"`；
- `depth` → `ContextRelation.distance`（0=直接关系，>0=扩展来的）；
- `relationType` → 喂给 **RST 关系类型 → 证据角色映射**，决定 support / context / contrast / background。

> **"图扩展输出 20" ≠ "最终 ContextPack 有 20 条扩展"**：组装还会按 `maxExpanded` / `maxItems` 再截断，并做"关系完整性过滤"（只留两端都在最终 items 里的关系）。所以这 20 条是**候选**，最终可能只剩一部分。

---

## 9. 局限 / 注意（讲课时点一下更专业）

1. **无质量剪枝**：优先级只管"关系类型好不好"，不管"内容和 query 像不像"，可能扩进关系对但内容不相关的段落。改进：加语义相似度阈值。
2. **预算按层贪心**：depth 优先于优先级，浅层低价值关系可能挤掉深层高价值关系。
3. **默认 maxDepth=2**：只扩两跳，是"上下文补全"而非"全图检索"，刻意保守。
4. **输出顺序不保证**：`selectWithMeta` 无 `ORDER BY`，优先级顺序在此丢失，下游需自行排序。

---

## 10. 一页速记

> **图扩展 = 从检索种子出发，在挖掘期建好的段落关系图上做带预算的 BFS，把前因后果/条件/对比等相邻段落补进上下文。**
>
> 三个记忆点：
> 1. **沿关系图 BFS**：默认 2 跳、双向、每层一次 SQL。
> 2. **双重预算控制**：总数 ≤ `min(maxResults, 20)`；关系优先级排序，语义关系优先于结构关系，可按意图定制顺序；**depth 第一、优先级第二**。
> 3. **输出**：满预算正常返回完整 20 条（顺序不保证），带 depth + relationType 语义标注，喂给证据角色分类；下游还会按 `maxExpanded`/`maxItems` 再砍。

---

## 附：关键文件

| 文件 | 职责 |
|------|------|
| `retrieval/GraphExpander.java` | BFS 遍历 + 预算 + 优先级 |
| `mapper/AssetRawSegmentRelationMapper.xml` | `selectNeighbors`（双向一跳邻居，UNION ALL） |
| `mapper/AssetRawSegmentMapper.xml` | `selectWithMeta`（扩展段落全文+元数据，无 ORDER BY） |
| `application/ContextAssembler.java` | 调用图扩展并组装进 ContextPack |
| `domain/AssemblyConfig.java` | `relationExpansion` / `maxRelationDepth`(2) / 13 种默认 relationTypes |
