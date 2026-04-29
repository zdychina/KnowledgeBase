"""RerankPipeline — cascading rerank strategies.

Strategy chain: ModelReranker (Zhipu) → LLMReranker → ScoreReranker (fallback)
Each strategy updates candidate.score_chain.rerank_score.
Route plan controls which strategy is preferred.
"""
from __future__ import annotations

import logging

from agent_serving.serving.schemas.models import (
    QueryPlan,
    QueryUnderstanding,
    RetrievalCandidate,
    RetrievalRoutePlan,
    ScoreChain,
)
from agent_serving.serving.pipeline.reranker import ScoreReranker

logger = logging.getLogger(__name__)


class RerankPipeline:
    """Cascading rerank pipeline: model → LLM → score fallback."""

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
        plan: QueryPlan,
        route_plan: RetrievalRoutePlan | None = None,
        understanding: QueryUnderstanding | None = None,
    ) -> list[RetrievalCandidate]:
        """Rerank candidates using cascading strategies."""
        if not candidates:
            return []

        # 1. Try model-based reranker (Zhipu rerank) if available
        if self._model_reranker:
            try:
                result = await self._model_reranker.rerank(
                    candidates, plan, understanding,
                )
                if result:
                    return self._annotate_rerank_scores(result)
            except Exception:
                logger.warning("Model reranker failed, trying next strategy", exc_info=True)

        # 2. Try LLM reranker if route plan allows
        method = "score"
        if route_plan:
            method = route_plan.rerank.method

        if method in ("llm", "cascade") and self._llm_reranker:
            try:
                result = await self._llm_reranker.rerank(
                    candidates, plan, understanding,
                )
                if result:
                    return self._annotate_rerank_scores(result)
            except Exception:
                logger.warning("LLM reranker failed, falling back to score", exc_info=True)

        # 3. Score-based fallback
        result = await self._score_reranker.rerank(candidates, plan)
        return self._annotate_rerank_scores(result)

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
