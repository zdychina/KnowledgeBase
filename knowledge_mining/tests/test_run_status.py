"""Test run status machine: completed, failed, partial failures."""
from __future__ import annotations

import shutil
import tempfile
from pathlib import Path

import pytest

from knowledge_mining.mining.contracts.models import MiningRunData
from knowledge_mining.mining.runtime import RuntimeTracker


@pytest.fixture
def tmp_dir():
    d = tempfile.mkdtemp()
    yield Path(d)
    shutil.rmtree(d)


class TestRunStatusMachine:
    def test_completed_no_failures(self, runtime_db):
        """Run with all docs committed should be 'completed' with no has_failures."""
        tracker = RuntimeTracker(runtime_db)
        tracker.create_run(MiningRunData(id="r1", status="running"))
        runtime_db.commit()

        tracker.complete_run("r1", committed_count=5, failed_count=0)
        runtime_db.commit()

        run = runtime_db.get_run("r1")
        assert run["status"] == "completed"
        assert run["committed_count"] == 5
        assert run["failed_count"] == 0

    def test_completed_with_failures_metadata(self, runtime_db):
        """Run with some failures should be 'completed' but have has_failures metadata."""
        tracker = RuntimeTracker(runtime_db)
        tracker.create_run(MiningRunData(id="r2", status="running"))
        runtime_db.commit()

        tracker.complete_run(
            "r2",
            committed_count=3,
            failed_count=2,
            metadata_json={"has_failures": True, "failed_count": 2},
        )
        runtime_db.commit()

        run = runtime_db.get_run("r2")
        assert run["status"] == "completed"
        meta = run["metadata_json"]
        if isinstance(meta, str):
            import json
            meta = json.loads(meta)
        assert meta["has_failures"] is True
        assert meta["failed_count"] == 2

    def test_failed_all_docs_failed(self, runtime_db):
        """Run with all docs failed should be 'failed'."""
        tracker = RuntimeTracker(runtime_db)
        tracker.create_run(MiningRunData(id="r3", status="running"))
        runtime_db.commit()

        # When all docs fail (committed_count=0), pipeline should set status "failed"
        run = runtime_db.get_run("r3")
        assert run is not None

        # Simulate what run.py does for all-failed case
        runtime_db.update_run_status(
            "r3", "failed",
            finished_at="2026-01-01T01:00:00",
            failed_count=3,
            committed_count=0,
            error_summary="All documents failed",
        )
        runtime_db.commit()

        run = runtime_db.get_run("r3")
        assert run["status"] == "failed"
        assert run["error_summary"] == "All documents failed"

    def test_fail_run_on_exception(self, runtime_db):
        """Pipeline exception should mark run as 'failed'."""
        tracker = RuntimeTracker(runtime_db)
        tracker.create_run(MiningRunData(id="r4", status="running"))
        runtime_db.commit()

        tracker.fail_run("r4", "Unexpected error: division by zero")
        runtime_db.commit()

        run = runtime_db.get_run("r4")
        assert run["status"] == "failed"
        assert "division by zero" in run["error_summary"]

    def test_valid_statuses(self, runtime_db):
        """All SQL-valid statuses should be writable."""
        for status in ("queued", "running", "completed", "interrupted", "failed", "cancelled"):
            run_id = f"r_{status}"
            tracker = RuntimeTracker(runtime_db)
            tracker.create_run(MiningRunData(id=run_id, status="running"))
            runtime_db.commit()
            runtime_db.update_run_status(run_id, status)
            runtime_db.commit()
            run = runtime_db.get_run(run_id)
            assert run["status"] == status

    def test_pipeline_partial_failure_status(self, tmp_dir):
        """Integration: pipeline with partial failures should have correct status."""
        from knowledge_mining.mining.jobs.run import run

        input_dir = tmp_dir / "input"
        input_dir.mkdir()
        # Create a valid markdown file
        (input_dir / "good.md").write_text("# Good\n\nValid content here.\n", encoding="utf-8")
        # Create an empty file that might produce no tree
        (input_dir / "empty.md").write_text("", encoding="utf-8")

        result = run(
            str(input_dir),
        )
        # Empty file should be skipped (no tree), not failed
        assert result["status"] == "completed"
