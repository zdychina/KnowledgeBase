"""LLMReranker — LLM-based listwise reranking.

Calls ServingLlmClient with a listwise prompt: query + top-N candidates
→ relevance ranking. Falls back gracefully when LLM is unavailable.
"""
from __future__ import annotations

import logging
from typing import Any

from agent_serving.serving.schemas.models import (
    QueryUnderstanding,
    RetrievalCandidate,
)

logger = logging.getLogger(__name__)


class LLMReranker:
    """Listwise LLM reranker with automatic fallback."""

    def __init__(self, llm_client: Any = None) -> None:
        self._llm = llm_client

    async def rerank(
        self,
        candidates: list[RetrievalCandidate],
        understanding: QueryUnderstanding | None = None,
    ) -> list[RetrievalCandidate] | None:
        """Rerank candidates via LLM listwise judgment."""
        if not candidates or not self._llm or not self._llm.is_available():
            return None

        try:
            return await self._try_llm_rerank(candidates, understanding)
        except Exception:
            logger.warning("LLM rerank failed", exc_info=True)
            return None

    async def _try_llm_rerank(
        self,
        candidates: list[RetrievalCandidate],
        understanding: QueryUnderstanding | None,
    ) -> list[RetrievalCandidate]:
        """Execute LLM reranking."""
        top_n = candidates[:20]
        items_text = []
        for i, c in enumerate(top_n):
            text_preview = c.metadata.get("text", "")[:200]
            title = c.metadata.get("title", "")
            items_text.append(f"[{i}] (score={c.score:.3f}) {title}: {text_preview}")

        query = understanding.original_query if understanding else ""

        result = await self._llm.execute(
            pipeline_stage="reranker",
            template_key="serving-reranker",
            input={
                "query": query,
                "candidates": "\n".join(items_text),
                "count": len(top_n),
            },
            expected_output_type="json_object",
        )

        if not result:
            raise ValueError("Empty LLM rerank response")

        inner = result.get("result", result) if isinstance(result, dict) else {}
        parsed = inner.get("parsed_output", {})
        if not parsed:
            raise ValueError("Empty LLM rerank response")

        ranking = parsed.get("ranking", [])
        if not ranking:
            raise ValueError("No ranking in LLM rerank response")

        indexed = {i: c for i, c in enumerate(top_n)}
        reordered: list[RetrievalCandidate] = []

        for item in ranking:
            idx = item.get("index", -1) if isinstance(item, dict) else -1
            if idx in indexed:
                c = indexed.pop(idx)
                new_score = item.get("score", c.score) if isinstance(item, dict) else c.score
                reordered.append(c.model_copy(update={"score": float(new_score)}))

        for c in indexed.values():
            reordered.append(c)

        reordered.extend(candidates[20:])

        return reordered
