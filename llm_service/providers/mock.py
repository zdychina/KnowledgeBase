from __future__ import annotations

from llm_service.providers.base import ProviderError, ProviderResponse


class MockProvider:
    def __init__(
        self,
        responses: list[dict] | None = None,
        error: ProviderError | None = None,
    ):
        self._responses = responses or []
        self._index = 0
        self._error = error

    @property
    def provider_name(self) -> str:
        return "mock"

    @property
    def default_model(self) -> str:
        return "mock-model"

    async def complete(
        self,
        messages: list[dict],
        params: dict,
    ) -> ProviderResponse:
        if self._error:
            raise self._error
        if not self._responses:
            return ProviderResponse(output_text="")
        resp = self._responses[self._index % len(self._responses)]
        self._index += 1
        content = resp.get("choices", [{}])[0].get("message", {}).get("content", "")
        usage = resp.get("usage", {})
        return ProviderResponse(
            output_text=content,
            prompt_tokens=usage.get("prompt_tokens"),
            completion_tokens=usage.get("completion_tokens"),
            total_tokens=usage.get("total_tokens"),
            raw_response=resp,
        )
