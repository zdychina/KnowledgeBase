"""Comprehensive tests for v1.1+v1.2 Knowledge Mining pipeline."""
from __future__ import annotations

import os
import shutil
import tempfile
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

from knowledge_mining.mining.contracts.models import (
    BatchParams,
    ContentBlock,
    DocumentProfile,
    MiningRunData,
    MiningRunDocumentData,
    RawFileData,
    RawSegmentData,
    ResumePlan,
    SectionNode,
    StageEvent,
    VALID_BLOCK_TYPES,
    VALID_RELATION_TYPES,
    VALID_SEMANTIC_ROLES,
    VALID_SOURCE_TYPES,
    VALID_UNIT_TYPES,
)
from knowledge_mining.mining.infra.hash_utils import (
    compute_raw_hash,
    compute_snapshot_hash,
    content_hash,
    normalize_for_snapshot,
    normalized_hash,
)
from knowledge_mining.mining.infra.db import AssetCoreDB, MiningRuntimeDB
from knowledge_mining.mining.infra.text_utils import token_count, normalize_text, jaccard_similarity


# ===================================================================
# Fixtures
# ===================================================================

@pytest.fixture
def tmp_dir():
    d = tempfile.mkdtemp()
    yield Path(d)
    shutil.rmtree(d)


# asset_db and runtime_db fixtures are provided by conftest.py (PostgreSQL)


@pytest.fixture
def md_content():
    return """# Test Command

Intro paragraph.

## Parameters

| Param | Type | Desc |
|-------|------|------|
| Name  | Str  | Name |
| Type  | Int  | Type |

## Example

```python
ADD APN: Name="internet"
```

## Notes

- First note
- Second note

### Sub-note

Detail here.
"""


@pytest.fixture
def input_dir(tmp_dir, md_content):
    d = tmp_dir / "input"
    d.mkdir()
    (d / "test.md").write_text(md_content, encoding="utf-8")
    (d / "readme.txt").write_text("Plain text readme\nSecond line\n\nThird paragraph\n", encoding="utf-8")
    return d


# ===================================================================
# T1: Models
# ===================================================================

class TestModels:
    def test_frozen_dataclasses(self):
        seg = RawSegmentData(document_key="doc:/a.md", segment_index=0, raw_text="hello")
        with pytest.raises(AttributeError):
            seg.raw_text = "changed"

    def test_valid_constants_match_schema(self):
        assert "folder_scan" in VALID_SOURCE_TYPES
        assert "paragraph" in VALID_BLOCK_TYPES
        assert "heading" in VALID_BLOCK_TYPES
        assert "previous" in VALID_RELATION_TYPES
        assert "section_header_of" in VALID_RELATION_TYPES
        assert "concept" in VALID_SEMANTIC_ROLES
        assert "raw_text" in VALID_UNIT_TYPES
        assert "contextual_text" in VALID_UNIT_TYPES
        assert "entity_card" in VALID_UNIT_TYPES


# ===================================================================
# T2: DB Adapter
# ===================================================================

class TestAssetCoreDB:
    def test_source_batch_crud(self, asset_db):
        asset_db.upsert_source_batch("b1", "BATCH-001", "folder_scan", "test")
        b = asset_db.get_source_batch("b1")
        assert b["batch_code"] == "BATCH-001"
        assert b["source_type"] == "folder_scan"

    def test_document_upsert_idempotent(self, asset_db):
        asset_db.upsert_document("d1", "doc:/a.md", "a.md", "command")
        asset_db.upsert_document("d2", "doc:/a.md", "a.md", "feature")
        d = asset_db.get_document_by_key("doc:/a.md")
        assert d["document_type"] == "feature"

    def test_snapshot_sharing(self, asset_db):
        """Two documents with same normalized_content_hash share a snapshot."""
        asset_db.upsert_snapshot("s1", "hash_abc", "raw1", "text/markdown")
        asset_db.upsert_snapshot("s2", "hash_abc", "raw2", "text/markdown")
        s = asset_db.get_snapshot_by_hash("hash_abc")
        assert s["raw_content_hash"] == "raw2"

    def test_build_and_release(self, asset_db):
        asset_db.insert_build("b1", "B-001", "building", "full", domain="default")
        asset_db.update_build_status("b1", "validated")
        asset_db.insert_release("r1", "R-001", "b1", domain="default")
        asset_db.activate_release("r1")
        ar = asset_db.get_active_release("default", "prod")
        assert ar["status"] == "active"

    def test_release_chain(self, asset_db):
        asset_db.insert_build("b1", "B-001", "validated", "full", domain="default")
        asset_db.insert_build("b2", "B-002", "validated", "full", domain="default")
        asset_db.insert_release("r1", "R-001", "b1", domain="default")
        asset_db.activate_release("r1")
        asset_db.insert_release("r2", "R-002", "b2", previous_release_id="r1", domain="default")
        asset_db.activate_release("r2")
        ar = asset_db.get_active_release("default", "prod")
        assert ar["release_code"] == "R-002"
        assert ar["previous_release_id"] == "r1"


class TestMiningRuntimeDB:
    def test_run_lifecycle(self, runtime_db):
        run = MiningRunData(id="r1", input_path="/test", status="running", started_at="2026-01-01T00:00:00")
        runtime_db.insert_run(run)
        runtime_db.update_run_status("r1", "completed", finished_at="2026-01-01T01:00:00", committed_count=5)
        r = runtime_db.get_run("r1")
        assert r["status"] == "completed"
        assert r["committed_count"] == 5

    def test_run_status_with_metadata(self, runtime_db):
        run = MiningRunData(id="r2", input_path="/test", status="running", started_at="2026-01-01T00:00:00")
        runtime_db.insert_run(run)
        runtime_db.update_run_status(
            "r2", "completed",
            finished_at="2026-01-01T01:00:00",
            metadata_json={"has_failures": True, "failed_count": 2},
        )
        r = runtime_db.get_run("r2")
        assert r["status"] == "completed"
        import json
        meta = r["metadata_json"]
        if isinstance(meta, str):
            meta = json.loads(meta)
        assert meta["has_failures"] is True
        assert meta["failed_count"] == 2

    def test_stage_events(self, runtime_db):
        runtime_db.insert_run(MiningRunData(id="r1", input_path="/test", started_at="2026-01-01T00:00:00"))
        evt = StageEvent(id="e1", run_id="r1", stage="parse", status="completed")
        runtime_db.insert_stage_event(evt)
        last = runtime_db.get_last_stage_status("r1", None, "parse")
        assert last == "completed"

    def test_resume_plan(self, runtime_db):
        runtime_db.insert_run(MiningRunData(id="r1", input_path="/test", started_at="2026-01-01T00:00:00"))
        runtime_db.insert_run_document(MiningRunDocumentData(
            id="rd1", run_id="r1", document_key="doc:/a.md",
            raw_content_hash="h1", action="NEW", status="committed",
            document_id="d1", document_snapshot_id="s1",
        ))
        runtime_db.insert_run_document(MiningRunDocumentData(
            id="rd2", run_id="r1", document_key="doc:/b.md",
            raw_content_hash="h2", action="NEW", status="failed",
        ))
        from knowledge_mining.mining.runtime import RuntimeTracker
        tracker = RuntimeTracker(runtime_db)
        plan = tracker.build_resume_plan("r1")
        assert "doc:/a.md" in plan.skip_document_keys
        assert "doc:/b.md" in plan.redo_document_keys


# ===================================================================
# T3: Hash Utils
# ===================================================================

class TestHashUtils:
    def test_snapshot_normalization(self):
        raw = "hello\r\nworld\n\n"
        norm = normalize_for_snapshot(raw)
        assert "\r" not in norm
        assert norm == "hello\nworld"

    def test_snapshot_hash_deterministic(self):
        h1 = compute_snapshot_hash("test\ncontent\n")
        h2 = compute_snapshot_hash("test\ncontent\n")
        assert h1 == h2

    def test_content_hash_vs_normalized(self):
        text = "Hello World"
        assert content_hash(text) != normalized_hash(text)


# ===================================================================
# T4-T7: Ported Modules
# ===================================================================

class TestIngestion:
    def test_discover_files(self, input_dir):
        from knowledge_mining.mining.ingestion import ingest_directory
        docs, summary = ingest_directory(input_dir)
        assert len(docs) == 2
        assert summary["parsed_documents"] == 2
        assert all(d.normalized_content_hash for d in docs)

    def test_skip_unrecognized(self, tmp_dir):
        (tmp_dir / "skip.xyz").write_text("data")
        from knowledge_mining.mining.ingestion import ingest_directory
        docs, summary = ingest_directory(tmp_dir)
        assert len(docs) == 0
        assert summary["skipped_files"] == 1


class TestStructure:
    def test_heading_text_cleans_markdown_links(self):
        from knowledge_mining.mining.infra.structure import parse_structure
        md = '## [适用NF](#ZH-CN_TOPIC_123)\n\nContent here.\n'
        tree = parse_structure(md)
        # Single top-level heading gets promoted to root
        assert tree.title == "适用NF"

    def test_parse_heading_tree(self, md_content):
        from knowledge_mining.mining.infra.structure import parse_structure
        tree = parse_structure(md_content)
        assert tree.title == "Test Command"
        assert any(c.title == "Parameters" for c in tree.children)

    def test_table_structure(self, md_content):
        from knowledge_mining.mining.infra.structure import parse_structure
        tree = parse_structure(md_content)
        all_blocks = _collect_blocks(tree)
        tables = [b for b in all_blocks if b.block_type == "table"]
        assert len(tables) == 1
        assert tables[0].structure["columns"] == ["Param", "Type", "Desc"]
        assert tables[0].structure["row_count"] == 2


class TestSegmentation:
    def test_heading_segments(self, md_content):
        from knowledge_mining.mining.infra.structure import parse_structure
        from knowledge_mining.mining.stages.segment import segment_document
        tree = parse_structure(md_content)
        segments = segment_document(tree, DocumentProfile(document_key="doc:/test.md"))
        # Headings are metadata (section_title/section_path), not independent segments
        headings = [s for s in segments if s.block_type == "heading"]
        assert len(headings) == 0
        # But heading info is preserved on content segments via section_title
        titles = [s.section_title for s in segments if s.section_title]
        # After cross-section orphan absorption, small sections may merge
        assert len(titles) >= 3

    def test_segment_hashes(self, md_content):
        from knowledge_mining.mining.infra.structure import parse_structure
        from knowledge_mining.mining.stages.segment import segment_document
        tree = parse_structure(md_content)
        segments = segment_document(tree, DocumentProfile(document_key="doc:/test.md"))
        for seg in segments:
            assert seg.content_hash, f"Missing content_hash for {seg.raw_text[:30]}"
            assert seg.normalized_hash, f"Missing normalized_hash"

    def test_structural_context_injection(self, md_content):
        """structural_context breadcrumb should be in metadata_json."""
        from knowledge_mining.mining.infra.structure import parse_structure
        from knowledge_mining.mining.stages.segment import segment_document
        tree = parse_structure(md_content)
        segments = segment_document(tree, DocumentProfile(document_key="doc:/test.md"))
        # Default mode is breadcrumb — all segments should have it
        for seg in segments:
            ctx = seg.metadata_json.get("structural_context", "")
            assert ctx, f"Missing structural_context for segment: {seg.raw_text[:40]}"
            # Should contain document title "Test Command"
            assert "Test Command" in ctx
            # Should not duplicate: "Test Command > Test Command" is wrong
            assert "Test Command > Test Command" not in ctx

    def test_structural_context_off(self, md_content):
        """When structural_context_mode=off, no breadcrumb should be injected."""
        from knowledge_mining.mining.infra.structure import parse_structure
        from knowledge_mining.mining.stages.segment import segment_document
        from knowledge_mining.mining.infra.domain_pack import DomainProfile, RetrievalPolicy
        tree = parse_structure(md_content)
        policy = RetrievalPolicy(structural_context_mode="off")
        profile = DomainProfile(
            domain_id="test", display_name="Test",
            entity_types=frozenset(), strong_entity_types=frozenset(),
            role_keyword_rules=(), heading_role_keywords=(),
            extractor_rules=(), llm_templates=(),
            semantic_roles=frozenset(), document_types=frozenset(),
            retrieval_policy=policy, eval_questions=(),
        )
        segments = segment_document(tree, DocumentProfile(document_key="doc:/test.md"),
                                    domain_profile=profile)
        for seg in segments:
            assert "structural_context" not in seg.metadata_json

    def test_orphan_absorption_cross_section(self):
        """Cross-section orphan segments should merge into parent section."""
        from knowledge_mining.mining.stages.segment import _absorb_orphan_segments
        from knowledge_mining.mining.infra.text_utils import token_count

        parent_path = [{"title": "Parent", "level": 1}]
        child_path = [{"title": "Parent", "level": 1}, {"title": "Child", "level": 2}]

        # Large parent segment + tiny orphan in child section
        big_text = "This is a substantial paragraph about the parent section. " * 10
        big_tc = token_count(big_text)

        segments = [
            RawSegmentData(
                document_key="doc:/test.md", segment_index=0,
                block_type="paragraph", semantic_role="concept",
                section_path=parent_path, section_title="Parent",
                raw_text=big_text,
                normalized_text=big_text.lower(), content_hash="h1", normalized_hash="nh1",
                token_count=big_tc, structure_json={}, source_offsets_json={},
                entity_refs_json=[], metadata_json={},
            ),
            RawSegmentData(
                document_key="doc:/test.md", segment_index=1,
                block_type="paragraph", semantic_role="unknown",
                section_path=child_path, section_title="Child",
                raw_text="UPF",
                normalized_text="upf", content_hash="h2", normalized_hash="nh2",
                token_count=1, structure_json={}, source_offsets_json={},
                entity_refs_json=[], metadata_json={},
            ),
        ]

        result = _absorb_orphan_segments(segments, min_tokens=128, max_tokens=512)
        # Orphan should be absorbed into parent
        assert len(result) == 1, f"Expected 1 segment after absorption, got {len(result)}"
        assert "UPF" in result[0].raw_text
        assert result[0].metadata_json.get("merged_from_orphan") is True

    def test_orphan_not_absorbed_when_parent_full(self):
        """Orphan should NOT merge if parent is already at max_tokens."""
        from knowledge_mining.mining.stages.segment import _absorb_orphan_segments
        from knowledge_mining.mining.infra.text_utils import token_count

        parent_path = [{"title": "Parent", "level": 1}]
        child_path = [{"title": "Parent", "level": 1}, {"title": "Child", "level": 2}]

        # Parent is already 512 tokens — max is 512
        big_text = "word " * 600
        big_tc = token_count(big_text)

        segments = [
            RawSegmentData(
                document_key="doc:/test.md", segment_index=0,
                block_type="paragraph", semantic_role="concept",
                section_path=parent_path, section_title="Parent",
                raw_text=big_text, normalized_text="n", content_hash="h1",
                normalized_hash="nh1", token_count=big_tc, structure_json={},
                source_offsets_json={}, entity_refs_json=[], metadata_json={},
            ),
            RawSegmentData(
                document_key="doc:/test.md", segment_index=1,
                block_type="paragraph", semantic_role="unknown",
                section_path=child_path, section_title="Child",
                raw_text="UPF", normalized_text="upf", content_hash="h2",
                normalized_hash="nh2", token_count=1, structure_json={},
                source_offsets_json={}, entity_refs_json=[], metadata_json={},
            ),
        ]

        result = _absorb_orphan_segments(segments, min_tokens=128, max_tokens=512)
        # Orphan should remain — parent is too large
        assert len(result) == 2


# REMOVED: TestExtractors - rule-based components deleted (RuleBasedEntityExtractor, DefaultRoleClassifier)


# ===================================================================
# T8-T12: Pipeline Modules
# ===================================================================

# REMOVED: TestEnrich - all tests depended on removed rule-based components


# REMOVED: TestRelations - all tests depended on removed build_relations function


class TestRetrievalUnits:
    # REMOVED: test_build_units - rule-based components deleted (RuleBasedEntityExtractor, DefaultRoleClassifier)

    def test_source_refs_with_segment_id(self):
        """source_refs_json should include raw_segment_ids when source_seg_id provided."""
        from knowledge_mining.mining.stages.retrieval_units import _build_source_refs
        seg = RawSegmentData(
            document_key="doc:/a.md", segment_index=3,
            source_offsets_json={"start": 10, "end": 50},
        )
        refs = _build_source_refs(seg, source_seg_id="seg-uuid-123")
        assert refs["raw_segment_ids"] == ["seg-uuid-123"]
        assert refs["document_key"] == "doc:/a.md"
        assert refs["segment_index"] == 3

    def test_source_refs_without_segment_id(self):
        """source_refs_json should have empty raw_segment_ids when source_seg_id is None."""
        from knowledge_mining.mining.stages.retrieval_units import _build_source_refs
        seg = RawSegmentData(document_key="doc:/a.md", segment_index=1)
        refs = _build_source_refs(seg)
        assert refs["raw_segment_ids"] == []

    def test_generated_question_unit_has_task_id(self):
        """llm_result_refs_json should include task_id from LLM."""
        from knowledge_mining.mining.stages.retrieval_units import _make_generated_question_unit
        seg = RawSegmentData(document_key="doc:/a.md", segment_index=0, raw_text="test content")
        unit = _make_generated_question_unit(seg, "What is X?", 0, "seg-1", "task-abc-123")
        assert unit.llm_result_refs_json["task_id"] == "task-abc-123"
        assert unit.llm_result_refs_json["source"] == "llm_runtime"
        assert unit.llm_result_refs_json["question_index"] == 0


class TestSnapshot:
    def test_select_or_create(self, asset_db):
        from knowledge_mining.mining.snapshot import select_or_create_snapshot
        doc = RawFileData(
            file_path="/test/a.md", relative_path="a.md", file_name="a.md",
            file_type="markdown", content="# Hello", raw_content_hash="rh1",
            normalized_content_hash="nh1",
        )
        profile = DocumentProfile(document_key="doc:/a.md")
        doc_id, snap_id, link_id = select_or_create_snapshot(asset_db, doc, profile)
        assert asset_db.get_document(doc_id) is not None
        assert asset_db.get_snapshot(snap_id) is not None


class TestPublishing:
    def test_assemble_and_publish(self, asset_db):
        from knowledge_mining.mining.stages.publishing import assemble_build, publish_release
        asset_db.upsert_document("d1", "doc:/a.md", "a.md")
        asset_db.upsert_snapshot("s1", "nh1", "rh1", "text/markdown")
        asset_db.insert_raw_segment(
            segment_id="seg-1", document_snapshot_id="s1",
            segment_key="doc:/a.md#0", segment_index=0,
            block_type="paragraph", semantic_role="concept",
            section_path=[], section_title="T",
            raw_text="test", normalized_text="test",
            content_hash="ch", normalized_hash="nh",
        )
        asset_db.commit()

        build_id = assemble_build(asset_db, run_id="r1", domain="default", snapshot_decisions=[
            {"document_id": "d1", "document_snapshot_id": "s1", "reason": "add", "selection_status": "active"},
        ])
        build = asset_db.get_build(build_id)
        assert build["status"] == "validated"

        release_id = publish_release(asset_db, build_id, domain="default")
        release = asset_db.get_active_release("default", "prod")
        assert release["id"] == release_id


# ===================================================================
# T14: End-to-End Pipeline
# ===================================================================

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


class TestEndToEndPipeline:
    def test_full_pipeline(self, input_dir, tmp_dir):
        from knowledge_mining.mining.jobs.run import run
        result = run(str(input_dir))
        assert result["status"] == "completed"
        assert result["committed_count"] == 2
        assert result["build_id"] is not None
        assert result["release_id"] is not None

    def test_phase1_only(self, input_dir, tmp_dir):
        from knowledge_mining.mining.jobs.run import run
        result = run(str(input_dir), phase1_only=True)
        assert result["status"] == "completed"
        assert result["build_id"] is None
        assert result["release_id"] is None

    def test_publish_after_phase1(self, input_dir, tmp_dir):
        from knowledge_mining.mining.jobs.run import run, publish
        result = run(str(input_dir))
        assert result["release_id"] is not None
        db = _make_db(AssetCoreDB)
        ar = db.get_active_release("cloud_core_network", "prod")
        assert ar is not None
        db.close()

    def test_stage_events_recorded(self, input_dir, tmp_dir):
        """Verify stage events are recorded for each document."""
        from knowledge_mining.mining.jobs.run import run
        result = run(str(input_dir))
        rdb = _make_db(MiningRuntimeDB)
        events = rdb.get_stage_events(result["run_id"])
        stages = {e["stage"] for e in events}
        assert "segment" in stages, f"Missing 'segment'. Got: {stages}"
        assert "discourse" in stages, f"Missing 'discourse'. Got: {stages}"
        assert "retrieval_units" in stages, f"Missing 'retrieval_units'. Got: {stages}"
        rdb.close()


# ===================================================================
# Helpers
# ===================================================================

def _collect_blocks(node: SectionNode) -> list[ContentBlock]:
    blocks = list(node.blocks)
    for child in node.children:
        blocks.extend(_collect_blocks(child))
    return blocks


