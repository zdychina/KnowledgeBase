# Phase 1 Serving 侧改动记录

> 日期：2026-05-20
> 依据：`task/2026-05-19-mining-serving-evolution.md` 第三章 Phase 1
> 状态：已完成，编译通过

---

## 一、HyDE 查询变换

### 背景

原始查询与文档表述存在词汇差异，直接用原始查询的 embedding 做向量检索时召回率不稳定。
HyDE（Hypothetical Document Embeddings）通过先让 LLM 生成一段假设性文档段落，再对该段落做 embedding，将查询映射到更接近真实文档的语义空间。

### 改动文件

**`infrastructure/ServingTemplates.java`**

新增 `serving-hyde-expansion` 模板，随服务启动自动注册到 LLM Service：

```java
private static final Map<String, Object> HYDE_EXPANSION = Map.ofEntries(
    Map.entry("template_key", "serving-hyde-expansion"),
    Map.entry("purpose", "生成假设性文档段落，用于 HyDE 向量检索"),
    Map.entry("system_prompt", "你是一个技术文档生成助手。根据用户的查询，生成一段可能出现在相关技术手册中的回答段落..."),
    Map.entry("user_prompt_template", "查询：$query\n\n请生成一段假设性的技术文档回答："),
    ...
);
```

**`infrastructure/EmbeddingClient.java`**

新增 `embedHyDE(String query)` 方法：

```
query
  → llmClient.execute("hyde", "serving-hyde-expansion", {query})
  → 从 response.result.raw_output 提取假设文档文本
  → embed(hypotheticalDoc)   ← 成功时使用假设文档的 embedding
  → embed(query)             ← LLM 不可用或失败时回退
```

**`application/SearchService.java`**

step 5（embedding 生成）从：
```java
queryEmbedding = embeddingClient.embed(request.query());
```
改为：
```java
queryEmbedding = embeddingClient.embedHyDE(request.query());
```

### 行为说明

- LLM Service 不可用时，`embedHyDE` 自动回退到 `embed(query)`，行为与之前完全一致
- HyDE 仅影响向量检索（`dense_vector` 路由），FTS 和实体检索不受影响
- 假设文档不需要准确，只需在语义空间接近真实文档即可

---

## 二、Graph Traversal Budget（关系优先级排序）

### 背景

原有 BFS 处理邻居节点时无优先级，所有关系类型平等竞争 `maxResults` 配额。当配额耗尽时，高价值的实体关系可能被低价值的结构关系（same_parent_section）挤占，导致扩展噪声大。

### 改动文件

**`retrieval/GraphExpander.java`**

新增关系优先级常量：

```java
private static final Map<String, Integer> RELATION_PRIORITY = Map.of(
    "entity_relation",      0,   // 最高优先
    "section_header_of",    1,
    "same_section",         2,
    "same_parent_section",  3    // 最低优先
    // 其他类型默认 4
);
```

BFS 每层邻居列表排序后再逐个填入配额：

```java
List<NeighborRow> sortedNeighbors = neighbors.stream()
    .sorted(Comparator.comparingInt(r ->
        RELATION_PRIORITY.getOrDefault(r.getRelationType(), 4)))
    .toList();
```

### 行为说明

- `maxResults`（来自 `AssemblyConfig.maxExpanded`，默认 10）仍是总节点上限，不变
- 配额充足时，排序无实质影响；配额紧张时，高优先级关系优先被纳入，低优先级被截断
- 当前 Mining 尚无 `entity_relation` 类型关系，该优先级为 Phase 2 Schema-First 实体关系提取就绪后生效

---

## 三、检索结果去重

### 背景

同一原始段落（`source_segment_id`）可能对应多个检索单元（不同 `unit_type`），经三路检索后在候选列表中重复出现，占用 `maxItems` 配额中的多个位置，降低结果多样性。

### 改动文件

**`rerank/RerankPipeline.java`**

在级联重排完成后、阈值过滤和截断之前，新增两个后处理步骤：

**步骤 1：Segment 级去重**（`deduplicateBySegment`）

```
按 metadata["source_segment_id"] 分组
  → 同一 segment 的多个候选只保留 score 最高的
  → 无 source_segment_id 的候选不参与去重（保留全部）
  → 按 score 降序重排
```

**步骤 2：低价值类型降权**（`downweightLowValueTypes`）

```
unit_type ∈ {heading, toc, link}  →  score × 0.5
  → 降权后重排
  → 降至 0.01 以下的候选在后续阈值过滤步骤中被移除
```

**完整后处理顺序（修改后）：**

```
级联重排结果
  → ① deduplicateBySegment     （同 segment 去重）
  → ② downweightLowValueTypes  （低价值类型降权）
  → ③ annotateRerankScores     （写入 scoreChain.rerankScore）
  → ④ 阈值过滤（score >= 0.01）
  → ⑤ 截断到 maxItems
```

### 行为说明

- 去重后候选总数可能减少，但每个位置代表不同的原始段落，多样性更好
- heading/TOC/link 降权为软过滤：score 够高时仍保留，只是排名靠后
- `source_segment_id` 由各 Retriever 在 `metadata` 中写入（FTS/Entity/Dense 三路均已支持）

---

## 四、验收检查点

| 检查项 | 验证方法 |
|--------|---------|
| HyDE 生效 | 开启 debug=true，trace 中 embedding 阶段应出现 `HyDE expansion succeeded` 日志 |
| HyDE 回退 | 断开 LLM Service，embedding 仍应正常完成（回退到直接 embed） |
| 关系优先级 | 单测 GraphExpander，同 depth 邻居中 entity_relation 应先于 same_parent_section |
| Segment 去重 | 构造同 source_segment_id 的两个候选，重排后只剩一个 |
| 低价值降权 | 构造 unit_type=heading 的候选，重排后 score 减半 |
| 编译 | `mvn compile` 无错误 ✓（已验证） |
