"""Embedding generator for Serving — pure HTTP, zero Mining import.

Provides:
- EmbeddingGenerator: calls Zhipu AI Embedding-3 API via httpx
- Matches the interface used by Mining's ZhipuEmbeddingGenerator
  (embed, embed_batch) so serving code can use it as a drop-in replacement.
"""
from __future__ import annotations

import logging
from typing import Any

import httpx

logger = logging.getLogger(__name__)


class EmbeddingGenerator:
    """Calls embedding API via HTTP (Zhipu or compatible).

    Falls back to empty list on failure (non-blocking for pipeline).
    """

    def __init__(
        self,
        api_key: str,
        *,
        model: str = "embedding-3",
        base_url: str = "https://open.bigmodel.cn/api/paas/v4",
        dimensions: int = 1024,
        timeout: int = 60,
    ) -> None:
        self._api_key = api_key
        self._model = model
        self._base_url = base_url.rstrip("/")
        self._dimensions = dimensions
        self._timeout = timeout

    @property
    def model_name(self) -> str:
        return self._model

    @property
    def dimensions(self) -> int:
        return self._dimensions

    def embed(self, texts: list[str]) -> list[list[float]]:
        """Call embeddings API. Returns list of float vectors.

        Returns empty list on any failure.
        """
        if not texts:
            return []

        try:
            payload: dict[str, Any] = {
                "model": self._model,
                "input": texts,
            }
            headers = {
                "Authorization": f"Bearer {self._api_key}",
                "Content-Type": "application/json",
            }

            with httpx.Client(timeout=self._timeout) as client:
                resp = client.post(
                    f"{self._base_url}/embeddings",
                    json=payload,
                    headers=headers,
                )
                resp.raise_for_status()
                data = resp.json()

            # Response format: {"data": [{"embedding": [...], "index": 0}, ...]}
            results = data.get("data", [])
            results.sort(key=lambda x: x.get("index", 0))
            return [item.get("embedding", []) for item in results]

        except Exception:
            logger.warning("Embedding call failed", exc_info=True)
            return []

    def embed_batch(self, texts: list[str], batch_size: int = 32) -> list[list[float]]:
        """Batch embedding with configurable batch size.

        Concatenates results from multiple API calls.
        Returns empty list on any failure.
        """
        if not texts:
            return []

        all_embeddings: list[list[float]] = []
        for i in range(0, len(texts), batch_size):
            batch = texts[i : i + batch_size]
            batch_result = self.embed(batch)
            if len(batch_result) != len(batch):
                logger.warning(
                    "Embedding batch mismatch: expected %d, got %d",
                    len(batch), len(batch_result),
                )
                return []
            all_embeddings.extend(batch_result)

        return all_embeddings
