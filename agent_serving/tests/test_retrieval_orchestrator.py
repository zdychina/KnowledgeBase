"""Tests for RetrievalOrchestrator — verifies full query semantics passthrough."""
from unittest.mock import AsyncMock, MagicMock

import pytest

from agent_serving.serving.pipeline.retrieval_orchestrator import (
    OrchestratorResult,
    RetrievalOrchestrator,
    RouteTrace,
)
from agent_serving.serving.schemas.constants import (
    ROUTE_DENSE_VECTOR,
    ROUTE_ENTITY_EXACT,
    ROUTE_LEXICAL_BM25,
)
from agent_serving.serving.schemas.models import (
    EntityRef,
    QueryUnderstanding,
    RetrievalCandidate,
    RetrievalQuery,
    RetrievalRoutePlan,
    RouteConfig,
    SubQuery,
)


def _make_understanding(**overrides) -> QueryUnderstanding:
    defaults = dict(
        original_query="如何配置SMF切片",
        intent="procedure",
        keywords=["SMF", "切片", "配置"],
        entities=[EntityRef(type="product", name="SMF", normalized_name="smf")],
        sub_queries=[SubQuery(text="SMF切片配置步骤")],
        scope={"domain": "cloud_core_network"},
    )
    defaults.update(overrides)
    return QueryUnderstanding(**defaults)


def _make_route_plan(routes: list[RouteConfig] | None = None) -> RetrievalRoutePlan:
    if routes is None:
        routes = [
            RouteConfig(name=ROUTE_LEXICAL_BM25, enabled=True, top_k=20),
            RouteConfig(name=ROUTE_ENTITY_EXACT, enabled=True, top_k=10),
            RouteConfig(name=ROUTE_DENSE_VECTOR, enabled=True, top_k=15),
        ]
    return RetrievalRoutePlan(routes=routes)


def _make_candidate(
    retrieval_unit_id: str = "ru-001",
    score: float = 0.9,
    source: str = "lexical_bm25",
) -> RetrievalCandidate:
    return RetrievalCandidate(
        retrieval_unit_id=retrieval_unit_id,
        score=score,
        source=source,
    )


def _mock_retriever(return_value=None, side_effect=None) -> MagicMock:
    """Create a mock retriever with an async .retrieve() method.

    The orchestrator calls retriever.retrieve(query, snapshot_ids, top_k=...),
    so we need to mock the .retrieve attribute, not the mock itself.
    """
    mock = MagicMock()
    mock.retrieve = AsyncMock(
        return_value=return_value if return_value is not None else [],
        side_effect=side_effect,
    )
    return mock


class TestKeywordsReachBm25:
    """Keywords from QueryUnderstanding reach the BM25 retriever."""

    @pytest.mark.asyncio
    async def test_keywords_passed(self):
        bm25 = _mock_retriever(return_value=[_make_candidate(source=ROUTE_LEXICAL_BM25)])
        entity = _mock_retriever()
        dense = _mock_retriever()

        orchestrator = RetrievalOrchestrator({
            ROUTE_LEXICAL_BM25: bm25,
            ROUTE_ENTITY_EXACT: entity,
            ROUTE_DENSE_VECTOR: dense,
        })

        understanding = _make_understanding()
        route_plan = _make_route_plan()
        result = await orchestrator.execute(
            understanding, route_plan,
            query_embedding=[0.1, 0.2],
            snapshot_ids=["snap-1"],
        )

        call_query: RetrievalQuery = bm25.retrieve.call_args[0][0]
        assert call_query.keywords == ["SMF", "切片", "配置"]
        assert call_query.original_query == "如何配置SMF切片"


class TestEntitiesReachEntityRetriever:
    """Entities from QueryUnderstanding reach the entity retriever."""

    @pytest.mark.asyncio
    async def test_entities_passed(self):
        bm25 = _mock_retriever()
        entity = _mock_retriever(
            return_value=[_make_candidate(retrieval_unit_id="ru-e1", source=ROUTE_ENTITY_EXACT)]
        )
        dense = _mock_retriever()

        orchestrator = RetrievalOrchestrator({
            ROUTE_LEXICAL_BM25: bm25,
            ROUTE_ENTITY_EXACT: entity,
            ROUTE_DENSE_VECTOR: dense,
        })

        understanding = _make_understanding()
        route_plan = _make_route_plan()
        result = await orchestrator.execute(
            understanding, route_plan,
            query_embedding=[0.1, 0.2],
            snapshot_ids=["snap-1"],
        )

        call_query: RetrievalQuery = entity.retrieve.call_args[0][0]
        assert len(call_query.entities) == 1
        assert call_query.entities[0].name == "SMF"
        assert call_query.entities[0].type == "product"


class TestDenseSkippedWithoutEmbedding:
    """Dense vector route is auto-skipped when no embedding is provided."""

    @pytest.mark.asyncio
    async def test_dense_skipped(self):
        bm25 = _mock_retriever(return_value=[_make_candidate(source=ROUTE_LEXICAL_BM25)])
        entity = _mock_retriever()
        dense = _mock_retriever()

        orchestrator = RetrievalOrchestrator({
            ROUTE_LEXICAL_BM25: bm25,
            ROUTE_ENTITY_EXACT: entity,
            ROUTE_DENSE_VECTOR: dense,
        })

        understanding = _make_understanding()
        route_plan = _make_route_plan()
        result = await orchestrator.execute(
            understanding, route_plan,
            query_embedding=None,
            snapshot_ids=["snap-1"],
        )

        # Dense retriever should NOT be called
        dense.retrieve.assert_not_called()

        # Trace should show skip
        dense_trace = next(t for t in result.route_traces if t.name == ROUTE_DENSE_VECTOR)
        assert dense_trace.attempted is False
        assert dense_trace.skipped_reason == "no_embedding"

        # BM25 and entity should still be called
        bm25.retrieve.assert_called_once()
        entity.retrieve.assert_called_once()


class TestTopKFromRouteConfig:
    """top_k from route config is passed correctly to each retriever."""

    @pytest.mark.asyncio
    async def test_top_k_passed(self):
        bm25 = _mock_retriever(return_value=[_make_candidate(source=ROUTE_LEXICAL_BM25)])
        entity = _mock_retriever()
        dense = _mock_retriever()

        orchestrator = RetrievalOrchestrator({
            ROUTE_LEXICAL_BM25: bm25,
            ROUTE_ENTITY_EXACT: entity,
            ROUTE_DENSE_VECTOR: dense,
        })

        route_plan = _make_route_plan(routes=[
            RouteConfig(name=ROUTE_LEXICAL_BM25, enabled=True, top_k=42),
            RouteConfig(name=ROUTE_ENTITY_EXACT, enabled=True, top_k=7),
            RouteConfig(name=ROUTE_DENSE_VECTOR, enabled=True, top_k=99),
        ])

        understanding = _make_understanding()
        result = await orchestrator.execute(
            understanding, route_plan,
            query_embedding=[0.1, 0.2],
            snapshot_ids=["snap-1"],
        )

        # Check top_k passed as keyword arg
        assert bm25.retrieve.call_args[1]["top_k"] == 42
        assert entity.retrieve.call_args[1]["top_k"] == 7
        assert dense.retrieve.call_args[1]["top_k"] == 99


class TestEmptySnapshotIdsReturnsEmpty:
    """Empty snapshot_ids returns an empty result immediately."""

    @pytest.mark.asyncio
    async def test_empty_snapshots(self):
        bm25 = _mock_retriever()
        entity = _mock_retriever()
        dense = _mock_retriever()

        orchestrator = RetrievalOrchestrator({
            ROUTE_LEXICAL_BM25: bm25,
            ROUTE_ENTITY_EXACT: entity,
            ROUTE_DENSE_VECTOR: dense,
        })

        understanding = _make_understanding()
        route_plan = _make_route_plan()
        result = await orchestrator.execute(
            understanding, route_plan,
            query_embedding=[0.1, 0.2],
            snapshot_ids=[],
        )

        assert result.candidates == []
        assert result.route_traces == []
        bm25.retrieve.assert_not_called()
        entity.retrieve.assert_not_called()
        dense.retrieve.assert_not_called()


class TestFailedRetrieverDoesNotCrash:
    """A retriever that raises does not crash the orchestrator."""

    @pytest.mark.asyncio
    async def test_retriever_failure_handled(self):
        bm25 = _mock_retriever(side_effect=RuntimeError("index corrupted"))
        entity = _mock_retriever(
            return_value=[_make_candidate(retrieval_unit_id="ru-e1", source=ROUTE_ENTITY_EXACT)]
        )
        dense = _mock_retriever()

        orchestrator = RetrievalOrchestrator({
            ROUTE_LEXICAL_BM25: bm25,
            ROUTE_ENTITY_EXACT: entity,
            ROUTE_DENSE_VECTOR: dense,
        })

        understanding = _make_understanding()
        route_plan = _make_route_plan()
        result = await orchestrator.execute(
            understanding, route_plan,
            query_embedding=[0.1, 0.2],
            snapshot_ids=["snap-1"],
        )

        # Should have candidates from entity route
        assert len(result.candidates) >= 1

        # BM25 trace should show failure
        bm25_trace = next(t for t in result.route_traces if t.name == ROUTE_LEXICAL_BM25)
        assert bm25_trace.attempted is True
        assert bm25_trace.candidate_count == 0
        assert "index corrupted" in bm25_trace.skipped_reason

        # Entity trace should show success
        entity_trace = next(t for t in result.route_traces if t.name == ROUTE_ENTITY_EXACT)
        assert entity_trace.attempted is True
        assert entity_trace.candidate_count == 1


class TestSourceNormalization:
    """Candidate source is normalized to the canonical route name."""

    @pytest.mark.asyncio
    async def test_source_overridden(self):
        # Retriever returns candidates with wrong source
        bm25 = _mock_retriever(
            return_value=[_make_candidate(retrieval_unit_id="ru-1", source="wrong_source")]
        )
        entity = _mock_retriever()
        dense = _mock_retriever()

        orchestrator = RetrievalOrchestrator({
            ROUTE_LEXICAL_BM25: bm25,
            ROUTE_ENTITY_EXACT: entity,
            ROUTE_DENSE_VECTOR: dense,
        })

        understanding = _make_understanding()
        route_plan = _make_route_plan()
        result = await orchestrator.execute(
            understanding, route_plan,
            query_embedding=[0.1, 0.2],
            snapshot_ids=["snap-1"],
        )

        assert result.candidates[0].source == ROUTE_LEXICAL_BM25


class TestSubQueriesPassed:
    """Sub-queries from understanding are extracted and passed in RetrievalQuery."""

    @pytest.mark.asyncio
    async def test_sub_queries(self):
        bm25 = _mock_retriever(return_value=[_make_candidate(source=ROUTE_LEXICAL_BM25)])
        entity = _mock_retriever()
        dense = _mock_retriever()

        orchestrator = RetrievalOrchestrator({
            ROUTE_LEXICAL_BM25: bm25,
            ROUTE_ENTITY_EXACT: entity,
            ROUTE_DENSE_VECTOR: dense,
        })

        understanding = _make_understanding(
            sub_queries=[
                SubQuery(text="SMF切片配置步骤"),
                SubQuery(text="SMF网络切片管理"),
            ]
        )
        route_plan = _make_route_plan()
        result = await orchestrator.execute(
            understanding, route_plan,
            query_embedding=[0.1, 0.2],
            snapshot_ids=["snap-1"],
        )

        call_query: RetrievalQuery = bm25.retrieve.call_args[0][0]
        assert call_query.sub_queries == ["SMF切片配置步骤", "SMF网络切片管理"]


class TestUnregisteredRouteSkipped:
    """Routes without a registered retriever are auto-skipped."""

    @pytest.mark.asyncio
    async def test_unregistered_skipped(self):
        bm25 = _mock_retriever(return_value=[_make_candidate(source=ROUTE_LEXICAL_BM25)])

        # Only BM25 registered, but route plan includes entity and dense
        orchestrator = RetrievalOrchestrator({
            ROUTE_LEXICAL_BM25: bm25,
        })

        understanding = _make_understanding()
        route_plan = _make_route_plan()
        result = await orchestrator.execute(
            understanding, route_plan,
            query_embedding=[0.1, 0.2],
            snapshot_ids=["snap-1"],
        )

        # BM25 should succeed
        assert len(result.candidates) == 1

        # Entity should show not_registered (no retriever registered)
        entity_trace = next(t for t in result.route_traces if t.name == ROUTE_ENTITY_EXACT)
        assert entity_trace.attempted is False
        assert entity_trace.skipped_reason == "not_registered"

        # Dense has an embedding so it would be attempted, but no retriever registered
        dense_trace = next(t for t in result.route_traces if t.name == ROUTE_DENSE_VECTOR)
        assert dense_trace.attempted is False
        assert dense_trace.skipped_reason == "not_registered"


class TestDisabledRouteSkipped:
    """Disabled routes in the route plan are not executed."""

    @pytest.mark.asyncio
    async def test_disabled_route(self):
        bm25 = _mock_retriever(return_value=[_make_candidate(source=ROUTE_LEXICAL_BM25)])
        entity = _mock_retriever()

        orchestrator = RetrievalOrchestrator({
            ROUTE_LEXICAL_BM25: bm25,
            ROUTE_ENTITY_EXACT: entity,
        })

        route_plan = _make_route_plan(routes=[
            RouteConfig(name=ROUTE_LEXICAL_BM25, enabled=True, top_k=20),
            RouteConfig(name=ROUTE_ENTITY_EXACT, enabled=False, top_k=10),
        ])

        understanding = _make_understanding()
        result = await orchestrator.execute(
            understanding, route_plan,
            query_embedding=None,
            snapshot_ids=["snap-1"],
        )

        # Only BM25 should be called
        bm25.retrieve.assert_called_once()
        entity.retrieve.assert_not_called()

        # No trace for disabled route
        assert not any(t.name == ROUTE_ENTITY_EXACT for t in result.route_traces)


class TestIntentAndScopePassed:
    """Intent and scope from understanding are carried through to RetrievalQuery."""

    @pytest.mark.asyncio
    async def test_intent_scope(self):
        bm25 = _mock_retriever(return_value=[_make_candidate(source=ROUTE_LEXICAL_BM25)])

        orchestrator = RetrievalOrchestrator({
            ROUTE_LEXICAL_BM25: bm25,
        })

        route_plan = _make_route_plan(routes=[
            RouteConfig(name=ROUTE_LEXICAL_BM25, enabled=True, top_k=20),
        ])

        understanding = _make_understanding(
            intent="troubleshooting",
            scope={"domain": "cloud_core_network", "product": "SMF"},
        )
        result = await orchestrator.execute(
            understanding, route_plan,
            query_embedding=None,
            snapshot_ids=["snap-1"],
        )

        call_query: RetrievalQuery = bm25.retrieve.call_args[0][0]
        assert call_query.intent == "troubleshooting"
        assert call_query.scope["domain"] == "cloud_core_network"
        assert call_query.scope["product"] == "SMF"
