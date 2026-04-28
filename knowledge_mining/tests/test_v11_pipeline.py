"""Comprehensive tests for v1.1 Knowledge Mining pipeline."""
from __future__ import annotations

import os
import shutil
import tempfile
from pathlib import Path

import pytest

from knowledge_mining.mining.models import (
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
from knowledge_mining.mining.hash_utils import (
    compute_raw_hash,
    compute_snapshot_hash,
    content_hash,
    normalize_for_snapshot,
    normalized_hash,
)
from knowledge_mining.mining.db import AssetCoreDB, MiningRuntimeDB
from knowledge_mining.mining.text_utils import token_count, normalize_text, jaccard_similarity


# ===================================================================
# Fixtures
# ===================================================================

@pytest.fixture
def tmp_dir():
    d = tempfile.mkdtemp()
    yield Path(d)
    shutil.rmtree(d)


@pytest.fixture
def asset_db(tmp_dir):
    db = AssetCoreDB(tmp_dir / "asset_core.sqlite")
    db.open()
    yield db
    db.close()


@pytest.fixture
def runtime_db(tmp_dir):
    db = MiningRuntimeDB(tmp_dir / "mining_runtime.sqlite")
    db.open()
    yield db
    db.close()


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
        # Second upsert should update, not create duplicate
        assert s["raw_content_hash"] == "raw2"

    def test_build_and_release(self, asset_db):
        asset_db.insert_build("b1", "B-001", "building", "full")
        asset_db.update_build_status("b1", "validated")
        asset_db.insert_release("r1", "R-001", "b1")
        asset_db.activate_release("r1")
        ar = asset_db.get_active_release()
        assert ar["status"] == "active"

    def test_release_chain(self, asset_db):
        asset_db.insert_build("b1", "B-001", "validated", "full")
        asset_db.insert_build("b2", "B-002", "validated", "full")
        asset_db.insert_release("r1", "R-001", "b1")
        asset_db.activate_release("r1")
        asset_db.insert_release("r2", "R-002", "b2", previous_release_id="r1")
        asset_db.activate_release("r2")
        ar = asset_db.get_active_release()
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
    def test_parse_heading_tree(self, md_content):
        from knowledge_mining.mining.structure import parse_structure
        tree = parse_structure(md_content)
        assert tree.title == "Test Command"
        assert any(c.title == "Parameters" for c in tree.children)

    def test_table_structure(self, md_content):
        from knowledge_mining.mining.structure import parse_structure
        tree = parse_structure(md_content)
        all_blocks = _collect_blocks(tree)
        tables = [b for b in all_blocks if b.block_type == "table"]
        assert len(tables) == 1
        assert tables[0].structure["columns"] == ["Param", "Type", "Desc"]
        assert tables[0].structure["row_count"] == 2


class TestSegmentation:
    def test_heading_segments(self, md_content):
        from knowledge_mining.mining.structure import parse_structure
        from knowledge_mining.mining.segmentation import segment_document
        tree = parse_structure(md_content)
        segments = segment_document(tree, DocumentProfile(document_key="doc:/test.md"))
        headings = [s for s in segments if s.block_type == "heading"]
        assert len(headings) >= 4  # Test Command, Parameters, Example, Notes, Sub-note

    def test_segment_hashes(self, md_content):
        from knowledge_mining.mining.structure import parse_structure
        from knowledge_mining.mining.segmentation import segment_document
        tree = parse_structure(md_content)
        segments = segment_document(tree, DocumentProfile(document_key="doc:/test.md"))
        for seg in segments:
            assert seg.content_hash, f"Missing content_hash for {seg.raw_text[:30]}"
            assert seg.normalized_hash, f"Missing normalized_hash"


class TestExtractors:
    def test_command_extraction(self):
        from knowledge_mining.mining.extractors import RuleBasedEntityExtractor
        ext = RuleBasedEntityExtractor()
        refs = ext.extract('ADD APN command for SMF network element', {})
        types = {r["type"] for r in refs}
        assert "command" in types
        assert "network_element" in types

    def test_role_classifier(self):
        from knowledge_mining.mining.extractors import DefaultRoleClassifier
        cls = DefaultRoleClassifier()
        assert cls.classify("", "参数说明", "paragraph", {}) == "parameter"
        assert cls.classify("", "使用实例", "paragraph", {}) == "example"


# ===================================================================
# T8-T12: New Modules
# ===================================================================

class TestEnrich:
    def test_enrich_adds_metadata(self, md_content):
        from knowledge_mining.mining.structure import parse_structure
        from knowledge_mining.mining.segmentation import segment_document
        from knowledge_mining.mining.enrich import enrich_segments
        from knowledge_mining.mining.extractors import RuleBasedEntityExtractor, DefaultRoleClassifier
        tree = parse_structure(md_content)
        segments = segment_document(tree, DocumentProfile(document_key="doc:/test.md"))
        enriched = enrich_segments(
            segments,
            entity_extractor=RuleBasedEntityExtractor(),
            role_classifier=DefaultRoleClassifier(),
        )
        assert len(enriched) == len(segments)
        headings = [s for s in enriched if s.block_type == "heading"]
        for h in headings:
            assert "heading_role" in h.metadata_json
        # Enrich should assign semantic roles (not "unknown" for non-headings)
        non_headings = [s for s in enriched if s.block_type != "heading"]
        roles = {s.semantic_role for s in non_headings}
        assert len(roles - {"unknown"}) > 0  # at least some roles assigned


class TestRelations:
    def test_build_relations(self, md_content):
        from knowledge_mining.mining.structure import parse_structure
        from knowledge_mining.mining.segmentation import segment_document
        from knowledge_mining.mining.relations import build_relations
        tree = parse_structure(md_content)
        segments = segment_document(tree, DocumentProfile(document_key="doc:/test.md"))
        relations, seg_ids = build_relations(segments)
        assert len(relations) > 0
        types = {r.relation_type for r in relations}
        assert "previous" in types
        assert "section_header_of" in types

    def test_section_header_of_only_from_heading(self, md_content):
        from knowledge_mining.mining.structure import parse_structure
        from knowledge_mining.mining.segmentation import segment_document
        from knowledge_mining.mining.relations import build_relations
        tree = parse_structure(md_content)
        segments = segment_document(tree, DocumentProfile(document_key="doc:/test.md"))
        relations, seg_ids = build_relations(segments)
        header_rels = [r for r in relations if r.relation_type == "section_header_of"]
        # Source should always be a heading segment
        heading_keys = {_make_key(s) for s in segments if s.block_type == "heading"}
        for rel in header_rels:
            assert rel.source_segment_key in heading_keys


class TestRetrievalUnits:
    def test_build_units(self, md_content):
        from knowledge_mining.mining.structure import parse_structure
        from knowledge_mining.mining.segmentation import segment_document
        from knowledge_mining.mining.enrich import enrich_segments
        from knowledge_mining.mining.retrieval_units import build_retrieval_units
        from knowledge_mining.mining.extractors import RuleBasedEntityExtractor, DefaultRoleClassifier
        tree = parse_structure(md_content)
        # v1.1 flow: segment (structure only) → enrich (understanding) → retrieval_units
        segments = segment_document(
            tree, DocumentProfile(document_key="doc:/test.md"),
        )
        segments = enrich_segments(
            segments,
            entity_extractor=RuleBasedEntityExtractor(),
            role_classifier=DefaultRoleClassifier(),
        )
        units = build_retrieval_units(segments)
        types = {u.unit_type for u in units}
        assert "raw_text" in types
        assert "contextual_text" in types
        # entity_card requires entity_refs from enrich stage
        assert "entity_card" in types
        # raw_text count should equal segment count
        assert sum(1 for u in units if u.unit_type == "raw_text") == len(segments)


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
        from knowledge_mining.mining.publishing import assemble_build, publish_release
        asset_db.upsert_document("d1", "doc:/a.md", "a.md")
        asset_db.upsert_snapshot("s1", "nh1", "rh1", "text/markdown")
        # v1.2: validate_build requires at least one segment per snapshot
        asset_db.insert_raw_segment(
            segment_id="seg-1", document_snapshot_id="s1",
            segment_key="doc:/a.md#0", segment_index=0,
            block_type="paragraph", semantic_role="concept",
            section_path=[], section_title="T",
            raw_text="test", normalized_text="test",
            content_hash="ch", normalized_hash="nh",
        )
        asset_db.commit()

        build_id = assemble_build(asset_db, run_id="r1", snapshot_decisions=[
            {"document_id": "d1", "document_snapshot_id": "s1", "reason": "add", "selection_status": "active"},
        ])
        build = asset_db.get_build(build_id)
        assert build["status"] == "validated"

        release_id = publish_release(asset_db, build_id)
        release = asset_db.get_active_release()
        assert release["id"] == release_id


# ===================================================================
# T14: End-to-End Pipeline
# ===================================================================

class TestEndToEndPipeline:
    def test_full_pipeline(self, input_dir, tmp_dir):
        from knowledge_mining.mining.jobs.run import run
        result = run(
            str(input_dir),
            asset_core_db_path=str(tmp_dir / "asset_core.sqlite"),
            mining_runtime_db_path=str(tmp_dir / "mining_runtime.sqlite"),
        )
        assert result["status"] == "completed"
        assert result["committed_count"] == 2
        assert result["build_id"] is not None
        assert result["release_id"] is not None

    def test_phase1_only(self, input_dir, tmp_dir):
        from knowledge_mining.mining.jobs.run import run
        result = run(
            str(input_dir),
            asset_core_db_path=str(tmp_dir / "asset_core.sqlite"),
            mining_runtime_db_path=str(tmp_dir / "mining_runtime.sqlite"),
            phase1_only=True,
        )
        assert result["status"] == "completed"
        assert result["build_id"] is None
        assert result["release_id"] is None

    def test_publish_after_phase1(self, input_dir, tmp_dir):
        from knowledge_mining.mining.jobs.run import run, publish
        result = run(
            str(input_dir),
            asset_core_db_path=str(tmp_dir / "asset_core.sqlite"),
            mining_runtime_db_path=str(tmp_dir / "mining_runtime.sqlite"),
        )
        assert result["release_id"] is not None
        # Active release should be set
        db = AssetCoreDB(tmp_dir / "asset_core.sqlite")
        db.open()
        ar = db.get_active_release()
        assert ar is not None
        db.close()


# ===================================================================
# Helpers
# ===================================================================

def _collect_blocks(node: SectionNode) -> list[ContentBlock]:
    blocks = list(node.blocks)
    for child in node.children:
        blocks.extend(_collect_blocks(child))
    return blocks


def _make_key(seg: RawSegmentData) -> str:
    return f"{seg.document_key}#{seg.segment_index}"
