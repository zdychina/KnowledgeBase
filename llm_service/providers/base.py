from __future__ import annotations

from dataclasses import dataclass
from typing import Protocol, runtime_checkable


@dataclass
class ProviderResponse:
    output_text: str
    prompt_tokens: int | None = None
    completion_tokens: int | None = None
    total_tokens: int | None = None
    raw_response: dict | None = None


class ProviderError(Exception):
    def __init__(self, error_type: str, message: str):
        self.error_type = error_type
        self.message = message
        super().__init__(message)


@runtime_checkable
class ProviderProtocol(Protocol):
    async def complete(
        self,
        messages: list[dict],
        params: dict,
        *,
        response_format: dict | None = None,
    ) -> ProviderResponse: ...

    @property
    def provider_name(self) -> str: ...

    @property
    def default_model(self) -> str: ...
