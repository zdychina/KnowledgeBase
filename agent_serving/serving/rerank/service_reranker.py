"""LLMServiceReranker — rerank via shared llm_service model endpoint."""
from __future__ import annotations

import logging

from agent_serving.serving.schemas.models import (
    QueryPlan,
    QueryUnderstanding,
    RetrievalCandidate,
)

logger = logging.getLogger(__name__)


class LLMServiceReranker:
    """Shared model reranker backed by llm_service /api/v1/models/rerank."""

    # llm_service RerankRequest.documents max_length=200
    _MAX_RERANK_DOCS = 200
    # Max chars per document sent to rerank API
    _MAX_DOC_CHARS = 1000

    def __init__(
        self,
        llm_client,
        *,
        model: str = "rerank",
        top_n: int = 100,
    ) -> None:
        self._llm_client = llm_client
        self._model = model
        self._top_n = top_n

    async def rerank(
        self,
        candidates: list[RetrievalCandidate],
        plan: QueryPlan,
        understanding: QueryUnderstanding | None = None,
    ) -> list[RetrievalCandidate] | None:
        if not candidates or self._llm_client is None:
            return None

        query = understanding.original_query if understanding else " ".join(plan.keywords)
        if not query:
            return None

        top_n = min(self._top_n, len(candidates))
        working_set = candidates[:top_n]

        # Batch rerank to respect API limit
        result = await self._rerank_batched(query, working_set)
        return result

    async def _rerank_batched(
        self,
        query: str,
        candidates: list[RetrievalCandidate],
    ) -> list[RetrievalCandidate] | None:
        """Rerank in batches if candidates exceed API limit, then merge by score."""
        if len(candidates) <= self._MAX_RERANK_DOCS:
            return await self._rerank_single(query, candidates)

        # Split into batches and rerank each
        all_scored: list[tuple[float, RetrievalCandidate]] = []
        for i in range(0, len(candidates), self._MAX_RERANK_DOCS):
            batch = candidates[i:i + self._MAX_RERANK_DOCS]
            batch_result = await self._rerank_single(query, batch)
            if batch_result is None:
                return None
            for c in batch_result:
                all_scored.append((c.score, c))

        # Sort all by score descending
        all_scored.sort(key=lambda x: x[0], reverse=True)
        return [c for _, c in all_scored]

    async def _rerank_single(
        self,
        query: str,
        candidates: list[RetrievalCandidate],
    ) -> list[RetrievalCandidate] | None:
        """Single rerank API call."""
        documents = []
        for candidate in candidates:
            text = candidate.metadata.get("text", "")
            title = candidate.metadata.get("title", "")
            documents.append(f"{title}: {text}" if title else text)

        try:
            response = await self._llm_client.rerank(
                query=query,
                documents=[doc[:self._MAX_DOC_CHARS] for doc in documents],
                model=self._model,
                top_n=len(documents),
            )
        except Exception:
            logger.warning("LLM service rerank call failed", exc_info=True)
            return None

        if not response or not response.get("results"):
            return None

        # Only return candidates that received rerank scores, sorted by relevance
        reordered: list[RetrievalCandidate] = []
        seen_indices: set[int] = set()
        for item in response["results"]:
            idx = item.get("index", -1)
            if 0 <= idx < len(candidates) and idx not in seen_indices:
                seen_indices.add(idx)
                candidate = candidates[idx]
                score = item.get("relevance_score", candidate.score)
                reordered.append(candidate.model_copy(update={"score": float(score)}))

        return reordered
