"""Integration tests: full search pipeline via FastAPI TestClient — v2."""
import json

import pytest
import pytest_asyncio
import aiosqlite
from httpx import ASGITransport, AsyncClient

from agent_serving.serving.main import app
from agent_serving.serving.repositories.schema_adapter import create_asset_tables_sqlite
from agent_serving.tests.conftest import _seed_v11_data


@pytest_asyncio.fixture
async def client():
    """Test client with in-memory DB seeded with v1.1 schema."""
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as ac:
        # Lifespan has run; replace its DB with our seeded one
        lifespan_db = getattr(app.state, "db", None)
        if lifespan_db:
            await lifespan_db.close()
        db = await aiosqlite.connect(":memory:")
        db.row_factory = aiosqlite.Row
        await create_asset_tables_sqlite(db)
        await _seed_v11_data(db)
        app.state.db = db
        app.state.domain_profile = None
        # Disable external services for tests
        app.state.llm_client = None
        app.state.embedding_generator = None
        yield ac
        await db.close()


class TestHealthEndpoint:
    @pytest.mark.asyncio
    async def test_health_check(self, client):
        resp = await client.get("/health")
        assert resp.status_code == 200
        data = resp.json()
        assert data["status"] == "ok"


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


class TestV2DebugTrace:
    """v2: debug output contains full trace."""

    @pytest.mark.asyncio
    async def test_debug_trace(self, client):
        resp = await client.post("/api/v1/search", json={
            "query": "ADD APN",
            "debug": True,
        })
        assert resp.status_code == 200
        pack = resp.json()
        assert pack["debug"] is not None

        # Check understanding
        assert "understanding" in pack["debug"]
        understanding = pack["debug"]["understanding"]
        assert understanding["intent"] == "command_usage"

        # Check route plan
        assert "route_plan" in pack["debug"]
        route_plan = pack["debug"]["route_plan"]
        assert len(route_plan["routes"]) > 0

        # Check trace
        assert "trace" in pack["debug"]
        trace = pack["debug"]["trace"]
        assert "stages" in trace
        stage_names = [s["name"] for s in trace["stages"]]
        assert "query_understanding" in stage_names
        assert "retrieval_router" in stage_names
        assert "retrieve" in stage_names
        assert "fusion" in stage_names
        assert "rerank" in stage_names
        assert "assembly" in stage_names

    @pytest.mark.asyncio
    async def test_debug_fusion_method(self, client):
        resp = await client.post("/api/v1/search", json={
            "query": "ADD APN",
            "debug": True,
        })
        pack = resp.json()
        assert pack["debug"]["fusion_method"] == "weighted_rrf"


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


class TestNoActiveRelease:
    @pytest.mark.asyncio
    async def test_returns_503_when_no_active_release(self, client):
        db = app.state.db
        await db.execute("UPDATE asset_publish_releases SET status = 'retired'")
        await db.commit()

        resp = await client.post("/api/v1/search", json={"query": "ADD APN"})
        assert resp.status_code == 503
