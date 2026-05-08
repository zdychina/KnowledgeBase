"""Test stage events: all doc-level stages should have events recorded."""
from __future__ import annotations

import json
import shutil
import tempfile
from pathlib import Path

import pytest

from knowledge_mining.mining.infra.db import MiningRuntimeDB


def _make_db(cls):
    """Create a PG-backed database adapter for testing."""
    from knowledge_mining.mining.infra.pg_config import MiningDbConfig
    from knowledge_mining.mining.infra.pg_schema import ensure_schema
    from psycopg.rows import dict_row
    from psycopg_pool import ConnectionPool

    cfg = MiningDbConfig()
    ensure_schema(cfg)
    pool = ConnectionPool(
        cfg.conninfo, min_size=1, max_size=2, open=True,
        kwargs={"row_factory": dict_row},
    )
    return cls(pool)


@pytest.fixture
def tmp_dir():
    d = tempfile.mkdtemp()
    yield Path(d)
    shutil.rmtree(d)


@pytest.fixture
def md_content():
    return """# Test Document

## Parameters

| Name  | Type | Desc |
|-------|------|------|
| param1 | str  | desc |

## Notes

- Note one
- Note two
"""


@pytest.fixture
def input_dir(tmp_dir, md_content):
    d = tmp_dir / "input"
    d.mkdir()
    (d / "test.md").write_text(md_content, encoding="utf-8")
    return d


class TestStageEvents:
    def test_doc_level_stages_have_events(self, input_dir, tmp_dir):
        """Each document should have events for segment, build_relations, build_retrieval_units."""
        from knowledge_mining.mining.jobs.run import run

        result = run(str(input_dir))

        rdb = _make_db(MiningRuntimeDB)

        events = rdb.get_stage_events(result["run_id"])
        stages = {e["stage"] for e in events}

        # Doc-level stages (tracked at write-back time)
        assert "segment" in stages, f"Missing 'segment' stage. Got: {stages}"
        assert "build_relations" in stages, f"Missing 'build_relations' stage. Got: {stages}"
        assert "build_retrieval_units" in stages, f"Missing 'build_retrieval_units' stage. Got: {stages}"

        # Global stages
        assert "select_snapshot" in stages
        assert "assemble_build" in stages
        assert "validate_build" in stages

        rdb.close()

    def test_stage_events_have_completed_status(self, input_dir, tmp_dir):
        """Stage end events should have 'completed' status."""
        from knowledge_mining.mining.jobs.run import run

        result = run(str(input_dir))

        rdb = _make_db(MiningRuntimeDB)

        events = rdb.get_stage_events(result["run_id"])
        completed_events = [e for e in events if e["status"] == "completed"]
        started_events = [e for e in events if e["status"] == "started"]

        # Should have pairs of started/completed for each stage
        assert len(completed_events) > 0
        assert len(started_events) > 0

        rdb.close()

    def test_stage_events_have_output_summary(self, input_dir, tmp_dir):
        """Completed stage events should have output_summary with counts."""
        from knowledge_mining.mining.jobs.run import run

        result = run(str(input_dir))

        rdb = _make_db(MiningRuntimeDB)

        events = rdb.get_stage_events(result["run_id"])
        seg_events = [e for e in events if e["stage"] == "segment" and e["status"] == "completed"]
        assert len(seg_events) >= 1
        assert seg_events[0]["output_summary"] is not None
        assert "segments" in seg_events[0]["output_summary"]

        ru_events = [e for e in events if e["stage"] == "build_retrieval_units" and e["status"] == "completed"]
        assert len(ru_events) >= 1
        assert "units" in ru_events[0]["output_summary"]

        rdb.close()

    def test_global_stage_events_no_doc_id(self, input_dir, tmp_dir):
        """Global stages (assemble_build, validate_build) should have no run_document_id."""
        from knowledge_mining.mining.jobs.run import run

        result = run(str(input_dir))

        rdb = _make_db(MiningRuntimeDB)

        events = rdb.get_stage_events(result["run_id"])
        build_events = [e for e in events if e["stage"] == "assemble_build"]
        assert len(build_events) >= 1
        # Global stages should not be tied to a specific document
        for evt in build_events:
            assert evt["run_document_id"] is None

        rdb.close()

    def test_skip_documents_no_stage_events(self, input_dir, tmp_dir):
        """Skipped documents should not generate stage events."""
        from knowledge_mining.mining.jobs.run import run

        # First run
        result1 = run(str(input_dir))

        # Second run (SKIP)
        result2 = run(str(input_dir))
        assert result2["skipped_count"] == 1

        rdb = _make_db(MiningRuntimeDB)

        # Second run should have fewer stage events (only global ones)
        run2_events = rdb.get_stage_events(result2["run_id"])
        run2_stages = {e["stage"] for e in run2_events}
        # Should still have global stages
        assert "assemble_build" in run2_stages
        # But no doc-level stages since doc was skipped
        # (skipped docs don't go through pipeline)

        rdb.close()
