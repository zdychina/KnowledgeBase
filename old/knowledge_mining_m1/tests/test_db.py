"""Test MiningDB with v0.5 fields using temporary SQLite files."""
from __future__ import annotations

import json
import sqlite3
import tempfile
from pathlib import Path

import pytest

from knowledge_mining.mining.db import MiningDB


@pytest.fixture()
def db_path(tmp_path: Path) -> Path:
    return tmp_path / "test.db"


@pytest.fixture()
def db(db_path: Path) -> MiningDB:
    mining_db = MiningDB(db_path)
    mining_db.create_tables()
    return mining_db


@pytest.fixture()
def conn(db: MiningDB) -> sqlite3.Connection:
    c = db.connect()
    yield c
    c.close()


def _make_batch(conn: sqlite3.Connection) -> str:
    return MiningDB.create_source_batch(conn, "test-batch-001", "folder_scan")


def _make_version(conn: sqlite3.Connection, batch_id: str) -> str:
    return MiningDB.create_publish_version(conn, "pv-001", "staging", batch_id)


def _bootstrap(conn: sqlite3.Connection) -> str:
    """Create batch + staging version, return pv_id."""
    batch_id = _make_batch(conn)
    return _make_version(conn, batch_id)


class TestMiningDBInit:
    def test_creates_parent_dirs(self, tmp_path: Path):
        nested = tmp_path / "a" / "b" / "c" / "test.db"
        mdb = MiningDB(nested)
        mdb.create_tables()
        assert nested.parent.exists()

    def test_connect_wal_mode(self, db: MiningDB):
        conn = db.connect()
        mode = conn.execute("PRAGMA journal_mode").fetchone()[0]
        conn.close()
        assert mode == "wal"

    def test_tables_created(self, conn: sqlite3.Connection):
        tables = {
            row[0]
            for row in conn.execute(
                "SELECT name FROM sqlite_master WHERE type='table'"
            ).fetchall()
        }
        assert "asset_source_batches" in tables
        assert "asset_publish_versions" in tables
        assert "asset_raw_documents" in tables
        assert "asset_raw_segments" in tables
        assert "asset_canonical_segments" in tables
        assert "asset_canonical_segment_sources" in tables


class TestCreateSourceBatch:
    def test_inserts_and_returns_id(self, conn: sqlite3.Connection):
        batch_id = MiningDB.create_source_batch(
            conn, "b1", "folder_scan", description="test",
        )
        assert batch_id
        row = conn.execute(
            "SELECT batch_code, source_type FROM asset_source_batches WHERE id = ?",
            (batch_id,),
        ).fetchone()
        assert row[0] == "b1"
        assert row[1] == "folder_scan"

    def test_metadata_json(self, conn: sqlite3.Connection):
        meta = {"key": "value"}
        batch_id = MiningDB.create_source_batch(
            conn, "b2", "api_import", metadata_json=meta,
        )
        row = conn.execute(
            "SELECT metadata_json FROM asset_source_batches WHERE id = ?",
            (batch_id,),
        ).fetchone()
        assert json.loads(row[0]) == meta


class TestCreatePublishVersion:
    def test_staging_default(self, conn: sqlite3.Connection):
        batch_id = _make_batch(conn)
        pv_id = MiningDB.create_publish_version(conn, "pv1", "staging", batch_id)
        row = conn.execute(
            "SELECT status, source_batch_id FROM asset_publish_versions WHERE id = ?",
            (pv_id,),
        ).fetchone()
        assert row[0] == "staging"
        assert row[1] == batch_id


class TestInsertRawDocument:
    def test_full_insert(self, conn: sqlite3.Connection):
        pv_id = _bootstrap(conn)
        doc_id = MiningDB.insert_raw_document(
            conn,
            publish_version_id=pv_id,
            document_key="docs/readme.md",
            source_uri="/data/readme.md",
            relative_path="docs/readme.md",
            file_name="readme.md",
            file_type="markdown",
            content_hash="sha256abc",
            source_type="folder_scan",
            title="Readme",
            document_type="command",
            scope_json={"product": "5G"},
            tags_json=["v1"],
            structure_quality="markdown_native",
        )
        assert doc_id
        row = conn.execute(
            "SELECT file_type, title, scope_json, tags_json FROM asset_raw_documents WHERE id = ?",
            (doc_id,),
        ).fetchone()
        assert row[0] == "markdown"
        assert row[1] == "Readme"
        assert json.loads(row[2]) == {"product": "5G"}
        assert json.loads(row[3]) == ["v1"]

    def test_defaults(self, conn: sqlite3.Connection):
        pv_id = _bootstrap(conn)
        doc_id = MiningDB.insert_raw_document(
            conn, pv_id, "a.txt", "/a.txt", "a.txt", "a.txt", "txt", "hash1",
        )
        row = conn.execute(
            "SELECT source_type, structure_quality, metadata_json FROM asset_raw_documents WHERE id = ?",
            (doc_id,),
        ).fetchone()
        assert row[0] is None
        assert row[1] == "unknown"
        assert json.loads(row[2]) == {}


class TestInsertRawSegment:
    def test_full_insert(self, conn: sqlite3.Connection):
        pv_id = _bootstrap(conn)
        doc_id = MiningDB.insert_raw_document(
            conn, pv_id, "a.md", "/a.md", "a.md", "a.md", "markdown", "h1",
        )
        seg_id = MiningDB.insert_raw_segment(
            conn,
            publish_version_id=pv_id,
            raw_document_id=doc_id,
            segment_key="a.md#0",
            segment_index=0,
            block_type="paragraph",
            semantic_role="concept",
            raw_text="Hello world",
            normalized_text="hello world",
            content_hash="ch1",
            normalized_hash="nh1",
            token_count=2,
            section_path=[{"title": "Intro", "level": 1}],
            section_title="Intro",
            entity_refs_json=[{"type": "command", "name": "ADD"}],
        )
        assert seg_id
        row = conn.execute(
            "SELECT block_type, semantic_role, section_path, entity_refs_json FROM asset_raw_segments WHERE id = ?",
            (seg_id,),
        ).fetchone()
        assert row[0] == "paragraph"
        assert row[1] == "concept"
        assert json.loads(row[2]) == [{"title": "Intro", "level": 1}]
        assert json.loads(row[3]) == [{"type": "command", "name": "ADD"}]

    def test_defaults(self, conn: sqlite3.Connection):
        pv_id = _bootstrap(conn)
        doc_id = MiningDB.insert_raw_document(
            conn, pv_id, "b.md", "/b.md", "b.md", "b.md", "markdown", "h2",
        )
        seg_id = MiningDB.insert_raw_segment(
            conn, pv_id, doc_id, "b.md#0", 0, "paragraph", "unknown",
            "text", "text", "h", "nh",
        )
        row = conn.execute(
            "SELECT structure_json, source_offsets_json, metadata_json FROM asset_raw_segments WHERE id = ?",
            (seg_id,),
        ).fetchone()
        assert json.loads(row[0]) == {}
        assert json.loads(row[1]) == {}
        assert json.loads(row[2]) == {}


class TestInsertCanonicalSegment:
    def test_full_insert(self, conn: sqlite3.Connection):
        pv_id = _bootstrap(conn)
        canon_id = MiningDB.insert_canonical_segment(
            conn,
            publish_version_id=pv_id,
            canonical_key="c000000",
            block_type="paragraph",
            semantic_role="concept",
            canonical_text="Hello world",
            search_text="hello world",
            title="Intro",
            summary="A greeting",
            entity_refs_json=[{"type": "command", "name": "ADD"}],
            scope_json={"product": "5G"},
            has_variants=True,
            variant_policy="require_scope",
            quality_score=0.95,
        )
        assert canon_id
        row = conn.execute(
            """SELECT canonical_key, has_variants, variant_policy, quality_score
               FROM asset_canonical_segments WHERE id = ?""",
            (canon_id,),
        ).fetchone()
        assert row[0] == "c000000"
        assert row[1] == 1  # SQLite stores bool as int
        assert row[2] == "require_scope"
        assert row[3] == pytest.approx(0.95)


class TestInsertSourceMapping:
    def test_primary_mapping(self, conn: sqlite3.Connection):
        pv_id = _bootstrap(conn)
        doc_id = MiningDB.insert_raw_document(
            conn, pv_id, "a.md", "/a.md", "a.md", "a.md", "markdown", "h1",
        )
        seg_id = MiningDB.insert_raw_segment(
            conn, pv_id, doc_id, "a.md#0", 0, "paragraph", "unknown",
            "text", "text", "h", "nh",
        )
        canon_id = MiningDB.insert_canonical_segment(
            conn, pv_id, "c000000", "paragraph", "unknown", "text", "text",
        )
        map_id = MiningDB.insert_source_mapping(
            conn, pv_id, canon_id, seg_id, "primary",
            is_primary=True, priority=0,
        )
        assert map_id
        row = conn.execute(
            "SELECT relation_type, is_primary, priority FROM asset_canonical_segment_sources WHERE id = ?",
            (map_id,),
        ).fetchone()
        assert row[0] == "primary"
        assert row[1] == 1
        assert row[2] == 0


class TestActivateVersion:
    def test_activates_new_archives_old(self, conn: sqlite3.Connection):
        # First version -> active
        batch1 = _make_batch(conn)
        pv1 = _make_version(conn, batch1)
        MiningDB.activate_version(conn, pv1)
        conn.commit()

        status1 = conn.execute(
            "SELECT status FROM asset_publish_versions WHERE id = ?", (pv1,),
        ).fetchone()[0]
        assert status1 == "active"

        # Second version -> staging, then activate
        batch2 = MiningDB.create_source_batch(conn, "b2", "folder_scan")
        pv2 = MiningDB.create_publish_version(conn, "pv2", "staging", batch2)
        MiningDB.activate_version(conn, pv2)
        conn.commit()

        status1 = conn.execute(
            "SELECT status FROM asset_publish_versions WHERE id = ?", (pv1,),
        ).fetchone()[0]
        status2 = conn.execute(
            "SELECT status FROM asset_publish_versions WHERE id = ?", (pv2,),
        ).fetchone()[0]
        assert status1 == "archived"
        assert status2 == "active"


class TestFailVersion:
    def test_marks_failed(self, conn: sqlite3.Connection):
        batch_id = _make_batch(conn)
        pv_id = _make_version(conn, batch_id)
        MiningDB.fail_version(conn, pv_id, "test error")
        conn.commit()

        row = conn.execute(
            "SELECT status, build_error FROM asset_publish_versions WHERE id = ?",
            (pv_id,),
        ).fetchone()
        assert row[0] == "failed"
        assert row[1] == "test error"

    def test_does_not_affect_active(self, conn: sqlite3.Connection):
        batch_id = _make_batch(conn)
        pv_active = _make_version(conn, batch_id)
        MiningDB.activate_version(conn, pv_active)
        conn.commit()

        batch2 = MiningDB.create_source_batch(conn, "b2", "folder_scan")
        pv_fail = MiningDB.create_publish_version(conn, "pv2", "staging", batch2)
        MiningDB.fail_version(conn, pv_fail, "bad data")
        conn.commit()

        status_active = conn.execute(
            "SELECT status FROM asset_publish_versions WHERE id = ?",
            (pv_active,),
        ).fetchone()[0]
        assert status_active == "active"
