from __future__ import annotations

from pathlib import Path
from contextlib import asynccontextmanager
from types import SimpleNamespace

import pytest

import knowledge_mining.mining.document_lifecycle as lifecycle
import knowledge_mining.mining.api.routes.knowledge as knowledge_routes
from knowledge_mining.mining.document_lifecycle import (
    DocumentLifecycleService,
    LifecycleResourceNotFound,
)
from knowledge_mining.mining.stages.withdrawal import (
    ActiveResourceNotFound,
    WithdrawalResult,
)


class FakeAssetDB:
    def __init__(self, *, download_row=None, batch_rows=None):
        self.download_row = download_row
        self.batch_rows = batch_rows or []
        self.fetchone_calls: list[tuple[str, tuple]] = []
        self.fetchall_calls: list[tuple[str, tuple]] = []

    def _fetchone(self, sql: str, params: tuple):
        self.fetchone_calls.append((sql, params))
        return self.download_row

    def _fetchall(self, sql: str, params: tuple):
        self.fetchall_calls.append((sql, params))
        return self.batch_rows


def test_active_download_sql_locks_document_snapshot_domain_and_selection_batch(
    tmp_path: Path,
):
    root = tmp_path / "uploads"
    source = root / "odn" / "batch-a" / "report.pdf"
    source.parent.mkdir(parents=True)
    source.write_bytes(b"pdf")
    db = FakeAssetDB(
        download_row={
            "document_name": "report.pdf",
            "title": "Report",
            "mime_type": "application/pdf",
            "source_uri": str(source),
        }
    )

    result = lifecycle.resolve_active_download(
        db,
        upload_root=root,
        domain="odn",
        channel="preview",
        document_id="doc-a",
    )

    assert result.path == source.resolve()
    assert result.filename == "report.pdf"
    assert result.media_type == "application/pdf"
    sql, params = db.fetchone_calls[0]
    normalized = " ".join(sql.split()).lower()
    assert "releases.status = 'active'" in normalized
    assert "selections.selection_status = 'active'" in normalized
    assert "documents.domain = releases.domain" in normalized
    assert "snapshots.domain = releases.domain" in normalized
    assert "batches.domain = releases.domain" in normalized
    assert "selections.source_batch_id is null or batches.id is not null" in normalized
    assert (
        "links.source_batch_id is not distinct from selections.source_batch_id"
        in normalized
    )
    assert "order by links.linked_at desc" in normalized
    assert params == ("odn", "preview", "doc-a")


def test_active_download_translates_missing_row_and_unsafe_file_to_one_not_found(
    tmp_path: Path,
):
    root = tmp_path / "uploads"
    root.mkdir()

    with pytest.raises(LifecycleResourceNotFound):
        lifecycle.resolve_active_download(
            FakeAssetDB(),
            upload_root=root,
            domain="odn",
            channel="prod",
            document_id="missing",
        )

    with pytest.raises(LifecycleResourceNotFound):
        lifecycle.resolve_active_download(
            FakeAssetDB(
                download_row={
                    "document_name": "missing.pdf",
                    "mime_type": "application/pdf",
                    "source_uri": str(root / "missing.pdf"),
                }
            ),
            upload_root=root,
            domain="odn",
            channel="prod",
            document_id="doc-a",
        )


def test_list_active_batches_is_domain_channel_scoped_and_paginated():
    rows = [
        {
            "source_batch_id": "batch-a",
            "batch_code": "B-A",
            "mining_run_id": "run-a",
            "active_document_count": 2,
            "deletable": True,
            "unclassified": False,
        }
    ]
    db = FakeAssetDB(batch_rows=rows)

    result = lifecycle.list_active_batches(
        db, domain="odn", channel="prod", limit=10, offset=5
    )

    assert result == rows
    sql, params = db.fetchall_calls[0]
    normalized = " ".join(sql.split()).lower()
    assert "releases.status = 'active'" in normalized
    assert "documents.domain = releases.domain" in normalized
    assert "snapshots.domain = releases.domain" in normalized
    assert "group by selections.source_batch_id" in normalized
    assert params == ("odn", "prod", 10, 5)


def test_service_uses_registry_channel_for_document_and_batch_withdrawal(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
):
    db = FakeAssetDB()
    calls: list[tuple[str, dict]] = []

    def fake_document(asset_db, **kwargs):
        calls.append(("document", kwargs))
        return WithdrawalResult(kwargs["domain"], 1, "build-d", "release-d")

    def fake_batch(asset_db, **kwargs):
        calls.append(("batch", kwargs))
        return WithdrawalResult(kwargs["domain"], 2, "build-b", "release-b")

    monkeypatch.setattr(lifecycle, "remove_document", fake_document)
    monkeypatch.setattr(lifecycle, "remove_batch", fake_batch)
    service = DocumentLifecycleService(
        db, upload_root=tmp_path, channel="preview", actor="api-user"
    )

    document = service.remove_document(domain="odn", document_id="doc-a")
    batch = service.remove_batch(domain="odn", source_batch_id="batch-a")

    assert document.release_id == "release-d"
    assert batch.release_id == "release-b"
    assert calls == [
        (
            "document",
            {
                "domain": "odn",
                "channel": "preview",
                "document_id": "doc-a",
                "actor": "api-user",
            },
        ),
        (
            "batch",
            {
                "domain": "odn",
                "channel": "preview",
                "source_batch_id": "batch-a",
                "actor": "api-user",
            },
        ),
    ]


def test_service_translates_repeated_withdrawal_to_uniform_not_found(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
):
    def missing(*args, **kwargs):
        raise ActiveResourceNotFound("internal detail")

    monkeypatch.setattr(lifecycle, "_withdraw_document", missing)
    monkeypatch.setattr(lifecycle, "_withdraw_source_batch", missing)
    service = DocumentLifecycleService(
        FakeAssetDB(), upload_root=tmp_path, channel="prod"
    )

    with pytest.raises(LifecycleResourceNotFound):
        service.remove_document(domain="odn", document_id="doc-a")
    with pytest.raises(LifecycleResourceNotFound):
        service.remove_batch(domain="odn", source_batch_id="batch-a")


@pytest.mark.asyncio
async def test_batches_endpoint_uses_registry_default_channel(monkeypatch):
    class Cursor:
        async def fetchall(self):
            return []

    class Connection:
        def __init__(self):
            self.params = None

        async def execute(self, sql, params):
            self.params = params
            return Cursor()

    class Pool:
        def __init__(self):
            self.conn = Connection()

        @asynccontextmanager
        async def connection(self):
            yield self.conn

    pool = Pool()
    monkeypatch.setattr(
        knowledge_routes,
        "resolve_domain",
        lambda domain: {"default_channel": "preview"},
        raising=False,
    )

    async def fake_pool(request, domain):
        return pool

    monkeypatch.setattr(knowledge_routes, "get_domain_async_pool", fake_pool)

    await knowledge_routes.list_batches(
        SimpleNamespace(), domain="odn", limit=10, offset=5
    )

    # active-scope params are document domain, snapshot domain, release domain,
    # then release channel.
    assert pool.conn.params[3] == "preview"
    assert pool.conn.params[-2:] == [10, 5]
