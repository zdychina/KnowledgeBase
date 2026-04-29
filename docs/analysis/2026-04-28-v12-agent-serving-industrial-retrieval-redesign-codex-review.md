# v1.2 Agent Serving 工业级检索重构方案审查

- Task: `TASK-20260421-v11-agent-serving`
- Date: 2026-04-28
- From: Codex
- To: Claude Serving
- 类型: architecture-review / redesign-request

## 审查背景

管理员明确指出：当前 Serving 不是工业级智能检索系统，更像“query 分词后查 FTS5，再拼 ContextPack”。本轮审查不再围绕现有 `QueryPlan` 和 `/search` 局部修补，而是要求 Claude Serving 重新按工业级 RAG / enterprise search / hybrid retrieval 的参考系设计。

同时，Mining 已开始转向 Domain Pack 驱动的半 GraphRAG 知识资产编译器。Serving 必须同步升级为“智能检索编排器”，能够消费 Mining 生产的多类资产，而不是只把 `asset_retrieval_units_fts` 当唯一入口。

## 当前结论

当前 Serving 不合格，不是因为少几个 if 或测试，而是核心范式不对：

```text
query -> rule normalize -> BM25/FTS5 -> rule rerank -> source drilldown -> ContextPack
```

这只能算基础检索 API，不能算工业级智能检索。工业级 Serving 应该是：

```text
query
  -> query understanding / decomposition / ambiguity detection
  -> retrieval router
  -> multi-path candidate generation
  -> fusion
  -> neural rerank
  -> evidence assembly / compression / citation / conflict handling
  -> evaluation / tracing / feedback
```

下一轮目标不是“修一下现有 QueryPlan”，而是把 Serving 从 DB 查询 API 重构为 **Retrieval Orchestrator**。

## 工业级参考

### Azure AI Search Hybrid Search

来源：https://learn.microsoft.com/en-us/azure/search/hybrid-search-overview

Azure AI Search 的 hybrid search 在同一个请求中并行执行 full-text queries 和 vector queries，并用 Reciprocal Rank Fusion 合并结果。官方文档明确把 BM25/文本检索、向量检索、RRF 融合作为混合检索基础能力。

对本项目的启发：

- 单路 FTS5 不能作为工业级 Serving 主链。
- `RetrieverManager` 不应只是抽象壳，至少要有 lexical + vector + entity/metadata 三路。
- Fusion 不应只是默认 identity，RRF 应作为多路召回的起步融合策略。

### Azure Semantic Ranker

来源：https://learn.microsoft.com/en-us/azure/search/semantic-search-overview

Azure semantic ranker 是 query-dependent reranker，对 BM25 或 RRF 排好序的初始结果进行语义重排，并可生成 captions / answers。它要求输入先经过 L1 召回，再对 top candidates 做 L2 rerank。

对本项目的启发：

- Serving 需要两阶段或三阶段检索：retrieve-many -> fusion -> rerank。
- 规则加分只能作为 fallback，不能作为主要相关性判断。
- Reranker 应能消费 query 与候选文本，输出相关性分数和解释。

### Microsoft GraphRAG / DRIFT Search

来源：

- https://microsoft.github.io/graphrag/index/overview/
- https://www.microsoft.com/en-us/research/blog/introducing-drift-search-combining-global-and-local-search-methods-to-improve-quality-and-efficiency/

GraphRAG 的 indexing 会生成 entities、relationships、claims、community reports 和 embeddings。DRIFT Search 强调结合 local search 和 global search，提高问题回答质量和效率。

对本项目的启发：

- Serving 要区分 local evidence retrieval 和 global/summary retrieval。
- 对局部事实问题，优先 raw segment / retrieval unit / entity exact / relation neighborhood。
- 对全局总结、跨章节归纳、比较类问题，后续应使用 document/section summary、community report 或 domain graph signal。
- 当前阶段我们不做完整本体层，但 Serving 必须先能消费半 GraphRAG 资产：`entity_refs_json`、`raw_segment_relations`、`generated_question`、`summary/table_row/raw_text`。

### Qdrant Hybrid Search + Reranking

来源：https://qdrant.tech/documentation/advanced-tutorials/reranking-hybrid-search/

Qdrant 的 hybrid search 示例展示了 dense + sparse retrieval，再通过 late interaction / ColBERT 等方式重排。这体现了工业检索中“召回和精排分离”的原则。

对本项目的启发：

- Dense vector 解决语义相似，sparse/BM25 解决精确词和术语。
- 对云核心网这类技术知识，命令、参数、版本、错误码、接口名必须走精确或 sparse 路径，不能只依赖 dense。
- Rerank 必须是正式阶段，而不是简单 heuristic boost。

### Pinecone Hybrid Search / Rerank

来源：

- https://docs.pinecone.io/guides/search/hybrid-search
- https://docs.pinecone.io/guides/search/rerank-results

Pinecone 文档将 dense/sparse hybrid search 与 rerank 作为常见 RAG 检索模式，并强调 initial retrieval 后使用 rerank 改善相关性。

对本项目的启发：

- Serving 的 retrieval routes 应支持 dense / sparse / lexical / metadata 分离。
- Candidate 应携带 route 来源、原始分数、融合分数、rerank 分数，便于 debug 和评测。

### Weaviate Hybrid Search

来源：https://docs.weaviate.io/weaviate/concepts/search/hybrid-search

Weaviate hybrid search 将 vector search 和 keyword search 结合，并支持 alpha 权重调节。

对本项目的启发：

- 不同查询类型需要不同 route weight。
- 命令/参数类问题偏 lexical/entity/table；概念类问题偏 dense/contextual；排障类问题偏 graph/role/filter。
- Retrieval router 应根据 query understanding 动态选择权重，而不是固定一种 plan。

### Elastic Hybrid Search / Semantic Reranking

来源：

- https://www.elastic.co/search-labs/blog/hybrid-search-elasticsearch
- https://www.elastic.co/search-labs/blog/semantic-reranking-with-retrievers

Elastic 的企业搜索路线同样强调 lexical + vector + rerank，并把 reranking 放在 retriever pipeline 中作为正式能力。

对本项目的启发：

- 企业知识库不是“向量化后一把梭”。
- 对技术文档，BM25 / sparse / exact filters 是不可替代的。
- Serving 必须变成可组合 retriever pipeline，而不是一个 SQL 查询函数。

### Haystack Pipeline / Rankers

来源：

- https://docs.haystack.deepset.ai/docs/pipelines
- https://docs.haystack.deepset.ai/docs/rankers

Haystack 通过 components 组装 pipeline，并提供 retrievers、rankers、joiners、routers 等模块。

对本项目的启发：

- Serving 应该有可配置 pipeline profile。
- Retriever、Router、Joiner/Fusion、Ranker、Assembler 都应是独立组件。
- Domain Pack 不只影响 Mining，也应影响 Serving 的 query understanding、route selection、entity matching、eval questions。

### OpenAI Evaluation Best Practices / Azure RAG Evaluators

来源：

- https://platform.openai.com/docs/guides/evaluation-best-practices
- https://learn.microsoft.com/en-us/azure/ai-foundry/concepts/evaluation-evaluators/rag-evaluators

工业级系统必须有评测闭环。Azure RAG evaluators 将 retrieval 作为独立评估对象，包括 document retrieval、groundedness、relevance 等。

对本项目的启发：

- Serving 改检索策略必须跑 eval，不允许只靠人工体感。
- Domain Pack 必须提供 eval questions、期望 evidence、must-hit/must-not-hit 规则。
- Serving 输出要带 trace，才能解释为什么召回、融合、重排、扩展。

## 目标架构

### 新 Serving 定位

Serving 不是“读取 active release 的 API”，而是：

> 面向 Agent / Skill 的智能检索编排器，负责根据问题动态选择检索路径，融合多源候选，重排证据，组装可引用、可压缩、可评测的 Evidence Context。

### 目标主链

```text
SearchRequest
  -> QueryUnderstanding
      - intent
      - sub_queries
      - entities
      - scope
      - evidence_need
      - ambiguity / missing_scope
  -> RetrievalRouter
      - route selection
      - route weights
      - filters
      - budgets
  -> CandidateGeneration
      - lexical_bm25
      - dense_vector
      - sparse_vector / keyword
      - entity_exact / alias
      - structure_table
      - graph_neighbor
      - generated_question
      - summary/global
  -> CandidateFusion
      - RRF / weighted RRF
      - route-aware dedup
  -> Rerank
      - cross-encoder or LLM reranker
      - rule fallback
  -> EvidenceAssembly
      - source segment drilldown
      - parent/child context
      - relation expansion
      - context compression
      - citation and provenance
      - conflict / missing evidence
  -> ContextPack / EvidencePack
  -> Trace + Eval Metrics
```

## 输入输出合同建议

### SearchRequest

保留当前 `query/scope/entities/debug`，但新增可选控制字段：

```json
{
  "query": "registerIPv4 和 bindingIPv4 有什么区别？",
  "domain": "cloud_core_network",
  "scope": {"products": ["UPF"]},
  "entities": [],
  "mode": "evidence",
  "debug": true,
  "budget": {
    "max_seed": 20,
    "max_context": 40,
    "max_tokens": 6000
  }
}
```

字段说明：

- `domain`: 指向 Domain Pack，默认由 active release metadata 或服务配置决定。
- `mode`: `evidence / answer_ready / diagnostic / eval`。
- `budget`: 调用方可约束输出大小。

### QueryUnderstanding

替代当前贫弱的 `NormalizedQuery`：

```json
{
  "intent": "comparison",
  "sub_queries": [
    "registerIPv4 的含义",
    "bindingIPv4 的含义",
    "二者区别"
  ],
  "entities": [
    {"type": "parameter", "name": "registerIPv4"},
    {"type": "parameter", "name": "bindingIPv4"}
  ],
  "scope": {"network_elements": ["UPF"]},
  "evidence_need": {
    "preferred_roles": ["parameter", "concept", "constraint"],
    "preferred_blocks": ["table", "paragraph"],
    "needs_comparison": true,
    "needs_citation": true
  },
  "ambiguities": []
}
```

### RetrievalRoutePlan

替代当前静态 `QueryPlan`：

```json
{
  "routes": [
    {"name": "entity_exact", "enabled": true, "weight": 1.4, "top_k": 20},
    {"name": "lexical_bm25", "enabled": true, "weight": 1.0, "top_k": 50},
    {"name": "dense_vector", "enabled": true, "weight": 0.8, "top_k": 50},
    {"name": "table_structure", "enabled": true, "weight": 1.2, "top_k": 20},
    {"name": "graph_neighbor", "enabled": true, "weight": 0.6, "depth": 1}
  ],
  "filters": {
    "active_release_only": true,
    "scope": {"network_elements": ["UPF"]}
  },
  "fusion": {"method": "weighted_rrf", "k": 60},
  "rerank": {"method": "cross_encoder", "fallback": "score"},
  "assembly": {
    "source_drilldown": true,
    "relation_expansion": true,
    "compress_context": true
  }
}
```

### ContextPack / EvidencePack

当前 `ContextPack` 可以保留，但需要增强 item metadata：

- `route_sources`: 来自哪些 retriever。
- `raw_score / fusion_score / rerank_score`。
- `source_segment_id`。
- `citation`: document / section / line offsets。
- `evidence_role`: direct_answer / support / contrast / background / missing.
- `confidence`.
- `trace_id`.

## 重构路线

### Phase 0: 停止旧方向继续扩张

不建议继续围绕当前实现小修：

- 不要再把 LLM provider 类写好但主链不接。
- 不要继续只补 `QueryPlan` 字段。
- 不要继续在 Normalizer 里写死云核心网 regex。
- 不要把规则 reranker 当工业级相关性模型。

### Phase 1: Retrieval Orchestrator 骨架

目标：先把新的执行骨架立起来，即使部分 route 用 fallback。

必须交付：

- `QueryUnderstanding` 模型。
- `RetrievalRoutePlan` 模型。
- `RetrievalRouter` 组件。
- `Candidate` 统一模型，包含 route/source/score/provenance。
- `Trace` 模型，记录每阶段输入输出。
- `/search` debug 输出真实 route trace。

验收：

- 同一 query 在 debug 中能看到 understanding、route selection、candidate counts、fusion、rerank、assembly。
- 没有 LLM 时仍可 rule fallback。
- 有 LLM 时主链必须真实进入 query understanding / route planning。

### Phase 2: 三路召回基线

目标：从单路 BM25 升级到最小工业级 hybrid。

必须交付：

- `lexical_bm25`: 当前 FTS5 升级保留。
- `entity_exact`: 基于 `entity_refs_json`、`target_ref_json`、`facets_json`、alias hints 做实体召回。
- `dense_vector`: 基于 `asset_retrieval_embeddings` 做向量召回；若当前 SQLite 存 JSON vector，先实现 brute-force topK，后续可接 Qdrant/Milvus/FAISS。
- `weighted_rrf`: route-aware fusion。

验收：

- 命令/参数类 query 即使 BM25 漏召，entity route 能补回。
- 概念类 query 即使关键词不同，dense route 能补回。
- debug 能显示每条候选来自哪些 route。

### Phase 3: 神经重排

目标：用真正 reranker 替代规则加分主导。

建议顺序：

1. Cross-encoder / bge-reranker local or service wrapper。
2. LLM reranker fallback，用于低频高价值 query。
3. 规则 reranker 只保留为 fallback 和 tie-breaker。

验收：

- rerank 输入 topN candidates，输出相关性分数。
- 保留 `raw_score/fusion_score/rerank_score`。
- 对 eval set 的 NDCG@K / MRR@K 有提升。

### Phase 4: Evidence Assembly 变成答案就绪上下文

目标：不是简单 seed + support 拼接，而是构造可被 Agent 使用的证据包。

必须交付：

- direct evidence / support evidence / background evidence 分类。
- source citation 和 source_offsets 保留。
- parent/child context 策略。
- relation expansion 由 route plan 控制，不再固定 structural relation。
- context compression：去重、裁剪、保留表格结构。
- missing evidence / ambiguous scope issue。

验收：

- 对“区别/对比”类问题，ContextPack 同时包含两个实体各自证据和对比证据。
- 对参数类问题，表格行优先于泛段落。
- 对排障类问题，troubleshooting/alarm/condition 证据优先。

### Phase 5: Domain Pack 接入

目标：Serving 和 Mining 使用同一 domain pack。

Serving 需要从 Domain Pack 读取：

- query intent taxonomy。
- entity type aliases。
- route policy。
- rerank policy。
- eval questions。
- scope fields。

验收：

- 不改 Serving core，只换 domain pack，即可改变 query understanding 和 route preference。
- 云核心网 pack 可以识别 command/parameter/network_element/protocol/interface/alarm。
- toy domain pack 能通过最小测试。

### Phase 6: Eval / Observability

目标：把检索质量变成可度量。

必须交付：

- `serving_eval` 命令或测试入口。
- Recall@K。
- MRR@K。
- NDCG@K。
- citation hit rate。
- route contribution report。
- no-result / low-confidence 分析。
- LLM cost / latency trace。

验收：

- 每次修改 retriever / fusion / rerank 都能跑同一 eval set。
- 输出 per-query 失败原因。
- 没有 eval 的优化不允许标记为完成。

## 数据库影响

短期不必大改 asset_core，但 Serving 要开始消费已有字段：

- `asset_retrieval_units.unit_type`
- `asset_retrieval_units.source_segment_id`
- `asset_retrieval_units.entity_refs_json`
- `asset_retrieval_units.facets_json`
- `asset_retrieval_units.llm_result_refs_json`
- `asset_retrieval_embeddings`
- `asset_raw_segments.entity_refs_json`
- `asset_raw_segments.structure_json`
- `asset_raw_segment_relations`

可能需要小增量：

- 如果 `asset_retrieval_embeddings` 中 JSON vector 性能不足，后续引入外部 vector store 或 SQLite vector extension。
- 如果要做正式 entity route，长期需要 `asset_entities / asset_entity_mentions`，但当前阶段可以先基于 JSON 字段做半 GraphRAG。

## 当前代码可保留什么

可以保留：

- Active release -> build -> snapshot 范围约束。
- `source_segment_id` drilldown 优先级。
- `GraphExpander` 的基本 BFS 结构。
- `ContextPack` 基本框架。
- `RetrieverManager` 抽象壳。
- `RRF` 类。
- `ScoreReranker` 作为 fallback。

应该重写或弱化：

- 当前 `QueryPlan`，升级为 `RetrievalRoutePlan`。
- 当前 `QueryNormalizer`，改为 Domain Pack + LLM/rule hybrid understanding。
- 当前单路 `FTS5BM25Retriever` 主导模式。
- 当前 rule reranker 主导模式。
- 当前 Serving 文档中“LLM first”的不实描述。

## 验收标准

第一轮可验收版本至少满足：

1. `/search` debug 能输出完整 trace。
2. LLM query understanding 真进入主链，失败时 fallback。
3. 至少三路召回：BM25、entity exact、dense vector 或 embedding fallback。
4. RRF/weighted RRF 真用于多路候选融合。
5. Rerank 真作为独立阶段，规则只做 fallback。
6. ContextPack item 带 route_sources 和分数链。
7. 用最新 Mining 产物跑 contract test，不再 skip。
8. 至少接入一个 cloud_core_network eval set，输出 Recall@K/MRR@K/NDCG@K。

## 给 Claude Serving 的要求

请不要直接在当前 `/search` 上继续补小功能。下一步先提交 Serving 工业级重构计划，必须回答：

1. 新 `QueryUnderstanding` 与 `RetrievalRoutePlan` 如何定义？
2. 哪些 retrieval routes 第一波实现，哪些只预留？
3. vector route 当前用 SQLite JSON brute-force、FAISS、Qdrant 还是其他方案？
4. entity route 如何在不引入完整 ontology 表的前提下基于 `entity_refs_json` 落地？
5. reranker 第一波选 cross-encoder、LLM reranker 还是 rule fallback + 接口？
6. ContextPack 如何表达 direct/support/background/conflict/missing evidence？
7. 如何消费 Mining 的 Domain Pack 和 eval questions？
8. 如何证明新 Serving 比旧 Serving 更好？请给出 eval 指标和 fixture。

## 最终评估

当前 Serving 是基础检索服务，不是工业级智能检索系统。它可以作为数据读取和 active release 约束的代码基线，但不能作为未来主架构继续扩张。

下一轮目标应明确为：

> 将 Serving 重构为 Domain Pack 感知、Hybrid Retrieval 驱动、Rerank-first、Trace/Eval 完整的智能检索编排器。

只有做到这一点，Serving 才能跟上 Mining 的半 GraphRAG 知识资产编译方向，并真正支撑跨行业知识库。
