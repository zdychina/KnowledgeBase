"""End-to-end pipeline test with temp mixed directory (md+txt+html+pdf)."""
from __future__ import annotations

import tempfile
import time
from pathlib import Path

from knowledge_mining.mining.db import MiningDB
from knowledge_mining.mining.jobs.run import run_pipeline
from knowledge_mining.mining.models import BatchParams


def _write_files(tmp: Path, files: dict[str, str | bytes]) -> None:
    for name, content in files.items():
        p = tmp / name
        p.parent.mkdir(parents=True, exist_ok=True)
        if isinstance(content, bytes):
            p.write_bytes(content)
        else:
            p.write_text(content, encoding="utf-8")


MIXED_DOCS = {
    "readme.md": """# ADD APN

ADD APN command configures APN settings.

## Parameters

| Param | Type | Description |
|-------|------|-------------|
| APNNAME | String | APN name |
| POOLID | Integer | Pool identifier |

## Example

```
ADD APN:APNNAME="internet",POOLID=1;
```
""",
    "notes.txt": """Network Slicing Overview

Network slicing is a key 5G core technology that allows multiple virtual networks
on the same physical infrastructure. Each slice can have different SLA requirements
including bandwidth, latency, and reliability targets.
""",
    "page.html": """<html><body><h1>Configuration Guide</h1><p>HTML content</p></body></html>""",
    "manual.pdf": b"%PDF-1.4 fake pdf content for testing",
}


class TestPipelineEndToEnd:
    def test_mixed_file_types(self):
        """Full pipeline with md+txt+html+pdf."""
        with tempfile.TemporaryDirectory() as tmp:
            tmp = Path(tmp)
            _write_files(tmp, MIXED_DOCS)

            db_path = tmp / "output.sqlite"
            summary = run_pipeline(tmp, db_path)

            # All 4 files discovered
            assert summary["discovered_documents"] == 4
            # md + txt are parsable
            assert summary["parsed_documents"] == 2
            # html + pdf are unparsable
            assert summary["unparsed_documents"] == 2

            # Only parsable docs produce segments
            assert summary["raw_segments"] > 0

            # Canonicals exist (dedup may reduce count)
            assert summary["canonical_segments"] > 0
            assert summary["source_mappings"] > 0

            # Successfully activated
            assert summary["status"] == "active"
            assert summary["active_version_id"] is not None

    def test_sqlite_content_verified(self):
        with tempfile.TemporaryDirectory() as tmp:
            tmp = Path(tmp)
            _write_files(tmp, MIXED_DOCS)

            db_path = tmp / "output.sqlite"
            run_pipeline(tmp, db_path)

            db = MiningDB(db_path)
            conn = db.connect()
            try:
                # Active version exists
                active = conn.execute(
                    "SELECT status FROM asset_publish_versions WHERE status = 'active'"
                ).fetchone()
                assert active is not None

                # All 4 raw documents
                doc_count = conn.execute(
                    "SELECT COUNT(*) FROM asset_raw_documents"
                ).fetchone()[0]
                assert doc_count == 4

                # File types present
                file_types = {
                    row[0]
                    for row in conn.execute(
                        "SELECT DISTINCT file_type FROM asset_raw_documents"
                    ).fetchall()
                }
                assert "markdown" in file_types
                assert "txt" in file_types
                assert "html" in file_types
                assert "pdf" in file_types

                # Segments only from parsable docs
                seg_count = conn.execute(
                    "SELECT COUNT(*) FROM asset_raw_segments"
                ).fetchone()[0]
                assert seg_count > 0

                # Canonicals exist
                canon_count = conn.execute(
                    "SELECT COUNT(*) FROM asset_canonical_segments"
                ).fetchone()[0]
                assert canon_count > 0

                # Source mappings link correctly
                map_count = conn.execute(
                    "SELECT COUNT(*) FROM asset_canonical_segment_sources"
                ).fetchone()[0]
                assert map_count > 0

                # Every canonical has exactly 1 primary source
                bad = conn.execute(
                    """SELECT canonical_segment_id, COUNT(*) as cnt
                       FROM asset_canonical_segment_sources
                       WHERE is_primary = 1
                       GROUP BY canonical_segment_id
                       HAVING cnt != 1"""
                ).fetchall()
                assert len(bad) == 0
            finally:
                conn.close()

    def test_with_batch_params(self):
        with tempfile.TemporaryDirectory() as tmp:
            tmp = Path(tmp)
            _write_files(tmp, {
                "doc.md": "# Title\n\nContent",
                "notes.txt": "Plain text",
            })

            bp = BatchParams(
                default_source_type="folder_scan",
                default_document_type="command",
                batch_scope={"product": "UDG5000"},
                tags=["5G", "core"],
            )
            db_path = tmp / "batch.sqlite"
            summary = run_pipeline(tmp, db_path, batch_params=bp)

            assert summary["status"] == "active"

            db = MiningDB(db_path)
            conn = db.connect()
            try:
                import json
                row = conn.execute(
                    "SELECT source_type, document_type, scope_json, tags_json FROM asset_raw_documents LIMIT 1"
                ).fetchone()
                assert row[0] == "folder_scan"
                assert row[1] == "command"
                scope = json.loads(row[2])
                assert scope["product"] == "UDG5000"
                tags = json.loads(row[3])
                assert "5G" in tags
            finally:
                conn.close()


class TestPipelineEdgeCases:
    def test_empty_directory(self):
        with tempfile.TemporaryDirectory() as tmp:
            db_path = Path(tmp) / "empty.sqlite"
            summary = run_pipeline(Path(tmp), db_path)
            assert summary["discovered_documents"] == 0
            assert summary["raw_segments"] == 0

    def test_only_unparsable_files(self):
        with tempfile.TemporaryDirectory() as tmp:
            tmp = Path(tmp)
            _write_files(tmp, {
                "page.html": "<html></html>",
                "doc.pdf": b"%PDF fake",
            })
            db_path = tmp / "unparsable.sqlite"
            summary = run_pipeline(tmp, db_path)

            assert summary["discovered_documents"] == 2
            assert summary["unparsed_documents"] == 2
            assert summary["parsed_documents"] == 0
            assert summary["raw_segments"] == 0

    def test_dedup_across_documents(self):
        """Identical content in multiple md files should deduplicate."""
        with tempfile.TemporaryDirectory() as tmp:
            tmp = Path(tmp)
            shared = "This is a shared paragraph used in multiple documents for testing."
            _write_files(tmp, {
                "a.md": f"# Doc A\n\n{shared}",
                "b.md": f"# Doc B\n\n{shared}",
            })
            db_path = tmp / "dedup.sqlite"
            summary = run_pipeline(tmp, db_path)

            assert summary["raw_segments"] >= 2
            assert summary["canonical_segments"] < summary["raw_segments"]

    def test_continuous_publish(self):
        """Two publishes to same DB: second archives first, new becomes active."""
        with tempfile.TemporaryDirectory() as tmp:
            tmp = Path(tmp)
            db_path = tmp / "cont.sqlite"

            # First publish: one doc
            input1 = tmp / "input1"
            input1.mkdir()
            _write_files(input1, {"v1.md": "# Version 1\n\nContent v1"})
            s1 = run_pipeline(input1, db_path)
            assert s1["status"] == "active"
            pv1 = s1["active_version_id"]

            # Ensure different timestamp for batch_code uniqueness
            time.sleep(1.1)

            # Second publish: two docs (different input dir)
            input2 = tmp / "input2"
            input2.mkdir()
            _write_files(input2, {
                "v1.md": "# Version 1\n\nContent v1",
                "v2.md": "# Version 2\n\nContent v2",
            })
            s2 = run_pipeline(input2, db_path)
            assert s2["status"] == "active"
            pv2 = s2["active_version_id"]

            db = MiningDB(db_path)
            conn = db.connect()
            try:
                st1 = conn.execute(
                    "SELECT status FROM asset_publish_versions WHERE id = ?",
                    (pv1,),
                ).fetchone()[0]
                st2 = conn.execute(
                    "SELECT status FROM asset_publish_versions WHERE id = ?",
                    (pv2,),
                ).fetchone()[0]
                assert st1 == "archived"
                assert st2 == "active"
            finally:
                conn.close()
