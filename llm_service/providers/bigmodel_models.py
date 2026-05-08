from __future__ import annotations

import httpx

from llm_service.providers.model_base import ModelProviderError
from llm_service.providers.utils import extract_doc_text


class BigModelProvider:
    """BigModel modality provider for embeddings and rerank."""

    def __init__(
        self,
        *,
        embedding_api_key: str = "",
        embedding_url: str = "https://open.bigmodel.cn/api/paas/v4/embeddings",
        embedding_model: str = "embedding-3",
        rerank_api_key: str = "",
        rerank_url: str = "https://open.bigmodel.cn/api/paas/v4/rerank",
        rerank_model: str = "",
        timeout: int = 60,
        bypass_proxy: bool = False,
        extra_headers: dict | None = None,
    ) -> None:
        self._embedding_api_key = embedding_api_key
        self._embedding_url = embedding_url.rstrip("/")
        self._embedding_model = embedding_model
        self._rerank_api_key = rerank_api_key
        self._rerank_url = rerank_url.rstrip("/")
        self._rerank_model = rerank_model
        self._extra_headers = extra_headers or {}
        self._timeout = timeout
        transport = httpx.AsyncHTTPTransport() if bypass_proxy else None
        self._client = httpx.AsyncClient(transport=transport, timeout=timeout)

    async def close(self) -> None:
        await self._client.aclose()

    def _headers(self, api_key: str, capability: str) -> dict[str, str]:
        if not api_key:
            raise ModelProviderError(
                "not_configured",
                f"BigModel API key is not configured for {capability}",
            )
        return {
            "Authorization": f"Bearer {api_key}",
            "Content-Type": "application/json",
            **self._extra_headers,
        }

    async def _post(
        self,
        url: str,
        api_key: str,
        capability: str,
        payload: dict,
    ) -> dict:
        try:
            resp = await self._client.post(
                url,
                json=payload,
                headers=self._headers(api_key, capability),
            )
        except httpx.TimeoutException as e:
            raise ModelProviderError("timeout", str(e)) from e
        except httpx.ConnectError as e:
            raise ModelProviderError("connection_error", str(e)) from e

        if resp.status_code == 429:
            raise ModelProviderError("rate_limited", resp.text)
        if resp.status_code >= 500:
            raise ModelProviderError("server_error", f"HTTP {resp.status_code}: {resp.text}")
        if resp.status_code >= 400:
            raise ModelProviderError("client_error", f"HTTP {resp.status_code}: {resp.text}")
        try:
            return resp.json()
        except Exception as e:
            raise ModelProviderError(
                "invalid_response", f"Non-JSON response from provider: {e}"
            ) from e

    async def embed(
        self,
        texts: list[str],
        *,
        model: str | None = None,
        dimensions: int | None = None,
    ) -> dict:
        payload: dict = {
            "model": model or self._embedding_model,
            "input": texts,
        }
        if dimensions is not None:
            payload["dimensions"] = dimensions
        data = await self._post(
            self._embedding_url,
            self._embedding_api_key,
            "embedding",
            payload,
        )
        return {
            "model": payload["model"],
            "data": data.get("data", []),
            "usage": data.get("usage"),
        }

    async def rerank(
        self,
        query: str,
        documents: list[str],
        *,
        model: str | None = None,
        top_n: int | None = None,
    ) -> dict:
        payload = {
            "model": model or self._rerank_model,
            "query": query,
            "documents": documents,
            "top_n": top_n if top_n is not None else len(documents),
            "return_documents": True,
        }
        data = await self._post(
            self._rerank_url,
            self._rerank_api_key,
            "rerank",
            payload,
        )
        results = data.get("results", [])
        # rerank-pro omits "index" — reconstruct from document content
        doc_to_idx: dict[str, list[int]] = {}
        for i, d in enumerate(documents):
            doc_to_idx.setdefault(d, []).append(i)
        used_indices: set[int] = set()
        for item in results:
            if "index" in item:
                used_indices.add(item["index"])
                continue
            _doc = item.get("document")
            doc_text = extract_doc_text(_doc)
            candidates = doc_to_idx.get(doc_text, [])
            # Pick first unused index to handle duplicate documents
            for ci in candidates:
                if ci not in used_indices:
                    item["index"] = ci
                    used_indices.add(ci)
                    break
            else:
                item["index"] = -1
        return {
            "model": payload["model"],
            "results": results,
            "usage": data.get("usage"),
        }
