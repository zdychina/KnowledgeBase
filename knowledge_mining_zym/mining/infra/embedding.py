"""Embedding generator protocol and Zhipu Embedding-3 implementation.

Provides:
- EmbeddingGenerator Protocol (hot-pluggable)
- ZhipuEmbeddingGenerator: calls Zhipu AI Embedding-3 API
- NoOpEmbeddingGenerator: fallback when embedding is not configured
"""
from __future__ import annotations

import json
import logging
import uuid
from typing import Any, Protocol, runtime_checkable

import httpx

logger = logging.getLogger(__name__)


@runtime_checkable
class EmbeddingGenerator(Protocol):
    """Protocol for generating text embeddings."""

    def embed(self, texts: list[str]) -> list[list[float]]: ...

    def embed_batch(self, texts: list[str], batch_size: int = 32) -> list[list[float]]: ...


class NoOpEmbeddingGenerator:
    """Fallback: returns empty embeddings when embedding is not configured."""

    def embed(self, texts: list[str]) -> list[list[float]]:
        return []

    def embed_batch(self, texts: list[str], batch_size: int = 32) -> list[list[float]]:
        return []


class ZhipuEmbeddingGenerator:
    """Zhipu AI Embedding-3 API client.

    Uses httpx to call the Zhipu embeddings endpoint directly.
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
        """Call Zhipu embeddings API. Returns list of float vectors.

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
            # Sort by index to match input order
            results.sort(key=lambda x: x.get("index", 0))
            return [item.get("embedding", []) for item in results]

        except Exception as e:
            logger.warning("Zhipu embedding API failed: %s", e)
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


class LLMServiceEmbeddingGenerator:
    """Embedding client backed by llm_service model endpoint."""

    def __init__(
        self,
        *,
        base_url: str = "http://localhost:8900",
        model: str = "embedding-3",
        dimensions: int = 1024,
        timeout: int = 60,
    ) -> None:
        self._base_url = base_url.rstrip("/")
        self._model = model
        self._dimensions = dimensions
        self._timeout = timeout

    @property
    def model_name(self) -> str:
        return self._model

    @property
    def dimensions(self) -> int:
        return self._dimensions

    def embed(self, texts: list[str]) -> list[list[float]]:
        if not texts:
            return []

        payload: dict[str, Any] = {
            "input": texts,
            "model": self._model,
            "dimensions": self._dimensions,
        }
        try:
            with httpx.Client(base_url=self._base_url, timeout=self._timeout) as client:
                resp = client.post("/api/v1/models/embeddings", json=payload)
                resp.raise_for_status()
                data = resp.json()
            results = data.get("data", [])
            results.sort(key=lambda x: x.get("index", 0))
            return [item.get("embedding", []) for item in results]
        except Exception as e:
            logger.warning("LLM service embedding call failed: %s", e)
            return []

    def embed_batch(self, texts: list[str], batch_size: int = 32) -> list[list[float]]:
        if not texts:
            return []

        all_embeddings: list[list[float]] = []
        for i in range(0, len(texts), batch_size):
            batch = texts[i : i + batch_size]
            batch_result = self.embed(batch)
            if len(batch_result) != len(batch):
                logger.warning(
                    "LLM service embedding batch mismatch: expected %d, got %d",
                    len(batch), len(batch_result),
                )
                return []
            all_embeddings.extend(batch_result)
        return all_embeddings
