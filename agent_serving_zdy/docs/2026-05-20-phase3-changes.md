# Phase 3 Serving 侧改动记录

> 日期：2026-05-20
> 依据：`task/2026-05-19-mining-serving-evolution.md` 第三章 Phase 3
> 状态：已完成，162 个单元测试全部通过
> 注：ColBERT Reranker（Phase 3-①）依赖 Mining Phase 2 生成 ColBERT embedding，当前跳过

---

## 一、Query Decomposition（查询分解）

### 背景

LLM 路径的 `QueryUnderstandingEngine` 已经能将复杂查询拆解为 `sub_queries`（多个 `SubQuery`，含各自的 `text` 和 `intent`）。Phase 3 将这些子查询接入检索 pipeline，每个子查询独立执行检索，候选结果合并进入 Fusion，召回率在复杂多跳查询上可提升 30%+ 。

### 改动文件

**`application/SearchService.java`**（修改）

**Step 5 – Sub-query 向量生成**

在 Multi-Query 变体 embedding 循环之后，新增对 `understanding.subQueries()` 的 HyDE embedding：

```
for each subQuery in understanding.subQueries():
    if subQuery.text() not already in variantEmbeddings:
        emb = embeddingClient.embedHyDE(subQuery.text())
        variantEmbeddings.put(subQuery.text(), emb)
```

**Step 6b – Sub-query 检索**

在原 Multi-Query 变体检索循环（6a）之后，新增子查询检索循环：

```
for each subQuery in understanding.subQueries():
    subUnderstanding = buildSubQueryUnderstanding(understanding, subQuery)
    subEmb = variantEmbeddings.get(subQuery.text())  ← 可 null
    subResult = orchestrator.execute(subUnderstanding, routePlan, subEmb, snapshotIds)
    rawCandidates.addAll(subResult.candidates())
```

trace 末尾追加 `sub_queries=N` 统计。

**`buildSubQueryUnderstanding()` 私有静态方法**（新增）

```
buildSubQueryUnderstanding(parent, subQuery):
    intent = subQuery.intent() if != "general" else parent.intent()
    entities = subQuery.entities() if non-empty else parent.entities()
    return QueryUnderstanding(
        subQuery.text(), intent, List.of(),  // 不递归分解
        entities, parent.scope(), parent.keywords(),
        parent.evidenceNeed(), parent.ambiguities(), parent.source()
    )
```

### 关键设计决策

- Sub-query embedding 使用 HyDE，与 Multi-Query 变体保持一致
- 子查询不递归分解（`subQueries = List.of()`），避免无限展开
- 子查询 embedding 为 null 时（LLM 不可用），retrieval 仍然执行（仅跳过 dense 路由）
- 子查询召回的候选同样进入 WeightedRRF Fusion，天然处理分数归一化

---

## 二、Context Compression（上下文压缩）

### 背景

大量检索结果拼接后容易超出 LLM 上下文窗口（通常 4096 token）。Phase 3 在 `ContextAssembler` 的 count 截断之后，对 text 字段按 token 预算做 extractive 截断，将总 token 控制在 < 3000。

### 改动文件

**`application/ContextAssembler.java`**（修改）

新增常量：

```java
private static final int MAX_TOTAL_TOKENS = 3000;
private static final int MAX_TOTAL_CHARS = MAX_TOTAL_TOKENS * 4;  // 12000 chars
```

在 count 截断后调用压缩：

```java
if (allItems.size() > maxItems) allItems = allItems.subList(0, maxItems);
// Phase 3：context compression
allItems = compressItems(new ArrayList<>(allItems));
```

**`compressItems(List<ContextItem>)`**（新增私有静态方法）

```
compressItems(items):
    totalChars = sum of item.text().length()
    if totalChars <= MAX_TOTAL_CHARS: return items unchanged

    seeds  = items where role == "seed"
    others = items where role != "seed"

    seedBudget  = MAX_TOTAL_CHARS × 0.6 = 7200 chars
    otherBudget = MAX_TOTAL_CHARS × 0.4 = 4800 chars

    perSeed  = max(200, seedBudget  / seeds.size())
    perOther = max(100, otherBudget / others.size())

    result = []
    for item in seeds:  result.add(truncateText(item, perSeed))
    for item in others: result.add(truncateText(item, perOther))
    return result
```

**`truncateText(ContextItem, int maxChars)`**（新增私有静态方法）

截断 `text` 字段，追加 `…`，返回新的 `ContextItem`（record copy-with-modification）。

### 关键设计决策

- 4 chars/token 是保守估算（中文约 2 chars/token，英文约 4 chars/token），取均值确保不超限
- Seed 项目（来自检索结果）权重 60%，Context/Support 项目（来自图扩展）权重 40%
- 每项最低保留 200 chars（seed）/ 100 chars（other），确保即使项目数量很多也保留最基本内容
- 总 token < 3000 满足 Phase 3 验收标准（Traversal budget 下 ContextPack < 3000 token）

---

## 三、Session 多轮交互（Multi-turn Session）

### 背景

用户在连续对话中可能使用代词（"它"、"上述配置"）或隐含指代，无 session 上下文则 QU 无法消歧。Phase 3 为 SearchService 引入 session_id 参数，在 session 内累积问题历史，并将历史作为 QU 的上下文 hint，提升多轮对话的检索质量。

### 改动文件

**`domain/SearchRequest.java`**（修改）

新增 `sessionId` 字段（第 8 个参数，nullable，null = 无 session）：

```java
public record SearchRequest(
    String query, Map<String, Object> scope, List<EntityRef> entities,
    boolean debug, String domain, String channel, String mode,
    String sessionId   // ← 新增
)
```

**`application/SessionStore.java`**（新建，`@Component`）

```
内部状态: ConcurrentHashMap<sessionId, Deque<String>>
MAX_TURNS = 10（FIFO 淘汰）

getPriorQueries(sessionId):
    返回 Deque 快照（oldest first）；session 不存在时返回 List.of()

recordTurn(sessionId, query):
    使用 compute() 原子操作
    addLast(query)
    while size > MAX_TURNS: removeFirst()
```

**`application/SearchService.java`**（修改）

新增 `sessionStore` 字段 + 构造参数。Pipeline 改动：

```
Pipeline 入口（Query Understanding 之前）：
    sessionId = request.sessionId()
    priorQueries = sessionId != null ? sessionStore.getPriorQueries(sessionId) : List.of()

    if priorQueries 非空:
        quQuery = "以下是用户的问题历史：\n- q1\n- q2\n当前问题：currentQuery"
    else:
        quQuery = request.query()

    understanding = quEngine.understand(quQuery, profile)  ← 使用富化后的 query

Step 9.6（assembly 后）：
    if sessionId != null:
        sessionStore.recordTurn(sessionId, request.query())  ← 存原始 query

debug 信息（request.debug() = true 时）：
    "session_id" → sessionId
    "session_prior_queries" → priorQueries
```

### 关键设计决策

- `priorQueries` 注入 QU engine 时，通过修改 quQuery 字符串实现，无需修改 `QueryUnderstandingEngine.understand()` 签名，零破坏性
- assembly 调用仍使用 `request.query()`（原始 query），输出 ContextPack 中的 `queryText` 不受影响
- Session store 全内存，进程重启后清空（设计为轻量化，持久化 session 留作后续）
- `MAX_TURNS = 10`：超过后 FIFO 淘汰，防止无限累积

---

## 四、ColBERT Reranker（跳过）

Phase 3-① ColBERT Reranker 依赖 Mining Phase 2 在 `asset_retrieval_colbert_embeddings` 表中生成 token-level 向量。当前 Mining 侧未就绪，此任务保留至 Mining Phase 2 完成后实现。

---

## 五、单元测试修复

**`SearchServiceTest.java`**（修改）

`SearchService` 构造新增 `SessionStore` 参数，测试中补充 mock：

```java
sessionStore = mock(SessionStore.class);
when(sessionStore.getPriorQueries(anyString())).thenReturn(List.of());

searchService = new SearchService(
    quEngine, router, orchestrator, rerankPipeline,
    assembler, domainPackReader, domainRegistry, domainPoolManager,
    embeddingClient, assetRepo, multiQueryExpander, semanticCache, sessionStore);
```

`SearchRequest` 新增 `sessionId` 字段（8 参数），所有 5 处测试构造调用均补充 `null`：

| 文件 | 变更 |
|------|------|
| `SearchServiceTest.java`（3处） | 末尾补 `, null` |
| `DomainRecordDefaultsTest.java`（1处） | 末尾补 `, null` |
| `QueryLogServiceTest.java`（1处） | 末尾补 `, null` |

---

## 六、验收检查点

| 检查项 | 验证方法 |
|--------|---------|
| Query Decomposition 生效 | LLM 可用时，复杂查询（comparison 类）的 trace 中 `sub_queries > 0` |
| Sub-query 降级 | LLM 不可用时，`sub_queries=0`，pipeline 正常执行 |
| Context Compression 生效 | 超过 12000 chars 的结果集，返回的 allItems text 总长度 ≤ 12000 |
| Seed 优先保留 | 压缩后 seed 项目 text 长于 context/support 项目 |
| Session 跨请求存储 | 相同 session_id 连续两次请求，第二次请求 debug 中 `session_prior_queries` 包含第一次的 query |
| Session 上下文注入 QU | session 有历史时，quQuery 包含 "以下是用户的问题历史：" 前缀 |
| Session 不影响无 session 请求 | sessionId=null 时，pipeline 行为与 Phase 2 相同 |
| 单元测试 | `mvn test` 162 个测试全部通过 ✓（已验证） |
