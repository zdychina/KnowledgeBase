"""Tests for EntityExactRetriever."""
import json

import pytest
import pytest_asyncio
import aiosqlite

from agent_serving.serving.schemas.models import RetrievalQuery, EntityRef
from agent_serving.serving.retrieval.entity_exact_retriever import EntityExactRetriever
from agent_serving.serving.repositories.schema_adapter import create_asset_tables_sqlite
from agent_serving.tests.conftest import _seed_v11_data


@pytest_asyncio.fixture
async def db_with_entities():
    db = await aiosqlite.connect(":memory:")
    db.row_factory = aiosqlite.Row
    await create_asset_tables_sqlite(db)
    await _seed_v11_data(db)
    yield db
    await db.close()


class TestEntityExactRetriever:
    @pytest.mark.asyncio
    async def test_retrieve_by_entity(self, db_with_entities):
        retriever = EntityExactRetriever(db_with_entities)
        rq = RetrievalQuery(
            original_query="SMF的作用",
            entities=[EntityRef(type="network_element", name="SMF", normalized_name="SMF")],
        )
        # Use snapshot_ids from seed data
        snapshot_ids = ["aaaa0000-0000-0000-0000-000000000003"]
        results = await retriever.retrieve(rq, snapshot_ids)
        # Should find entity_card for SMF
        assert len(results) > 0
        assert any("SMF" in r.metadata.get("text", "") for r in results)

    @pytest.mark.asyncio
    async def test_entity_refs_json_matching(self, db_with_entities):
        retriever = EntityExactRetriever(db_with_entities)
        rq = RetrievalQuery(original_query="SMF", keywords=["SMF"])
        snapshot_ids = ["aaaa0000-0000-0000-0000-000000000003"]
        results = await retriever.retrieve(rq, snapshot_ids)
        # Should find units with SMF entity
        assert len(results) > 0

    @pytest.mark.asyncio
    async def test_source_marker(self, db_with_entities):
        retriever = EntityExactRetriever(db_with_entities)
        rq = RetrievalQuery(original_query="SMF", keywords=["SMF"])
        snapshot_ids = ["aaaa0000-0000-0000-0000-000000000003"]
        results = await retriever.retrieve(rq, snapshot_ids)
        for r in results:
            assert r.source == "entity_exact"

    @pytest.mark.asyncio
    async def test_score_chain(self, db_with_entities):
        retriever = EntityExactRetriever(db_with_entities)
        rq = RetrievalQuery(
            original_query="SMF",
            entities=[EntityRef(type="network_element", name="SMF")],
        )
        snapshot_ids = ["aaaa0000-0000-0000-0000-000000000003"]
        results = await retriever.retrieve(rq, snapshot_ids)
        for r in results:
            assert r.score_chain is not None
            assert "entity_exact" in r.score_chain.route_sources

    @pytest.mark.asyncio
    async def test_no_results_for_unknown_entity(self, db_with_entities):
        retriever = EntityExactRetriever(db_with_entities)
        rq = RetrievalQuery(original_query="NONEXISTENT", keywords=["NONEXISTENT"])
        snapshot_ids = ["aaaa0000-0000-0000-0000-000000000003"]
        results = await retriever.retrieve(rq, snapshot_ids)
        assert len(results) == 0

    @pytest.mark.asyncio
    async def test_empty_snapshot_ids(self, db_with_entities):
        retriever = EntityExactRetriever(db_with_entities)
        rq = RetrievalQuery(original_query="SMF", keywords=["SMF"])
        results = await retriever.retrieve(rq, [])
        assert len(results) == 0
