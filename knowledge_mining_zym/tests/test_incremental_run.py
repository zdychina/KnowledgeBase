"""Test incremental run: second run should correctly classify UPDATE/SKIP."""
from __future__ import annotations

import shutil
import tempfile
from pathlib import Path

import pytest


@pytest.fixture
def tmp_dir():
    d = tempfile.mkdtemp()
    yield Path(d)
    shutil.rmtree(d)


@pytest.fixture
def md_content():
    return """# Test Document

## Section One

Content paragraph one.

## Section Two

Content paragraph two.
"""


@pytest.fixture
def input_dir(tmp_dir, md_content):
    d = tmp_dir / "input"
    d.mkdir()
    (d / "test.md").write_text(md_content, encoding="utf-8")
    return d


class TestIncrementalRun:
    def test_second_run_skips_unchanged(self, input_dir, tmp_dir):
        """Second run with identical content should SKIP all documents."""
        from knowledge_mining.mining.jobs.run import run

        # First run
        result1 = run(str(input_dir))
        assert result1["status"] == "completed"
        assert result1["committed_count"] == 1
        assert result1["new_count"] == 1
        assert result1["skipped_count"] == 0

        # Second run (same content) — should SKIP
        result2 = run(str(input_dir))
        assert result2["status"] == "completed"
        assert result2["skipped_count"] == 1
        assert result2["new_count"] == 0
        assert result2["updated_count"] == 0

    def test_second_run_detects_update(self, input_dir, tmp_dir):
        """Second run with changed content should UPDATE the document."""
        from knowledge_mining.mining.jobs.run import run

        # First run
        result1 = run(str(input_dir))
        assert result1["new_count"] == 1

        # Modify the file
        (input_dir / "test.md").write_text(
            "# Modified Title\n\nNew content here.\n", encoding="utf-8",
        )

        # Second run (changed content) — should UPDATE
        result2 = run(str(input_dir))
        assert result2["status"] == "completed"
        assert result2["updated_count"] == 1
        assert result2["new_count"] == 0
        assert result2["skipped_count"] == 0

    def test_mixed_new_update_skip(self, input_dir, tmp_dir):
        """Run with mix of NEW, UPDATE, and SKIP documents."""
        from knowledge_mining.mining.jobs.run import run

        # First run with one file
        result1 = run(str(input_dir))
        assert result1["new_count"] == 1

        # Add a new file, modify existing
        (input_dir / "new_doc.md").write_text("# New Doc\n\nNew content.\n", encoding="utf-8")
        (input_dir / "test.md").write_text(
            "# Changed Title\n\nChanged content.\n", encoding="utf-8",
        )

        # Second run: 1 UPDATE + 1 NEW
        result2 = run(str(input_dir))
        assert result2["updated_count"] == 1
        assert result2["new_count"] == 1
