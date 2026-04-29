"""Tests for WeightedRRFFusion."""
import pytest

from agent_serving.serving.schemas.models import (
    QueryPlan,
    RetrievalCandidate,
    RetrievalRoutePlan,
    RouteConfig,
    ScoreChain,
)
from agent_serving.serving.pipeline.fusion import WeightedRRFFusion


def _candidate(ru_id, score, source="fts_bm25"):
    return RetrievalCandidate(
        retrieval_unit_id=ru_id, score=score, source=source,
        metadata={},
        score_chain=ScoreChain(raw_score=score, route_sources=[source]),
    )


class TestWeightedRRFFusion:
    @pytest.mark.asyncio
    async def test_multi_source_weighted_fusion(self):
        fusion = WeightedRRFFusion(k=60)
        route_plan = RetrievalRoutePlan(
            routes=[
                RouteConfig(name="fts_bm25", weight=1.0),
                RouteConfig(name="entity_exact", weight=1.4),
            ],
        )
        candidates = [
            _candidate("a", 0.9, "fts_bm25"),
            _candidate("a", 0.8, "entity_exact"),
            _candidate("b", 0.7, "fts_bm25"),
            _candidate("c", 0.6, "entity_exact"),
        ]
        result = await fusion.fuse(candidates, QueryPlan(), route_plan)
        # "a" appears in both sources, should rank highest
        assert result[0].retrieval_unit_id == "a"

    @pytest.mark.asyncio
    async def test_weight_increases_score(self):
        fusion = WeightedRRFFusion(k=60)
        route_plan = RetrievalRoutePlan(
            routes=[
                RouteConfig(name="source_a", weight=1.0),
                RouteConfig(name="source_b", weight=2.0),
            ],
        )
        # b only in source_b (weight 2.0), a only in source_a (weight 1.0)
        candidates = [
            _candidate("a", 0.9, "source_a"),
            _candidate("b", 0.9, "source_b"),
        ]
        result = await fusion.fuse(candidates, QueryPlan(), route_plan)
        # source_b has higher weight, so "b" should rank higher
        assert result[0].retrieval_unit_id == "b"

    @pytest.mark.asyncio
    async def test_score_chain_updated(self):
        fusion = WeightedRRFFusion(k=60)
        route_plan = RetrievalRoutePlan(
            routes=[RouteConfig(name="fts_bm25", weight=1.0)],
        )
        candidates = [_candidate("a", 0.9, "fts_bm25")]
        result = await fusion.fuse(candidates, QueryPlan(), route_plan)
        assert result[0].score_chain is not None
        assert result[0].score_chain.fusion_score > 0
        assert "fts_bm25" in result[0].score_chain.route_sources

    @pytest.mark.asyncio
    async def test_empty_candidates(self):
        fusion = WeightedRRFFusion()
        result = await fusion.fuse([], QueryPlan())
        assert result == []

    @pytest.mark.asyncio
    async def test_route_sources_aggregation(self):
        fusion = WeightedRRFFusion(k=60)
        route_plan = RetrievalRoutePlan(
            routes=[
                RouteConfig(name="source_a", weight=1.0),
                RouteConfig(name="source_b", weight=1.0),
            ],
        )
        candidates = [
            _candidate("x", 0.9, "source_a"),
            _candidate("x", 0.8, "source_b"),
        ]
        result = await fusion.fuse(candidates, QueryPlan(), route_plan)
        # "x" appears in both sources
        assert "source_a" in result[0].score_chain.route_sources
        assert "source_b" in result[0].score_chain.route_sources

    @pytest.mark.asyncio
    async def test_no_route_plan(self):
        fusion = WeightedRRFFusion(k=60)
        candidates = [_candidate("a", 0.9, "fts")]
        result = await fusion.fuse(candidates, QueryPlan(), route_plan=None)
        assert len(result) == 1
