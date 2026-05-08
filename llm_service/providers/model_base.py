from __future__ import annotations

from typing import Protocol, runtime_checkable


class ModelProviderError(Exception):
    def __init__(self, error_type: str, message: str):
        self.error_type = error_type
        self.message = message
        super().__init__(message)


@runtime_checkable
class ModelProviderProtocol(Protocol):
    async def embed(
        self,
        texts: list[str],
        *,
        model: str | None = None,
        dimensions: int | None = None,
    ) -> dict: ...

    async def rerank(
        self,
        query: str,
        documents: list[str],
        *,
        model: str | None = None,
        top_n: int | None = None,
    ) -> dict: ...
