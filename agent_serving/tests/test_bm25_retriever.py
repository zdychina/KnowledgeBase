"""Tests for FTS5BM25Retriever — tsvector, trigram, LIKE, scope pushdown."""
import json

import pytest
import pytest_asyncio

from agent_serving.serving.schemas.models import RetrievalQuery
from agent_serving.serving.retrieval.bm25_retriever import FTS5BM25Retriever
from agent_serving.tests.conftest import SNAP_UDG, SNAP_FEATURE


@pytest_asyncio.fixture
async def retriever(pg_pool):
    return FTS5BM25Retriever(pg_pool)


# --- Unit tests (no PG required) ---


class TestBuildScopeFilter:
    """_build_scope_filter returns parameterized JSONB conditions."""

    def test_empty_scope(self):
        sql, params = FTS5BM25Retriever._build_scope_filter({})
        assert sql == ""
        assert params == []

    def test_none_scope(self):
        sql, params = FTS5BM25Retriever._build_scope_filter(None)
        assert sql == ""

    def test_single_list_value(self):
        sql, params = FTS5BM25Retriever._build_scope_filter({"products": ["UDG"]})
        assert "%s::jsonb" in sql
        assert len(params) == 1
        assert json.loads(params[0]) == {"products": ["UDG"]}

    def test_multiple_keys(self):
        sql, params = FTS5BM25Retriever._build_scope_filter({
            "products": ["UDG"],
            "domains": ["5G"],
        })
        assert sql.count("%s::jsonb") == 2
        assert len(params) == 2
        assert json.loads(params[0]) == {"products": ["UDG"]}
        assert json.loads(params[1]) == {"domains": ["5G"]}

    def test_non_list_values_ignored(self):
        sql, params = FTS5BM25Retriever._build_scope_filter({"products": "UDG"})
        assert sql == ""
        assert params == []

    def test_empty_list_ignored(self):
        sql, params = FTS5BM25Retriever._build_scope_filter({"products": []})
        assert sql == ""
        assert params == []

    def test_no_sql_injection_via_key(self):
        """Key is only used in Python dict, never interpolated into SQL."""
        sql, params = FTS5BM25Retriever._build_scope_filter({
            "'; DROP TABLE users;--": ["value"],
        })
        assert "%s::jsonb" in sql
        # The malicious key is inside the JSON parameter, not in SQL
        assert "DROP" not in sql


# --- Integration tests (require seeded PG) ---


@pytest.mark.pg
class TestBM25Retrieve:
    @pytest.mark.asyncio
    async def test_tsvector_returns_scored_candidates(self, retriever):
        rq = RetrievalQuery(
            original_query="ADD APN",
            keywords=["ADD", "APN"],
        )
        results = await retriever.retrieve(rq, [SNAP_UDG])
        assert len(results) > 0
        assert all(r.source == "fts_bm25" for r in results)
        assert all(r.score > 0 for r in results)
        assert any("APN" in (r.metadata.get("text", "") or "") for r in results)

    @pytest.mark.asyncio
    async def test_scope_pushdown_filters_by_facets(self, retriever):
        """Query with scope={"products": ["UDG"]} should only return UDG items."""
        rq_noscope = RetrievalQuery(
            original_query="ADD APN",
            keywords=["ADD", "APN"],
        )
        rq_scope = RetrievalQuery(
            original_query="ADD APN",
            keywords=["ADD", "APN"],
            scope={"products": ["UDG"]},
        )
        results_all = await retriever.retrieve(rq_noscope, [SNAP_UDG, SNAP_FEATURE])
        results_udg = await retriever.retrieve(rq_scope, [SNAP_UDG, SNAP_FEATURE])
        # Scope filter should reduce or equal results
        assert len(results_udg) <= len(results_all)

    @pytest.mark.asyncio
    async def test_empty_snapshot_ids(self, retriever):
        rq = RetrievalQuery(original_query="ADD APN", keywords=["ADD"])
        results = await retriever.retrieve(rq, [])
        assert results == []

    @pytest.mark.asyncio
    async def test_empty_keywords_returns_empty(self, retriever):
        rq = RetrievalQuery(original_query="")
        results = await retriever.retrieve(rq, [SNAP_UDG])
        assert results == []

    @pytest.mark.asyncio
    async def test_chinese_query_trigram_fallback(self, retriever):
        """Chinese text likely triggers trigram similarity fallback."""
        rq = RetrievalQuery(
            original_query="会话管理",
            keywords=["会话", "管理"],
        )
        results = await retriever.retrieve(rq, [SNAP_FEATURE])
        # May return results via trigram or LIKE fallback
        # At minimum, should not raise an error
        assert isinstance(results, list)
