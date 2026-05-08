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
        self._url = base_url.rstrip("/")
        self._api_key = api_key
        self._model = model
        self._extra_headers = headers or {}
        self._timeout = timeout
        transport = httpx.AsyncHTTPTransport() if bypass_proxy else None
        self._client = httpx.AsyncClient(transport=transport, timeout=timeout)

    async def close(self) -> None:
        await self._client.aclose()

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
        *,
        response_format: dict | None = None,
    ) -> ProviderResponse:
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
        if response_format is not None:
            body["response_format"] = response_format
        try:
            resp = await self._client.post(self._url, json=body, headers=headers)
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

        try:
            data = resp.json()
        except Exception as e:
            raise ProviderError(
                "invalid_response", f"Non-JSON response from provider: {e}"
            ) from e
        content = data.get("choices", [{}])[0].get("message", {}).get("content", "")
        usage = data.get("usage", {})
        return ProviderResponse(
            output_text=content,
            prompt_tokens=usage.get("prompt_tokens"),
            completion_tokens=usage.get("completion_tokens"),
            total_tokens=usage.get("total_tokens"),
            raw_response=data,
        )
