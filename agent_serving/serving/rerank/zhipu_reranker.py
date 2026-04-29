"""ZhipuReranker — calls Zhipu rerank API for cross-encoder reranking.

Uses Zhipu's dedicated rerank model to reorder candidates by relevance.
Same API key as embedding (EMBEDDING_API_KEY).

API spec:
  POST /paas/v4/rerank
  Body: {model: "rerank", query: str, documents: str[], top_n: int}
  Response: {results: [{index: int, relevance_score: float, document: {...}}]}
"""
from __future__ import annotations

import logging

import httpx

from agent_serving.serving.schemas.models import (
    QueryPlan,
    QueryUnderstanding,
    RetrievalCandidate,
)

logger = logging.getLogger(__name__)


class ZhipuReranker:
    """Zhipu rerank API client for relevance-based candidate reordering."""

    def __init__(
        self,
        api_key: str,
        *,
        base_url: str = "https://open.bigmodel.cn/api/paas/v4",
        model: str = "rerank",
        top_n: int = 20,
        timeout: int = 30,
    ) -> None:
        self._api_key = api_key
        self._base_url = base_url.rstrip("/")
        self._model = model
        self._top_n = top_n
        self._timeout = timeout

    async def rerank(
        self,
        candidates: list[RetrievalCandidate],
        plan: QueryPlan,
        understanding: QueryUnderstanding | None = None,
    ) -> list[RetrievalCandidate] | None:
        """Rerank candidates via Zhipu rerank API. Returns None on failure."""
        if not candidates:
            return None

        query = understanding.original_query if understanding else " ".join(plan.keywords)
        if not query:
            return None

        # Build documents from candidate texts
        top_n = min(self._top_n, len(candidates))
        working_set = candidates[:top_n]
        documents = []
        for c in working_set:
            text = c.metadata.get("text", "")
            title = c.metadata.get("title", "")
            doc = f"{title}: {text}" if title else text
            documents.append(doc[:1000])

        try:
            results = await self._call_api(query, documents)
        except Exception:
            logger.warning("Zhipu rerank API call failed", exc_info=True)
            return None

        if not results:
            return None

        # Reorder candidates based on rerank results
        reordered: list[RetrievalCandidate] = []
        seen_indices: set[int] = set()
        for item in results:
            idx = item.get("index", -1)
            if 0 <= idx < len(working_set) and idx not in seen_indices:
                seen_indices.add(idx)
                c = working_set[idx]
                score = item.get("relevance_score", c.score)
                reordered.append(c.model_copy(update={"score": float(score)}))

        # Append any candidates not returned by the API
        for idx, c in enumerate(working_set):
            if idx not in seen_indices:
                reordered.append(c)

        # Append remaining candidates beyond top_n
        reordered.extend(candidates[top_n:])

        return reordered

    async def _call_api(
        self,
        query: str,
        documents: list[str],
    ) -> list[dict]:
        """Call Zhipu rerank API."""
        payload = {
            "model": self._model,
            "query": query,
            "documents": documents,
            "top_n": len(documents),
        }
        headers = {
            "Authorization": f"Bearer {self._api_key}",
            "Content-Type": "application/json",
        }

        async with httpx.AsyncClient(timeout=self._timeout) as client:
            resp = await client.post(
                f"{self._base_url}/rerank",
                json=payload,
                headers=headers,
            )
            resp.raise_for_status()
            data = resp.json()

        return data.get("results", [])
