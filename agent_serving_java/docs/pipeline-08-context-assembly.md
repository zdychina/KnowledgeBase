# Pipeline Stage 08: 上下文组装 (Context Assembly)

## 概述

本阶段将重排后的检索候选转换为最终返回给用户的 `ContextPack`。核心流水线：

**seed 构建 → 源文档下钻 → 图扩展 → 关系获取 → 源引用 → 问题检测 → 证据分类 → 截断 → 打包**

## 流程图

```
ContextAssembler.assemble(query, understanding, scope, candidates, routePlan)
  │
  ├─ 1. 构建 seed items（从 RetrievalCandidate → ContextItem）
  │
  ├─ 2. 源文档下钻
  │   ├─ 从 candidate.metadata 提取 segment IDs
  │   │   ├─ 优先级1: source_segment_id
  │   │   ├─ 优先级2: source_refs_json → raw_segment_ids
  │   │   └─ 优先级3: target_ref_json
  │   └─ 查询 AssetRawSegment → buildSourceItems
  │
  ├─ 3. 图扩展（可选，relationExpansion=true 时）
  │   ├─ GraphExpander.expand(seedIds, maxDepth, relationTypes, maxResults, snapshotIds)
  │   │   └─ BFS 逐层遍历关系图
  │   ├─ 构建 expansion 关系
  │   └─ 扩展项 role = "support"
  │
  ├─ 4. 直接关系获取
  │   └─ repo.getRelationsForSegments(segmentIds, relationTypes, snapshotIds)
  │
  ├─ 5. 关系去重
  │   └─ 按 id 去重
  │
  ├─ 6. 文档源引用
  │   ├─ 提取 document IDs
  │   └─ repo.getDocumentSources(documentIds, snapshotIds)
  │
  ├─ 7. 问题检测
  │   ├─ 无结果 → "no_result"
  │   └─ 所有分数 < 0.1 → "low_confidence"
  │
  ├─ 8. 证据角色分类
  │   └─ EvidenceRoleClassifier.classify(seedItems, understanding)
  │       ├─ score ≥ 0.7 + seed → "direct_answer"
  │       ├─ score ≥ 0.4 + seed → "support"
  │       ├─ score < 0.4 + seed → "background"
  │       └─ contrast 关系 → "contrast"
  │
  ├─ 9. 截断
  │   └─ maxItems + maxExpanded（默认 10 + 10 = 20）
  │
  ├─ 10. 关系过滤
  │   └─ 只保留两端都在最终 items 中的关系
  │
  └─ 11. 打包 ContextPack
      ├─ ContextQuery（查询元信息）
      ├─ items（seed + source + expanded）
      ├─ relations
      ├─ sources（文档引用）
      ├─ evidence_groups（按 snapshot 分组）
      ├─ issues（问题列表）
      └─ suggestions（建议列表）
```

## 输入

| 输入 | 类型 | 来源 | 说明 |
|------|------|------|------|
| `query` | String | 原始请求 | 用户查询文本 |
| `understanding` | QueryUnderstanding | Stage 02 | 意图、实体、关键词 |
| `scope` | ActiveScope | Stage 04 | snapshot IDs |
| `candidates` | List\<RetrievalCandidate\> | Stage 07 重排结果 | 已排序候选 |
| `routePlan` | RetrievalRoutePlan | Stage 03 | assembly 配置 |

## 输出

### ContextPack（record）

| 字段 | 类型 | 说明 |
|------|------|------|
| `query` | ContextQuery | 查询元信息 |
| `items` | List\<ContextItem\> | 所有上下文条目（seed + source + expanded） |
| `relations` | List\<ContextRelation\> | 关系边 |
| `sources` | List\<SourceRef\> | 文档源引用 |
| `evidenceGroups` | List\<EvidenceGroup\> | 按 snapshot 分组的证据集合 |
| `issues` | List\<Issue\> | 检测到的问题 |
| `suggestions` | List\<String\> | 改进建议 |
| `debug` | Map\<String, Object\> | 调试信息 |

### ContextItem（record）

| 字段 | 类型 | 说明 |
|------|------|------|
| `id` | String | 条目 ID |
| `kind` | String | `retrieval_unit` 或 `raw_segment` |
| `role` | String | `seed` / `context` / `support` |
| `text` | String | 文本内容 |
| `score` | double | 分数 |
| `title` | String | 标题 |
| `blockType` | String | 块类型 |
| `semanticRole` | String | 语义角色 |
| `sourceId` | String | 文档 ID |
| `relationToSeed` | String | 与 seed 的关系类型 |
| `sourceRefs` | Map | 源引用 |
| `metadata` | Map | 附加元数据 |
| `routeSources` | List\<String\> | 贡献路由 |
| `scoreChain` | ScoreChain | 分数链 |
| `evidenceRole` | String | 证据角色 |
| `citation` | Map | 引用信息 |

### ContextRelation（record）

| 字段 | 类型 | 说明 |
|------|------|------|
| `id` | String | 关系 ID |
| `fromId` | String | 起始节点 ID |
| `toId` | String | 目标节点 ID |
| `relationType` | String | 关系类型 |
| `distance` | int | 扩展距离（0 = 直接关系） |

### ContextQuery（record）

| 字段 | 类型 | 说明 |
|------|------|------|
| `originalQuery` | String | 用户原始查询 |
| `understanding` | String | 格式化的理解摘要 |
| `intent` | String | 意图 |
| `entities` | List\<EntityRef\> | 实体列表 |
| `scope` | Map | 作用域 |
| `keywords` | List\<String\> | 关键词 |
| `source` | String | 理解来源（llm/rule） |
| `releaseId` | String | release ID |
| `buildId` | String | build ID |
| `snapshotCount` | int | snapshot 数量 |

### EvidenceGroup（record）

| 字段 | 类型 | 说明 |
|------|------|------|
| `snapshotId` | String | snapshot ID |
| `itemIds` | List\<String\> | 该 snapshot 下的条目 ID |
| `relationIds` | List\<String\> | 相关关系 ID |

### Issue（record）

| 字段 | 类型 | 说明 |
|------|------|------|
| `type` | String | 问题类型（`no_result` / `low_confidence`） |
| `message` | String | 问题描述 |
| `details` | Map | 附加信息 |

### SourceRef（record）

| 字段 | 类型 | 说明 |
|------|------|------|
| `documentId` | String | 文档 ID |
| `documentKey` | String | 文档键 |
| `title` | String | 文档标题 |
| `relativePath` | String | 相对路径 |
| `scope` | Map | 文档 scope |
| `metadata` | Map | 附加元数据 |

## 涉及的关键文件

| 文件 | 职责 |
|------|------|
| `application/ContextAssembler.java` | **核心**，10 步组装流水线 |
| `retrieval/GraphExpander.java` | BFS 图扩展 |
| `evidence/EvidenceRoleClassifier.java` | 证据角色分类 |
| `domain/ContextPack.java` | 输出 record |
| `domain/ContextItem.java` | 条目 record |
| `domain/ContextRelation.java` | 关系 record |
| `domain/ContextQuery.java` | 查询 record |
| `domain/EvidenceGroup.java` | 证据分组 record |
| `domain/Issue.java` | 问题 record |
| `domain/SourceRef.java` | 源引用 record |
| `domain/AssemblyConfig.java` | 组装配置 |
| `repository/AssetRepository.java` | 段/关系/文档查询 |
| `mapper/AssetRawSegmentMapper.xml` | 段查询 SQL |
| `mapper/AssetRawSegmentRelationMapper.xml` | 关系查询 SQL |
| `mapper/AssetDocumentMapper.xml` | 文档查询 SQL |

---

## 实现细节

### 1. Seed Item 构建

```java
// 每个 RetrievalCandidate 转为 ContextItem
new ContextItem(
    c.retrievalUnitId(),     // id
    "retrieval_unit",         // kind
    "seed",                   // role
    metadata.text,            // text
    c.score(),                // score
    metadata.title,           // title
    metadata.block_type,      // blockType
    metadata.semantic_role,   // semanticRole
    null,                     // sourceId
    null,                     // relationToSeed
    sourceRefs,               // sourceRefs
    c.metadata(),             // metadata
    routeSources,             // routeSources
    c.scoreChain(),           // scoreChain
    "",                       // evidenceRole（后续由 classifier 填充）
    citation                  // citation
);
```

Citation 构建：从 metadata 中提取 `raw_segment_ids`、`section`(title)、`document_snapshot_id`。

### 2. 源文档下钻

三级优先级提取 segment IDs：

```java
// Priority 1: source_segment_id（直接指定）
String segId = metadata.get("source_segment_id");
if (segId != null && !segId.isBlank()) return List.of(segId);

// Priority 2: source_refs_json → raw_segment_ids
Map parsed = JSON.parse(metadata.get("source_refs_json"));
List<String> segIds = parsed.get("raw_segment_ids");

// Priority 3: target_ref_json（命令/实体类型的 target 引用）
segIds = JSON.parse(metadata.get("target_ref_json")).get("raw_segment_ids");
```

### 3. GraphExpander BFS

```java
public List<ExpandedSegmentRow> expand(seedIds, maxDepth, relationTypes, maxResults, snapshotIds) {
    Set<String> visited = new LinkedHashSet<>(seedIds);  // 已访问
    Set<String> frontier = new LinkedHashSet<>(seedIds);  // 当前层

    for (depth = 1; depth <= maxDepth; depth++) {
        // 查询 frontier 的邻居
        List<NeighborRow> neighbors = relationMapper.selectNeighbors(frontier, relationTypes, snapshotIds);

        Set<String> nextFrontier;
        for (neighbor : neighbors) {
            if (!visited.contains(neighbor)) {
                visited.add(neighbor);
                nextFrontier.add(neighbor);
                expandedIds.put(neighbor, depth);

                // 提前终止
                if (expandedIds.size() >= maxResults) return resolveSegments(...);
            }
        }
        frontier = nextFrontier;
    }

    return resolveSegments(expandedIds, rootSeed, snapshotIds);
}
```

每层 BFS 触发一次 SQL 查询，`maxDepth` 限制层数，`maxResults` 限制总数。

### 4. 证据角色分类

```java
// 基于分数和关系的简单分类
determineRole(item, understanding):
    if seed:
        score >= 0.7 → "direct_answer"
        score >= 0.4 → "support"
        else         → "background"
    if has relationType:
        "contrasts_with" → "contrast"
        "elaborates/conditions/causes/results_in" → "support"
        else → "background"
    else:
        score >= 0.4 → "support"
        else → "background"
```

### 5. RST 关系类型 → 证据角色映射

```java
Map<String, String> RST_ROLE_MAP = Map.of(
    "elaborates", "support",
    "conditions", "support",
    "causes", "support",
    "results_in", "support",
    "backgrounds", "background",
    "enables", "support",
    "parallels", "context",
    "contrasts_with", "contrast",
    "previous", "context",
    "next", "context",
    "same_section", "context",
    "same_parent_section", "context",
    "section_header_of", "context"
);
```

### 6. Evidence Groups

按 `document_snapshot_id` 分组，每组包含该 snapshot 下的所有 item IDs 和相关 relation IDs。

### 7. 问题检测和建议

```java
// 无结果
if (seedItems.isEmpty()) {
    issues.add(new Issue("no_result", "未找到相关内容", {query}));
    suggestions.add("尝试使用更通用的关键词");
}

// 低置信度
if (items.stream().allMatch(item -> item.score() < 0.1)) {
    issues.add(new Issue("low_confidence", "检索结果置信度较低", {top_score}));
    suggestions.add("尝试更精确的描述或添加产品/版本约束");
}
```

### 8. 关系完整性过滤

```java
// 只保留两端都在最终 items 中的关系
Set<String> itemIds = allItems.stream().map(ContextItem::id).collect(toSet());
filteredRelations = uniqueRelations.stream()
    .filter(r -> itemIds.contains(r.fromId()) && itemIds.contains(r.toId()))
    .toList();
```

## 配置参数

### AssemblyConfig（record）

| 字段 | 默认值 | 说明 |
|------|--------|------|
| `sourceDrilldown` | true | 是否下钻源文档 |
| `relationExpansion` | true | 是否图扩展 |
| `maxItems` | 10 | seed + source 最大条数 |
| `maxExpanded` | 10 | 扩展最大条数 |
| `maxRelationDepth` | 2 | BFS 最大深度 |
| `relationTypes` | 13 种 | 遍历的关系类型列表 |

### EvidenceRoleClassifier 阈值

| 参数 | 值 | 说明 |
|------|-----|------|
| HIGH_SCORE_THRESHOLD | 0.7 | direct_answer 最低分 |
| MEDIUM_SCORE_THRESHOLD | 0.4 | support 最低分 |

## 工业化参考

| 参考实践 | 说明 |
|----------|------|
| **Source Drilldown** | 检索系统的标准两阶段模式：先检索精炼表示，再获取完整原文 |
| **Graph Expansion** | 知识图谱增强检索（KGR），通过关系扩展补充上下文 |
| **BFS with Depth Limit** | 经典的有限深度图遍历，控制扩展范围 |
| **Evidence Role Classification** | 类似 Google 的 passage-level relevance 分级 |
| **Issue Detection** | 类似搜索引擎的 zero-results 和 low-quality 检测 |
| **Evidence Groups** | 按文档分组展示，类似搜索结果的 site clustering |

## 当前实现的不足

### 1. 证据角色分类过于简单

仅基于分数阈值和固定映射，不考虑查询意图。如 troubleshooting 查询应该偏好 procedure_step 角色。

**改进方向**：结合 `EvidenceNeed.preferredRoles` 和 intent 调整分类逻辑。

### 2. GraphExpander 无剪枝

BFS 扩展时没有质量过滤，可能引入不相关内容。

**改进方向**：添加分数或语义相似度阈值过滤扩展节点。

### 3. 截断策略粗糙

直接按顺序截断（seed → source → expanded），不考虑质量排序。

**改进方向**：按分数降序截断，保证最高质量的项不被丢弃。

### 4. 无上下文长度控制

没有控制总文本长度，可能超出 LLM 上下文窗口。

**改进方向**：添加 token 计数，按 token budget 截断。

### 5. Evidence Groups 不包含质量信息

分组只有 item IDs 和 relation IDs，不包含每组的平均分数或角色分布。

**改进方向**：在 EvidenceGroup 中添加 `avgScore` 和 `roleDistribution`。

### 6. 图扩展的关系类型固定

13 种关系类型硬编码在 AssemblyConfig 默认值中。

**改进方向**：根据 intent 动态选择关系类型（如 troubleshooting 偏好 causes/results_in）。

### 7. Suggestion 过于泛化

只有两条固定建议，不针对具体问题。

**改进方向**：基于 intent 和 detected issues 生成个性化建议（如"尝试使用命令格式 ADD UPF"）。
