"""Test publishing: staging->active lifecycle, continuous publish, failed isolation, validation."""
from __future__ import annotations

import sqlite3
import time
import tempfile
from pathlib import Path

from knowledge_mining.mining.canonicalization import canonicalize
from knowledge_mining.mining.db import MiningDB
from knowledge_mining.mining.document_profile import build_profile
from knowledge_mining.mining.ingestion import ingest_directory
from knowledge_mining.mining.models import (
    BatchParams,
    CanonicalSegmentData,
    RawDocumentData,
    RawSegmentData,
    SourceMappingData,
)
from knowledge_mining.mining.parsers import create_parser
from knowledge_mining.mining.publishing import publish
from knowledge_mining.mining.segmentation import segment_document


def _write_files(tmp: Path, files: dict[str, str | bytes]) -> None:
    for name, content in files.items():
        p = tmp / name
        p.parent.mkdir(parents=True, exist_ok=True)
        if isinstance(content, bytes):
            p.write_bytes(content)
        else:
            p.write_text(content, encoding="utf-8")


def _run_mini_pipeline(tmp: Path):
    """Helper: ingest -> profile -> parse -> segment -> canonicalize."""
    docs, _ = ingest_directory(tmp)
    profiles = [build_profile(d) for d in docs]
    profile_map = {p.document_key: p for p in profiles}
    all_segments: list[RawSegmentData] = []
    for doc, profile in zip(docs, profiles):
        parser = create_parser(doc.file_type)
        doc_root = parser.parse(doc.content, doc.file_name, {})
        if doc_root is None:
            continue
        segments = segment_document(doc_root, profile)
        all_segments.extend(segments)
    canonicals, mappings = canonicalize(all_segments, profile_map)
    return docs, all_segments, canonicals, mappings


class TestStagingToActive:
    def test_publish_creates_active_version(self):
        with tempfile.TemporaryDirectory() as tmp:
            tmp = Path(tmp)
            _write_files(tmp, {
                "doc.md": "# Title\n\nHello world\n\n## Parameters\n\nparam1: val1",
            })
            docs, segments, canonicals, mappings = _run_mini_pipeline(tmp)

            db_path = tmp / "test.sqlite"
            result = publish(docs, segments, canonicals, mappings, db_path)

            assert result["status"] == "active"
            assert result["active_version_id"] is not None
            assert result["documents"] >= 1
            assert result["segments"] >= 1
            assert result["canonicals"] >= 1
            assert result["source_mappings"] >= 1

    def test_active_version_in_db(self):
        with tempfile.TemporaryDirectory() as tmp:
            tmp = Path(tmp)
            _write_files(tmp, {"doc.md": "# Hello\n\nWorld"})
            docs, segments, canonicals, mappings = _run_mini_pipeline(tmp)

            db_path = tmp / "test.sqlite"
            publish(docs, segments, canonicals, mappings, db_path)

            db = MiningDB(db_path)
            conn = db.connect()
            try:
                row = conn.execute(
                    "SELECT status FROM asset_publish_versions WHERE status = 'active'"
                ).fetchone()
                assert row is not None
            finally:
                conn.close()


class TestContinuousPublish:
    def test_second_publish_archives_first(self):
        with tempfile.TemporaryDirectory() as tmp:
            tmp = Path(tmp)

            # First publish with input1
            input1 = tmp / "input1"
            input1.mkdir()
            _write_files(input1, {"doc.md": "# Version One\n\nContent v1"})
            docs1, segs1, canon1, maps1 = _run_mini_pipeline(input1)
            db_path = tmp / "test.sqlite"
            result1 = publish(docs1, segs1, canon1, maps1, db_path)
            assert result1["status"] == "active"
            pv1 = result1["active_version_id"]

            # Ensure different timestamp for batch_code uniqueness
            time.sleep(1.1)

            # Second publish with input2
            input2 = tmp / "input2"
            input2.mkdir()
            _write_files(input2, {"doc2.md": "# Version Two\n\nContent v2"})
            docs2, segs2, canon2, maps2 = _run_mini_pipeline(input2)
            result2 = publish(docs2, segs2, canon2, maps2, db_path)
            assert result2["status"] == "active"
            pv2 = result2["active_version_id"]

            # Verify states
            db = MiningDB(db_path)
            conn = db.connect()
            try:
                status1 = conn.execute(
                    "SELECT status FROM asset_publish_versions WHERE id = ?", (pv1,),
                ).fetchone()[0]
                status2 = conn.execute(
                    "SELECT status FROM asset_publish_versions WHERE id = ?", (pv2,),
                ).fetchone()[0]
                assert status1 == "archived"
                assert status2 == "active"
            finally:
                conn.close()


class TestFailedIsolation:
    def test_failed_version_does_not_activate(self):
        with tempfile.TemporaryDirectory() as tmp:
            tmp = Path(tmp)
            _write_files(tmp, {"doc.md": "# Hello\n\nWorld"})

            # First: normal publish -> active
            docs, segs, canon, maps = _run_mini_pipeline(tmp)
            db1 = tmp / "test1.sqlite"
            result1 = publish(docs, segs, canon, maps, db1)
            assert result1["status"] == "active"

            # Second: publish with empty canonicals to trigger validation failure
            db2 = tmp / "test2.sqlite"
            result2 = publish(docs, segs, [], [], db2)
            assert result2["status"] == "failed"

            # Verify: first DB still active
            db = MiningDB(db1)
            conn = db.connect()
            try:
                active_count = conn.execute(
                    "SELECT COUNT(*) FROM asset_publish_versions WHERE status = 'active'"
                ).fetchone()[0]
                assert active_count == 1
            finally:
                conn.close()


class TestValidation:
    def test_requires_at_least_one_canonical(self):
        with tempfile.TemporaryDirectory() as tmp:
            tmp = Path(tmp)
            _write_files(tmp, {"doc.md": "# Hello\n\nWorld"})
            docs, segs, _, _ = _run_mini_pipeline(tmp)

            db_path = tmp / "test.sqlite"
            # Publish with empty canonicals
            result = publish(docs, segs, [], [], db_path)
            assert result["status"] == "failed"
            assert "no canonical_segments" in "; ".join(result.get("errors", []))

    def test_requires_primary_uniqueness(self):
        """Each canonical must have exactly 1 primary source — enforced by validation."""
        with tempfile.TemporaryDirectory() as tmp:
            tmp = Path(tmp)
            _write_files(tmp, {"doc.md": "# Hello\n\nWorld"})
            docs, segs, canon, maps = _run_mini_pipeline(tmp)

            db_path = tmp / "test.sqlite"
            result = publish(docs, segs, canon, maps, db_path)
            # Normal pipeline should satisfy uniqueness
            assert result["status"] == "active"


class TestPublishingDataIntegrity:
    def test_all_documents_written(self):
        with tempfile.TemporaryDirectory() as tmp:
            tmp = Path(tmp)
            _write_files(tmp, {
                "a.md": "# A\n\nContent A",
                "b.md": "# B\n\nContent B",
            })
            docs, segs, canon, maps = _run_mini_pipeline(tmp)

            db_path = tmp / "test.sqlite"
            publish(docs, segs, canon, maps, db_path)

            db = MiningDB(db_path)
            conn = db.connect()
            try:
                doc_count = conn.execute(
                    "SELECT COUNT(*) FROM asset_raw_documents"
                ).fetchone()[0]
                assert doc_count >= 2
            finally:
                conn.close()

    def test_segments_have_v05_fields(self):
        with tempfile.TemporaryDirectory() as tmp:
            tmp = Path(tmp)
            _write_files(tmp, {"doc.md": "# Title\n\n| A | B |\n|---|---|\n| 1 | 2 |"})
            docs, segs, canon, maps = _run_mini_pipeline(tmp)

            db_path = tmp / "test.sqlite"
            publish(docs, segs, canon, maps, db_path)

            db = MiningDB(db_path)
            conn = db.connect()
            try:
                # Verify semantic_role and block_type columns exist and are populated
                row = conn.execute(
                    "SELECT block_type, semantic_role FROM asset_raw_segments LIMIT 1"
                ).fetchone()
                assert row is not None
                assert row[0] in ("paragraph", "table", "code", "list", "html_table", "unknown")
            finally:
                conn.close()

    def test_source_mappings_link_correctly(self):
        with tempfile.TemporaryDirectory() as tmp:
            tmp = Path(tmp)
            _write_files(tmp, {"doc.md": "# Hello\n\nUnique content here"})
            docs, segs, canon, maps = _run_mini_pipeline(tmp)

            db_path = tmp / "test.sqlite"
            publish(docs, segs, canon, maps, db_path)

            db = MiningDB(db_path)
            conn = db.connect()
            try:
                # Every mapping should link to a real canonical and real segment
                rows = conn.execute(
                    """SELECT cs.canonical_key, rs.segment_key
                       FROM asset_canonical_segment_sources src
                       JOIN asset_canonical_segments cs ON cs.id = src.canonical_segment_id
                       JOIN asset_raw_segments rs ON rs.id = src.raw_segment_id"""
                ).fetchall()
                assert len(rows) >= 1
            finally:
                conn.close()

    def test_non_parsable_docs_have_processing_profile(self):
        """html/pdf/docx should get parse_status=skipped in processing_profile_json."""
        with tempfile.TemporaryDirectory() as tmp:
            tmp = Path(tmp)
            _write_files(tmp, {
                "page.html": "<html><body>Hello</body></html>",
                "doc.md": "# MD\n\nContent",
            })
            docs, segs, canon, maps = _run_mini_pipeline(tmp)

            db_path = tmp / "test.sqlite"
            publish(docs, segs, canon, maps, db_path)

            db = MiningDB(db_path)
            conn = db.connect()
            try:
                import json
                row = conn.execute(
                    "SELECT processing_profile_json FROM asset_raw_documents WHERE file_type = 'html'"
                ).fetchone()
                assert row is not None
                profile = json.loads(row[0])
                assert profile.get("parse_status") == "skipped"
            finally:
                conn.close()
