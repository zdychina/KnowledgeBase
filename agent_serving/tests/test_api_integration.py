"""Integration tests: full search pipeline via FastAPI TestClient — v2 (PG backend)."""
import json

import pytest
import pytest_asyncio
from httpx import ASGITransport, AsyncClient

from agent_serving.serving.main import app


@pytest_asyncio.fixture
async def client(pg_pool):
    """Test client wired to the test PG pool."""
    # Store the pool in app.state so the search endpoint uses it
    app.state.pool = pg_pool
    app.state.embedding_dimensions = 1024
    app.state.domain_profile = None
    app.state.llm_client = None
    app.state.embedding_generator = None

    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as ac:
        yield ac


@pytest.mark.pg
class TestHealthEndpoint:
    @pytest.mark.asyncio
    async def test_health_check(self, client):
        resp = await client.get("/health")
        assert resp.status_code == 200
        data = resp.json()
        assert data["status"] == "ok"


@pytest.mark.pg
class TestSearchEndpoint:
    @pytest.mark.asyncio
    async def test_search_returns_context_pack(self, client):
        resp = await client.post("/api/v1/search", json={"query": "ADD APN"})
        assert resp.status_code == 200
        pack = resp.json()
        assert "query" in pack
        assert "items" in pack
        assert "relations" in pack
        assert "sources" in pack
        assert "issues" in pack
        assert len(pack["items"]) > 0, f"Expected non-empty items for 'ADD APN', got {len(pack['items'])}"

    @pytest.mark.asyncio
    async def test_search_returns_nonempty_items(self, client):
        resp = await client.post("/api/v1/search", json={"query": "ADD APN"})
        assert resp.status_code == 200
        pack = resp.json()
        assert len(pack["items"]) > 0

    @pytest.mark.asyncio
    async def test_search_command_query(self, client):
        resp = await client.post("/api/v1/search", json={"query": "ADD APN 怎么写"})
        assert resp.status_code == 200
        pack = resp.json()
        assert pack["query"]["intent"] == "command_usage"

    @pytest.mark.asyncio
    async def test_search_keyword_query(self, client):
        resp = await client.post("/api/v1/search", json={"query": "5G eMBB"})
        assert resp.status_code == 200
        pack = resp.json()
        assert pack["query"]["intent"] in ("concept_lookup", "general")

    @pytest.mark.asyncio
    async def test_search_with_scope(self, client):
        resp = await client.post("/api/v1/search", json={
            "query": "ADD APN",
            "scope": {"products": ["UDG"]},
        })
        assert resp.status_code == 200
        pack = resp.json()
        assert "items" in pack

    @pytest.mark.asyncio
    async def test_search_has_relations(self, client):
        resp = await client.post("/api/v1/search", json={"query": "ADD APN"})
        assert resp.status_code == 200
        pack = resp.json()
        assert isinstance(pack["relations"], list)

    @pytest.mark.asyncio
    async def test_search_has_sources(self, client):
        resp = await client.post("/api/v1/search", json={"query": "ADD APN"})
        assert resp.status_code == 200
        pack = resp.json()
        assert isinstance(pack["sources"], list)


@pytest.mark.pg
class TestV2DebugTrace:
    @pytest.mark.asyncio
    async def test_debug_trace(self, client):
        resp = await client.post("/api/v1/search", json={
            "query": "ADD APN",
            "debug": True,
        })
        assert resp.status_code == 200
        pack = resp.json()
        assert pack["debug"] is not None
        assert "understanding" in pack["debug"]
        assert pack["debug"]["understanding"]["intent"] == "command_usage"
        assert "route_plan" in pack["debug"]
        assert len(pack["debug"]["route_plan"]["routes"]) > 0
        assert "trace" in pack["debug"]
        stage_names = [s["name"] for s in pack["debug"]["trace"]["stages"]]
        for expected in ["query_understanding", "retrieval_router", "retrieve", "fusion", "rerank", "assembly"]:
            assert expected in stage_names, f"Missing stage: {expected}"

    @pytest.mark.asyncio
    async def test_debug_fusion_method(self, client):
        resp = await client.post("/api/v1/search", json={
            "query": "ADD APN",
            "debug": True,
        })
        pack = resp.json()
        assert pack["debug"]["fusion_method"] == "weighted_rrf"


@pytest.mark.pg
class TestContextPackStructure:
    @pytest.mark.asyncio
    async def test_items_have_required_fields(self, client):
        resp = await client.post("/api/v1/search", json={"query": "ADD APN"})
        assert resp.status_code == 200
        pack = resp.json()
        for item in pack["items"]:
            assert "id" in item
            assert "kind" in item
            assert "role" in item
            assert "text" in item
            assert "score" in item
            assert item["kind"] in ("retrieval_unit", "raw_segment")
            assert item["role"] in ("seed", "context", "support")

    @pytest.mark.asyncio
    async def test_relations_have_required_fields(self, client):
        resp = await client.post("/api/v1/search", json={"query": "ADD APN"})
        assert resp.status_code == 200
        pack = resp.json()
        for rel in pack["relations"]:
            assert "id" in rel
            assert "from_id" in rel
            assert "to_id" in rel
            assert "relation_type" in rel
