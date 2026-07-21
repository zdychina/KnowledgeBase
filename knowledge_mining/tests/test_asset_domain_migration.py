from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
import sqlite3
from types import SimpleNamespace
from uuid import uuid4

import psycopg
from psycopg import sql
import pytest

from knowledge_mining.mining.infra.pg_schema import _execute_ddl, _split_ddl
from knowledge_mining.mining.infra import pg_schema
from knowledge_mining.tests import conftest as mining_conftest


_REPO_ROOT = Path(__file__).resolve().parents[2]
_ASSET_DDL = _REPO_ROOT / "databases" / "asset_core" / "schemas" / "002_asset_core_postgresql.sql"
_MIGRATION_DDL = _REPO_ROOT / "databases" / "asset_core" / "schemas" / "003_asset_core_domain_isolation.sql"

_LEGACY_DDL = """
CREATE TABLE asset_source_batches (
    id TEXT PRIMARY KEY,
    batch_code TEXT NOT NULL UNIQUE,
    domain TEXT NOT NULL,
    created_at TEXT NOT NULL
);
CREATE TABLE asset_documents (
    id TEXT PRIMARY KEY,
    document_key TEXT NOT NULL,
    created_at TEXT NOT NULL,
    CONSTRAINT {document_unique} UNIQUE (document_key)
);
CREATE TABLE asset_document_snapshots (
    id TEXT PRIMARY KEY,
    normalized_content_hash TEXT NOT NULL,
    raw_content_hash TEXT NOT NULL,
    created_at TEXT NOT NULL,
    CONSTRAINT {snapshot_unique} UNIQUE (normalized_content_hash)
);
CREATE TABLE asset_document_snapshot_links (
    id TEXT PRIMARY KEY,
    document_id TEXT NOT NULL REFERENCES asset_documents(id),
    document_snapshot_id TEXT NOT NULL REFERENCES asset_document_snapshots(id),
    source_batch_id TEXT REFERENCES asset_source_batches(id),
    linked_at TEXT NOT NULL
);
CREATE TABLE asset_builds (
    id TEXT PRIMARY KEY,
    domain TEXT,
    source_batch_id TEXT REFERENCES asset_source_batches(id),
    created_at TEXT NOT NULL
);
CREATE TABLE asset_build_document_snapshots (
    build_id TEXT NOT NULL REFERENCES asset_builds(id),
    document_id TEXT NOT NULL REFERENCES asset_documents(id),
    document_snapshot_id TEXT NOT NULL REFERENCES asset_document_snapshots(id),
    PRIMARY KEY (build_id, document_id)
);
CREATE TABLE asset_publish_releases (
    id TEXT PRIMARY KEY,
    build_id TEXT NOT NULL REFERENCES asset_builds(id),
    domain TEXT,
    channel TEXT NOT NULL,
    status TEXT NOT NULL
);
CREATE UNIQUE INDEX {active_unique}
    ON asset_publish_releases(domain) WHERE status = 'active';
CREATE TABLE mining_runs (
    id TEXT PRIMARY KEY,
    source_batch_id TEXT,
    domain TEXT
);
CREATE TABLE mining_run_documents (
    id TEXT PRIMARY KEY,
    run_id TEXT NOT NULL REFERENCES mining_runs(id),
    document_id TEXT,
    document_snapshot_id TEXT
);
"""


@pytest.mark.parametrize("dbname", ["coremasterkb", "shared", "coremasterkb_dev"])
def test_disposable_database_guard_rejects_shared_names(dbname: str) -> None:
    guard = getattr(mining_conftest, "_assert_disposable_database")

    with pytest.raises(RuntimeError, match="_test"):
        guard(SimpleNamespace(pg_dbname=dbname))


def test_disposable_database_guard_accepts_test_suffix() -> None:
    guard = getattr(mining_conftest, "_assert_disposable_database")

    guard(SimpleNamespace(pg_dbname="coremasterkb_domain_test"))


def test_pure_tests_do_not_initialize_or_connect_to_postgres(monkeypatch) -> None:
    calls: list[str] = []
    monkeypatch.setattr(
        mining_conftest,
        "ensure_schema",
        lambda config: calls.append("ensure_schema"),
    )
    monkeypatch.setattr(
        psycopg,
        "connect",
        lambda *args, **kwargs: calls.append("connect"),
    )
    request = SimpleNamespace(fixturenames=())

    cleanup = mining_conftest._cleanup_db.__wrapped__(request)
    next(cleanup)
    with pytest.raises(StopIteration):
        next(cleanup)

    assert mining_conftest._ensure_schema._fixture_function_marker.autouse is False
    assert calls == []


def test_session_guard_is_autouse_and_never_connects(monkeypatch) -> None:
    calls: list[str] = []
    monkeypatch.setattr(
        mining_conftest,
        "ensure_schema",
        lambda config: calls.append("ensure_schema"),
    )
    monkeypatch.setattr(
        psycopg,
        "connect",
        lambda *args, **kwargs: calls.append("connect"),
    )
    guard_fixture = getattr(mining_conftest, "_guard_test_database")

    assert guard_fixture._fixture_function_marker.autouse is True
    with pytest.raises(RuntimeError, match="_test"):
        guard_fixture.__wrapped__(SimpleNamespace(pg_dbname="coremasterkb"))
    guard_fixture.__wrapped__(SimpleNamespace(pg_dbname="coremasterkb_domain_test"))
    assert calls == []


def test_schema_runner_applies_domain_migration_transactionally(monkeypatch) -> None:
    class DdlPath:
        def __init__(self, name: str):
            self.name = name

        def read_text(self, *, encoding: str) -> str:
            assert encoding == "utf-8"
            return self.name

    class Connection:
        def close(self) -> None:
            pass

    paths = [
        DdlPath(name)
        for name in ("asset", "runtime", "runtime_v3", "runtime_v4", "domain", "ontology")
    ]
    monkeypatch.setattr(pg_schema, "_ASSET_DDL", paths[0])
    monkeypatch.setattr(pg_schema, "_RUNTIME_DDL", paths[1])
    monkeypatch.setattr(pg_schema, "_RUNTIME_DDL_V3", paths[2])
    monkeypatch.setattr(pg_schema, "_RUNTIME_DDL_V4", paths[3])
    monkeypatch.setattr(pg_schema, "_ASSET_DOMAIN_DDL", paths[4], raising=False)
    monkeypatch.setattr(pg_schema, "_ONTOLOGY_DDL", paths[5])
    monkeypatch.setattr(pg_schema, "ensure_database", lambda cfg: None)
    monkeypatch.setattr(pg_schema.psycopg, "connect", lambda *args, **kwargs: Connection())
    calls: list[tuple[str, bool]] = []

    def record_ddl(connection, ddl: str, *, transactional: bool = False) -> None:
        calls.append((ddl, transactional))

    monkeypatch.setattr(pg_schema, "_execute_ddl", record_ddl)
    pg_schema.ensure_schema(SimpleNamespace(conninfo="unused"))

    assert calls == [
        ("asset", False),
        ("runtime", False),
        ("runtime_v3", False),
        ("runtime_v4", True),
        ("domain", True),
        ("ontology", False),
    ]


def test_schema_splitter_ignores_semicolons_inside_line_comments() -> None:
    statements = _split_ddl(
        "-- executed transactionally; do not add BEGIN/COMMIT here.\n"
        "ALTER TABLE mining_runs ADD COLUMN IF NOT EXISTS current_stage TEXT;\n"
        "UPDATE mining_runs SET current_stage = 'queued';\n"
    )

    assert len(statements) == 2
    assert "do not add BEGIN/COMMIT here" in statements[0]
    assert statements[1].lstrip().startswith("UPDATE mining_runs")


def test_sqlite_fresh_schema_uses_domain_scoped_uniques() -> None:
    ddl = (
        _REPO_ROOT / "databases" / "asset_core" / "schemas" / "001_asset_core.sqlite.sql"
    ).read_text(encoding="utf-8")
    connection = sqlite3.connect(":memory:")
    connection.executescript(ddl)

    connection.execute(
        "INSERT INTO asset_documents (id, domain, document_key, created_at) VALUES (?, ?, ?, ?)",
        ("doc_odn", "odn", "doc:/same.pdf", "2024-01-01T00:00:00Z"),
    )
    connection.execute(
        "INSERT INTO asset_documents (id, domain, document_key, created_at) VALUES (?, ?, ?, ?)",
        ("doc_civil", "civil_engineering", "doc:/same.pdf", "2024-01-01T00:00:00Z"),
    )
    with pytest.raises(sqlite3.IntegrityError):
        connection.execute(
            "INSERT INTO asset_documents (id, domain, document_key, created_at) VALUES (?, ?, ?, ?)",
            ("doc_duplicate", "odn", "doc:/same.pdf", "2024-01-01T00:00:00Z"),
        )

    for row_id, domain in (("snap_odn", "odn"), ("snap_civil", "civil_engineering")):
        connection.execute(
            """INSERT INTO asset_document_snapshots
            (id, domain, normalized_content_hash, raw_content_hash, mime_type, created_at)
            VALUES (?, ?, 'same-hash', ?, 'text/plain', '2024-01-01T00:00:00Z')""",
            (row_id, domain, f"raw-{row_id}"),
        )
    with pytest.raises(sqlite3.IntegrityError):
        connection.execute(
            """INSERT INTO asset_document_snapshots
            (id, domain, normalized_content_hash, raw_content_hash, mime_type, created_at)
            VALUES ('snap_duplicate', 'odn', 'same-hash', 'raw-duplicate',
                    'text/plain', '2024-01-01T00:00:00Z')"""
        )

    selection_columns = {
        row[1]: row for row in connection.execute("PRAGMA table_info(asset_build_document_snapshots)")
    }
    assert "source_batch_id" in selection_columns


@pytest.fixture
def conn(db_config, _ensure_schema):
    schema_name = f"test_asset_domain_{uuid4().hex}"
    connection = psycopg.connect(db_config.conninfo, autocommit=True)
    connection.execute(sql.SQL("CREATE SCHEMA {}").format(sql.Identifier(schema_name)))
    connection.execute(
        sql.SQL("SET search_path TO {}, public").format(sql.Identifier(schema_name))
    )
    try:
        yield connection
    finally:
        connection.execute("SET search_path TO public")
        connection.execute(
            sql.SQL("DROP SCHEMA {} CASCADE").format(sql.Identifier(schema_name))
        )
        connection.close()


@pytest.fixture(params=["default_names", "custom_names", "unknown_names"])
def legacy_conn(conn, request):
    if request.param == "default_names":
        document_unique = "asset_documents_document_key_key"
        snapshot_unique = "asset_document_snapshots_normalized_content_hash_key"
        active_unique = "asset_release_legacy_domain_guard"
    elif request.param == "custom_names":
        document_unique = "legacy_document_key_unique"
        snapshot_unique = "legacy_snapshot_hash_unique"
        active_unique = "some_unrecognized_active_domain_index"
    else:
        document_unique = "unrecognized_identity_guard_731"
        snapshot_unique = "unrecognized_content_guard_947"
        active_unique = "uq_asset_publish_releases_domain_channel_active"
    conn.execute(
        _LEGACY_DDL.format(
            document_unique=document_unique,
            snapshot_unique=snapshot_unique,
            active_unique=active_unique,
        )
    )
    _seed_legacy_data(conn)
    return conn


def _seed_legacy_data(conn) -> None:
    conn.execute(
        """INSERT INTO asset_source_batches (id, batch_code, domain, created_at) VALUES
        ('batch_odn_old', 'code_odn_old', 'odn', '2024-01-01T00:00:00Z'),
        ('batch_odn_recent', 'code_odn_recent', 'odn', '2024-01-02T00:00:00Z'),
        ('batch_odn_tie', 'code_odn_tie', 'odn', '2024-01-02T00:00:00Z'),
        ('batch_civil', 'code_civil', 'civil_engineering', '2024-01-02T00:00:00Z'),
        ('batch_run', 'code_run', 'run_domain', '2024-01-02T00:00:00Z'),
        ('batch_default', 'code_default', 'default', '2024-01-02T00:00:00Z')"""
    )
    conn.execute(
        """INSERT INTO asset_documents (id, document_key, created_at) VALUES
        ('doc_single', 'doc:/single.pdf', '2024-01-01T00:00:00Z'),
        ('doc_shared', 'doc:/shared.pdf', '2024-01-01T00:00:00Z'),
        ('doc_unscoped', 'doc:/unscoped.pdf', '2024-01-01T00:00:00Z'),
        ('doc_selected', 'doc:/selected.pdf', '2024-01-01T00:00:00Z'),
        ('doc_ambiguous', 'doc:/ambiguous.pdf', '2024-01-01T00:00:00Z'),
        ('doc_build_only', 'doc:/build-only.pdf', '2024-01-01T00:00:00Z'),
        ('doc_release_only', 'doc:/release-only.pdf', '2024-01-01T00:00:00Z'),
        ('doc_run_domain', 'doc:/run-domain.pdf', '2024-01-01T00:00:00Z'),
        ('doc_run_batch', 'doc:/run-batch.pdf', '2024-01-01T00:00:00Z'),
        ('doc_wrong_domain', 'doc:/wrong-domain.pdf', '2024-01-01T00:00:00Z'),
        ('doc_wrong_document', 'doc:/wrong-document.pdf', '2024-01-01T00:00:00Z'),
        ('doc_link_other', 'doc:/link-other.pdf', '2024-01-01T00:00:00Z'),
        ('doc_wrong_snapshot', 'doc:/wrong-snapshot.pdf', '2024-01-01T00:00:00Z'),
        ('doc_late', 'doc:/late.pdf', '2024-01-01T00:00:00Z'),
        ('doc_duplicate_link', 'doc:/duplicate-link.pdf', '2024-01-01T00:00:00Z'),
        ('doc_default_only', 'doc:/default-only.pdf', '2024-01-01T00:00:00Z'),
        ('doc_pre_scoped', 'doc:/pre-scoped.pdf', '2024-01-01T00:00:00Z')"""
    )
    conn.execute(
        """INSERT INTO asset_document_snapshots
        (id, normalized_content_hash, raw_content_hash, created_at) VALUES
        ('snap_single', 'hash-single', 'raw-single', '2024-01-01T00:00:00Z'),
        ('snap_shared', 'hash-shared', 'raw-shared', '2024-01-01T00:00:00Z'),
        ('snap_unscoped', 'hash-unscoped', 'raw-unscoped', '2024-01-01T00:00:00Z'),
        ('snap_selected', 'hash-selected', 'raw-selected', '2024-01-01T00:00:00Z'),
        ('snap_ambiguous', 'hash-ambiguous', 'raw-ambiguous', '2024-01-01T00:00:00Z'),
        ('snap_build_only', 'hash-build-only', 'raw-build-only', '2024-01-01T00:00:00Z'),
        ('snap_release_only', 'hash-release-only', 'raw-release-only', '2024-01-01T00:00:00Z'),
        ('snap_run_domain', 'hash-run-domain', 'raw-run-domain', '2024-01-01T00:00:00Z'),
        ('snap_run_batch', 'hash-run-batch', 'raw-run-batch', '2024-01-01T00:00:00Z'),
        ('snap_wrong_domain', 'hash-wrong-domain', 'raw-wrong-domain', '2024-01-01T00:00:00Z'),
        ('snap_wrong_document', 'hash-wrong-document', 'raw-wrong-document', '2024-01-01T00:00:00Z'),
        ('snap_wrong_snapshot', 'hash-wrong-snapshot', 'raw-wrong-snapshot', '2024-01-01T00:00:00Z'),
        ('snap_link_other', 'hash-link-other', 'raw-link-other', '2024-01-01T00:00:00Z'),
        ('snap_late', 'hash-late', 'raw-late', '2024-01-01T00:00:00Z'),
        ('snap_duplicate_link', 'hash-duplicate-link', 'raw-duplicate-link', '2024-01-01T00:00:00Z'),
        ('snap_default_only', 'hash-default-only', 'raw-default-only', '2024-01-01T00:00:00Z'),
        ('snap_pre_scoped', 'hash-pre-scoped', 'raw-pre-scoped', '2024-01-01T00:00:00Z')"""
    )
    conn.execute(
        """INSERT INTO asset_document_snapshot_links
        (id, document_id, document_snapshot_id, source_batch_id, linked_at) VALUES
        ('link_single', 'doc_single', 'snap_single', 'batch_odn_recent', '2024-01-02T00:00:00Z'),
        ('link_shared_odn', 'doc_shared', 'snap_shared', 'batch_odn_recent', '2024-01-02T00:00:00Z'),
        ('link_shared_civil', 'doc_shared', 'snap_shared', 'batch_civil', '2024-01-02T00:00:00Z'),
        ('link_selected_old', 'doc_selected', 'snap_selected', 'batch_odn_old', '2024-01-01T00:00:00Z'),
        ('link_selected_recent', 'doc_selected', 'snap_selected', 'batch_odn_recent', '2024-01-02T00:00:00Z'),
        ('link_ambiguous_a', 'doc_ambiguous', 'snap_ambiguous', 'batch_odn_recent', '2024-01-02T00:00:00Z'),
        ('link_ambiguous_b', 'doc_ambiguous', 'snap_ambiguous', 'batch_odn_tie', '2024-01-02T00:00:00Z'),
        ('link_wrong_domain', 'doc_wrong_domain', 'snap_wrong_domain', 'batch_civil', '2024-01-02T00:00:00Z'),
        ('link_wrong_document', 'doc_link_other', 'snap_wrong_document', 'batch_odn_recent', '2024-01-02T00:00:00Z'),
        ('link_wrong_snapshot', 'doc_wrong_snapshot', 'snap_link_other', 'batch_odn_recent', '2024-01-02T00:00:00Z'),
        ('link_late', 'doc_late', 'snap_late', 'batch_odn_recent', '2024-01-04T00:00:00Z'),
        ('link_duplicate_a', 'doc_duplicate_link', 'snap_duplicate_link', 'batch_odn_recent', '2024-01-02T00:00:00Z'),
        ('link_duplicate_b', 'doc_duplicate_link', 'snap_duplicate_link', 'batch_odn_recent', '2024-01-02T00:00:00Z'),
        ('link_default_only', 'doc_default_only', 'snap_default_only', 'batch_default', '2024-01-02T00:00:00Z')"""
    )
    conn.execute(
        """INSERT INTO asset_builds (id, domain, source_batch_id, created_at) VALUES
        ('build_odn', 'odn', NULL, '2024-01-03T00:00:00Z'),
        ('build_only', 'build_domain', NULL, '2024-01-03T00:00:00Z'),
        ('build_release', NULL, NULL, '2024-01-03T00:00:00Z'),
        ('build_civil', 'civil_engineering', NULL, '2024-01-03T00:00:00Z')"""
    )
    conn.execute(
        """INSERT INTO asset_build_document_snapshots
        (build_id, document_id, document_snapshot_id) VALUES
        ('build_odn', 'doc_selected', 'snap_selected'),
        ('build_odn', 'doc_ambiguous', 'snap_ambiguous'),
        ('build_only', 'doc_build_only', 'snap_build_only'),
        ('build_release', 'doc_release_only', 'snap_release_only'),
        ('build_odn', 'doc_wrong_domain', 'snap_wrong_domain'),
        ('build_odn', 'doc_wrong_document', 'snap_wrong_document'),
        ('build_odn', 'doc_wrong_snapshot', 'snap_wrong_snapshot'),
        ('build_odn', 'doc_late', 'snap_late'),
        ('build_odn', 'doc_duplicate_link', 'snap_duplicate_link')"""
    )
    conn.execute(
        """INSERT INTO asset_build_document_snapshots
        (build_id, document_id, document_snapshot_id) VALUES
        ('build_odn', 'doc_shared', 'snap_shared'),
        ('build_civil', 'doc_shared', 'snap_shared')"""
    )
    conn.execute(
        """INSERT INTO asset_publish_releases
        (id, build_id, domain, channel, status) VALUES
        ('release_odn', 'build_odn', 'odn', 'prod', 'active'),
        ('release_only', 'build_release', 'release_domain', 'prod', 'retired')"""
    )
    conn.execute(
        "INSERT INTO mining_runs (id, source_batch_id, domain) VALUES "
        "('run_domain', NULL, 'run_domain'), "
        "('run_batch', 'batch_run', NULL)"
    )
    conn.execute(
        """INSERT INTO mining_run_documents
        (id, run_id, document_id, document_snapshot_id) VALUES
        ('run_doc_domain', 'run_domain', 'doc_run_domain', 'snap_run_domain'),
        ('run_doc_batch', 'run_batch', 'doc_run_batch', 'snap_run_batch')"""
    )


def _run_migration(conn) -> None:
    _execute_ddl(conn, _MIGRATION_DDL.read_text(encoding="utf-8"), transactional=True)


@dataclass(frozen=True)
class MigratedRows:
    documents: dict[str, str]
    snapshots: dict[str, str]
    selections: dict[tuple[str, str], str | None]


@pytest.fixture
def migrated_rows(legacy_conn) -> MigratedRows:
    _run_migration(legacy_conn)
    documents = dict(
        legacy_conn.execute("SELECT id, domain FROM asset_documents").fetchall()
    )
    snapshots = dict(
        legacy_conn.execute("SELECT id, domain FROM asset_document_snapshots").fetchall()
    )
    selections = {
        (build_id, document_id): source_batch_id
        for build_id, document_id, source_batch_id in legacy_conn.execute(
            """SELECT build_id, document_id, source_batch_id
            FROM asset_build_document_snapshots"""
        ).fetchall()
    }
    return MigratedRows(documents, snapshots, selections)


def test_migration_assigns_domain_sentinels(migrated_rows) -> None:
    assert migrated_rows.documents["doc_single"] == "odn"
    assert migrated_rows.snapshots["snap_shared"] == "__legacy_shared__"
    assert migrated_rows.documents["doc_unscoped"] == "__legacy_unscoped__"
    assert migrated_rows.snapshots["snap_single"] == "odn"
    assert migrated_rows.documents["doc_build_only"] == "build_domain"
    assert migrated_rows.snapshots["snap_build_only"] == "build_domain"
    assert migrated_rows.documents["doc_release_only"] == "release_domain"
    assert migrated_rows.snapshots["snap_release_only"] == "release_domain"
    assert migrated_rows.documents["doc_run_domain"] == "run_domain"
    assert migrated_rows.snapshots["snap_run_domain"] == "run_domain"
    assert migrated_rows.documents["doc_run_batch"] == "run_domain"
    assert migrated_rows.snapshots["snap_run_batch"] == "run_domain"
    assert migrated_rows.documents["doc_default_only"] == "__legacy_unscoped__"
    assert migrated_rows.snapshots["snap_default_only"] == "__legacy_unscoped__"


@pytest.fixture
def explicit_domain_conn(conn):
    conn.execute(
        _LEGACY_DDL.format(
            document_unique="explicit_document_key_unique",
            snapshot_unique="explicit_snapshot_hash_unique",
            active_unique="explicit_legacy_active_domain_index",
        )
    )
    _seed_legacy_data(conn)
    conn.execute(
        "ALTER TABLE asset_documents ADD COLUMN domain TEXT NOT NULL DEFAULT 'default'"
    )
    conn.execute(
        """ALTER TABLE asset_document_snapshots
        ADD COLUMN domain TEXT NOT NULL DEFAULT 'default'"""
    )
    conn.execute("UPDATE asset_documents SET domain = 'curated' WHERE id = 'doc_pre_scoped'")
    conn.execute(
        "UPDATE asset_document_snapshots SET domain = 'curated' WHERE id = 'snap_pre_scoped'"
    )
    return conn


def test_migration_preserves_explicit_default_and_nondefault_domains(
    explicit_domain_conn,
) -> None:
    _run_migration(explicit_domain_conn)
    _run_migration(explicit_domain_conn)

    document_domains = dict(
        explicit_domain_conn.execute("SELECT id, domain FROM asset_documents").fetchall()
    )
    snapshot_domains = dict(
        explicit_domain_conn.execute(
            "SELECT id, domain FROM asset_document_snapshots"
        ).fetchall()
    )
    assert document_domains["doc_default_only"] == "default"
    assert snapshot_domains["snap_default_only"] == "default"
    assert document_domains["doc_pre_scoped"] == "curated"
    assert snapshot_domains["snap_pre_scoped"] == "curated"


def test_migration_backfills_unique_recent_selection_batch(migrated_rows) -> None:
    assert migrated_rows.selections[("build_odn", "doc_selected")] == "batch_odn_recent"


def test_migration_backfills_shared_asset_per_build_domain(migrated_rows) -> None:
    assert migrated_rows.documents["doc_shared"] == "__legacy_shared__"
    assert migrated_rows.snapshots["snap_shared"] == "__legacy_shared__"
    assert migrated_rows.selections[("build_odn", "doc_shared")] == "batch_odn_recent"
    assert migrated_rows.selections[("build_civil", "doc_shared")] == "batch_civil"


def test_migration_leaves_ambiguous_selection_batch_null(migrated_rows) -> None:
    assert migrated_rows.selections[("build_odn", "doc_ambiguous")] is None
    assert migrated_rows.selections[("build_odn", "doc_wrong_domain")] is None
    assert migrated_rows.selections[("build_odn", "doc_wrong_document")] is None
    assert migrated_rows.selections[("build_odn", "doc_wrong_snapshot")] is None
    assert migrated_rows.selections[("build_odn", "doc_late")] is None


def test_migration_treats_duplicate_links_to_one_batch_as_unambiguous(migrated_rows) -> None:
    assert migrated_rows.selections[("build_odn", "doc_duplicate_link")] == "batch_odn_recent"


def test_migration_is_idempotent(legacy_conn) -> None:
    _run_migration(legacy_conn)
    before = legacy_conn.execute(
        """SELECT
        (SELECT jsonb_agg(to_jsonb(d) ORDER BY id) FROM asset_documents d),
        (SELECT jsonb_agg(to_jsonb(s) ORDER BY id) FROM asset_document_snapshots s),
        (SELECT count(*) FROM pg_constraint WHERE connamespace = current_schema()::regnamespace),
        (SELECT count(*) FROM pg_indexes WHERE schemaname = current_schema())"""
    ).fetchone()

    _run_migration(legacy_conn)

    after = legacy_conn.execute(
        """SELECT
        (SELECT jsonb_agg(to_jsonb(d) ORDER BY id) FROM asset_documents d),
        (SELECT jsonb_agg(to_jsonb(s) ORDER BY id) FROM asset_document_snapshots s),
        (SELECT count(*) FROM pg_constraint WHERE connamespace = current_schema()::regnamespace),
        (SELECT count(*) FROM pg_indexes WHERE schemaname = current_schema())"""
    ).fetchone()
    assert after == before


def _index_oid(connection, schema_name: str, index_name: str) -> int | None:
    row = connection.execute(
        """SELECT indexes.oid
        FROM pg_class AS indexes
        JOIN pg_namespace AS namespaces ON namespaces.oid = indexes.relnamespace
        WHERE namespaces.nspname = %s AND indexes.relname = %s""",
        (schema_name, index_name),
    ).fetchone()
    return row[0] if row else None


def test_active_release_index_is_schema_safe_and_oid_stable(legacy_conn) -> None:
    index_name = "uq_asset_publish_releases_domain_channel_active"
    legacy_conn.execute(
        """CREATE UNIQUE INDEX IF NOT EXISTS uq_asset_publish_releases_domain_channel_active
        ON public.asset_publish_releases(domain, channel)
        WHERE status = 'active'"""
    )
    public_before = _index_oid(legacy_conn, "public", index_name)
    assert public_before is not None

    _run_migration(legacy_conn)

    assert _index_oid(legacy_conn, "public", index_name) == public_before
    target_before = _index_oid(legacy_conn, legacy_conn.execute("SELECT current_schema()").fetchone()[0], index_name)
    assert target_before is not None
    _run_migration(legacy_conn)
    target_after = _index_oid(
        legacy_conn,
        legacy_conn.execute("SELECT current_schema()").fetchone()[0],
        index_name,
    )
    assert target_after == target_before


def test_migration_scopes_uniques_and_active_releases_by_domain_channel(legacy_conn) -> None:
    _run_migration(legacy_conn)
    insert_document(legacy_conn, domain="odn", key="doc:/same.pdf", row_id="new_odn")
    insert_document(
        legacy_conn,
        domain="civil_engineering",
        key="doc:/same.pdf",
        row_id="new_civil",
    )
    with pytest.raises(psycopg.errors.UniqueViolation):
        insert_document(legacy_conn, domain="odn", key="doc:/same.pdf", row_id="dup")

    legacy_conn.execute(
        """INSERT INTO asset_publish_releases
        (id, build_id, domain, channel, status) VALUES
        ('release_preview', 'build_odn', 'odn', 'preview', 'active')"""
    )
    legacy_conn.execute(
        """INSERT INTO asset_publish_releases
        (id, build_id, domain, channel, status) VALUES
        ('release_civil_prod', 'build_civil', 'civil_engineering', 'prod', 'active'),
        ('release_odn_retired', 'build_odn', 'odn', 'prod', 'retired')"""
    )
    with pytest.raises(psycopg.errors.UniqueViolation):
        legacy_conn.execute(
            """INSERT INTO asset_publish_releases
            (id, build_id, domain, channel, status) VALUES
            ('release_prod_duplicate', 'build_odn', 'odn', 'prod', 'active')"""
        )


def test_migration_catalog_has_domain_constraints_and_selection_provenance(legacy_conn) -> None:
    _run_migration(legacy_conn)
    not_null = dict(
        legacy_conn.execute(
            """SELECT table_name, is_nullable
            FROM information_schema.columns
            WHERE table_schema = current_schema()
              AND column_name = 'domain'
              AND table_name IN ('asset_documents', 'asset_document_snapshots')"""
        ).fetchall()
    )
    assert not_null == {
        "asset_documents": "NO",
        "asset_document_snapshots": "NO",
    }

    unique_sets = {
        (table_name, tuple(columns))
        for table_name, columns in legacy_conn.execute(
            """SELECT relations.relname,
                      ARRAY(
                          SELECT attributes.attname
                          FROM unnest(constraints.conkey) AS keys(attnum)
                          JOIN pg_attribute AS attributes
                            ON attributes.attrelid = constraints.conrelid
                           AND attributes.attnum = keys.attnum
                          ORDER BY attributes.attname
                      )
            FROM pg_constraint AS constraints
            JOIN pg_class AS relations ON relations.oid = constraints.conrelid
            WHERE constraints.connamespace = current_schema()::regnamespace
              AND constraints.contype = 'u'
              AND relations.relname IN ('asset_documents', 'asset_document_snapshots')"""
        ).fetchall()
    }
    assert ("asset_documents", ("document_key", "domain")) in unique_sets
    assert ("asset_document_snapshots", ("domain", "normalized_content_hash")) in unique_sets
    assert ("asset_documents", ("document_key",)) not in unique_sets
    assert ("asset_document_snapshots", ("normalized_content_hash",)) not in unique_sets

    foreign_keys = {
        (local_attribute, referenced_attribute, delete_action)
        for local_attribute, referenced_attribute, delete_action in legacy_conn.execute(
            """SELECT local_attributes.attname,
                      referenced_attributes.attname,
                      constraints.confdeltype
            FROM pg_constraint AS constraints
            JOIN LATERAL unnest(constraints.conkey, constraints.confkey)
              AS keys(local_attnum, referenced_attnum) ON true
            JOIN pg_attribute AS local_attributes
              ON local_attributes.attrelid = constraints.conrelid
             AND local_attributes.attnum = keys.local_attnum
            JOIN pg_attribute AS referenced_attributes
              ON referenced_attributes.attrelid = constraints.confrelid
             AND referenced_attributes.attnum = keys.referenced_attnum
            WHERE constraints.conrelid = 'asset_build_document_snapshots'::regclass
              AND constraints.confrelid = 'asset_source_batches'::regclass
              AND constraints.contype = 'f'"""
        ).fetchall()
    }
    assert ("source_batch_id", "id", "n") in foreign_keys
    assert legacy_conn.execute(
        "SELECT to_regclass('idx_asset_build_document_snapshots_batch')"
    ).fetchone()[0] is not None


def test_migration_does_not_accept_fk_to_batch_code_as_correct(legacy_conn) -> None:
    _run_migration(legacy_conn)
    legacy_conn.execute(
        """ALTER TABLE asset_build_document_snapshots
        DROP CONSTRAINT fk_asset_build_document_snapshots_source_batch"""
    )
    legacy_conn.execute(
        "UPDATE asset_build_document_snapshots SET source_batch_id = NULL"
    )
    legacy_conn.execute(
        """ALTER TABLE asset_build_document_snapshots
        ADD CONSTRAINT legacy_wrong_source_batch_fk
        FOREIGN KEY (source_batch_id) REFERENCES asset_source_batches(batch_code)
        ON DELETE SET NULL"""
    )

    _run_migration(legacy_conn)

    referenced_columns = {
        row[0]
        for row in legacy_conn.execute(
            """SELECT referenced_attributes.attname
            FROM pg_constraint AS constraints
            JOIN unnest(constraints.confkey) AS keys(attnum) ON true
            JOIN pg_attribute AS referenced_attributes
              ON referenced_attributes.attrelid = constraints.confrelid
             AND referenced_attributes.attnum = keys.attnum
            WHERE constraints.conrelid = 'asset_build_document_snapshots'::regclass
              AND constraints.confrelid = 'asset_source_batches'::regclass
              AND constraints.contype = 'f'"""
        ).fetchall()
    }
    assert referenced_columns == {"id"}
    assert legacy_conn.execute(
        """SELECT source_batch_id
        FROM asset_build_document_snapshots
        WHERE build_id = 'build_odn' AND document_id = 'doc_selected'"""
    ).fetchone() == ("batch_odn_recent",)


def insert_document(conn, *, domain: str, key: str, row_id: str | None = None) -> None:
    conn.execute(
        """INSERT INTO asset_documents (id, domain, document_key, created_at)
        VALUES (%s, %s, %s, '2024-02-01T00:00:00Z')""",
        (row_id or uuid4().hex, domain, key),
    )


def test_fresh_schema_uses_domain_scoped_uniques(conn) -> None:
    _execute_ddl(conn, _ASSET_DDL.read_text(encoding="utf-8"))
    assert conn.execute(
        """SELECT count(*)
        FROM pg_indexes
        WHERE schemaname = current_schema()
          AND indexname = 'idx_asset_build_document_snapshots_batch'"""
    ).fetchone()[0] == 1
    insert_document(conn, domain="odn", key="doc:/same.pdf")
    insert_document(conn, domain="civil_engineering", key="doc:/same.pdf")
    with pytest.raises(psycopg.errors.UniqueViolation):
        insert_document(conn, domain="odn", key="doc:/same.pdf")

    insert_snapshot(conn, domain="odn", normalized_hash="same-hash")
    insert_snapshot(conn, domain="civil_engineering", normalized_hash="same-hash")
    with pytest.raises(psycopg.errors.UniqueViolation):
        insert_snapshot(conn, domain="odn", normalized_hash="same-hash")


def insert_snapshot(conn, *, domain: str, normalized_hash: str) -> None:
    row_id = uuid4().hex
    conn.execute(
        """INSERT INTO asset_document_snapshots
        (id, domain, normalized_content_hash, raw_content_hash, mime_type, created_at)
        VALUES (%s, %s, %s, %s, 'text/plain', '2024-02-01T00:00:00Z')""",
        (row_id, domain, normalized_hash, f"raw-{row_id}"),
    )


def test_transactional_ddl_rolls_back_the_whole_migration(conn) -> None:
    with pytest.raises(psycopg.errors.UndefinedTable):
        _execute_ddl(
            conn,
            "CREATE TABLE transaction_probe (id integer); "
            "INSERT INTO table_that_does_not_exist VALUES (1);",
            transactional=True,
        )

    exists = conn.execute("SELECT to_regclass('transaction_probe')").fetchone()[0]
    assert exists is None


def test_ensure_schema_twice_preserves_data_and_catalog(db_config, _ensure_schema) -> None:
    def snapshot() -> tuple:
        connection = psycopg.connect(db_config.conninfo, autocommit=True)
        try:
            return connection.execute(
                """SELECT
                (SELECT count(*) FROM asset_documents),
                (SELECT count(*) FROM asset_document_snapshots),
                (SELECT COALESCE(md5(string_agg(row_to_json(d)::text, '' ORDER BY id)), '')
                   FROM asset_documents d),
                (SELECT COALESCE(md5(string_agg(row_to_json(s)::text, '' ORDER BY id)), '')
                   FROM asset_document_snapshots s),
                (SELECT count(*) FROM pg_constraint
                   WHERE connamespace = 'public'::regnamespace),
                (SELECT count(*) FROM pg_indexes WHERE schemaname = 'public')"""
            ).fetchone()
        finally:
            connection.close()

    # Converge any pre-existing disposable DB state before measuring the two
    # consecutive idempotency calls below.
    pg_schema.ensure_schema(db_config)
    before = snapshot()
    pg_schema.ensure_schema(db_config)
    pg_schema.ensure_schema(db_config)
    assert snapshot() == before
