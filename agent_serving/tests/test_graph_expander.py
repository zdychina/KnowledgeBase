"""Tests for GraphExpander — BFS expand, fetch segments, _get_neighbors."""
import pytest
import pytest_asyncio

from agent_serving.serving.retrieval.graph_expander import GraphExpander
from agent_serving.tests.conftest import (
    RS_ADD_APN_UDG,
    RS_5G_CONCEPT,
    SNAP_UDG,
    SNAP_FEATURE,
)


@pytest_asyncio.fixture
async def graph(pg_pool):
    return GraphExpander(pg_pool)


@pytest.mark.pg
class TestGraphExpand:
    @pytest.mark.asyncio
    async def test_expand_from_seed_returns_neighbors(self, graph):
        """Expand from RS_ADD_APN_UDG should find RS_5G_CONCEPT via 'next' relation."""
        results = await graph.expand(
            seed_segment_ids=[RS_ADD_APN_UDG],
            max_depth=2,
            snapshot_ids=[SNAP_UDG],
        )
        assert len(results) > 0
        # Should find RS_5G_CONCEPT as a neighbor
        found_ids = {r["segment_id"] for r in results}
        assert RS_5G_CONCEPT in found_ids

    @pytest.mark.asyncio
    async def test_expand_depth_metadata(self, graph):
        results = await graph.expand(
            seed_segment_ids=[RS_ADD_APN_UDG],
            max_depth=2,
            snapshot_ids=[SNAP_UDG],
        )
        for r in results:
            assert "depth" in r
            assert "relation_type" in r
            assert "from_segment_id" in r
            assert r["depth"] >= 1

    @pytest.mark.asyncio
    async def test_expand_max_results_truncation(self, graph):
        results = await graph.expand(
            seed_segment_ids=[RS_ADD_APN_UDG],
            max_depth=2,
            max_results=1,
            snapshot_ids=[SNAP_UDG],
        )
        assert len(results) <= 1

    @pytest.mark.asyncio
    async def test_expand_empty_seeds(self, graph):
        results = await graph.expand(
            seed_segment_ids=[],
            max_depth=2,
        )
        assert results == []

    @pytest.mark.asyncio
    async def test_expand_relation_types_filter(self, graph):
        """Filter to only 'next' relations."""
        results = await graph.expand(
            seed_segment_ids=[RS_ADD_APN_UDG],
            max_depth=2,
            relation_types=["next"],
            snapshot_ids=[SNAP_UDG],
        )
        for r in results:
            assert r["relation_type"] == "next"


@pytest.mark.pg
class TestFetchExpandedSegments:
    @pytest.mark.asyncio
    async def test_fetch_expanded_with_metadata(self, graph):
        expansions = [{
            "segment_id": RS_5G_CONCEPT,
            "depth": 1,
            "relation_type": "next",
            "from_segment_id": RS_ADD_APN_UDG,
        }]
        results = await graph.fetch_expanded_segments(
            expansions, snapshot_ids=[SNAP_FEATURE],
        )
        assert len(results) > 0
        r = results[0]
        assert r["expansion_depth"] == 1
        assert r["expansion_relation_type"] == "next"
        assert r["from_segment_id"] == RS_ADD_APN_UDG
        assert "raw_text" in r

    @pytest.mark.asyncio
    async def test_fetch_expanded_empty(self, graph):
        results = await graph.fetch_expanded_segments([])
        assert results == []


@pytest.mark.pg
class TestGetNeighbors:
    @pytest.mark.asyncio
    async def test_get_neighbors_with_snapshot_filter(self, graph):
        neighbors = await graph._get_neighbors(
            segment_ids=[RS_ADD_APN_UDG],
            snapshot_ids=[SNAP_UDG],
        )
        assert isinstance(neighbors, list)
        # Should find RS_5G_CONCEPT via next relation
        neighbor_ids = {str(n["neighbor_id"]) for n in neighbors}
        assert RS_5G_CONCEPT in neighbor_ids

    @pytest.mark.asyncio
    async def test_get_neighbors_without_snapshot(self, graph):
        """Without snapshot filter, should still find neighbors."""
        neighbors = await graph._get_neighbors(
            segment_ids=[RS_ADD_APN_UDG],
        )
        assert isinstance(neighbors, list)
        assert len(neighbors) > 0

    @pytest.mark.asyncio
    async def test_get_neighbors_with_relation_type_filter(self, graph):
        neighbors = await graph._get_neighbors(
            segment_ids=[RS_ADD_APN_UDG],
            relation_types=["next"],
            snapshot_ids=[SNAP_UDG],
        )
        for n in neighbors:
            assert n["relation_type"] == "next"

    @pytest.mark.asyncio
    async def test_get_neighbors_empty_segment_ids(self, graph):
        neighbors = await graph._get_neighbors(segment_ids=[])
        assert neighbors == []
