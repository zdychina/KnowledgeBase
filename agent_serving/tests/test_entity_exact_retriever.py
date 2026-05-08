"""Tests for EntityExactRetriever — PG backend."""
import pytest
import pytest_asyncio

from agent_serving.serving.schemas.models import RetrievalQuery, EntityRef
from agent_serving.serving.retrieval.entity_exact_retriever import EntityExactRetriever


@pytest_asyncio.fixture
async def retriever(pg_pool):
    return EntityExactRetriever(pg_pool)


@pytest.mark.pg
class TestEntityExactRetriever:
    @pytest.mark.asyncio
    async def test_retrieve_by_entity(self, retriever):
        rq = RetrievalQuery(
            original_query="SMF的作用",
            entities=[EntityRef(type="network_element", name="SMF", normalized_name="SMF")],
        )
        snapshot_ids = ["aaaa0000-0000-0000-0000-000000000003"]
        results = await retriever.retrieve(rq, snapshot_ids)
        assert len(results) > 0
        assert any("SMF" in r.metadata.get("text", "") for r in results)

    @pytest.mark.asyncio
    async def test_entity_refs_json_matching(self, retriever):
        rq = RetrievalQuery(original_query="SMF", keywords=["SMF"])
        snapshot_ids = ["aaaa0000-0000-0000-0000-000000000003"]
        results = await retriever.retrieve(rq, snapshot_ids)
        assert len(results) > 0

    @pytest.mark.asyncio
    async def test_source_marker(self, retriever):
        rq = RetrievalQuery(original_query="SMF", keywords=["SMF"])
        snapshot_ids = ["aaaa0000-0000-0000-0000-000000000003"]
        results = await retriever.retrieve(rq, snapshot_ids)
        for r in results:
            assert r.source == "entity_exact"

    @pytest.mark.asyncio
    async def test_score_chain(self, retriever):
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
    async def test_no_results_for_unknown_entity(self, retriever):
        rq = RetrievalQuery(original_query="NONEXISTENT", keywords=["NONEXISTENT"])
        snapshot_ids = ["aaaa0000-0000-0000-0000-000000000003"]
        results = await retriever.retrieve(rq, snapshot_ids)
        assert len(results) == 0

    @pytest.mark.asyncio
    async def test_empty_snapshot_ids(self, retriever):
        rq = RetrievalQuery(original_query="SMF", keywords=["SMF"])
        results = await retriever.retrieve(rq, [])
        assert len(results) == 0

    @pytest.mark.asyncio
    async def test_scope_pushdown_filters(self, retriever):
        """Scope pushdown should restrict results to matching facets."""
        from agent_serving.tests.conftest import SNAP_UDG, SNAP_FEATURE
        rq_no_scope = RetrievalQuery(
            original_query="SMF",
            entities=[EntityRef(type="network_element", name="SMF")],
        )
        rq_scope = RetrievalQuery(
            original_query="SMF",
            entities=[EntityRef(type="network_element", name="SMF")],
            scope={"domains": ["5G"]},
        )
        results_all = await retriever.retrieve(rq_no_scope, [SNAP_FEATURE, SNAP_UDG])
        results_scoped = await retriever.retrieve(rq_scope, [SNAP_FEATURE, SNAP_UDG])
        # Scoped results should be subset of unscoped
        assert len(results_scoped) <= len(results_all)
