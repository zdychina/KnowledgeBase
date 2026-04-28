from __future__ import annotations

import httpx

from llm_service.providers.base import ProviderError, ProviderResponse


class OpenAICompatibleProvider:
    def __init__(
        self,
        base_url: str,
        api_key: str,
        model: str,
        headers: dict | None = None,
        timeout: int = 30,
        bypass_proxy: bool = False,
    ):
        self._base_url = base_url.rstrip("/")
        self._api_key = api_key
        self._model = model
        self._extra_headers = headers or {}
        self._timeout = timeout
        self._bypass_proxy = bypass_proxy

    @property
    def provider_name(self) -> str:
        return "openai_compatible"

    @property
    def default_model(self) -> str:
        return self._model

    async def complete(
        self,
        messages: list[dict],
        params: dict,
    ) -> ProviderResponse:
        url = f"{self._base_url}/chat/completions"
        headers = {
            "Authorization": f"Bearer {self._api_key}",
            "Content-Type": "application/json",
            **self._extra_headers,
        }
        body = {
            "model": self._model,
            "messages": messages,
            **params,
        }
        transport = httpx.AsyncHTTPTransport() if self._bypass_proxy else None
        async with httpx.AsyncClient(transport=transport, timeout=self._timeout) as client:
            try:
                resp = await client.post(url, json=body, headers=headers)
            except httpx.TimeoutException as e:
                raise ProviderError("timeout", str(e)) from e
            except httpx.ConnectError as e:
                raise ProviderError("connection_error", str(e)) from e

        if resp.status_code == 429:
            raise ProviderError("rate_limited", resp.text)
        if resp.status_code >= 500:
            raise ProviderError("server_error", f"HTTP {resp.status_code}: {resp.text}")
        if resp.status_code >= 400:
            raise ProviderError("client_error", f"HTTP {resp.status_code}: {resp.text}")

        data = resp.json()
        content = data.get("choices", [{}])[0].get("message", {}).get("content", "")
        usage = data.get("usage", {})
        return ProviderResponse(
            output_text=content,
            prompt_tokens=usage.get("prompt_tokens"),
            completion_tokens=usage.get("completion_tokens"),
            total_tokens=usage.get("total_tokens"),
            raw_response=data,
        )
