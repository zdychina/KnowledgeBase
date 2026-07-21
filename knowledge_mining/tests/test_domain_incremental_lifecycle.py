"""Focused contracts for domain-aware incremental document lifecycle."""
from __future__ import annotations

from typing import Any
from types import SimpleNamespace

import pytest

from knowledge_mining.mining.infra.db import AssetCoreDB
from knowledge_mining.mining.jobs import run as run_job
from knowledge_mining.mining.contracts.models import BatchParams, RawFileData


def _state(**overrides: Any) -> dict[str, Any]:
    state = {
        "document_id": "doc-odn",
        "document_domain": "odn",
        "document_key": "doc:/same.md",
        "historical_snapshot_id": None,
        "historical_snapshot_hash": None,
        "historical_link_id": None,
        "historical_source_batch_id": None,
        "historical_snapshot_complete": False,
        "active_release_id": None,
        "active_build_id": None,
        "active_snapshot_id": None,
        "active_snapshot_hash": None,
        "active_source_batch_id": None,
        "active_snapshot_complete": False,
    }
    state.update(overrides)
    return state


@pytest.mark.parametrize(
    ("state", "incoming_hash", "expected"),
    [
        pytest.param(None, "h1", "NEW", id="no-domain-document-is-new"),
        pytest.param(
            _state(
                historical_snapshot_id="snap-h1",
                historical_snapshot_hash="h1",
                historical_snapshot_complete=True,
                active_snapshot_id="snap-h1",
                active_snapshot_hash="h1",
                active_snapshot_complete=True,
            ),
            "h1",
            "SKIP",
            id="complete-active-same-hash-skips",
        ),
        pytest.param(
            _state(
                historical_snapshot_id="snap-h1",
                historical_snapshot_hash="h1",
                historical_snapshot_complete=True,
            ),
            "h1",
            "RESTORE",
            id="complete-history-without-active-selection-restores",
        ),
        pytest.param(
            _state(active_snapshot_id="snap-h2", active_snapshot_hash="h2", active_snapshot_complete=True),
            "h1",
            "UPDATE",
            id="different-active-hash-updates",
        ),
        pytest.param(
            _state(
                historical_snapshot_id="snap-shell",
                historical_snapshot_hash="h1",
                historical_snapshot_complete=False,
            ),
            "h1",
            "UPDATE",
            id="incomplete-historical-shell-is-remined",
        ),
        pytest.param(
            _state(
                historical_snapshot_id="snap-h1",
                historical_snapshot_hash="h1",
                historical_snapshot_complete=True,
                active_snapshot_id="snap-h2",
                active_snapshot_hash="h2",
                active_snapshot_complete=True,
            ),
            "h1",
            "UPDATE",
            id="h1-after-active-h2-is-update-not-restore",
        ),
        pytest.param(_state(), "h1", "UPDATE", id="existing-document-without-history-updates"),
    ],
)
def test_lifecycle_decision_matrix(
    state: dict[str, Any] | None,
    incoming_hash: str,
    expected: str,
) -> None:
    assert run_job.decide_document_lifecycle_action(
        state,
        normalized_content_hash=incoming_hash,
    ) == expected


class _RecordingAssetDB(AssetCoreDB):
    def __init__(self, result: dict[str, Any] | None) -> None:
        self.result = result
        self.calls: list[tuple[str, tuple[Any, ...]]] = []

    def _fetchone(self, sql: str, params: tuple[Any, ...] = ()) -> dict[str, Any] | None:
        self.calls.append((sql, params))
        return self.result


def test_lifecycle_query_uses_active_release_and_domain_scoped_assets() -> None:
    expected = _state(
        historical_snapshot_id="snap-h1",
        historical_snapshot_hash="h1",
        historical_link_id="link-old",
        historical_source_batch_id="batch-old",
        historical_snapshot_complete=True,
        active_release_id="release-active",
        active_build_id="build-active",
        active_snapshot_id="snap-h2",
        active_snapshot_hash="h2",
        active_source_batch_id="batch-active",
        active_snapshot_complete=True,
    )
    db = _RecordingAssetDB(expected)

    actual = db.get_document_lifecycle_state(
        domain="odn",
        channel="prod",
        document_key="doc:/same.md",
        normalized_content_hash="h1",
    )

    assert actual == expected
    assert len(db.calls) == 1
    sql, params = db.calls[0]
    normalized_sql = " ".join(sql.lower().split())
    assert "asset_publish_releases" in normalized_sql
    assert "releases.status = 'active'" in normalized_sql
    assert "releases.domain = %s" in normalized_sql
    assert "releases.channel = %s" in normalized_sql
    assert "builds.domain = %s" in normalized_sql
    assert "selections.selection_status = 'active'" in normalized_sql
    assert "selections.source_batch_id is null or active_batches.id is not null" in normalized_sql
    assert "documents.domain = %s" in normalized_sql
    assert "historical_snapshots.domain = %s" in normalized_sql
    assert "active_snapshots.domain = %s" in normalized_sql
    assert "order by builds.created_at" not in normalized_sql
    assert "odn" in params
    assert "prod" in params
    assert "h1" in params
    assert "__legacy_shared__" not in params


def test_lifecycle_query_is_keyword_only() -> None:
    db = _RecordingAssetDB(None)

    with pytest.raises(TypeError):
        db.get_document_lifecycle_state("odn", "prod", "doc:/same.md", "h1")  # type: ignore[misc]


class _PhaseAssetDB:
    def __init__(self, state: dict[str, Any] | None) -> None:
        self.pool = object()
        self.state = state
        self.lifecycle_calls: list[dict[str, Any]] = []
        self.source_batches: list[dict[str, Any]] = []
        self.links: list[dict[str, Any]] = []

    def upsert_source_batch(self, **kwargs: Any) -> str:
        self.source_batches.append(kwargs)
        return kwargs["batch_id"]

    def get_document_lifecycle_state(self, **kwargs: Any) -> dict[str, Any] | None:
        self.lifecycle_calls.append(kwargs)
        return self.state

    def insert_snapshot_link(self, **kwargs: Any) -> str:
        self.links.append(kwargs)
        return kwargs["link_id"]

    def commit(self) -> None:
        return None


class _PhaseRuntimeDB:
    def __init__(self) -> None:
        self.documents: dict[str, dict[str, Any]] = {}
        self.source_batch_id: str | None = None

    def _fetchone(self, sql: str, params: tuple[Any, ...] = ()) -> dict[str, Any]:
        return {"status": "running"}

    def _execute(self, sql: str, params: tuple[Any, ...] = ()) -> None:
        if sql.startswith("UPDATE mining_runs SET source_batch_id"):
            self.source_batch_id = params[0]

    def insert_run_document(self, data: Any) -> str:
        self.documents[data.id] = dict(data.__dict__)
        return data.id

    def update_run_document(self, rd_id: str, **changes: Any) -> None:
        self.documents[rd_id].update({key: value for key, value in changes.items() if value is not None})

    def commit(self) -> None:
        return None


def _raw_doc(*, content_hash: str = "h1") -> RawFileData:
    return RawFileData(
        file_path="C:/input/same.md",
        relative_path="same.md",
        file_name="same.md",
        file_type="markdown",
        content="# Same\n\nBody.",
        raw_content_hash=f"raw-{content_hash}",
        normalized_content_hash=content_hash,
        file_size=17,
        source_uri="file:///input/same.md",
        title="Current title",
        scope_json={"site": "current"},
        tags_json=["current"],
    )


def _run_focused_phase1(
    monkeypatch: pytest.MonkeyPatch,
    *,
    state: dict[str, Any] | None,
    domain: str = "odn",
    channel: str | None = "prod",
    pipeline_document_id: str = "doc-new",
    pipeline_snapshot_id: str = "snap-new",
) -> tuple[dict[str, Any], _PhaseAssetDB, _PhaseRuntimeDB, list[Any]]:
    from knowledge_mining.mining.infra import ontology_store

    asset_db = _PhaseAssetDB(state)
    runtime_db = _PhaseRuntimeDB()
    pipeline_contexts: list[Any] = []

    monkeypatch.setattr(ontology_store.OntologyStore, "active_version", lambda self, domain: None)

    class SpyPipeline:
        def __init__(self, stages, **kwargs):
            self.stages = stages

        def process_all(self, contexts):
            pipeline_contexts.extend(contexts)
            return [
                ctx.with_updates(
                    document_id=(state or {}).get("document_id") or pipeline_document_id,
                    snapshot_id=pipeline_snapshot_id,
                )
                for ctx in contexts
            ]

    monkeypatch.setattr(run_job, "StreamingPipeline", SpyPipeline)

    captured: dict[str, Any] = {}

    def capture_finalize(*args, **kwargs):
        captured["batch_id"] = args[4]
        captured["decisions"] = args[5]
        captured["counts"] = args[6]
        return captured

    monkeypatch.setattr(run_job, "_finalize_run", capture_finalize)

    result = run_job._run_pipeline(
        asset_db,
        runtime_db,
        input_path=SimpleNamespace(),
        params=BatchParams(),
        phase1_only=True,
        run_id="run-focused",
        llm_services={},
        embedding_generator=None,
        profile=SimpleNamespace(domain_id=domain),
        channel=channel,
        docs=[_raw_doc()],
        ingest_summary={},
    )
    return result, asset_db, runtime_db, pipeline_contexts


def test_phase1_plain_skip_keeps_active_batch_without_link_or_pipeline(monkeypatch) -> None:
    state = _state(
        historical_snapshot_id="snap-h1",
        historical_snapshot_hash="h1",
        historical_snapshot_complete=True,
        active_snapshot_id="snap-h1",
        active_snapshot_hash="h1",
        active_source_batch_id="batch-active",
        active_snapshot_complete=True,
    )

    result, asset_db, runtime_db, pipeline_contexts = _run_focused_phase1(
        monkeypatch,
        state=state,
        channel=None,
    )

    assert asset_db.lifecycle_calls == [{
        "domain": "odn",
        "channel": "prod",
        "document_key": "doc:/same.md",
        "normalized_content_hash": "h1",
    }]
    assert pipeline_contexts == []
    assert asset_db.links == []
    assert result["counts"]["committed_count"] == 0
    assert result["counts"]["skipped_count"] == 1
    assert result["decisions"] == [{
        "document_id": "doc-odn",
        "document_snapshot_id": "snap-h1",
        "document_key": "doc:/same.md",
        "lifecycle_action": "SKIP",
        "source_batch_id": "batch-active",
    }]
    runtime_row = next(iter(runtime_db.documents.values()))
    assert runtime_row["action"] == "SKIP"
    assert runtime_row["metadata_json"] == {"file_size": 17, "source_batch_id": "batch-active"}


def test_phase1_restore_links_current_batch_without_pipeline(monkeypatch) -> None:
    state = _state(
        historical_snapshot_id="snap-h1",
        historical_snapshot_hash="h1",
        historical_link_id="link-old",
        historical_source_batch_id="batch-old",
        historical_snapshot_complete=True,
    )

    result, asset_db, runtime_db, pipeline_contexts = _run_focused_phase1(
        monkeypatch,
        state=state,
    )

    assert pipeline_contexts == []
    assert len(asset_db.links) == 1
    assert asset_db.links[0] == {
        "domain": "odn",
        "link_id": asset_db.links[0]["link_id"],
        "document_id": "doc-odn",
        "document_snapshot_id": "snap-h1",
        "source_batch_id": result["batch_id"],
        "relative_path": "same.md",
        "source_uri": "file:///input/same.md",
        "title": "Current title",
        "scope_json": {"site": "current"},
        "tags_json": ["current"],
        "metadata_json": {},
    }
    assert result["counts"]["committed_count"] == 0
    assert result["counts"]["skipped_count"] == 1
    assert result["decisions"] == [{
        "document_id": "doc-odn",
        "document_snapshot_id": "snap-h1",
        "document_key": "doc:/same.md",
        "lifecycle_action": "RESTORE",
        "source_batch_id": result["batch_id"],
    }]
    runtime_row = next(iter(runtime_db.documents.values()))
    assert runtime_row["action"] == "SKIP"
    assert runtime_row["metadata_json"] == {
        "file_size": 17,
        "lifecycle_action": "RESTORE",
        "source_batch_id": result["batch_id"],
    }


@pytest.mark.parametrize(
    "state",
    [
        _state(
            historical_snapshot_id="snap-shell",
            historical_snapshot_hash="h1",
            historical_snapshot_complete=False,
        ),
        _state(
            historical_snapshot_id="snap-h1",
            historical_snapshot_hash="h1",
            historical_snapshot_complete=True,
            active_snapshot_id="snap-h2",
            active_snapshot_hash="h2",
            active_snapshot_complete=True,
        ),
    ],
    ids=["incomplete-shell", "historical-h1-behind-active-h2"],
)
def test_phase1_update_cases_enter_pipeline(monkeypatch, state) -> None:
    result, asset_db, runtime_db, pipeline_contexts = _run_focused_phase1(
        monkeypatch,
        state=state,
        pipeline_snapshot_id="snap-h1",
    )

    assert len(pipeline_contexts) == 1
    assert pipeline_contexts[0].action == "UPDATE"
    assert asset_db.links == []
    assert result["counts"]["committed_count"] == 1
    assert result["counts"]["updated_count"] == 1
    runtime_row = next(iter(runtime_db.documents.values()))
    assert runtime_row["action"] == "UPDATE"


def test_same_key_and_hash_are_new_and_independently_mined_in_each_domain(monkeypatch) -> None:
    odn, odn_db, _, odn_contexts = _run_focused_phase1(
        monkeypatch,
        state=None,
        domain="odn",
        pipeline_document_id="doc-odn",
        pipeline_snapshot_id="snap-odn",
    )
    civil, civil_db, _, civil_contexts = _run_focused_phase1(
        monkeypatch,
        state=None,
        domain="civil_engineering",
        pipeline_document_id="doc-civil",
        pipeline_snapshot_id="snap-civil",
    )

    assert odn_contexts[0].action == "NEW"
    assert civil_contexts[0].action == "NEW"
    assert odn_db.lifecycle_calls[0]["domain"] == "odn"
    assert civil_db.lifecycle_calls[0]["domain"] == "civil_engineering"
    assert odn["decisions"][0]["document_id"] != civil["decisions"][0]["document_id"]
    assert odn["decisions"][0]["document_snapshot_id"] != civil["decisions"][0]["document_snapshot_id"]


def test_legacy_shared_assets_are_invisible_and_classify_as_new() -> None:
    # The lifecycle repository is queried with an exact business domain; a
    # legacy-only repository therefore returns no state for that domain.
    assert run_job.decide_document_lifecycle_action(
        None,
        normalized_content_hash="legacy-hash",
    ) == "NEW"


def _seed_batch(asset_db: AssetCoreDB, *, domain: str, batch_id: str) -> None:
    asset_db.upsert_source_batch(
        domain=domain,
        batch_id=batch_id,
        batch_code=f"{domain}-{batch_id}",
        source_type="folder_scan",
    )


def _seed_linked_snapshot(
    asset_db: AssetCoreDB,
    *,
    domain: str,
    document_id: str,
    document_key: str,
    snapshot_id: str,
    content_hash: str,
    batch_id: str | None,
    complete: bool = True,
) -> tuple[str, str]:
    asset_db.upsert_document(
        domain=domain,
        document_id=document_id,
        document_key=document_key,
        document_name="same.md",
    )
    snapshot_id = asset_db.upsert_snapshot(
        domain=domain,
        snapshot_id=snapshot_id,
        normalized_content_hash=content_hash,
        raw_content_hash=f"raw-{content_hash}",
        mime_type="text/markdown",
        title=content_hash,
    )
    asset_db.insert_snapshot_link(
        domain=domain,
        link_id=f"link-{document_id}-{content_hash}",
        document_id=document_id,
        document_snapshot_id=snapshot_id,
        source_batch_id=batch_id,
        relative_path="same.md",
        source_uri="file:///same.md",
    )
    if complete:
        asset_db.insert_raw_segment(
            segment_id=f"segment-{snapshot_id}",
            document_snapshot_id=snapshot_id,
            segment_key=f"{document_key}#0",
            segment_index=0,
            raw_text=content_hash,
            normalized_text=content_hash,
        )
    return document_id, snapshot_id


def test_repository_uses_active_release_not_newer_build_and_excludes_removed(asset_db) -> None:
    _seed_batch(asset_db, domain="odn", batch_id="batch-h1")
    _seed_batch(asset_db, domain="odn", batch_id="batch-h2")
    document_id, snapshot_h1 = _seed_linked_snapshot(
        asset_db,
        domain="odn",
        document_id="doc-odn",
        document_key="doc:/same.md",
        snapshot_id="snap-h1",
        content_hash="h1",
        batch_id="batch-h1",
    )
    _, snapshot_h2 = _seed_linked_snapshot(
        asset_db,
        domain="odn",
        document_id=document_id,
        document_key="doc:/same.md",
        snapshot_id="snap-h2",
        content_hash="h2",
        batch_id="batch-h2",
    )
    asset_db.insert_build(
        "build-active",
        "B-ACTIVE",
        "validated",
        "full",
        domain="odn",
        source_batch_id="batch-h2",
    )
    asset_db.upsert_build_document_snapshot(
        build_id="build-active",
        document_id=document_id,
        document_snapshot_id=snapshot_h2,
        source_batch_id="batch-h2",
        selection_status="active",
        reason="add",
    )
    asset_db.insert_release(
        "release-active",
        "R-ACTIVE",
        "build-active",
        domain="odn",
        channel="prod",
        status="active",
    )

    # This build is newer but unpublished. It must not replace current truth.
    asset_db.insert_build(
        "build-newer-unpublished",
        "B-NEWER",
        "validated",
        "incremental",
        domain="odn",
        source_batch_id="batch-h1",
        parent_build_id="build-active",
    )
    asset_db.upsert_build_document_snapshot(
        build_id="build-newer-unpublished",
        document_id=document_id,
        document_snapshot_id=snapshot_h1,
        source_batch_id="batch-h1",
        selection_status="active",
        reason="update",
    )

    state = asset_db.get_document_lifecycle_state(
        domain="odn",
        channel="prod",
        document_key="doc:/same.md",
        normalized_content_hash="h1",
    )

    assert state is not None
    assert state["historical_snapshot_id"] == snapshot_h1
    assert state["active_build_id"] == "build-active"
    assert state["active_snapshot_id"] == snapshot_h2
    assert state["active_source_batch_id"] == "batch-h2"
    assert run_job.decide_document_lifecycle_action(
        state,
        normalized_content_hash="h1",
    ) == "UPDATE"

    asset_db._execute(
        "UPDATE asset_build_document_snapshots SET selection_status = 'removed', reason = 'remove' "
        "WHERE build_id = %s AND document_id = %s",
        ("build-active", document_id),
    )
    removed_state = asset_db.get_document_lifecycle_state(
        domain="odn",
        channel="prod",
        document_key="doc:/same.md",
        normalized_content_hash="h1",
    )
    assert removed_state is not None
    assert removed_state["active_snapshot_id"] is None
    assert run_job.decide_document_lifecycle_action(
        removed_state,
        normalized_content_hash="h1",
    ) == "RESTORE"


def test_repository_reuses_historical_snapshot_but_not_across_domains(asset_db) -> None:
    from knowledge_mining.mining.contracts.models import DocumentProfile
    from knowledge_mining.mining.snapshot import select_or_create_snapshot

    for domain in ("odn", "civil_engineering"):
        _seed_batch(asset_db, domain=domain, batch_id=f"batch-{domain}")

    profile = DocumentProfile(document_key="doc:/same.md")
    h1 = _raw_doc(content_hash="h1")
    h2 = _raw_doc(content_hash="h2")
    odn_document, odn_h1, _ = select_or_create_snapshot(
        asset_db,
        h1,
        profile,
        domain="odn",
        batch_id="batch-odn",
    )
    _, odn_h2, _ = select_or_create_snapshot(
        asset_db,
        h2,
        profile,
        domain="odn",
        batch_id="batch-odn",
    )
    _, odn_h1_again, _ = select_or_create_snapshot(
        asset_db,
        h1,
        profile,
        domain="odn",
        batch_id="batch-odn",
    )
    civil_document, civil_h1, _ = select_or_create_snapshot(
        asset_db,
        h1,
        profile,
        domain="civil_engineering",
        batch_id="batch-civil_engineering",
    )

    assert odn_h1 != odn_h2
    assert odn_h1_again == odn_h1
    assert civil_document != odn_document
    assert civil_h1 != odn_h1


def test_incomplete_repository_snapshot_is_not_restored(asset_db) -> None:
    _seed_batch(asset_db, domain="odn", batch_id="batch-shell")
    _seed_linked_snapshot(
        asset_db,
        domain="odn",
        document_id="doc-shell",
        document_key="doc:/shell.md",
        snapshot_id="snap-shell",
        content_hash="shell-hash",
        batch_id="batch-shell",
        complete=False,
    )

    state = asset_db.get_document_lifecycle_state(
        domain="odn",
        channel="prod",
        document_key="doc:/shell.md",
        normalized_content_hash="shell-hash",
    )

    assert state is not None
    assert state["historical_snapshot_complete"] is False
    assert run_job.decide_document_lifecycle_action(
        state,
        normalized_content_hash="shell-hash",
    ) == "UPDATE"
