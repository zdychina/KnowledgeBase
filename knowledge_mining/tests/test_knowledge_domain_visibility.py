from __future__ import annotations

from contextlib import asynccontextmanager
from dataclasses import dataclass
from typing import Any

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from knowledge_mining.mining.api.routes import knowledge as knowledge_routes
from knowledge_mining.mining.api.routes.knowledge import router


KNOWLEDGE_ENDPOINTS = (
    "/api/knowledge/stats",
    "/api/knowledge/documents",
    "/api/knowledge/documents/doc-active",
    "/api/knowledge/documents/doc-active/segments",
    "/api/knowledge/documents/doc-active/units",
    "/api/knowledge/documents/doc-active/relations",
    "/api/knowledge/segments",
    "/api/knowledge/units",
    "/api/knowledge/relations",
    "/api/knowledge/batches",
)

ACTIVE_SCOPE_FRAGMENTS = (
    "r.domain = %s",
    "r.channel = %s",
    "r.status = 'active'",
    "bs.selection_status = 'active'",
    "d.domain = %s",
    "s.domain = %s",
)

RESOURCE_IDS = {
    "documents": ("doc-active", "doc-removed", "doc-legacy", "doc-cross"),
    "segments": ("seg-active", "seg-removed", "seg-legacy", "seg-cross"),
    "units": ("unit-active", "unit-removed", "unit-legacy", "unit-cross"),
    "relations": ("rel-active", "rel-removed", "rel-legacy", "rel-cross"),
}


def _has_active_scope(sql: str) -> bool:
    return "SELECT DISTINCT" in sql and all(
        fragment in sql for fragment in ACTIVE_SCOPE_FRAGMENTS
    )


class _Cursor:
    def __init__(self, *, row: dict[str, Any] | None = None, rows=None):
        self._row = row
        self._rows = list(rows or [])

    async def fetchone(self):
        return self._row if self._row is not None else (self._rows[0] if self._rows else None)

    async def fetchall(self):
        return list(self._rows)


class _Connection:
    def __init__(self):
        self.statements: list[tuple[str, list[Any]]] = []

    async def execute(self, sql, params=()):
        sql = str(sql)
        params = list(params)
        self.statements.append((sql, params))
        scoped = _has_active_scope(sql)

        if "AS documents" in sql and "AS retrieval_units" in sql:
            visible = 1 if scoped else 4
            return _Cursor(row={
                "documents": visible,
                "snapshots": visible,
                "segments": visible,
                "relations": visible,
                "retrieval_units": visible,
                "embeddings": visible,
                "builds": 1,
                "releases": 1,
            })
        if "GROUP BY u.unit_type" in sql:
            return _Cursor(rows=[{"unit_type": "raw_text", "c": 1}])
        if "SELECT DISTINCT r.id, r.build_id" in sql:
            return _Cursor(rows=[{
                "id": "release-active",
                "build_id": "build-active",
                "domain": "odn",
                "channel": "prod",
            }])
        if "active_document_count" in sql:
            return _Cursor(rows=[
                {
                    "source_batch_id": "batch-active",
                    "batch_code": "BATCH-ACTIVE",
                    "mining_run_id": "run-active",
                    "active_document_count": 1,
                    "created_at": "2026-07-20T00:00:00Z",
                    "deletable": True,
                    "unclassified": False,
                },
                {
                    "source_batch_id": None,
                    "batch_code": None,
                    "mining_run_id": None,
                    "active_document_count": 1,
                    "created_at": None,
                    "deletable": False,
                    "unclassified": True,
                },
            ])
        if "COUNT(" in sql:
            return _Cursor(row={"c": 1 if scoped else 4})
        if "SELECT scope.document_snapshot_id" in sql:
            return _Cursor(row={"document_snapshot_id": "snapshot-active"})
        if "normalized_content_hash" in sql:
            return _Cursor(rows=[{
                "id": "snapshot-active",
                "title": "Active",
                "normalized_content_hash": "active-hash",
                "mime_type": "text/plain",
                "created_at": "2026-07-20T00:00:00Z",
                "linked_at": "2026-07-20T00:00:00Z",
                "relative_path": "active.txt",
                "source_uri": None,
            }])
        if "document_key" in sql and "ORDER BY d.created_at" not in sql:
            return _Cursor(row={
                "id": "doc-active",
                "document_key": "doc:/active",
                "document_name": "active.txt",
                "document_type": "reference",
                "created_at": "2026-07-20T00:00:00Z",
                "source_batch_id": "batch-active",
                "batch_code": "BATCH-ACTIVE",
            })
        if "raw_text_preview" in sql:
            return _Cursor(rows=self._resource_rows("segments", scoped))
        if "text_preview" in sql:
            return _Cursor(rows=self._resource_rows("units", scoped))
        if "source_text" in sql and "document_snapshot_id" in sql:
            return _Cursor(rows=self._resource_rows("relations", scoped))
        if "ORDER BY d.created_at" in sql:
            return _Cursor(rows=self._resource_rows("documents", scoped))
        if "SELECT DISTINCT r.id AS release_id" in sql:
            return _Cursor(rows=[])
        return _Cursor(rows=[])

    @staticmethod
    def _resource_rows(resource: str, scoped: bool) -> list[dict[str, Any]]:
        ids = RESOURCE_IDS[resource][:1] if scoped else RESOURCE_IDS[resource]
        return [{"id": value} for value in ids]


class _Pool:
    def __init__(self):
        self.conn = _Connection()

    @asynccontextmanager
    async def connection(self):
        yield self.conn


class _DomainPools:
    def __init__(self, pool: _Pool):
        self.pool = pool
        self.domains: list[str] = []

    async def async_pool(self, domain: str):
        self.domains.append(domain)
        return self.pool


@dataclass
class _ApiHarness:
    client: TestClient
    pool: _Pool
    domain_pools: _DomainPools


@pytest.fixture
def api() -> _ApiHarness:
    app = FastAPI()
    app.include_router(router)
    pool = _Pool()
    domain_pools = _DomainPools(pool)
    # The global pool is present only so the pre-Task-8 implementation can run
    # far enough to produce a behavioral RED instead of a setup exception.
    app.state.pg_pool = pool
    app.state.domain_pools = domain_pools
    return _ApiHarness(
        TestClient(app, raise_server_exceptions=False), pool, domain_pools
    )


@pytest.mark.parametrize("url", KNOWLEDGE_ENDPOINTS)
@pytest.mark.parametrize("params", ({}, {"domain": "   "}))
def test_all_knowledge_endpoints_require_nonblank_domain(api, url, params):
    response = api.client.get(url, params=params)
    assert response.status_code == 422


def test_knowledge_route_uses_requested_domain_pool_without_global_pool():
    app = FastAPI()
    app.include_router(router)
    pool = _Pool()
    domain_pools = _DomainPools(pool)
    app.state.domain_pools = domain_pools

    with TestClient(app, raise_server_exceptions=False) as client:
        response = client.get(
            "/api/knowledge/documents", params={"domain": "odn"}
        )

    assert response.status_code == 200
    assert domain_pools.domains == ["odn"]


@pytest.mark.parametrize("resource", ("documents", "segments", "units", "relations"))
def test_knowledge_lists_hide_removed_legacy_and_cross_domain_assets(api, resource):
    response = api.client.get(
        f"/api/knowledge/{resource}", params={"domain": "odn"}
    )

    assert response.status_code == 200
    assert {item["id"] for item in response.json()["items"]} == {
        RESOURCE_IDS[resource][0]
    }


def test_every_knowledge_query_uses_complete_distinct_active_scope(api):
    for url in KNOWLEDGE_ENDPOINTS:
        response = api.client.get(url, params={"domain": "odn"})
        assert response.status_code == 200, (url, response.text)

    assert api.pool.conn.statements
    for sql, params in api.pool.conn.statements:
        if (
            "FROM asset_publish_releases r" in sql
            and "JOIN asset_builds b" in sql
            and "asset_build_document_snapshots" not in sql
        ):
            assert "r.status = 'active'" in sql, sql
            assert params == ["odn", "odn", "prod"]
        else:
            assert _has_active_scope(sql), sql
            assert params.count("odn") >= 3, (sql, params)
            assert "prod" in params, (sql, params)


def test_documents_filter_source_batch_in_database_before_pagination(api):
    response = api.client.get(
        "/api/knowledge/documents",
        params={
            "domain": "odn",
            "source_batch_id": "batch-active",
            "limit": 1,
            "offset": 20,
        },
    )

    assert response.status_code == 200
    document_sql = [
        (sql, params)
        for sql, params in api.pool.conn.statements
        if "asset_documents" in sql
    ]
    assert len(document_sql) == 2
    for sql, params in document_sql:
        assert "scope.source_batch_id = %s" in sql
        assert "batch-active" in params
    assert document_sql[-1][1][-2:] == [1, 20]


def test_documents_filter_unclassified_in_database_and_rejects_mixed_filter(api):
    response = api.client.get(
        "/api/knowledge/documents",
        params={"domain": "odn", "unclassified": "true"},
    )

    assert response.status_code == 200
    assert api.pool.conn.statements
    assert all(
        "scope.source_batch_id IS NULL" in sql
        for sql, _ in api.pool.conn.statements
    )

    mixed = api.client.get(
        "/api/knowledge/documents",
        params={
            "domain": "odn",
            "source_batch_id": "batch-active",
            "unclassified": "true",
        },
    )
    assert mixed.status_code == 422


def test_batches_aggregate_active_documents_and_keep_unclassified_without_magic_id(api):
    response = api.client.get(
        "/api/knowledge/batches", params={"domain": "odn"}
    )

    assert response.status_code == 200
    assert response.json() == {
        "items": [
            {
                "source_batch_id": "batch-active",
                "batch_code": "BATCH-ACTIVE",
                "mining_run_id": "run-active",
                "active_document_count": 1,
                "created_at": "2026-07-20T00:00:00Z",
                "deletable": True,
                "unclassified": False,
            },
            {
                "source_batch_id": None,
                "batch_code": None,
                "mining_run_id": None,
                "active_document_count": 1,
                "created_at": None,
                "deletable": False,
                "unclassified": True,
            },
        ]
    }
    sql, params = api.pool.conn.statements[-1]
    assert "COUNT(DISTINCT scope.document_id) AS active_document_count" in sql
    assert "scope.source_batch_id IS NOT NULL AS deletable" in sql
    assert "scope.source_batch_id IS NULL AS unclassified" in sql
    assert params.count("odn") >= 3


def test_knowledge_queries_default_to_registry_channel(api, monkeypatch):
    monkeypatch.setattr(
        knowledge_routes,
        "resolve_domain",
        lambda domain: {"default_channel": "preview"},
    )

    response = api.client.get(
        "/api/knowledge/documents", params={"domain": "odn"}
    )

    assert response.status_code == 200
    assert api.pool.conn.statements
    assert all("preview" in params for _, params in api.pool.conn.statements)
    assert all("prod" not in params for _, params in api.pool.conn.statements)


def test_document_detail_does_not_expose_managed_server_paths(api):
    response = api.client.get(
        "/api/knowledge/documents/doc-active", params={"domain": "odn"}
    )

    assert response.status_code == 200
    for snapshot in response.json()["snapshots"]:
        assert "source_uri" not in snapshot
        assert "relative_path" not in snapshot


def test_stats_reads_active_release_even_when_build_has_no_active_selection(api):
    response = api.client.get(
        "/api/knowledge/stats", params={"domain": "odn"}
    )

    assert response.status_code == 200
    release_queries = [
        (sql, params)
        for sql, params in api.pool.conn.statements
        if "FROM asset_publish_releases r" in sql
        and "JOIN asset_builds b" in sql
        and "asset_build_document_snapshots" not in sql
    ]
    assert len(release_queries) == 1
    sql, params = release_queries[0]
    assert "r.status = 'active'" in sql
    assert params == ["odn", "odn", "prod"]
