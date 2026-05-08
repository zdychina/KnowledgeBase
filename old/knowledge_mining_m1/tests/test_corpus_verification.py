"""Boundary tests for real corpus scenarios aligned with v0.5 schema."""
from __future__ import annotations

import tempfile
from pathlib import Path

from knowledge_mining.mining.canonicalization import canonicalize
from knowledge_mining.mining.document_profile import build_profile
from knowledge_mining.mining.ingestion import ingest_directory
from knowledge_mining.mining.jobs.run import run_pipeline
from knowledge_mining.mining.models import BatchParams
from knowledge_mining.mining.parsers import create_parser
from knowledge_mining.mining.segmentation import segment_document


def _write_files(tmp: Path, files: dict[str, str]) -> None:
    for name, content in files.items():
        p = tmp / name
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text(content, encoding="utf-8")


def test_no_manifest_plain_markdown():
    """v0.5: No manifest, no frontmatter — pure directory scan works."""
    with tempfile.TemporaryDirectory() as tmp:
        tmp = Path(tmp)
        _write_files(tmp, {
            "doc.md": "# Plain\n\nJust text",
        })
        summary = run_pipeline(tmp, tmp / "test.sqlite")
        assert summary["discovered_documents"] == 1
        assert summary["raw_segments"] >= 1


def test_batch_params_inherited():
    """v0.5: BatchParams scope/tags inherited into profile."""
    with tempfile.TemporaryDirectory() as tmp:
        tmp = Path(tmp)
        _write_files(tmp, {
            "doc.md": "# Notes\n\nSome content",
        })
        bp = BatchParams(
            default_source_type="expert_authored",
            default_document_type="expert_note",
            batch_scope={"scenario": "5GC"},
            tags=["5G", "core"],
        )
        docs, _ = ingest_directory(tmp, bp)
        profile = build_profile(docs[0])
        assert profile.source_type == "expert_authored"
        assert profile.scope_json == {"scenario": "5GC"}
        assert profile.document_type == "expert_note"
        assert "5G" in profile.tags_json


def test_html_table_in_markdown():
    """Markdown with HTML table preserved as html_table block."""
    with tempfile.TemporaryDirectory() as tmp:
        tmp = Path(tmp)
        _write_files(tmp, {
            "doc.md": "# Data\n\n<table>\n<tr><td>A</td></tr>\n</table>",
        })
        docs, _ = ingest_directory(tmp)
        profile = build_profile(docs[0])
        parser = create_parser("markdown")
        root = parser.parse(docs[0].content, docs[0].file_name, {})
        segments = segment_document(root, profile)
        html_table_segs = [s for s in segments if s.block_type == "html_table"]
        assert len(html_table_segs) >= 1


def test_manifest_jsonl_is_skipped():
    """v0.5: manifest.jsonl is not a document, it is skipped."""
    with tempfile.TemporaryDirectory() as tmp:
        tmp = Path(tmp)
        _write_files(tmp, {
            "doc.md": "# Title\n\nContent",
            "manifest.jsonl": '{"doc_id":"x"}\n',
        })
        docs, summary = ingest_directory(tmp)
        assert len(docs) == 1
        assert summary["skipped_files"] == 1
