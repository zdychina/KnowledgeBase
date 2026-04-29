"""Tests for RerankPipeline."""
import pytest

from agent_serving.serving.schemas.models import (
    QueryPlan,
    QueryUnderstanding,
    RetrievalCandidate,
    RetrievalRoutePlan,
    RerankConfig,
    ScoreChain,
)
from agent_serving.serving.pipeline.reranker import ScoreReranker
from agent_serving.serving.rerank.pipeline import RerankPipeline


def _candidate(ru_id, score, source="fts_bm25"):
    return RetrievalCandidate(
        retrieval_unit_id=ru_id, score=score, source=source,
        metadata={"semantic_role": "parameter"},
        score_chain=ScoreChain(raw_score=score, route_sources=[source]),
    )


class TestRerankPipeline:
    @pytest.mark.asyncio
    async def test_score_reranker_fallback(self):
        pipeline = RerankPipeline()
        candidates = [_candidate("a", 0.9), _candidate("b", 0.5)]
        plan = QueryPlan(budget={"max_items": 1})
        result = await pipeline.rerank(candidates, plan)
        assert len(result) == 1
        assert result[0].retrieval_unit_id == "a"

    @pytest.mark.asyncio
    async def test_score_chain_annotated(self):
        pipeline = RerankPipeline()
        candidates = [_candidate("a", 0.9)]
        result = await pipeline.rerank(candidates, QueryPlan())
        assert result[0].score_chain is not None
        assert result[0].score_chain.rerank_score > 0

    @pytest.mark.asyncio
    async def test_empty_candidates(self):
        pipeline = RerankPipeline()
        result = await pipeline.rerank([], QueryPlan())
        assert result == []

    @pytest.mark.asyncio
    async def test_cascade_falls_back_to_score(self):
        """When method=cascade but no LLM reranker, falls back to score."""
        pipeline = RerankPipeline(llm_reranker=None)
        candidates = [_candidate("a", 0.9), _candidate("b", 0.5)]
        route_plan = RetrievalRoutePlan(
            rerank=RerankConfig(method="cascade"),
        )
        result = await pipeline.rerank(
            candidates, QueryPlan(), route_plan=route_plan,
        )
        assert len(result) == 2
        assert result[0].retrieval_unit_id == "a"

    @pytest.mark.asyncio
    async def test_with_understanding(self):
        pipeline = RerankPipeline()
        understanding = QueryUnderstanding(
            original_query="test", intent="general",
        )
        candidates = [_candidate("a", 0.9)]
        result = await pipeline.rerank(
            candidates, QueryPlan(), understanding=understanding,
        )
        assert len(result) == 1
