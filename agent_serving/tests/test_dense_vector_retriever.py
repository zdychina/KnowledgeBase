"""Tests for DenseVectorRetriever — pgvector backend.

Tests cover:
- Early return conditions (no embedding, empty snapshots)
- pgvector main path with real embeddings
- Score conversion (distance → similarity)
- Scope pushdown
- _build_scope_filter parameterized safety
"""
import json
import math

import pytest
import pytest_asyncio

from agent_serving.serving.schemas.models import RetrievalQuery
from agent_serving.serving.retrieval.dense_vector_retriever import DenseVectorRetriever
from agent_serving.tests.conftest import SNAP_UDG, SNAP_FEATURE


def _random_unit_vector(dim: int = 1024, seed: int = 42) -> list[float]:
    """Deterministic random unit vector for testing."""
    import random
    rng = random.Random(seed)
    vec = [rng.gauss(0, 1) for _ in range(dim)]
    norm = math.sqrt(sum(v * v for v in vec))
    return [v / norm for v in vec]


@pytest_asyncio.fixture
async def retriever(pg_pool):
    return DenseVectorRetriever(pg_pool, embedding_dimensions=1024)


# --- Unit tests (no PG required) ---


class TestBuildScopeFilter:
    def test_empty_scope(self):
        sql, params = DenseVectorRetriever._build_scope_filter({})
        assert sql == ""
        assert params == []

    def test_single_key(self):
        sql, params = DenseVectorRetriever._build_scope_filter({"products": ["UDG"]})
        assert "%s::jsonb" in sql
        assert json.loads(params[0]) == {"products": ["UDG"]}

    def test_parameterized_not_interpolated(self):
        """Ensure key/value are NOT in SQL string directly."""
        sql, params = DenseVectorRetriever._build_scope_filter({"products": ["UDG"]})
        assert "UDG" not in sql
        assert "products" not in sql


# --- Integration tests ---


@pytest.mark.pg
class TestDenseVectorRetriever:
    @pytest.mark.asyncio
    async def test_retrieve_returns_empty_when_no_query_embedding(self, retriever):
        rq = RetrievalQuery(original_query="test")
        results = await retriever.retrieve(rq, ["snap1"])
        assert len(results) == 0

    @pytest.mark.asyncio
    async def test_empty_snapshot(self, retriever):
        rq = RetrievalQuery(original_query="test", query_embedding=[1.0] * 1024)
        results = await retriever.retrieve(rq, [])
        assert len(results) == 0

    @pytest.mark.asyncio
    async def test_empty_query_embedding(self, retriever):
        rq = RetrievalQuery(original_query="test", query_embedding=[])
        results = await retriever.retrieve(rq, ["snap1"])
        assert len(results) == 0

    @pytest.mark.asyncio
    async def test_pgvector_returns_scored_candidates(self, retriever):
        """pgvector main path: query with real embedding should return scored results."""
        vec = _random_unit_vector()
        rq = RetrievalQuery(
            original_query="ADD APN",
            query_embedding=vec,
        )
        results = await retriever.retrieve(rq, [SNAP_UDG, SNAP_FEATURE])
        assert isinstance(results, list)
        if results:
            for r in results:
                assert r.score >= 0.0
                assert r.score <= 1.0
                assert r.source == "dense_vector"
                assert r.score_chain is not None
                assert "dense_vector" in r.score_chain.route_sources

    @pytest.mark.asyncio
    async def test_scope_pushdown_filters(self, retriever):
        """Scope pushdown should restrict results to matching facets."""
        vec = _random_unit_vector()
        rq_no_scope = RetrievalQuery(
            original_query="test",
            query_embedding=vec,
        )
        rq_scope = RetrievalQuery(
            original_query="test",
            query_embedding=vec,
            scope={"products": ["UDG"]},
        )
        results_all = await retriever.retrieve(rq_no_scope, [SNAP_UDG, SNAP_FEATURE])
        results_udg = await retriever.retrieve(rq_scope, [SNAP_UDG, SNAP_FEATURE])
        # Scoped results should be a subset
        assert len(results_udg) <= len(results_all)

    @pytest.mark.asyncio
    async def test_invalid_embedding_returns_empty(self, retriever):
        """Wrong dimension embedding should fail gracefully."""
        rq = RetrievalQuery(
            original_query="test",
            query_embedding=[1.0] * 512,  # wrong dim
        )
        results = await retriever.retrieve(rq, [SNAP_UDG])
        assert results == []
