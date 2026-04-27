"""Test provenance: source_refs_json and llm_result_refs_json audit fields."""
from __future__ import annotations

import json
import shutil
import tempfile
from pathlib import Path

import pytest

from knowledge_mining.mining.models import (
    DocumentProfile,
    RawSegmentData,
)


@pytest.fixture
def md_content():
    return """# Test Document

## Section One

Content paragraph one has enough text for question generation testing.

## Section Two

Content paragraph two has enough text for question generation testing.
"""


class TestSourceRefsJson:
    def test_raw_segment_ids_in_source_refs(self):
        """source_refs_json should contain raw_segment_ids when seg_id is provided."""
        from knowledge_mining.mining.retrieval_units import _build_source_refs

        seg = RawSegmentData(
            document_key="doc:/test.md",
            segment_index=5,
            source_offsets_json={"start": 100, "end": 200},
        )
        refs = _build_source_refs(seg, source_seg_id="seg-uuid-abc")

        assert refs["document_key"] == "doc:/test.md"
        assert refs["segment_index"] == 5
        assert refs["offsets"] == {"start": 100, "end": 200}
        assert refs["raw_segment_ids"] == ["seg-uuid-abc"]

    def test_no_raw_segment_ids_when_no_seg_id(self):
        """source_refs_json should not have raw_segment_ids when seg_id is None."""
        from knowledge_mining.mining.retrieval_units import _build_source_refs

        seg = RawSegmentData(document_key="doc:/test.md", segment_index=1)
        refs = _build_source_refs(seg)

        assert "raw_segment_ids" not in refs

    def test_raw_text_unit_source_refs_in_pipeline(self, md_content):
        """Raw text units built through pipeline should have raw_segment_ids."""
        from knowledge_mining.mining.structure import parse_structure
        from knowledge_mining.mining.segmentation import segment_document
        from knowledge_mining.mining.retrieval_units import build_retrieval_units

        tree = parse_structure(md_content)
        segments = segment_document(tree, DocumentProfile(document_key="doc:/test.md"))
        seg_ids = {
            f"doc:/test.md#{i}": f"seg-uuid-{i}" for i in range(len(segments))
        }

        units = build_retrieval_units(segments, seg_ids=seg_ids)

        raw_text_units = [u for u in units if u.unit_type == "raw_text"]
        for unit in raw_text_units:
            assert "raw_segment_ids" in unit.source_refs_json
            assert len(unit.source_refs_json["raw_segment_ids"]) == 1


class TestLlmResultRefsJson:
    def test_generated_question_refs_with_task_id(self):
        """Generated question unit should include task_id in llm_result_refs_json."""
        from knowledge_mining.mining.retrieval_units import _make_generated_question_unit

        seg = RawSegmentData(
            document_key="doc:/test.md",
            segment_index=0,
            raw_text="Test content for question",
        )
        unit = _make_generated_question_unit(
            seg, "What is this about?", 0, "seg-1", "task-xyz-789",
        )

        assert unit.llm_result_refs_json["source"] == "llm_runtime"
        assert unit.llm_result_refs_json["question_index"] == 0
        assert unit.llm_result_refs_json["task_id"] == "task-xyz-789"

    def test_generated_question_refs_without_task_id(self):
        """Generated question unit without task_id should only have basic fields."""
        from knowledge_mining.mining.retrieval_units import _make_generated_question_unit

        seg = RawSegmentData(
            document_key="doc:/test.md",
            segment_index=0,
            raw_text="Test content",
        )
        unit = _make_generated_question_unit(seg, "What is X?", 0, "seg-1")

        assert unit.llm_result_refs_json["source"] == "llm_runtime"
        assert "task_id" not in unit.llm_result_refs_json
        assert unit.llm_result_refs_json["question_index"] == 0

    def test_contextual_enhanced_refs_with_task_id(self):
        """Contextual enhanced unit should include task_id in llm_result_refs_json."""
        from knowledge_mining.mining.retrieval_units import _make_contextual_enhanced_unit

        seg = RawSegmentData(
            document_key="doc:/test.md",
            segment_index=0,
            raw_text="Content to enhance",
        )
        unit = _make_contextual_enhanced_unit(
            seg, "Section intro about configuration", "seg-1", "task-ctx-456",
        )

        assert unit.llm_result_refs_json["source"] == "contextual_retrieval"
        assert unit.llm_result_refs_json["task_id"] == "task-ctx-456"

    def test_db_roundtrip_source_refs(self):
        """Source refs with raw_segment_ids should survive DB roundtrip."""
        import tempfile
        from knowledge_mining.mining.db import AssetCoreDB

        tmp = tempfile.mkdtemp()
        try:
            db = AssetCoreDB(Path(tmp) / "test.sqlite")
            db.open()

            db.upsert_snapshot("snap-1", "nh", "rh", "text/markdown")
            db.insert_retrieval_unit(
                unit_id="ru-1",
                document_snapshot_id="snap-1",
                unit_key="ru:doc:/a.md#0:raw_text",
                unit_type="raw_text",
                target_type="raw_segment",
                source_refs_json={
                    "document_key": "doc:/a.md",
                    "segment_index": 0,
                    "raw_segment_ids": ["seg-uuid-123"],
                },
            )
            db.commit()

            units = db.get_retrieval_units_by_snapshot("snap-1")
            assert len(units) == 1
            refs = json.loads(units[0]["source_refs_json"])
            assert refs["raw_segment_ids"] == ["seg-uuid-123"]

            db.close()
        finally:
            import shutil
            shutil.rmtree(tmp)
