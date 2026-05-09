"""HTTP client wrapping the serving API."""

from __future__ import annotations

import logging
import os
import time

import httpx

from mcp_server.schemas import (
    HealthResult,
    SearchInput,
)
from mcp_server.evidence_rules import evaluate_evidence as _evaluate_evidence

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


def search_knowledge(inp: SearchInput) -> dict:
    """POST /api/v1/search — 透传 serving 原始结果 + 附加证据评估。

    返回结构：
    {
        ...serving 原始返回的所有字段（query, items, relations, evidence_groups, sources, issues, suggestions, debug 等）...,
        "evidence_assessment": { ... }  // MCP Server 附加的评估
    }
    """
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
            return {"error": f"HTTP {resp.status_code}", "raw": resp.text[:500]}
        data = resp.json()
    except httpx.HTTPError as exc:
        logger.warning("search failed: %s", exc)
        return {"error": str(exc)}

    # 从 serving 结果中提取信息，计算证据评估
    items = data.get("items", [])
    intent = data.get("query", {}).get("intent", "")
    from mcp_server.schemas import ItemSummary
    summaries = [
        ItemSummary(
            evidence_role=item.get("evidence_role", ""),
            score=item.get("score", 0.0),
            semantic_role=item.get("semantic_role", ""),
        )
        for item in items
    ]
    assessment = _evaluate_evidence(summaries, intent, inp.query)

    # 透传 serving 原始结果 + 附加评估
    data["evidence_assessment"] = assessment.model_dump()
    return data
