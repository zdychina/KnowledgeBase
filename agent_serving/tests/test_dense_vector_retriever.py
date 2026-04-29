"""Tests for DenseVectorRetriever."""
import json

import pytest
import pytest_asyncio
import aiosqlite

from agent_serving.serving.schemas.models import RetrievalQuery
from agent_serving.serving.retrieval.dense_vector_retriever import (
    DenseVectorRetriever,
    _cosine_similarity_matrix,
)
from agent_serving.serving.repositories.schema_adapter import create_asset_tables_sqlite
from agent_serving.tests.conftest import _seed_v11_data


def _make_embedding(dim=8):
    """Create a simple test embedding vector."""
    import math
    return [1.0 / math.sqrt(dim)] * dim


@pytest_asyncio.fixture
async def db_with_embeddings():
    db = await aiosqlite.connect(":memory:")
    db.row_factory = aiosqlite.Row
    await create_asset_tables_sqlite(db)
    await _seed_v11_data(db)

    # Insert test embeddings (real table already created by shared DDL)
    now = "2026-04-21T00:00:00Z"
    vec1 = json.dumps(_make_embedding(8))

    await db.execute(
        "INSERT INTO asset_retrieval_embeddings "
        "(id, retrieval_unit_id, embedding_model, embedding_provider, text_kind, "
        "embedding_dim, embedding_vector, content_hash, created_at) "
        "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)",
        ("emb-0001", "eeee0000-0000-0000-0000-000000000001", "test", "zhipu",
         "retrieval_unit", 8, vec1, "hash1", now),
    )
    await db.execute(
        "INSERT INTO asset_retrieval_embeddings "
        "(id, retrieval_unit_id, embedding_model, embedding_provider, text_kind, "
        "embedding_dim, embedding_vector, content_hash, created_at) "
        "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)",
        ("emb-0005", "eeee0000-0000-0000-0000-000000000005", "test", "zhipu",
         "retrieval_unit", 8, vec1, "hash5", now),
    )
    await db.commit()
    yield db
    await db.close()


class TestDenseVectorRetriever:
    @pytest.mark.asyncio
    async def test_retrieve_with_query(self, db_with_embeddings):
        retriever = DenseVectorRetriever(db_with_embeddings)
        query_vec = _make_embedding(8)
        snapshot_ids = ["aaaa0000-0000-0000-0000-000000000001"]
        rq = RetrievalQuery(original_query="test", query_embedding=query_vec)
        results = await retriever.retrieve(rq, snapshot_ids)
        assert len(results) > 0
        assert results[0].source == "dense_vector"

    @pytest.mark.asyncio
    async def test_score_chain(self, db_with_embeddings):
        retriever = DenseVectorRetriever(db_with_embeddings)
        query_vec = _make_embedding(8)
        snapshot_ids = ["aaaa0000-0000-0000-0000-000000000001"]
        rq = RetrievalQuery(original_query="test", query_embedding=query_vec)
        results = await retriever.retrieve(rq, snapshot_ids)
        for r in results:
            assert r.score_chain is not None
            assert "dense_vector" in r.score_chain.route_sources

    @pytest.mark.asyncio
    async def test_empty_query(self, db_with_embeddings):
        retriever = DenseVectorRetriever(db_with_embeddings)
        rq = RetrievalQuery(original_query="test", query_embedding=[])
        results = await retriever.retrieve(rq, ["snap1"])
        assert len(results) == 0

    @pytest.mark.asyncio
    async def test_no_embedding_auto_skip(self, db_with_embeddings):
        retriever = DenseVectorRetriever(db_with_embeddings)
        rq = RetrievalQuery(original_query="test")  # no query_embedding
        results = await retriever.retrieve(rq, ["snap1"])
        assert len(results) == 0

    @pytest.mark.asyncio
    async def test_empty_snapshot(self, db_with_embeddings):
        retriever = DenseVectorRetriever(db_with_embeddings)
        rq = RetrievalQuery(original_query="test", query_embedding=[1.0] * 8)
        results = await retriever.retrieve(rq, [])
        assert len(results) == 0

    @pytest.mark.asyncio
    async def test_cache_invalidation(self, db_with_embeddings):
        retriever = DenseVectorRetriever(db_with_embeddings)
        retriever._cache["test"] = []
        retriever.invalidate_cache()
        assert len(retriever._cache) == 0

    def test_cosine_similarity_identical(self):
        vec = [1.0, 0.0, 0.0]
        matrix = [[1.0, 0.0, 0.0]]
        result = _cosine_similarity_matrix(vec, matrix)
        assert abs(result[0] - 1.0) < 0.001

    def test_cosine_similarity_orthogonal(self):
        vec = [1.0, 0.0]
        matrix = [[0.0, 1.0]]
        result = _cosine_similarity_matrix(vec, matrix)
        assert abs(result[0]) < 0.001

    def test_cosine_similarity_zero_query(self):
        vec = [0.0, 0.0]
        matrix = [[1.0, 0.0]]
        result = _cosine_similarity_matrix(vec, matrix)
        assert result[0] == 0.0
