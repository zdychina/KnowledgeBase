"""RerankPipeline — cascading rerank strategies with real trace.

Strategy chain: ModelReranker (Zhipu) → LLMReranker → ScoreReranker (fallback)
Each step records provider, timing, candidate counts, and fallback reason.
"""
from __future__ import annotations

import logging
import time

from agent_serving.serving.schemas.models import (
    QueryUnderstanding,
    RetrievalCandidate,
    RetrievalRoutePlan,
    RerankTraceStep,
    ScoreChain,
)
from agent_serving.serving.pipeline.reranker import ScoreReranker

logger = logging.getLogger(__name__)


class RerankPipeline:
    """Cascading rerank pipeline: model → LLM → score fallback.

    Returns (reranked_candidates, trace_steps) for full observability.
    """

    def __init__(
        self,
        model_reranker=None,
        llm_reranker=None,
        score_reranker=None,
    ) -> None:
        self._model_reranker = model_reranker
        self._llm_reranker = llm_reranker
        self._score_reranker = score_reranker or ScoreReranker()

    async def rerank(
        self,
        candidates: list[RetrievalCandidate],
        route_plan: RetrievalRoutePlan | None = None,
        understanding: QueryUnderstanding | None = None,
    ) -> tuple[list[RetrievalCandidate], list[RerankTraceStep]]:
        """Rerank candidates using cascading strategies with real trace."""
        if not candidates:
            return [], []

        trace: list[RerankTraceStep] = []
        count_before = len(candidates)

        # 1. Try model-based reranker (Zhipu rerank) if available
        if self._model_reranker:
            step = RerankTraceStep(
                provider="model", attempted=True, count_before=count_before,
            )
            t0 = time.perf_counter()
            try:
                result = await self._model_reranker.rerank(
                    candidates, understanding,
                )
                step.latency_ms = (time.perf_counter() - t0) * 1000
                if result:
                    step.succeeded = True
                    step.count_after = len(result)
                    trace.append(step)
                    return self._annotate_rerank_scores(result), trace
                step.fallback_reason = "model_reranker returned empty"
            except Exception as exc:
                step.latency_ms = (time.perf_counter() - t0) * 1000
                step.fallback_reason = str(exc)[:200]
                logger.warning("Model reranker failed: %s", exc)
            trace.append(step)

        # 2. Try LLM reranker if route plan allows
        method = "score"
        if route_plan:
            method = route_plan.rerank.method

        if method in ("llm", "cascade") and self._llm_reranker:
            step = RerankTraceStep(
                provider="llm", attempted=True, count_before=count_before,
            )
            t0 = time.perf_counter()
            try:
                result = await self._llm_reranker.rerank(
                    candidates, understanding,
                )
                step.latency_ms = (time.perf_counter() - t0) * 1000
                if result:
                    step.succeeded = True
                    step.count_after = len(result)
                    trace.append(step)
                    return self._annotate_rerank_scores(result), trace
                step.fallback_reason = "llm_reranker returned empty"
            except Exception as exc:
                step.latency_ms = (time.perf_counter() - t0) * 1000
                step.fallback_reason = str(exc)[:200]
                logger.warning("LLM reranker failed: %s", exc)
            trace.append(step)

        # 3. Score-based fallback (always succeeds)
        step = RerankTraceStep(
            provider="score", attempted=True, count_before=count_before,
        )
        t0 = time.perf_counter()
        result = await self._score_reranker.rerank(candidates, route_plan=route_plan)
        step.latency_ms = (time.perf_counter() - t0) * 1000
        step.succeeded = True
        step.count_after = len(result)
        trace.append(step)
        return self._annotate_rerank_scores(result), trace

    def _annotate_rerank_scores(
        self,
        candidates: list[RetrievalCandidate],
    ) -> list[RetrievalCandidate]:
        """Update each candidate's score_chain with rerank_score."""
        result = []
        for c in candidates:
            chain = c.score_chain or ScoreChain(
                raw_score=c.score,
                route_sources=[c.source],
            )
            chain = chain.model_copy(update={"rerank_score": c.score})
            result.append(c.model_copy(update={"score_chain": chain}))
        return result
