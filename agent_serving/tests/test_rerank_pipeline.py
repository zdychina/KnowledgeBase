"""Tests for RerankPipeline — trace-aware cascading rerank."""
import pytest

from agent_serving.serving.schemas.models import (
    QueryPlan,
    QueryUnderstanding,
    RetrievalCandidate,
    RetrievalRoutePlan,
    RerankConfig,
    RerankTraceStep,
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


class TestRerankPipelineTrace:
    """Tests verifying RerankPipeline returns (candidates, trace) tuple."""

    @pytest.mark.asyncio
    async def test_returns_tuple(self):
        """rerank() returns a (list, list[RerankTraceStep]) tuple."""
        pipeline = RerankPipeline()
        candidates = [_candidate("a", 0.9), _candidate("b", 0.5)]
        result = await pipeline.rerank(candidates)
        assert isinstance(result, tuple)
        assert len(result) == 2
        ranked, trace = result
        assert isinstance(ranked, list)
        assert isinstance(trace, list)

    @pytest.mark.asyncio
    async def test_score_reranker_trace(self):
        """Score reranker always succeeds with provider='score'."""
        pipeline = RerankPipeline()
        candidates = [_candidate("a", 0.9), _candidate("b", 0.5)]
        ranked, trace = await pipeline.rerank(candidates)
        assert len(trace) == 1
        step = trace[0]
        assert step.provider == "score"
        assert step.attempted is True
        assert step.succeeded is True
        assert step.count_before == 2
        assert step.count_after == len(ranked)
        assert step.latency_ms >= 0
        assert step.fallback_reason == ""

    @pytest.mark.asyncio
    async def test_score_reranker_truncation(self):
        """Score reranker respects route_plan.assembly.max_items."""
        from agent_serving.serving.schemas.models import AssemblyConfig
        pipeline = RerankPipeline()
        candidates = [_candidate(f"ru-{i}", 0.9 - i * 0.1) for i in range(5)]
        route_plan = RetrievalRoutePlan(
            assembly=AssemblyConfig(max_items=2),
        )
        ranked, trace = await pipeline.rerank(candidates, route_plan=route_plan)
        assert len(ranked) == 2
        assert trace[0].count_after == 2
        assert trace[0].provider == "score"

    @pytest.mark.asyncio
    async def test_empty_candidates(self):
        """Empty candidates returns empty list + empty trace."""
        pipeline = RerankPipeline()
        ranked, trace = await pipeline.rerank([])
        assert ranked == []
        assert trace == []

    @pytest.mark.asyncio
    async def test_cascade_falls_back_to_score(self):
        """When method=cascade but no LLM reranker, falls back to score."""
        pipeline = RerankPipeline(llm_reranker=None)
        candidates = [_candidate("a", 0.9), _candidate("b", 0.5)]
        route_plan = RetrievalRoutePlan(
            rerank=RerankConfig(method="cascade"),
        )
        ranked, trace = await pipeline.rerank(
            candidates, route_plan=route_plan,
        )
        assert len(ranked) == 2
        assert ranked[0].retrieval_unit_id == "a"
        assert len(trace) == 1
        assert trace[0].provider == "score"

    @pytest.mark.asyncio
    async def test_with_understanding(self):
        pipeline = RerankPipeline()
        understanding = QueryUnderstanding(
            original_query="test", intent="general",
        )
        candidates = [_candidate("a", 0.9)]
        ranked, trace = await pipeline.rerank(
            candidates, understanding=understanding,
        )
        assert len(ranked) == 1
        assert len(trace) == 1

    @pytest.mark.asyncio
    async def test_model_reranker_success(self):
        """When model reranker succeeds, trace has provider='model', succeeded=True."""
        from unittest.mock import AsyncMock

        mock_model = AsyncMock()
        mock_model.rerank.return_value = [
            _candidate("a", 0.95),
            _candidate("b", 0.6),
        ]
        pipeline = RerankPipeline(model_reranker=mock_model)
        candidates = [_candidate("a", 0.9), _candidate("b", 0.5)]

        ranked, trace = await pipeline.rerank(candidates)
        assert len(trace) == 1
        assert trace[0].provider == "model"
        assert trace[0].attempted is True
        assert trace[0].succeeded is True
        assert trace[0].count_before == 2
        assert trace[0].count_after == 2
        assert trace[0].latency_ms >= 0

    @pytest.mark.asyncio
    async def test_model_reranker_fails_falls_through(self):
        """When model reranker fails, trace has model step (failed) + score step."""
        from unittest.mock import AsyncMock

        mock_model = AsyncMock()
        mock_model.rerank.side_effect = RuntimeError("API error")

        pipeline = RerankPipeline(model_reranker=mock_model)
        candidates = [_candidate("a", 0.9), _candidate("b", 0.5)]

        ranked, trace = await pipeline.rerank(candidates)
        # Should have 2 trace steps: model (failed) + score (success)
        assert len(trace) == 2
        assert trace[0].provider == "model"
        assert trace[0].attempted is True
        assert trace[0].succeeded is False
        assert "API error" in trace[0].fallback_reason
        assert trace[1].provider == "score"
        assert trace[1].succeeded is True

    @pytest.mark.asyncio
    async def test_model_reranker_returns_empty(self):
        """When model reranker returns empty list, falls through to score."""
        from unittest.mock import AsyncMock

        mock_model = AsyncMock()
        mock_model.rerank.return_value = []

        pipeline = RerankPipeline(model_reranker=mock_model)
        candidates = [_candidate("a", 0.9)]

        ranked, trace = await pipeline.rerank(candidates)
        assert len(trace) == 2
        assert trace[0].provider == "model"
        assert trace[0].succeeded is False
        assert "empty" in trace[0].fallback_reason.lower()
        assert trace[1].provider == "score"
        assert trace[1].succeeded is True

    @pytest.mark.asyncio
    async def test_llm_reranker_success(self):
        """LLM reranker succeeds when route plan allows it."""
        from unittest.mock import AsyncMock

        mock_llm = AsyncMock()
        mock_llm.rerank.return_value = [
            _candidate("b", 0.95),
            _candidate("a", 0.6),
        ]

        pipeline = RerankPipeline(llm_reranker=mock_llm)
        candidates = [_candidate("a", 0.9), _candidate("b", 0.5)]
        route_plan = RetrievalRoutePlan(
            rerank=RerankConfig(method="llm"),
        )

        ranked, trace = await pipeline.rerank(candidates, route_plan=route_plan)
        assert len(trace) == 1
        assert trace[0].provider == "llm"
        assert trace[0].succeeded is True

    @pytest.mark.asyncio
    async def test_llm_reranker_skipped_when_method_score(self):
        """LLM reranker is not attempted when method='score'."""
        from unittest.mock import AsyncMock

        mock_llm = AsyncMock()
        pipeline = RerankPipeline(llm_reranker=mock_llm)
        candidates = [_candidate("a", 0.9)]
        route_plan = RetrievalRoutePlan(
            rerank=RerankConfig(method="score"),
        )

        ranked, trace = await pipeline.rerank(candidates, route_plan=route_plan)
        # Only score step — LLM not attempted
        assert len(trace) == 1
        assert trace[0].provider == "score"
        mock_llm.rerank.assert_not_called()

    @pytest.mark.asyncio
    async def test_score_chain_annotated(self):
        """Each candidate gets rerank_score in score_chain."""
        pipeline = RerankPipeline()
        candidates = [_candidate("a", 0.9)]
        ranked, _ = await pipeline.rerank(candidates)
        assert ranked[0].score_chain is not None
        assert ranked[0].score_chain.rerank_score > 0

    @pytest.mark.asyncio
    async def test_all_three_cascade_steps(self):
        """Full cascade: model fails, LLM fails, score succeeds."""
        from unittest.mock import AsyncMock

        mock_model = AsyncMock()
        mock_model.rerank.side_effect = RuntimeError("model down")

        mock_llm = AsyncMock()
        mock_llm.rerank.side_effect = RuntimeError("llm down")

        pipeline = RerankPipeline(
            model_reranker=mock_model,
            llm_reranker=mock_llm,
        )
        candidates = [_candidate("a", 0.9), _candidate("b", 0.5)]
        route_plan = RetrievalRoutePlan(
            rerank=RerankConfig(method="cascade"),
        )

        ranked, trace = await pipeline.rerank(candidates, route_plan=route_plan)
        assert len(trace) == 3
        assert trace[0].provider == "model"
        assert trace[0].succeeded is False
        assert trace[1].provider == "llm"
        assert trace[1].succeeded is False
        assert trace[2].provider == "score"
        assert trace[2].succeeded is True
        assert len(ranked) == 2
