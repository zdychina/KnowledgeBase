"""HTTP client wrapping the serving API."""

from __future__ import annotations

import logging
import os
import time

import httpx

from mcp_server.schemas import (
    HealthResult,
    SearchResult,
    QueryUnderstanding,
    EvidenceItem,
    SourceRef,
    IssueNote,
    SearchInput,
)

logger = logging.getLogger(__name__)

SERVING_URL = os.environ.get("SERVING_URL", "http://127.0.0.1:8000").rstrip("/")
HEALTH_TIMEOUT = float(os.environ.get("HEALTH_TIMEOUT", "5.0"))
SEARCH_TIMEOUT = float(os.environ.get("SEARCH_TIMEOUT", "60.0"))

# 直连，不走任何代理 — trust_env=False 忽略所有代理/SSL环境变量
_client = httpx.Client(trust_env=False)


def health_check() -> HealthResult:
    """GET /health — returns structured result, never raises."""
    start = time.monotonic()
    try:
        resp = _client.get(f"{SERVING_URL}/health", timeout=HEALTH_TIMEOUT)
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


def search_knowledge(inp: SearchInput) -> SearchResult:
    """POST /api/v1/search — maps ContextPack → simplified SearchResult."""
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
            f"{SERVING_URL}/api/v1/search",
            json=payload,
            timeout=SEARCH_TIMEOUT,
        )
        if resp.status_code != 200:
            logger.warning("search returned HTTP %d for query=%r", resp.status_code, inp.query[:80])
            return SearchResult(
                issues=[IssueNote(type="api_error", message=f"HTTP {resp.status_code}")],
            )
        data = resp.json()
    except httpx.HTTPError as exc:
        logger.warning("search failed: %s", exc)
        return SearchResult(
            issues=[IssueNote(type="connection_error", message=str(exc))],
        )

    # --- map query understanding ---
    raw_query = data.get("query", {})
    query_understanding = QueryUnderstanding(
        original=raw_query.get("original", inp.query),
        intent=raw_query.get("intent", ""),
        keywords=raw_query.get("keywords", []),
        entities=raw_query.get("entities", []),
    )

    # --- map items ---
    items: list[EvidenceItem] = []
    for i, raw in enumerate(data.get("items", [])):
        text = raw.get("text", "")
        if inp.max_text_length > 0 and len(text) > inp.max_text_length:
            text = text[: inp.max_text_length] + "..."
        items.append(
            EvidenceItem(
                index=i,
                role=raw.get("role", ""),
                evidence_role=raw.get("evidence_role", ""),
                score=raw.get("score", 0.0),
                title=raw.get("title", ""),
                semantic_role=raw.get("semantic_role", ""),
                block_type=raw.get("block_type", ""),
                text=text,
                citation=raw.get("citation", {}),
            )
        )

    # --- map sources ---
    sources = [
        SourceRef(
            document_key=s.get("document_key", s.get("source_id", "")),
            title=s.get("title", ""),
        )
        for s in data.get("sources", [])
    ]

    # --- map issues ---
    issues = [
        IssueNote(type=iss.get("type", "unknown"), message=iss.get("message", ""))
        for iss in data.get("issues", [])
    ]

    return SearchResult(
        query_understanding=query_understanding,
        items=items,
        sources=sources,
        issues=issues,
        suggestions=data.get("suggestions", []),
        item_count=len(items),
    )
