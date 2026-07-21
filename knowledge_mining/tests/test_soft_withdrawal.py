from __future__ import annotations

from contextlib import contextmanager
from copy import deepcopy
from threading import Event, Lock, Thread
from types import SimpleNamespace
from typing import Any

import pytest

from knowledge_mining.mining.infra.db import AssetCoreDB
from knowledge_mining.mining.jobs import run as run_job
from knowledge_mining.mining.stages.publishing import publish_release, validate_build
from knowledge_mining.mining.stages.withdrawal import (
    ActiveResourceNotFound,
    withdraw_document,
    withdraw_source_batch,
)


class InMemoryAssetDB:
    """Transactional AssetCoreDB test double for lifecycle behavior."""

    def __init__(self) -> None:
        self.builds: dict[str, dict[str, Any]] = {}
        self.selections: dict[str, list[dict[str, Any]]] = {}
        self.releases: dict[str, dict[str, Any]] = {}
        self.events: list[str] = []
        self.fail_activate = False
        self.require_locked_reads = False
        self._transaction_depth = 0
        self._locked_domains: set[str] = set()

    @contextmanager
    def transaction(self):
        outer = self._transaction_depth == 0
        before = None
        if outer:
            before = deepcopy((self.builds, self.selections, self.releases))
            self.events.append("transaction:begin")
        self._transaction_depth += 1
        try:
            yield
        except Exception:
            self._transaction_depth -= 1
            if outer:
                assert before is not None
                self.builds, self.selections, self.releases = before
                self._locked_domains.clear()
                self.events.append("transaction:rollback")
            raise
        else:
            self._transaction_depth -= 1
            if outer:
                self._locked_domains.clear()
                self.events.append("transaction:commit")

    def acquire_domain_publish_lock(self, domain: str) -> None:
        assert self._transaction_depth > 0, "lock acquired outside transaction"
        if domain not in self._locked_domains:
            self._locked_domains.add(domain)
            self.events.append(f"lock:{domain}")

    def _assert_locked(self, domain: str) -> None:
        if self.require_locked_reads:
            assert self._transaction_depth > 0
            assert domain in self._locked_domains

    def get_active_release(self, domain: str, channel: str = "prod") -> dict[str, Any] | None:
        self._assert_locked(domain)
        self.events.append(f"read-active-release:{domain}:{channel}")
        for release in self.releases.values():
            if (
                release["domain"] == domain
                and release["channel"] == channel
                and release["status"] == "active"
            ):
                return deepcopy(release)
        return None

    def get_active_build(self, *, domain: str, channel: str) -> dict[str, Any] | None:
        self._assert_locked(domain)
        self.events.append(f"read-active-build:{domain}:{channel}")
        release = self.get_active_release(domain, channel)
        if release is None:
            return None
        build = self.builds.get(release["build_id"])
        if build is None or build["domain"] != domain:
            return None
        return deepcopy(build)

    def get_build(self, build_id: str) -> dict[str, Any] | None:
        build = self.builds.get(build_id)
        if build is not None and self.require_locked_reads:
            assert self._transaction_depth > 0
            assert self._locked_domains
        self.events.append(f"read-build:{build_id}")
        return deepcopy(build) if build is not None else None

    def get_build_snapshots(self, build_id: str) -> list[dict[str, Any]]:
        build = self.builds.get(build_id)
        if build is not None and self.require_locked_reads:
            self._assert_locked(build["domain"])
        return deepcopy(self.selections.get(build_id, []))

    def get_active_document_ids_by_batch(
        self, *, domain: str, channel: str, source_batch_id: str
    ) -> list[str]:
        self._assert_locked(domain)
        self.events.append(f"resolve-batch:{domain}:{channel}:{source_batch_id}")
        build = self.get_active_build(domain=domain, channel=channel)
        if build is None:
            return []
        return [
            row["document_id"]
            for row in self.selections.get(build["id"], [])
            if row["selection_status"] == "active"
            and row.get("source_batch_id") == source_batch_id
        ]

    def insert_build(
        self,
        build_id: str,
        build_code: str,
        status: str = "building",
        build_mode: str = "full",
        domain: str | None = None,
        source_batch_id: str | None = None,
        parent_build_id: str | None = None,
        mining_run_id: str | None = None,
        summary_json: dict[str, Any] | None = None,
        validation_json: dict[str, Any] | None = None,
    ) -> str:
        assert self._transaction_depth > 0
        self.builds[build_id] = {
            "id": build_id,
            "build_code": build_code,
            "status": status,
            "build_mode": build_mode,
            "domain": domain,
            "source_batch_id": source_batch_id,
            "parent_build_id": parent_build_id,
            "mining_run_id": mining_run_id,
            "summary_json": deepcopy(summary_json or {}),
            "validation_json": deepcopy(validation_json or {}),
        }
        self.selections[build_id] = []
        return build_id

    def update_build_status(
        self,
        build_id: str,
        status: str,
        finished_at: str | None = None,
        summary_json: dict[str, Any] | None = None,
        validation_json: dict[str, Any] | None = None,
    ) -> None:
        self.builds[build_id]["status"] = status
        if summary_json is not None:
            self.builds[build_id]["summary_json"] = deepcopy(summary_json)
        if validation_json is not None:
            self.builds[build_id]["validation_json"] = deepcopy(validation_json)

    def upsert_build_document_snapshot(
        self,
        *,
        build_id: str,
        document_id: str,
        document_snapshot_id: str,
        source_batch_id: str | None,
        selection_status: str = "active",
        reason: str = "add",
        metadata_json: dict[str, Any] | None = None,
    ) -> None:
        rows = self.selections.setdefault(build_id, [])
        rows[:] = [row for row in rows if row["document_id"] != document_id]
        rows.append(
            {
                "build_id": build_id,
                "document_id": document_id,
                "document_snapshot_id": document_snapshot_id,
                "source_batch_id": source_batch_id,
                "selection_status": selection_status,
                "reason": reason,
                "metadata_json": deepcopy(metadata_json or {}),
            }
        )

    def count_segments_by_snapshot(self, document_snapshot_id: str) -> int:
        return 1

    def insert_release(
        self,
        release_id: str,
        release_code: str,
        build_id: str,
        domain: str = "default",
        channel: str = "prod",
        status: str = "staging",
        previous_release_id: str | None = None,
        released_by: str | None = None,
        release_notes: str | None = None,
        metadata_json: dict[str, Any] | None = None,
    ) -> str:
        assert self._transaction_depth > 0
        self.releases[release_id] = {
            "id": release_id,
            "release_code": release_code,
            "build_id": build_id,
            "domain": domain,
            "channel": channel,
            "status": status,
            "previous_release_id": previous_release_id,
            "released_by": released_by,
            "release_notes": release_notes,
            "metadata_json": deepcopy(metadata_json or {}),
        }
        return release_id

    def activate_release(self, release_id: str) -> None:
        assert self._transaction_depth > 0
        if self.fail_activate:
            raise RuntimeError("injected release activation failure")
        release = self.releases[release_id]
        for current in self.releases.values():
            if (
                current["domain"] == release["domain"]
                and current["channel"] == release["channel"]
                and current["status"] == "active"
            ):
                current["status"] = "retired"
        release["status"] = "active"

    def commit(self) -> None:
        pass


def _selection(
    document_id: str,
    *,
    batch: str | None,
    status: str = "active",
    reason: str = "add",
    snapshot_id: str | None = None,
    metadata: dict[str, Any] | None = None,
) -> dict[str, Any]:
    return {
        "document_id": document_id,
        "document_snapshot_id": snapshot_id or f"snap-{document_id}",
        "source_batch_id": batch,
        "selection_status": status,
        "reason": reason,
        "metadata_json": deepcopy(metadata or {"origin": document_id}),
    }


def _seed_active(
    asset_db: InMemoryAssetDB,
    *,
    domain: str,
    rows: list[dict[str, Any]],
    channel: str = "prod",
) -> tuple[str, str]:
    ordinal = len(asset_db.builds) + 1
    build_id = f"build-{domain}-{ordinal}"
    release_id = f"release-{domain}-{ordinal}"
    asset_db.builds[build_id] = {
        "id": build_id,
        "build_code": f"B-{ordinal}",
        "status": "published",
        "build_mode": "full",
        "domain": domain,
        "source_batch_id": None,
        "parent_build_id": None,
        "mining_run_id": None,
        "summary_json": {"operation": "mining"},
        "validation_json": {},
    }
    asset_db.selections[build_id] = [
        {"build_id": build_id, **deepcopy(row)} for row in rows
    ]
    asset_db.releases[release_id] = {
        "id": release_id,
        "release_code": f"R-{ordinal}",
        "build_id": build_id,
        "domain": domain,
        "channel": channel,
        "status": "active",
        "previous_release_id": None,
        "released_by": "seed",
        "release_notes": None,
        "metadata_json": {},
    }
    return build_id, release_id


def _active_rows(
    asset_db: InMemoryAssetDB, domain: str, channel: str = "prod"
) -> dict[str, dict[str, Any]]:
    release = asset_db.get_active_release(domain, channel)
    assert release is not None
    return {
        row["document_id"]: row
        for row in asset_db.get_build_snapshots(release["build_id"])
    }


def _release_count(asset_db: InMemoryAssetDB, domain: str) -> int:
    return sum(release["domain"] == domain for release in asset_db.releases.values())


def test_withdraw_document_clones_all_provenance_and_only_changes_requested_domain() -> None:
    asset_db = InMemoryAssetDB()
    _seed_active(
        asset_db,
        domain="odn",
        rows=[
            _selection("doc-a", batch="batch-a", metadata={"path": "a.pdf"}),
            _selection("doc-b", batch="batch-b", metadata={"path": "b.pdf"}),
            _selection(
                "doc-old",
                batch="batch-old",
                status="removed",
                reason="remove",
                metadata={"path": "old.pdf"},
            ),
        ],
    )
    civil_build, civil_release = _seed_active(
        asset_db,
        domain="civil_engineering",
        rows=[_selection("doc-civil", batch="batch-civil")],
    )
    civil_before = deepcopy(asset_db.selections[civil_build])

    result = withdraw_document(
        asset_db,
        domain="odn",
        channel="prod",
        document_id="doc-a",
        actor="tester",
    )

    rows = _active_rows(asset_db, "odn")
    assert result.domain == "odn"
    assert result.removed_count == 1
    assert rows["doc-a"] == {
        "build_id": result.build_id,
        "document_id": "doc-a",
        "document_snapshot_id": "snap-doc-a",
        "source_batch_id": "batch-a",
        "selection_status": "removed",
        "reason": "remove",
        "metadata_json": {"path": "a.pdf"},
    }
    assert rows["doc-b"]["source_batch_id"] == "batch-b"
    assert rows["doc-b"]["selection_status"] == "active"
    assert rows["doc-old"]["source_batch_id"] == "batch-old"
    assert rows["doc-old"]["selection_status"] == "removed"
    assert asset_db.builds[result.build_id]["source_batch_id"] is None
    assert asset_db.builds[result.build_id]["summary_json"]["operation"] == "withdrawal"
    assert asset_db.releases[result.release_id]["released_by"] == "tester"
    assert asset_db.get_active_release("civil_engineering", "prod")["id"] == civil_release
    assert asset_db.selections[civil_build] == civil_before


def test_withdraw_source_batch_resolves_only_current_active_provenance_under_lock() -> None:
    asset_db = InMemoryAssetDB()
    asset_db.require_locked_reads = True
    _seed_active(
        asset_db,
        domain="odn",
        rows=[
            _selection("doc-a", batch="batch-target"),
            _selection("doc-b", batch="batch-other"),
            _selection(
                "doc-removed",
                batch="batch-target",
                status="removed",
                reason="remove",
            ),
        ],
    )

    result = withdraw_source_batch(
        asset_db,
        domain="odn",
        channel="prod",
        source_batch_id="batch-target",
        actor="tester",
    )

    asset_db.require_locked_reads = False
    rows = _active_rows(asset_db, "odn")
    assert result.removed_count == 1
    assert rows["doc-a"]["selection_status"] == "removed"
    assert rows["doc-b"]["selection_status"] == "active"
    assert rows["doc-removed"]["selection_status"] == "removed"
    lock_index = asset_db.events.index("lock:odn")
    resolve_index = asset_db.events.index("resolve-batch:odn:prod:batch-target")
    assert lock_index < resolve_index


def test_old_batch_does_not_remove_document_updated_by_later_batch() -> None:
    asset_db = InMemoryAssetDB()
    _seed_active(
        asset_db,
        domain="odn",
        rows=[_selection("doc-updated", batch="batch-new", reason="update")],
    )
    release_count = _release_count(asset_db, "odn")

    with pytest.raises(ActiveResourceNotFound):
        withdraw_source_batch(
            asset_db,
            domain="odn",
            channel="prod",
            source_batch_id="batch-old",
            actor="tester",
        )

    assert _release_count(asset_db, "odn") == release_count
    assert _active_rows(asset_db, "odn")["doc-updated"]["selection_status"] == "active"


def test_repeated_withdrawal_creates_no_release() -> None:
    asset_db = InMemoryAssetDB()
    _seed_active(asset_db, domain="odn", rows=[_selection("doc-a", batch="batch-a")])

    withdraw_document(
        asset_db,
        domain="odn",
        channel="prod",
        document_id="doc-a",
        actor="tester",
    )
    release_count = _release_count(asset_db, "odn")

    with pytest.raises(ActiveResourceNotFound):
        withdraw_document(
            asset_db,
            domain="odn",
            channel="prod",
            document_id="doc-a",
            actor="tester",
        )

    assert _release_count(asset_db, "odn") == release_count


def test_last_document_can_publish_empty_active_build() -> None:
    asset_db = InMemoryAssetDB()
    _seed_active(asset_db, domain="odn", rows=[_selection("only-doc", batch="batch-a")])

    result = withdraw_document(
        asset_db,
        domain="odn",
        channel="prod",
        document_id="only-doc",
        actor="tester",
    )

    active = [
        row
        for row in asset_db.get_build_snapshots(result.build_id)
        if row["selection_status"] == "active"
    ]
    assert active == []
    assert asset_db.get_active_release("odn", "prod")["id"] == result.release_id


def test_empty_build_override_is_limited_to_withdrawal_operation() -> None:
    asset_db = InMemoryAssetDB()
    asset_db.builds["normal"] = {
        "id": "normal",
        "status": "building",
        "build_mode": "full",
        "domain": "odn",
        "parent_build_id": None,
        "summary_json": {"operation": "mining"},
    }
    asset_db.selections["normal"] = []
    asset_db.builds["withdrawal"] = {
        **asset_db.builds["normal"],
        "id": "withdrawal",
        "summary_json": {"operation": "withdrawal"},
    }
    asset_db.selections["withdrawal"] = []

    with pytest.raises(ValueError, match="no active snapshots"):
        validate_build(asset_db, "normal")
    with pytest.raises(ValueError, match="withdrawal"):
        validate_build(asset_db, "normal", allow_empty=True)
    validate_build(asset_db, "withdrawal", allow_empty=True)


def test_status_update_without_metadata_preserves_withdrawal_summary() -> None:
    captured: list[tuple[str, tuple[Any, ...]]] = []
    asset_db = AssetCoreDB.__new__(AssetCoreDB)
    asset_db._execute = lambda sql, params=(): captured.append((sql, params))

    asset_db.update_build_status("build-a", "validated")

    assert captured[0][1][2] is None
    assert captured[0][1][3] is None


def test_publish_failure_rolls_back_build_release_and_active_switch() -> None:
    asset_db = InMemoryAssetDB()
    _seed_active(
        asset_db,
        domain="odn",
        rows=[
            _selection("doc-a", batch="batch-a"),
            _selection("doc-b", batch="batch-b"),
        ],
    )
    before = deepcopy((asset_db.builds, asset_db.selections, asset_db.releases))
    asset_db.fail_activate = True

    with pytest.raises(RuntimeError, match="injected"):
        withdraw_document(
            asset_db,
            domain="odn",
            channel="prod",
            document_id="doc-a",
            actor="tester",
        )

    assert (asset_db.builds, asset_db.selections, asset_db.releases) == before
    assert asset_db.events[-1] == "transaction:rollback"


def test_publish_release_locks_before_validating_requested_domain() -> None:
    asset_db = InMemoryAssetDB()
    asset_db.require_locked_reads = True
    asset_db.builds["build-civil"] = {
        "id": "build-civil",
        "build_code": "B-CIVIL",
        "status": "validated",
        "build_mode": "full",
        "domain": "civil_engineering",
        "source_batch_id": None,
        "parent_build_id": None,
        "summary_json": {"operation": "mining"},
    }

    with pytest.raises(ValueError, match="belongs to domain"):
        publish_release(
            asset_db,
            "build-civil",
            domain="odn",
            channel="preview",
            released_by="tester",
        )

    assert asset_db.events[:3] == [
        "transaction:begin",
        "lock:odn",
        "read-build:build-civil",
    ]
    assert asset_db.releases == {}


class _AdvisoryLockRegistry:
    def __init__(self) -> None:
        self.guard = Lock()
        self.locks: dict[str, Lock] = {}
        self.executions: list[tuple[str, tuple[Any, ...]]] = []

    def lock_for(self, key: str) -> Lock:
        with self.guard:
            return self.locks.setdefault(key, Lock())


class _FakeCursor:
    def __init__(self, connection: "_FakeConnection") -> None:
        self.connection = connection

    def __enter__(self) -> "_FakeCursor":
        return self

    def __exit__(self, exc_type, exc, tb) -> None:
        return None

    def execute(self, sql: str, params: tuple[Any, ...]) -> None:
        self.connection.registry.executions.append((sql, params))
        if "pg_advisory_xact_lock" in sql:
            key = str(params[0])
            if key not in self.connection.held_keys:
                self.connection.registry.lock_for(key).acquire()
                self.connection.held_keys.add(key)


class _FakeConnection:
    autocommit = False

    def __init__(self, registry: _AdvisoryLockRegistry) -> None:
        self.registry = registry
        self.held_keys: set[str] = set()

    def cursor(self, **kwargs: Any) -> _FakeCursor:
        return _FakeCursor(self)

    def release_locks(self) -> None:
        for key in self.held_keys:
            self.registry.lock_for(key).release()
        self.held_keys.clear()


class _FakePool:
    def __init__(self, registry: _AdvisoryLockRegistry) -> None:
        self.registry = registry

    @contextmanager
    def connection(self):
        connection = _FakeConnection(self.registry)
        try:
            yield connection
        finally:
            connection.release_locks()


def test_domain_publish_lock_requires_transaction_and_uses_domain_key() -> None:
    registry = _AdvisoryLockRegistry()
    asset_db = AssetCoreDB(_FakePool(registry))

    with pytest.raises(RuntimeError, match="transaction"):
        asset_db.acquire_domain_publish_lock("odn")

    with asset_db.transaction():
        asset_db.acquire_domain_publish_lock("odn")
        asset_db.acquire_domain_publish_lock("odn")

    advisory = [item for item in registry.executions if "pg_advisory_xact_lock" in item[0]]
    assert len(advisory) == 1
    assert "hashtextextended(%s, 0)" in advisory[0][0]
    assert advisory[0][1] == ("asset-publish:odn",)


def test_domain_publish_lock_serializes_same_domain_but_allows_other_domains() -> None:
    registry = _AdvisoryLockRegistry()
    asset_db = AssetCoreDB(_FakePool(registry))
    first_entered = Event()
    release_first = Event()
    same_entered = Event()
    other_entered = Event()

    def hold_first() -> None:
        with asset_db.transaction():
            asset_db.acquire_domain_publish_lock("odn")
            first_entered.set()
            assert release_first.wait(2)

    def enter(domain: str, entered: Event) -> None:
        assert first_entered.wait(2)
        with asset_db.transaction():
            asset_db.acquire_domain_publish_lock(domain)
            entered.set()

    holder = Thread(target=hold_first)
    same = Thread(target=enter, args=("odn", same_entered))
    other = Thread(target=enter, args=("civil_engineering", other_entered))
    holder.start()
    assert first_entered.wait(2)
    same.start()
    other.start()

    assert other_entered.wait(2)
    assert not same_entered.wait(0.1)
    release_first.set()
    assert same_entered.wait(2)

    for thread in (holder, same, other):
        thread.join(2)
        assert not thread.is_alive()


def test_finalize_uses_one_locked_asset_transaction_before_success_events(monkeypatch) -> None:
    events: list[str] = []

    class AssetDB:
        in_transaction = False
        locked_domain: str | None = None

        @contextmanager
        def transaction(self):
            assert not self.in_transaction
            self.in_transaction = True
            events.append("asset:begin")
            try:
                yield
            except Exception:
                events.append("asset:rollback")
                raise
            else:
                events.append("asset:commit")
            finally:
                self.in_transaction = False
                self.locked_domain = None

        def acquire_domain_publish_lock(self, domain: str) -> None:
            assert self.in_transaction
            self.locked_domain = domain
            events.append(f"asset:lock:{domain}")

        def commit(self) -> None:
            pass

    class RuntimeDB:
        def _fetchone(self, sql, params):
            return {"status": "running"}

        def get_run(self, run_id):
            return {"status": "running"}

        def commit(self) -> None:
            pass

    class Tracker:
        def set_run_phase(self, *args):
            return True

        def start_stage(self, run_id, stage):
            events.append(f"tracker:start:{stage}")
            return stage

        def end_stage(self, stage, *args, **kwargs):
            events.append(f"tracker:success:{stage}")

        def complete_run(self, *args, **kwargs):
            events.append("tracker:success:run")
            return True

    asset_db = AssetDB()

    def assert_locked(operation: str) -> None:
        assert asset_db.in_transaction
        assert asset_db.locked_domain == "odn"
        events.append(f"asset:{operation}")

    def classify(db, decisions, **kwargs):
        assert_locked("classify")
        return decisions

    def assemble(db, **kwargs):
        assert_locked("assemble+validate")
        return "build-new"

    def publish(db, build_id, **kwargs):
        assert_locked("release-switch")
        return "release-new"

    def quality(db, build_id):
        assert_locked("quality")
        return {}

    monkeypatch.setattr(run_job, "classify_documents", classify)
    monkeypatch.setattr(run_job, "assemble_build", assemble)
    monkeypatch.setattr(run_job, "publish_release", publish)
    monkeypatch.setattr(run_job, "demo_quality_summary", quality)

    result = run_job._finalize_run(
        asset_db,
        RuntimeDB(),
        Tracker(),
        "run-a",
        "batch-a",
        [{"document_id": "doc-a", "document_snapshot_id": "snap-a"}],
        {
            "committed_count": 1,
            "new_count": 1,
            "updated_count": 0,
            "failed_count": 0,
            "skipped_count": 0,
        },
        1,
        False,
        False,
        SimpleNamespace(domain_id="odn"),
        channel="preview",
    )

    assert result["release_id"] == "release-new"
    assert events.count("asset:begin") == 1
    assert events.count("asset:lock:odn") == 1
    assert events.index("asset:classify") < events.index("asset:assemble+validate")
    assert events.index("asset:assemble+validate") < events.index("asset:release-switch")
    commit_index = events.index("asset:commit")
    success_indexes = [
        index for index, event in enumerate(events) if event.startswith("tracker:success:")
    ]
    assert success_indexes
    assert all(commit_index < index for index in success_indexes)


def test_manual_publish_preserves_requested_domain_and_channel(monkeypatch) -> None:
    captured: dict[str, Any] = {}

    class AssetDB:
        def _fetchone(self, sql, params):
            return {"domain": "civil_engineering"}

        def close(self) -> None:
            pass

    class RuntimeDB:
        def get_run(self, run_id):
            return {
                "id": run_id,
                "status": "completed",
                "build_id": "build-a",
                "domain": "odn",
            }

        def close(self) -> None:
            pass

    def publish(db, build_id, **kwargs):
        captured.update(kwargs)
        return "release-a"

    monkeypatch.setattr(
        run_job,
        "resolve_domain",
        lambda domain: {"id": domain, "default_channel": "prod"},
    )
    monkeypatch.setattr(run_job, "resolve_domain_database", lambda *args: object())
    monkeypatch.setattr(run_job, "_create_dbs", lambda config: (AssetDB(), RuntimeDB()))
    monkeypatch.setattr(run_job, "publish_release", publish)

    result = run_job.publish(
        "run-a",
        domain="odn",
        channel="preview",
        db_config=object(),
        released_by="tester",
    )

    assert captured["domain"] == "odn"
    assert captured["channel"] == "preview"
    assert result["release_id"] == "release-a"
