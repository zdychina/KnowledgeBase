"""HTTP client — pure passthrough to the knowledge base backend."""

from __future__ import annotations

import logging
import os
import time

import httpx

from mcp_server.schemas import (
    HealthResult,
    SearchInput,
)

logger = logging.getLogger(__name__)

BACKEND_URL = os.environ.get("SERVING_URL", "http://121.89.90.178:8081").rstrip("/")
HEALTH_TIMEOUT = float(os.environ.get("HEALTH_TIMEOUT", "10.0"))
SEARCH_TIMEOUT = float(os.environ.get("SEARCH_TIMEOUT", "120.0"))

_client = httpx.Client(trust_env=False)


def health_check() -> HealthResult:
    """GET /health — returns structured result, never raises."""
    start = time.monotonic()
    try:
        resp = _client.get(f"{BACKEND_URL}/health", timeout=HEALTH_TIMEOUT)
        latency_ms = (time.monotonic() - start) * 1000
        if resp.status_code == 200:
            data = resp.json()
            return HealthResult(
                available=True,
                status=data.get("status", "ok"),
                version=data.get("version", ""),
                latency_ms=round(latency_ms, 1),
            )
        logger.warning("health_check returned HTTP %d", resp.status_code)
        return HealthResult(
            available=False,
            status="error",
            latency_ms=round(latency_ms, 1),
            error=f"HTTP {resp.status_code}",
        )
    except httpx.HTTPError as exc:
        latency_ms = (time.monotonic() - start) * 1000
        logger.warning("health_check failed: %s", exc)
        return HealthResult(
            available=False,
            status="unreachable",
            latency_ms=round(latency_ms, 1),
            error=str(exc),
        )


def search_knowledge(inp: SearchInput) -> dict:
    """POST /api/v1/search — pure passthrough, returns backend JSON as-is."""
    payload: dict = {
        "query": inp.query,
        "domain": inp.domain,
        "debug": inp.debug,
    }
    if inp.scope:
        payload["scope"] = inp.scope
    if inp.entities:
        payload["entities"] = [e.model_dump() for e in inp.entities]

    try:
        resp = _client.post(
            f"{BACKEND_URL}/api/v1/search",
            json=payload,
            timeout=SEARCH_TIMEOUT,
        )
        if resp.status_code != 200:
            logger.warning("search returned HTTP %d for query=%r", resp.status_code, inp.query[:80])
            return {"error": f"HTTP {resp.status_code}", "raw": resp.text[:500]}
        return resp.json()
    except httpx.HTTPError as exc:
        logger.warning("search failed: %s", exc)
        return {"error": str(exc)}
