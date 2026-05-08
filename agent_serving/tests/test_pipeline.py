"""Tests for pipeline components: Fusion, Reranker, QueryPlanner, RetrieverManager, LLM providers."""
import pytest

from agent_serving.serving.schemas.models import (
    ContextItem,
    ExpansionConfig,
    NormalizedQuery,
    QueryPlan,
    RetrievalBudget,
    RetrievalCandidate,
    RetrievalRoutePlan,
    RetrieverConfig,
    RouteConfig,
    ScoreChain,
    SearchRequest,
)
from agent_serving.serving.pipeline.fusion import IdentityFusion, RRFFusion
from agent_serving.serving.pipeline.reranker import ScoreReranker
from agent_serving.serving.pipeline.query_planner import (
    QueryPlanner,
    RulePlannerProvider,
)
from agent_serving.serving.pipeline.llm_providers import (
    LLMNormalizerProvider,
    LLMRerankerProvider,
)
from agent_serving.serving.schemas.json_utils import (
    parse_source_refs,
    parse_target_ref,
    safe_json_parse,
)


def _candidate(ru_id, score, source="fts_bm25"):
    return RetrievalCandidate(
        retrieval_unit_id=ru_id, score=score, source=source, metadata={},
    )


class TestIdentityFusion:
    @pytest.mark.asyncio
    async def test_dedup_keeps_higher_score(self):
        fusion = IdentityFusion()
        candidates = [
            _candidate("a", 0.9, "fts"),
            _candidate("a", 0.5, "like"),
            _candidate("b", 0.7, "fts"),
        ]
        result = await fusion.fuse(candidates, QueryPlan())
        assert len(result) == 2
        assert result[0].score == 0.9  # Sorted desc
        assert result[1].score == 0.7

    @pytest.mark.asyncio
    async def test_empty_input(self):
        fusion = IdentityFusion()
        result = await fusion.fuse([], QueryPlan())
        assert result == []


class TestRRFFusion:
    @pytest.mark.asyncio
    async def test_multi_source_fusion(self):
        fusion = RRFFusion(k=60)
        candidates = [
            _candidate("a", 0.9, "fts"),
            _candidate("b", 0.8, "fts"),
            _candidate("a", 0.5, "vector"),
            _candidate("c", 0.7, "vector"),
        ]
        result = await fusion.fuse(candidates, QueryPlan())
        ids = [c.retrieval_unit_id for c in result]
        # "a" appears in both sources, should rank highest
        assert ids[0] == "a"

    @pytest.mark.asyncio
    async def test_single_source(self):
        fusion = RRFFusion()
        candidates = [_candidate("x", 0.9, "fts"), _candidate("y", 0.5, "fts")]
        result = await fusion.fuse(candidates, QueryPlan())
        assert len(result) == 2


class TestScoreReranker:
    @pytest.mark.asyncio
    async def test_role_preference(self):
        reranker = ScoreReranker()
        plan = QueryPlan(desired_roles=["parameter"])
        candidates = [
            RetrievalCandidate(retrieval_unit_id="a", score=0.5, source="fts", metadata={"semantic_role": "concept"}),
            RetrievalCandidate(retrieval_unit_id="b", score=0.8, source="fts", metadata={"semantic_role": "parameter"}),
        ]
        result = await reranker.rerank(candidates, plan)
        assert result[0].metadata["semantic_role"] == "parameter"

    @pytest.mark.asyncio
    async def test_budget_truncation(self):
        reranker = ScoreReranker()
        plan = QueryPlan(budget=RetrievalBudget(max_items=2))
        candidates = [_candidate(f"ru-{i}", i * 0.1) for i in range(5)]
        result = await reranker.rerank(candidates, plan)
        assert len(result) == 2

    @pytest.mark.asyncio
    async def test_empty_candidates(self):
        reranker = ScoreReranker()
        result = await reranker.rerank([], QueryPlan())
        assert result == []


class TestRulePlannerProvider:
    def test_builds_plan_from_normalized(self):
        provider = RulePlannerProvider()
        normalized = NormalizedQuery(
            original_query="ADD APN",
            intent="command_usage",
            keywords=["ADD", "APN"],
        )
        plan = provider.build_plan(normalized)
        assert plan.intent == "command_usage"
        assert plan.keywords == ["ADD", "APN"]

    def test_scope_override(self):
        provider = RulePlannerProvider()
        normalized = NormalizedQuery(original_query="test", scope={"products": ["X"]})
        plan = provider.build_plan(normalized, scope_override={"products": ["Y"]})
        assert plan.scope_constraints == {"products": ["Y"]}


class TestQueryPlannerFacade:
    def test_delegates_to_provider(self):
        planner = QueryPlanner(RulePlannerProvider())
        normalized = NormalizedQuery(original_query="test", intent="general")
        plan = planner.plan(normalized)
        assert plan.intent == "general"


class TestLLMProviders:
    def test_normalizer_returns_none_when_no_client(self):
        import asyncio
        provider = LLMNormalizerProvider()
        result = asyncio.get_event_loop().run_until_complete(
            provider.normalize("test"),
        )
        assert result is None

    def test_reranker_returns_none_when_no_client(self):
        import asyncio
        provider = LLMRerankerProvider()
        result = asyncio.get_event_loop().run_until_complete(
            provider.rerank([], QueryPlan()),
        )
        assert result is None


class TestJsonUtils:
    def test_parse_source_refs_valid(self):
        assert parse_source_refs('{"raw_segment_ids": ["a", "b"]}') == ["a", "b"]

    def test_parse_source_refs_empty(self):
        assert parse_source_refs(None) == []
        assert parse_source_refs("{}") == []

    def test_parse_source_refs_invalid_type(self):
        assert parse_source_refs('{"raw_segment_ids": [1, 2]}') == []

    def test_parse_target_ref_single(self):
        assert parse_target_ref('{"raw_segment_id": "abc"}') == ["abc"]

    def test_parse_target_ref_multiple(self):
        assert parse_target_ref('{"raw_segment_ids": ["a", "b"]}') == ["a", "b"]

    def test_parse_target_ref_empty(self):
        assert parse_target_ref(None) == []
        assert parse_target_ref("{}") == []

    def test_safe_json_parse_dict_passthrough(self):
        assert safe_json_parse({"a": 1}) == {"a": 1}

    def test_safe_json_parse_string(self):
        assert safe_json_parse('{"b": 2}') == {"b": 2}

    def test_safe_json_parse_invalid(self):
        assert safe_json_parse("not json") == {}


# --- v1.2 Tests ---


class TestV12Deduplication:
    """Step 1.5: raw_text / contextual_text dedup by source_segment_id."""

    @pytest.mark.asyncio
    async def test_dedup_keeps_higher_score(self):
        reranker = ScoreReranker()
        plan = QueryPlan(budget=RetrievalBudget(max_items=10))
        candidates = [
            RetrievalCandidate(
                retrieval_unit_id="ru-raw", score=0.9, source="fts",
                metadata={"unit_type": "raw_text", "source_segment_id": "seg-1"},
            ),
            RetrievalCandidate(
                retrieval_unit_id="ru-ctx", score=0.7, source="fts",
                metadata={"unit_type": "contextual_text", "source_segment_id": "seg-1"},
            ),
        ]
        result = await reranker.rerank(candidates, plan)
        ids = [c.retrieval_unit_id for c in result]
        assert "ru-raw" in ids
        assert "ru-ctx" not in ids  # Deduped — lower score

    @pytest.mark.asyncio
    async def test_different_segments_not_deduped(self):
        reranker = ScoreReranker()
        plan = QueryPlan(budget=RetrievalBudget(max_items=10))
        candidates = [
            RetrievalCandidate(
                retrieval_unit_id="ru-1", score=0.9, source="fts",
                metadata={"unit_type": "raw_text", "source_segment_id": "seg-1"},
            ),
            RetrievalCandidate(
                retrieval_unit_id="ru-2", score=0.7, source="fts",
                metadata={"unit_type": "raw_text", "source_segment_id": "seg-2"},
            ),
        ]
        result = await reranker.rerank(candidates, plan)
        assert len(result) == 2

    @pytest.mark.asyncio
    async def test_entity_card_not_deduped(self):
        reranker = ScoreReranker()
        plan = QueryPlan(budget=RetrievalBudget(max_items=10))
        candidates = [
            RetrievalCandidate(
                retrieval_unit_id="ru-entity-1", score=0.9, source="fts",
                metadata={"unit_type": "entity_card", "source_segment_id": "seg-1"},
            ),
            RetrievalCandidate(
                retrieval_unit_id="ru-raw", score=0.7, source="fts",
                metadata={"unit_type": "raw_text", "source_segment_id": "seg-1"},
            ),
        ]
        result = await reranker.rerank(candidates, plan)
        assert len(result) == 2  # entity_card passes through dedup


class TestV12Downweight:
    """Step 2.1: Low-value block_type downweight."""

    @pytest.mark.asyncio
    async def test_heading_downweighted(self):
        reranker = ScoreReranker()
        plan = QueryPlan(budget=RetrievalBudget(max_items=10))
        candidates = [
            RetrievalCandidate(
                retrieval_unit_id="ru-heading", score=1.0, source="fts",
                metadata={"block_type": "heading"},
            ),
            RetrievalCandidate(
                retrieval_unit_id="ru-para", score=1.0, source="fts",
                metadata={"block_type": "paragraph"},
            ),
        ]
        result = await reranker.rerank(candidates, plan)
        # paragraph should rank higher (heading was downweighted)
        assert result[0].retrieval_unit_id == "ru-para"

    @pytest.mark.asyncio
    async def test_toc_downweighted(self):
        reranker = ScoreReranker()
        plan = QueryPlan(budget=RetrievalBudget(max_items=10))
        candidates = [
            RetrievalCandidate(
                retrieval_unit_id="ru-toc", score=1.0, source="fts",
                metadata={"block_type": "toc"},
            ),
            RetrievalCandidate(
                retrieval_unit_id="ru-para", score=0.5, source="fts",
                metadata={"block_type": "paragraph"},
            ),
        ]
        result = await reranker.rerank(candidates, plan)
        # paragraph (0.5) still beats toc (1.0 * 0.3 = 0.3)
        assert result[0].retrieval_unit_id == "ru-para"


class TestV12RuleScoring:
    """Step 2.2: Rule-based scoring boost."""

    @pytest.mark.asyncio
    async def test_intent_role_boost(self):
        reranker = ScoreReranker()
        plan = QueryPlan(desired_roles=["parameter"])
        candidates = [
            RetrievalCandidate(
                retrieval_unit_id="ru-concept", score=1.0, source="fts",
                metadata={"semantic_role": "concept"},
            ),
            RetrievalCandidate(
                retrieval_unit_id="ru-param", score=1.0, source="fts",
                metadata={"semantic_role": "parameter"},
            ),
        ]
        result = await reranker.rerank(candidates, plan)
        assert result[0].retrieval_unit_id == "ru-param"
        assert result[0].score > result[1].score

    @pytest.mark.asyncio
    async def test_scope_boost(self):
        reranker = ScoreReranker()
        plan = QueryPlan(
            scope_constraints={"products": ["UDG"]},
            budget=RetrievalBudget(max_items=10),
        )
        candidates = [
            RetrievalCandidate(
                retrieval_unit_id="ru-match", score=1.0, source="fts",
                metadata={"facets_json": '{"products": ["UDG"]}'},
            ),
            RetrievalCandidate(
                retrieval_unit_id="ru-nomatch", score=1.0, source="fts",
                metadata={"facets_json": '{"products": ["UNC"]}'},
            ),
        ]
        result = await reranker.rerank(candidates, plan)
        assert result[0].retrieval_unit_id == "ru-match"

    @pytest.mark.asyncio
    async def test_entity_boost(self):
        reranker = ScoreReranker()
        plan = QueryPlan(
            keywords=["add apn"],
            budget=RetrievalBudget(max_items=10),
        )
        candidates = [
            RetrievalCandidate(
                retrieval_unit_id="ru-entity", score=1.0, source="fts",
                metadata={"entity_refs_json": '[{"type": "command", "name": "ADD APN", "normalized_name": "add apn"}]'},
            ),
            RetrievalCandidate(
                retrieval_unit_id="ru-noentity", score=1.0, source="fts",
                metadata={"entity_refs_json": "[]"},
            ),
        ]
        result = await reranker.rerank(candidates, plan)
        assert result[0].retrieval_unit_id == "ru-entity"


class TestV12SourceSegmentIdBridge:
    """Step 1.2: Assembler source_segment_id 4-layer priority."""

    def test_source_segment_id_highest_priority(self):
        from agent_serving.serving.application.assembler import ContextAssembler
        from unittest.mock import MagicMock

        assembler = ContextAssembler(MagicMock(), MagicMock())
        candidate = RetrievalCandidate(
            retrieval_unit_id="ru-1", score=0.9, source="fts",
            metadata={
                "source_segment_id": "seg-primary",
                "source_refs_json": '{"raw_segment_ids": ["seg-secondary"]}',
                "target_type": "raw_segment",
                "target_ref_json": '{"raw_segment_id": "seg-tertiary"}',
            },
        )
        result = assembler._resolve_candidate_sources(candidate)
        assert result == ["seg-primary"]

    def test_source_refs_json_fallback(self):
        from agent_serving.serving.application.assembler import ContextAssembler
        from unittest.mock import MagicMock

        assembler = ContextAssembler(MagicMock(), MagicMock())
        candidate = RetrievalCandidate(
            retrieval_unit_id="ru-1", score=0.9, source="fts",
            metadata={
                "source_refs_json": '{"raw_segment_ids": ["seg-from-refs"]}',
                "target_type": "raw_segment",
                "target_ref_json": '{"raw_segment_id": "seg-from-target"}',
            },
        )
        result = assembler._resolve_candidate_sources(candidate)
        assert result == ["seg-from-refs"]

    def test_target_ref_json_fallback(self):
        from agent_serving.serving.application.assembler import ContextAssembler
        from unittest.mock import MagicMock

        assembler = ContextAssembler(MagicMock(), MagicMock())
        candidate = RetrievalCandidate(
            retrieval_unit_id="ru-1", score=0.9, source="fts",
            metadata={
                "target_type": "raw_segment",
                "target_ref_json": '{"raw_segment_id": "seg-from-target"}',
            },
        )
        result = assembler._resolve_candidate_sources(candidate)
        assert result == ["seg-from-target"]

    def test_empty_fallback(self):
        from agent_serving.serving.application.assembler import ContextAssembler
        from unittest.mock import MagicMock

        assembler = ContextAssembler(MagicMock(), MagicMock())
        candidate = RetrievalCandidate(
            retrieval_unit_id="ru-1", score=0.9, source="fts",
            metadata={},
        )
        result = assembler._resolve_candidate_sources(candidate)
        assert result == []


class TestV12LLMNormalizerFallback:
    """Step 3.2: LLM normalizer fallback to rule-based."""

    def test_sync_normalize_uses_rules(self):
        from agent_serving.serving.application.normalizer import QueryNormalizer
        normalizer = QueryNormalizer()
        result = normalizer.normalize("什么是5G")
        assert result.intent == "concept_lookup"
        assert "5G" in result.keywords

    @pytest.mark.asyncio
    async def test_async_normalize_fallback_when_no_llm(self):
        from agent_serving.serving.application.normalizer import QueryNormalizer
        normalizer = QueryNormalizer()
        result = await normalizer.anormalize("ADD APN命令怎么写")
        assert result.intent == "command_usage"
        assert len(result.entities) > 0


class TestV12LLMPlannerFallback:
    """Step 3.3: LLM planner fallback to rule-based."""

    def test_sync_plan_uses_rules(self):
        from agent_serving.serving.pipeline.query_planner import QueryPlanner, RulePlannerProvider
        planner = QueryPlanner(RulePlannerProvider())
        normalized = NormalizedQuery(
            original_query="ADD APN",
            intent="command_usage",
            keywords=["ADD", "APN"],
        )
        plan = planner.plan(normalized)
        assert plan.intent == "command_usage"

    @pytest.mark.asyncio
    async def test_async_plan_fallback_when_no_llm(self):
        from agent_serving.serving.pipeline.query_planner import LLMPlannerProvider
        provider = LLMPlannerProvider()
        normalized = NormalizedQuery(
            original_query="test",
            intent="general",
            keywords=["test"],
        )
        plan = await provider.abuild_plan(normalized)
        assert plan.intent == "general"


# --- v2 Tests ---


class TestV2TraceCollector:
    """TraceCollector timing and output."""

    def test_trace_stages(self):
        from agent_serving.serving.observability.trace import TraceCollector
        tc = TraceCollector()
        tc.start_stage("understand")
        tc.end_stage("understand", output_summary="intent=command_usage")
        tc.start_stage("retrieve")
        tc.end_stage("retrieve", output_summary="10 candidates")
        trace = tc.build_trace(request_id="test-123")
        assert trace.request_id == "test-123"
        assert len(trace.stages) == 2
        assert trace.stages[0].name == "understand"
        assert trace.stages[0].duration_ms >= 0
        assert trace.total_duration_ms >= 0

    def test_trace_error_stage(self):
        from agent_serving.serving.observability.trace import TraceCollector
        tc = TraceCollector()
        tc.start_stage("failing_stage")
        tc.end_stage("failing_stage", error="something went wrong")
        trace = tc.build_trace()
        assert trace.stages[0].error == "something went wrong"


class TestV2DomainPackReader:
    """Domain pack reading for Serving."""

    def test_load_default_profile(self):
        from agent_serving.serving.domain_pack_reader import load_serving_profile
        profile = load_serving_profile(None)
        assert profile.domain_id == "default"
        assert len(profile.route_policy) > 0

    def test_get_route_policy(self):
        from agent_serving.serving.domain_pack_reader import (
            load_serving_profile,
            get_route_policy,
        )
        profile = load_serving_profile(None)
        policy = get_route_policy(profile, "command_usage")
        assert "entity_exact" in policy
        assert policy["entity_exact"]["weight"] > 1.0


class TestV2RetrieverManager:
    """RetrieverManager v2 route plan integration."""

    @pytest.mark.asyncio
    async def test_retrieve_from_route_plan(self):
        from agent_serving.serving.pipeline.retriever_manager import RetrieverManager
        from agent_serving.serving.schemas.models import (
            RetrievalRoutePlan,
            RouteConfig,
            ScoreChain,
        )
        from unittest.mock import AsyncMock

        mock_retriever = AsyncMock()
        mock_retriever.retrieve.return_value = [
            RetrievalCandidate(
                retrieval_unit_id="ru-1", score=0.9, source="fts_bm25",
                metadata={},
                score_chain=ScoreChain(raw_score=0.9, route_sources=["fts_bm25"]),
            ),
        ]

        mgr = RetrieverManager({"fts_bm25": mock_retriever})
        route_plan = RetrievalRoutePlan(
            routes=[RouteConfig(name="fts_bm25", enabled=True, weight=1.0)],
        )
        results = await mgr.retrieve_from_route_plan(route_plan, ["snap-1"])
        assert len(results) == 1
        assert results[0].score_chain.route_sources == ["fts_bm25"]


class TestV2Models:
    """v2 new model validation."""

    def test_search_request_domain(self):
        req = SearchRequest(query="test", domain="cloud_core_network")
        assert req.domain == "cloud_core_network"
        assert req.mode == "evidence"

    def test_retrieval_candidate_score_chain(self):
        sc = ScoreChain(raw_score=0.9, fusion_score=0.8, rerank_score=0.85, route_sources=["fts_bm25"])
        c = RetrievalCandidate(
            retrieval_unit_id="ru-1", score=0.85, source="fts_bm25",
            metadata={}, score_chain=sc,
        )
        assert c.score_chain.raw_score == 0.9
        assert c.score_chain.fusion_score == 0.8

    def test_context_item_v2_fields(self):
        item = ContextItem(
            id="ru-1", kind="retrieval_unit", role="seed",
            text="test", score=0.9,
            route_sources=["fts_bm25", "entity_exact"],
            evidence_role="direct_answer",
            citation={"section": "ADD APN"},
        )
        assert len(item.route_sources) == 2
        assert item.evidence_role == "direct_answer"
        assert item.citation["section"] == "ADD APN"

    def test_retrieval_route_plan(self):
        plan = RetrievalRoutePlan(
            routes=[
                RouteConfig(name="fts_bm25", weight=1.0, top_k=50),
                RouteConfig(name="entity_exact", weight=1.4, top_k=20),
            ],
        )
        assert len(plan.routes) == 2
        assert plan.routes[1].weight == 1.4

    def test_trace_model(self):
        from agent_serving.serving.schemas.models import Trace, TraceStage
        trace = Trace(
            request_id="req-1",
            stages=[TraceStage(name="test", duration_ms=10.0)],
            total_duration_ms=10.0,
        )
        assert len(trace.stages) == 1


# --- v1.4 Tests: scope pushdown, evidence groups, assembler v2 ---


class TestScopePushdownSafety:
    """Verify _build_scope_filter uses parameterized binding (no SQL injection)."""

    def test_bm25_scope_filter_parameterized(self):
        from agent_serving.serving.retrieval.bm25_retriever import FTS5BM25Retriever
        sql, params = FTS5BM25Retriever._build_scope_filter({"products": ["UDG"]})
        assert "%s::jsonb" in sql
        assert "UDG" not in sql  # value is in params, not SQL

    def test_dense_scope_filter_parameterized(self):
        from agent_serving.serving.retrieval.dense_vector_retriever import DenseVectorRetriever
        sql, params = DenseVectorRetriever._build_scope_filter({"products": ["UDG"]})
        assert "%s::jsonb" in sql
        assert "UDG" not in sql

    def test_entity_scope_filter_parameterized(self):
        from agent_serving.serving.retrieval.entity_exact_retriever import EntityExactRetriever
        sql, params = EntityExactRetriever._build_scope_filter({"products": ["UDG"]})
        assert "%s::jsonb" in sql
        assert "UDG" not in sql


class TestEvidenceGroupUnit:
    """EvidenceGroup relation_ids should only include group-related relations."""

    def test_evidence_groups_filter_relations_by_item_ids(self):
        from agent_serving.serving.application.assembler import ContextAssembler
        from agent_serving.serving.schemas.models import (
            ContextItem,
            ContextRelation,
            EvidenceGroup,
        )
        from unittest.mock import MagicMock

        assembler = ContextAssembler(MagicMock(), MagicMock())

        items = [
            ContextItem(
                id="item-1", kind="retrieval_unit", role="seed",
                text="t1", score=0.9,
                metadata={"document_snapshot_id": "snap-A"},
            ),
            ContextItem(
                id="item-2", kind="raw_segment", role="context",
                text="t2", score=0.0,
                metadata={"document_snapshot_id": "snap-B"},
            ),
        ]
        relations = [
            ContextRelation(
                id="rel-1", from_id="item-1", to_id="item-2",
                relation_type="next", distance=1,
            ),
            ContextRelation(
                id="rel-2", from_id="item-X", to_id="item-Y",
                relation_type="next", distance=1,
            ),
        ]

        groups = assembler._build_evidence_groups(items, relations)
        assert len(groups) == 2

        group_a = next(g for g in groups if g.document_snapshot_id == "snap-A")
        assert "item-1" in group_a.item_ids
        # rel-1 connects item-1 ↔ item-2, so it's in group A (from_id matches)
        assert "rel-1" in group_a.relation_ids
        # rel-2 is unrelated to group A's items
        assert "rel-2" not in group_a.relation_ids

    def test_evidence_groups_empty_when_no_snapshot(self):
        from agent_serving.serving.application.assembler import ContextAssembler
        from unittest.mock import MagicMock

        assembler = ContextAssembler(MagicMock(), MagicMock())

        items = [
            ContextItem(
                id="item-1", kind="retrieval_unit", role="seed",
                text="t1", score=0.9, metadata={},
            ),
        ]
        groups = assembler._build_evidence_groups(items, [])
        assert groups == []


class TestAssemblerIssues:
    """Test _build_issues covers no_result and low_confidence."""

    def test_low_confidence_issue(self):
        from agent_serving.serving.application.assembler import ContextAssembler
        from agent_serving.serving.schemas.models import ContextItem
        from unittest.mock import MagicMock

        assembler = ContextAssembler(MagicMock(), MagicMock())

        items = [
            ContextItem(
                id="ru-1", kind="retrieval_unit", role="seed",
                text="test", score=0.05,
            ),
        ]
        issues = assembler._build_issues(items)
        assert len(issues) == 1
        assert issues[0].type == "low_confidence"

    def test_no_issue_when_good_scores(self):
        from agent_serving.serving.application.assembler import ContextAssembler
        from agent_serving.serving.schemas.models import ContextItem
        from unittest.mock import MagicMock

        assembler = ContextAssembler(MagicMock(), MagicMock())

        items = [
            ContextItem(
                id="ru-1", kind="retrieval_unit", role="seed",
                text="test", score=0.85,
            ),
        ]
        issues = assembler._build_issues(items)
        assert len(issues) == 0
