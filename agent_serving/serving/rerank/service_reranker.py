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

    def __init__(
        self,
        llm_client,
        *,
        model: str = "rerank",
        top_n: int = 20,
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
        documents = []
        for candidate in working_set:
            text = candidate.metadata.get("text", "")
            title = candidate.metadata.get("title", "")
            documents.append(f"{title}: {text}" if title else text)

        try:
            response = await self._llm_client.rerank(
                query=query,
                documents=[doc[:1000] for doc in documents],
                model=self._model,
                top_n=len(documents),
            )
        except Exception:
            logger.warning("LLM service rerank call failed", exc_info=True)
            return None

        if not response or not response.get("results"):
            return None

        reordered: list[RetrievalCandidate] = []
        seen_indices: set[int] = set()
        for item in response["results"]:
            idx = item.get("index", -1)
            if 0 <= idx < len(working_set) and idx not in seen_indices:
                seen_indices.add(idx)
                candidate = working_set[idx]
                score = item.get("relevance_score", candidate.score)
                reordered.append(candidate.model_copy(update={"score": float(score)}))

        for idx, candidate in enumerate(working_set):
            if idx not in seen_indices:
                reordered.append(candidate)

        reordered.extend(candidates[top_n:])
        return reordered
