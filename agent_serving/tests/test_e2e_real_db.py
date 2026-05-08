"""E2E real DB test — verify /api/v1/search returns non-empty items on real PG data.

This test proves the main API chain works end-to-end with PostgreSQL.
Requires seeded PG (run `python -m agent_serving.scripts.seed_pg` first).
External services (LLM, embedding, rerank) are disabled to verify BM25+entity baseline.
"""
from __future__ import annotations

import os

import pytest
import pytest_asyncio
from httpx import ASGITransport, AsyncClient

from agent_serving.serving.main import app

# Skip if PG not configured
pytestmark = pytest.mark.skipif(
    not os.environ.get("PG_HOST"),
    reason="PG_HOST not set — skipping E2E PG test",
)

BASIC_QUERIES = [
    "什么是业务感知",
    "SA识别的定义是什么",
    "UPF如何识别用户业务",
]


@pytest_asyncio.fixture
async def real_client(pg_pool):
    """Test client wired to the test PG pool, with external services disabled."""
    app.state.pool = pg_pool
    app.state.embedding_dimensions = 1024
    app.state.llm_client = None
    app.state.embedding_generator = None
    app.state.domain_profile = None

    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as ac:
        yield ac


@pytest.mark.pg
class TestE2ERealDB:
    """E2E: real PG + real API endpoint -> non-empty items."""

    @pytest.mark.asyncio
    async def test_basic_queries_return_items(self, real_client):
        """All basic queries must return non-empty items via the main API chain."""
        for query in BASIC_QUERIES:
            resp = await real_client.post("/api/v1/search", json={"query": query})
            assert resp.status_code == 200, f"Query '{query}' returned {resp.status_code}"
            pack = resp.json()
            assert len(pack["items"]) > 0, (
                f"Query '{query}' returned 0 items. "
                f"intent={pack['query']['intent']}, "
                f"issues={[i['type'] for i in pack.get('issues', [])]}"
            )

    @pytest.mark.asyncio
    async def test_debug_trace_has_all_stages(self, real_client):
        """Debug output should contain all pipeline stages."""
        resp = await real_client.post("/api/v1/search", json={
            "query": "什么是业务感知",
            "debug": True,
        })
        assert resp.status_code == 200
        pack = resp.json()
        assert pack["debug"] is not None
        stages = [s["name"] for s in pack["debug"]["trace"]["stages"]]
        for expected in ["query_understanding", "retrieval_router", "retrieve", "fusion", "rerank", "assembly"]:
            assert expected in stages, f"Missing stage: {expected}"

    @pytest.mark.asyncio
    async def test_bm25_entity_baseline_without_llm(self, real_client):
        """BM25+entity retrieval must work without LLM/embedding."""
        resp = await real_client.post("/api/v1/search", json={
            "query": "ADD UPF",
            "debug": True,
        })
        assert resp.status_code == 200
        pack = resp.json()
        assert len(pack["items"]) > 0, "BM25+entity baseline returned 0 items"
        assert pack["debug"]["understanding"]["source"] == "rule"
