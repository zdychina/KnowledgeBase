"""Contract tests — v2 Retrieval Orchestrator contract with Mining assets.

Tests that Serving correctly consumes Mining-produced data:
- entity_card retrieval units
- generated_question retrieval units
- entity_refs_json field
- source_refs_json provenance
- retrieval unit types
"""
import json

import pytest
import pytest_asyncio

from agent_serving.serving.schemas.models import (
    EntityRef,
    RetrievalQuery,
)
from agent_serving.serving.retrieval.entity_exact_retriever import EntityExactRetriever


@pytest_asyncio.fixture
async def retriever(pg_pool):
    return EntityExactRetriever(pg_pool)


@pytest.mark.pg
class TestEntityCardContract:
    """Mining produces entity_card retrieval units; Serving must consume them."""

    @pytest.mark.asyncio
    async def test_entity_card_retrieved_by_name(self, retriever):
        rq = RetrievalQuery(
            original_query="SMF",
            entities=[EntityRef(type="network_element", name="SMF")],
        )
        snapshot_ids = ["aaaa0000-0000-0000-0000-000000000003"]
        results = await retriever.retrieve(rq, snapshot_ids)
        entity_cards = [r for r in results if r.metadata.get("unit_type") == "entity_card"]
        assert len(entity_cards) > 0, "Should find entity_card for SMF"
        assert any("SMF" in r.metadata.get("text", "") for r in entity_cards)


@pytest.mark.pg
class TestGeneratedQuestionContract:
    """Mining produces generated_question units; Serving must consume them."""

    @pytest.mark.asyncio
    async def test_generated_question_retrieved(self, retriever):
        rq = RetrievalQuery(original_query="SMF", keywords=["SMF"])
        snapshot_ids = ["aaaa0000-0000-0000-0000-000000000003"]
        results = await retriever.retrieve(rq, snapshot_ids)
        questions = [r for r in results if r.metadata.get("unit_type") == "generated_question"]
        assert len(questions) > 0, "Should find generated_question containing SMF"


@pytest.mark.pg
class TestEntityRefsJsonContract:
    """Mining populates entity_refs_json; Serving must parse it correctly."""

    @pytest.mark.asyncio
    async def test_entity_refs_parsed(self, retriever):
        rq = RetrievalQuery(original_query="SMF", keywords=["SMF"])
        snapshot_ids = ["aaaa0000-0000-0000-0000-000000000003"]
        results = await retriever.retrieve(rq, snapshot_ids)
        assert len(results) > 0, "Should find results for SMF"
        for r in results:
            refs_str = r.metadata.get("entity_refs_json", "[]")
            refs = json.loads(refs_str)
            assert isinstance(refs, list), "entity_refs_json should be a list"


@pytest.mark.pg
class TestSourceRefsJsonContract:
    """Mining populates source_refs_json; Serving must use it for provenance."""

    @pytest.mark.asyncio
    async def test_source_refs_in_metadata(self, retriever):
        rq = RetrievalQuery(original_query="SMF", keywords=["SMF"])
        snapshot_ids = ["aaaa0000-0000-0000-0000-000000000003"]
        results = await retriever.retrieve(rq, snapshot_ids)
        for r in results:
            refs_str = r.metadata.get("source_refs_json", "{}")
            refs = json.loads(refs_str)
            assert isinstance(refs, dict), "source_refs_json should be a dict"
