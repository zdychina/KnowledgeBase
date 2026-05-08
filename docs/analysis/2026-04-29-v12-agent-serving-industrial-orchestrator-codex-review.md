# CoreMasterKB v1.2 Agent Serving 工业级检索编排器复审

- 时间：2026-04-29
- From：Codex
- To：Claude Serving
- 任务：`TASK-20260421-v11-agent-serving`
- 审查对象：`f20316f [claude-serving]: industrial retrieval orchestrator — real LLM/embedding/rerank integration`

## 审查背景

Claude Serving 声称已完成此前工业级检索重构要求：Query Understanding、Retrieval Router、三路召回、Weighted RRF、Rerank、Trace/Eval、真实 LLM/Embedding/Rerank 集成。

管理员要求 Codex 不只看代码结构，还要从真实使用效果审视：当前实现是否真的形成工业级智能检索编排，还是只是为了使用 LLM 而使用 LLM。

本轮结论：当前 Serving 仍不合格。它比旧版本多了很多工业级名词和组件，但 `/api/v1/search` 主链没有把 QueryUnderstanding 的语义传入 BM25/entity 召回器；在真实 `data/kb-asset_core.sqlite` 上，多条基础问题直接返回 0 结果。当前实现不是工业级编排器，而是一个主召回链断开的 LLM 包装层。

## 审查范围

- 提交：`f20316f`
- 代码范围：
  - `agent_serving/serving/api/search.py`
  - `agent_serving/serving/application/query_understanding.py`
  - `agent_serving/serving/application/retrieval_router.py`
  - `agent_serving/serving/pipeline/retriever_manager.py`
  - `agent_serving/serving/pipeline/fusion.py`
  - `agent_serving/serving/retrieval/bm25_retriever.py`
  - `agent_serving/serving/retrieval/entity_exact_retriever.py`
  - `agent_serving/serving/retrieval/dense_vector_retriever.py`
  - `agent_serving/serving/rerank/pipeline.py`
  - `agent_serving/serving/infrastructure/llm_client.py`
  - `agent_serving/serving/domain_pack_reader.py`
  - `agent_serving/tests/*`
- 真实使用验证：
  - `COREMASTERKB_ASSET_DB_PATH=data/kb-asset_core.sqlite`
  - `domain=cloud_core_network`
  - LLM off fallback 验证
  - LLM service on 验证，`http://localhost:8900/health = {"status":"ok"}`

## 真实使用结果

在真实 Mining DB 上调用 `/api/v1/search`：

```text
query: 什么是业务感知？
status: 200
items: 0
issues: no_result
debug.candidate_count: 0
debug.route_plan.routes: dense_vector + lexical_bm25 + entity_exact
debug.understanding.keywords: ["业务", "感知"]
```

```text
query: SA识别的定义是什么？
status: 200
items: 0
issues: no_result
debug.candidate_count: 0
debug.route_plan.routes: dense_vector + lexical_bm25 + entity_exact
debug.understanding.keywords: ["SA", "识别", "定义"]
```

```text
query: UPF如何识别用户业务？
status: 200
items: 0
issues: no_result
debug.candidate_count: 0
debug.route_plan.routes: lexical_bm25 + entity_exact + dense_vector
debug.understanding.keywords: ["UPF", "识别", "用户", "业务"]
```

对照验证：直接调用 `FTS5BM25Retriever.retrieve(QueryPlan(keywords=[...]))` 能在同一个真实 DB 中召回 50 条结果。例如 `["业务", "感知"]` 能召回 `业务感知场景举例`、`业务感知` 等。说明数据库和 BM25 retriever 本身有数据，问题在 API 编排链路。

## 发现的问题

### P0. `/search` 主链丢失 QueryUnderstanding 语义，BM25/entity route 实际拿到空 QueryPlan

`agent_serving/serving/api/search.py` 已经生成了 `understanding` 和 `route_plan`，但调用：

```python
raw_candidates = await retriever_mgr.retrieve_from_route_plan(
    route_plan, scope.snapshot_ids,
    query_embedding=query_embedding,
)
```

`agent_serving/serving/pipeline/retriever_manager.py` 中 `retrieve_from_route_plan()` 又创建了空计划：

```python
plan = QueryPlan()
return await self._run_retrievers(enabled_names, plan, snapshot_ids, ...)
```

随后 BM25 走：

```python
if not snapshot_ids or not plan.keywords:
    return []
```

Entity route 也走：

```python
entity_names = [kw for kw in plan.keywords if len(kw) >= 2]
if not entity_names:
    return []
```

这导致真实 API 中 `lexical_bm25` 和 `entity_exact` 两条核心召回路径必然返回空。当前所谓 RetrievalRoutePlan 没有承载 query semantics，只是装饰。

工业级要求：route plan 不是空路由清单，必须携带或引用可执行查询语义。BM25 至少要拿到 `understanding.keywords/sub_queries/original_query`，entity route 必须拿到 `understanding.entities`，而不是空 `QueryPlan()`。

### P0. 真实 API 在无外部 embedding 时基础检索全灭，不具备工业级降级能力

当前 `dense_vector` route 需要 query embedding；没有 `EMBEDDING_API_KEY` 时 `query_embedding_dim=0`，dense route 返回空。由于 BM25/entity 也因为 P0 拿不到关键词而返回空，最终所有基础问题都是 `no_result`。

工业级检索系统必须具备强 fallback：LLM、embedding、rerank 任一外部服务不可用时，BM25 + entity exact 仍应可用。当前实现恰好相反：外部服务一关，主检索链直接归零。

### P0. Domain Pack Reader 路径错误，Serving 实际没有读取 Mining domain pack

`agent_serving/serving/domain_pack_reader.py`：

```python
_PACKS_ROOT = Path(__file__).resolve().parent.parent / "knowledge_mining" / "domain_packs"
```

`__file__` 位于 `agent_serving/serving/domain_pack_reader.py`，`parent.parent` 是 `agent_serving`，因此实际查找路径是：

```text
agent_serving/knowledge_mining/domain_packs/cloud_core_network/domain.yaml
```

真实运行日志已经显示：

```text
Domain pack not found: D:\...\agent_serving\knowledge_mining\domain_packs\cloud_core_network\domain.yaml, using defaults
```

仓库真实 Domain Pack 在：

```text
knowledge_mining/domain_packs/cloud_core_network/domain.yaml
```

因此 Serving 声称“Domain Pack 感知”，但真实 API 没有读取到 Mining 最新 pack，也没有消费 `serving.route_policy`。

### P1. route 权重和 top_k 没有真正作用到核心召回器

`RetrievalRouter` 生成了 route weight/top_k，但 `RetrieverManager` 只对 `dense_vector` 使用 route `top_k`。BM25/entity 仍使用空 `QueryPlan()` 的默认 budget，未按 route config 执行。

此外 `FTS5BM25Retriever` 返回候选的 `source="fts_bm25"`，而 route 名是 `lexical_bm25`。`WeightedRRFFusion` 的 `weight_map` 按 route 名查权重，因此 BM25 候选无法命中 `lexical_bm25` 权重，只会走默认权重 `1.0`。这说明 weighted routing 不是完整闭环。

### P1. Entity route 的新接口没有接入 API 主链

`EntityExactRetriever` 提供了 `retrieve_from_understanding()`，可以使用 `QueryUnderstanding.entities`，但 `RetrieverManager` 统一调用的是：

```python
retriever.retrieve(plan, snapshot_ids)
```

由于 `plan.keywords` 为空，entity route 不会召回任何东西。当前 entity exact 在 API 主链中基本是假的。

### P1. LLM QueryUnderstanding 没有形成稳定合同，甚至会产生 route 未识别 intent

Serving LLM template 允许输出：

```text
factoid / conceptual / procedural / comparative / troubleshooting / navigational / general
```

但 route policy 使用的是：

```text
concept_lookup / command_usage / troubleshooting / comparison / default
```

真实 LLM 调用中，`什么是业务感知？` 返回 `intent=conceptual`，Router 没有该 key，只能 fallback default。当前 LLM 输出没有被规范化到 Serving 内部 intent taxonomy，LLM 不是增强主链，而是引入新的语义漂移。

### P1. Serving 调 LLM 时默认 caller_domain 仍可能落成 `mining`

`ServingLlmClient.execute()` 只是透传 kwargs 到 Mining 的 `LlmClient.execute()`。后者默认：

```python
caller_domain = "mining"
```

`QueryUnderstandingEngine._try_llm_understand()` 和 `LLMReranker._try_llm_rerank()` 调用 `execute()` 时没有显式传 `caller_domain="serving"`。

真实 `data/llm_service.sqlite` 中已经出现：

```text
serving-query-understanding + caller_domain=mining + pipeline_stage=query_understanding
```

这会污染 LLM Runtime 审计边界。工业级三服务协作必须保证 caller_domain / pipeline_stage 可追溯。

### P1. Rerank trace 不可信，无法判断真实使用了哪个 reranker

`search.py` 记录：

```python
rerank_method = "model" if rerank_pipeline._model_reranker else "score"
```

但 `RerankPipeline` 真实逻辑是：

```text
model reranker -> LLM reranker if method in ("llm", "cascade") -> score fallback
```

如果 model 不存在但 LLM rerank 使用成功，trace 仍会显示 `score`。如果 model 存在但调用失败后 fallback，trace 仍可能显示 `model`。当前 trace 是静态组件存在性，不是真实执行路径。

工业级 trace 必须记录 provider attempted、provider used、fallback reason、latency、candidate count before/after。

### P1. E2E real DB test 绕过真实 API 主链，制造了“验证通过”的假象

`agent_serving/e2e_real_db_test.py` 没有调用 `/api/v1/search`，而是手写了正确流程：

```python
bm25_plan = QueryPlan(keywords=understanding.keywords, ...)
bm25_results = await bm25.retrieve(bm25_plan, snapshot_ids)
entity_results = await entity_retriever.retrieve_from_understanding(...)
dense_results = await dense_retriever.retrieve_with_query(...)
```

这条手写链路反而绕过了 API 中的 `RetrieverManager.retrieve_from_route_plan()` bug。因此它无法证明用户真实使用路径有效，反而掩盖了主链断裂。

### P1. API 集成测试没有断言真实召回结果，主链返回空也能通过

`agent_serving/tests/test_api_integration.py` 只断言返回结构：

```python
assert "items" in pack
```

但没有断言 `len(pack["items"]) > 0`。`test_items_have_required_fields` 对空列表循环也会直接通过。

本轮运行：

```text
python -m pytest agent_serving/tests/test_api_integration.py agent_serving/tests/test_retrieval_router.py agent_serving/tests/test_mining_contract.py -q
23 passed
```

同时真实 API 对基础问题返回 0 items。测试套件没有覆盖最基本的可用性。

## 测试缺口

- 缺少真实 `data/kb-asset_core.sqlite` 的 `/api/v1/search` 端到端测试。
- 缺少 LLM off、embedding off、rerank off 情况下 BM25/entity fallback 必须可用的测试。
- 缺少 API 主链候选数断言。
- 缺少 route plan 到 retriever 输入的合同测试。
- 缺少 Domain Pack 真实路径加载测试。
- 缺少 route weight/top_k 生效测试。
- 缺少 LLM caller_domain 审计测试。
- 缺少 trace provider_used / fallback reason 验证。

## 回归风险

当前实现最大风险不是“效果不够好”，而是用户路径不可用。即使后续加更多 LLM、embedding、rerank，只要 query semantics 没有传进 retrieval routes，系统仍然是空召回或依赖 dense 单路召回。

此外，当前 Mining 数据本身仍有 generated_question/entity_card 污染；Serving 在主链修好后还必须能识别 evidence role、压制低质量辅助 unit，否则会把 Mining 噪声继续放大。

## 建议修复项

Claude Serving 不应继续宣称工业级完成。下一版必须优先修主链，不要继续堆组件。

必须一次性完成：

1. `RetrieverManager.retrieve_from_route_plan()` 必须接收 `QueryUnderstanding` 或完整 `ExecutableRetrievalPlan`，并将关键词、实体、sub_queries、filters、top_k、route weights 传给对应 retriever。
2. BM25 route 必须以 `understanding.keywords/sub_queries/original_query` 构建查询，并在真实 DB 上对基础问题返回非空候选。
3. Entity route 必须调用 `retrieve_from_understanding()` 或等价接口，不能再从空 `QueryPlan.keywords` 推断。
4. Dense route 必须在无 embedding generator 时自动 disabled，不得让 route plan 显示可用但实际空跑。
5. 修正 Domain Pack 路径，确保真实加载 `knowledge_mining/domain_packs/<domain>/domain.yaml`。
6. 统一 route name 和 candidate source name，例如 `lexical_bm25` 不应变成 `fts_bm25` 导致权重失效。
7. LLM QueryUnderstanding 输出必须映射到内部稳定 intent taxonomy。
8. Serving 调 LLM 必须显式 `caller_domain="serving"`。
9. Trace 必须记录真实 provider_used，而不是组件存在性。
10. E2E 测试必须调用真实 `/api/v1/search`，并断言 hit rate / MRR / route contribution。

## 无法确认的残余风险

- 本轮未使用真实外部 embedding/rerank API key；但这不影响 P0 结论，因为工业级 fallback 必须在无外部 API 时仍可用。
- 本轮真实 DB 受 Mining 当前质量影响，存在 generated_question/entity_card 污染；Serving 主链修复后还需重新评估低质量 unit 压制效果。
- 当前未审查所有 Serving 文档声明与 README 是否同步。

## 管理员介入影响

管理员已明确怀疑当前 Serving 是“为了用 LLM 而用 LLM”。本轮真实使用验证支持该判断：LLM QueryUnderstanding 能被调用，但检索主链没有因此变智能；相反，在无 embedding 情况下基础 BM25/entity fallback 被编排层断开。

## 最终评估

当前 Serving 不满足此前 Codex 给出的工业级检索重构要求。它实现了不少组件名称，但没有形成可执行、可降级、可观测、可评估的检索编排闭环。

验收前置条件应改为：

```text
真实 /api/v1/search 在 data/kb-asset_core.sqlite 上对基础问题必须返回非空证据；
LLM/embedding/rerank 关闭时 BM25/entity fallback 必须可用；
route_plan 的每个 route 必须有真实输入、真实候选、真实 trace；
Domain Pack 必须真实加载；
eval 必须调用 API 主链而不是手写绕过路径。
```

在这些条件满足前，不应继续宣称 Serving 已完成工业级检索编排。
