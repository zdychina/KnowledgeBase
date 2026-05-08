"""Test v0.5 dataclass models: creation, frozen, defaults, field alignment."""
from __future__ import annotations

from dataclasses import FrozenInstanceError

import pytest

from knowledge_mining.mining.models import (
    BatchParams,
    CanonicalSegmentData,
    ContentBlock,
    DocumentProfile,
    RawDocumentData,
    RawSegmentData,
    SectionNode,
    SourceMappingData,
)


# ---------------------------------------------------------------------------
# BatchParams
# ---------------------------------------------------------------------------

class TestBatchParams:
    def test_defaults(self):
        bp = BatchParams()
        assert bp.default_source_type == "folder_scan"
        assert bp.default_document_type is None
        assert bp.batch_scope == {}
        assert bp.tags == []
        assert bp.storage_root_uri is None
        assert bp.original_root_name is None

    def test_custom_values(self):
        bp = BatchParams(
            default_source_type="api_import",
            default_document_type="command",
            batch_scope={"product": "5G"},
            tags=["m1", "test"],
            storage_root_uri="file:///data",
            original_root_name="docs",
        )
        assert bp.default_source_type == "api_import"
        assert bp.default_document_type == "command"
        assert bp.batch_scope == {"product": "5G"}
        assert bp.tags == ["m1", "test"]
        assert bp.storage_root_uri == "file:///data"
        assert bp.original_root_name == "docs"

    def test_frozen(self):
        bp = BatchParams()
        with pytest.raises(FrozenInstanceError):
            bp.default_source_type = "other"  # type: ignore[misc]

    def test_independent_defaults(self):
        """Two instances share no mutable default state."""
        bp1 = BatchParams()
        bp2 = BatchParams()
        bp1.tags.append("shared?")
        assert bp2.tags == []


# ---------------------------------------------------------------------------
# RawDocumentData
# ---------------------------------------------------------------------------

class TestRawDocumentData:
    @pytest.fixture()
    def sample_doc(self) -> RawDocumentData:
        return RawDocumentData(
            file_path="/data/readme.md",
            relative_path="readme.md",
            file_name="readme.md",
            file_type="markdown",
            content="# Hello",
            content_hash="abc123",
        )

    def test_required_fields(self, sample_doc: RawDocumentData):
        assert sample_doc.file_path == "/data/readme.md"
        assert sample_doc.relative_path == "readme.md"
        assert sample_doc.file_name == "readme.md"
        assert sample_doc.file_type == "markdown"
        assert sample_doc.content == "# Hello"
        assert sample_doc.content_hash == "abc123"

    def test_optional_defaults(self, sample_doc: RawDocumentData):
        assert sample_doc.source_uri == ""
        assert sample_doc.source_type is None
        assert sample_doc.document_type is None
        assert sample_doc.title is None
        assert sample_doc.scope_json == {}
        assert sample_doc.tags_json == []
        assert sample_doc.structure_quality == "unknown"
        assert sample_doc.processing_profile_json == {}
        assert sample_doc.metadata_json == {}

    def test_frozen(self, sample_doc: RawDocumentData):
        with pytest.raises(FrozenInstanceError):
            sample_doc.file_type = "txt"  # type: ignore[misc]

    def test_all_file_types(self):
        for ft in ("markdown", "html", "pdf", "doc", "docx", "txt", "other"):
            doc = RawDocumentData(
                file_path="/x", relative_path="x", file_name="x",
                file_type=ft, content="", content_hash="h",
            )
            assert doc.file_type == ft


# ---------------------------------------------------------------------------
# DocumentProfile
# ---------------------------------------------------------------------------

class TestDocumentProfile:
    def test_defaults(self):
        dp = DocumentProfile(document_key="a.md")
        assert dp.document_key == "a.md"
        assert dp.source_type == "other"
        assert dp.document_type is None
        assert dp.scope_json == {}
        assert dp.tags_json == []
        assert dp.structure_quality == "unknown"
        assert dp.title is None

    def test_full(self):
        dp = DocumentProfile(
            document_key="b.md",
            source_type="folder_scan",
            document_type="command",
            scope_json={"product": "5G"},
            tags_json=["v1"],
            structure_quality="markdown_native",
            title="Commands",
        )
        assert dp.source_type == "folder_scan"
        assert dp.document_type == "command"
        assert dp.title == "Commands"

    def test_frozen(self):
        dp = DocumentProfile(document_key="a.md")
        with pytest.raises(FrozenInstanceError):
            dp.title = "new"  # type: ignore[misc]


# ---------------------------------------------------------------------------
# ContentBlock
# ---------------------------------------------------------------------------

class TestContentBlock:
    def test_required(self):
        cb = ContentBlock(block_type="paragraph", text="hello")
        assert cb.block_type == "paragraph"
        assert cb.text == "hello"
        assert cb.language is None
        assert cb.level is None

    def test_heading(self):
        cb = ContentBlock(block_type="heading", text="Title", level=2)
        assert cb.level == 2

    def test_code(self):
        cb = ContentBlock(block_type="code", text="print()", language="python")
        assert cb.language == "python"


# ---------------------------------------------------------------------------
# SectionNode
# ---------------------------------------------------------------------------

class TestSectionNode:
    def test_defaults(self):
        sn = SectionNode(title=None, level=0)
        assert sn.children == ()
        assert sn.blocks == ()

    def test_with_blocks_and_children(self):
        block = ContentBlock(block_type="paragraph", text="text")
        child = SectionNode(title="Sub", level=2)
        sn = SectionNode(title="Root", level=1, blocks=(block,), children=(child,))
        assert len(sn.blocks) == 1
        assert len(sn.children) == 1


# ---------------------------------------------------------------------------
# RawSegmentData
# ---------------------------------------------------------------------------

class TestRawSegmentData:
    def test_required_and_defaults(self):
        seg = RawSegmentData(document_key="a.md", segment_index=0)
        assert seg.document_key == "a.md"
        assert seg.segment_index == 0
        assert seg.block_type == "unknown"
        assert seg.semantic_role == "unknown"
        assert seg.section_path == []
        assert seg.section_title is None
        assert seg.raw_text == ""
        assert seg.normalized_text == ""
        assert seg.content_hash == ""
        assert seg.normalized_hash == ""
        assert seg.token_count is None
        assert seg.structure_json == {}
        assert seg.source_offsets_json == {}
        assert seg.entity_refs_json == []
        assert seg.metadata_json == {}

    def test_no_removed_fields(self):
        """v0.5 must NOT have segment_type, command_name, heading_level."""
        seg = RawSegmentData(document_key="a.md", segment_index=0)
        assert not hasattr(seg, "segment_type")
        assert not hasattr(seg, "command_name")
        assert not hasattr(seg, "heading_level")

    def test_frozen(self):
        seg = RawSegmentData(document_key="a.md", segment_index=0)
        with pytest.raises(FrozenInstanceError):
            seg.raw_text = "nope"  # type: ignore[misc]

    def test_full_construction(self):
        seg = RawSegmentData(
            document_key="b.md",
            segment_index=3,
            block_type="paragraph",
            semantic_role="concept",
            section_path=[{"title": "Intro", "level": 1}],
            section_title="Intro",
            raw_text="Hello world",
            normalized_text="hello world",
            content_hash="h1",
            normalized_hash="h2",
            token_count=2,
            structure_json={"paragraph_count": 1},
            source_offsets_json={"block_index": 0},
            entity_refs_json=[{"type": "command", "name": "ADD APN"}],
            metadata_json={"source": "test"},
        )
        assert seg.block_type == "paragraph"
        assert seg.semantic_role == "concept"
        assert seg.section_path[0]["title"] == "Intro"
        assert seg.token_count == 2


# ---------------------------------------------------------------------------
# CanonicalSegmentData
# ---------------------------------------------------------------------------

class TestCanonicalSegmentData:
    def test_required_and_defaults(self):
        cs = CanonicalSegmentData(canonical_key="c000000")
        assert cs.canonical_key == "c000000"
        assert cs.block_type == "unknown"
        assert cs.semantic_role == "unknown"
        assert cs.canonical_text == ""
        assert cs.search_text == ""
        assert cs.title is None
        assert cs.summary is None
        assert cs.entity_refs_json == []
        assert cs.scope_json == {}
        assert cs.has_variants is False
        assert cs.variant_policy == "none"
        assert cs.quality_score is None
        assert cs.metadata_json == {}
        assert cs.raw_segment_refs == []

    def test_no_removed_fields(self):
        cs = CanonicalSegmentData(canonical_key="c000000")
        assert not hasattr(cs, "segment_type")
        assert not hasattr(cs, "command_name")
        assert not hasattr(cs, "section_role")

    def test_frozen(self):
        cs = CanonicalSegmentData(canonical_key="c000000")
        with pytest.raises(FrozenInstanceError):
            cs.canonical_text = "nope"  # type: ignore[misc]


# ---------------------------------------------------------------------------
# SourceMappingData
# ---------------------------------------------------------------------------

class TestSourceMappingData:
    def test_required_and_defaults(self):
        sm = SourceMappingData(
            canonical_key="c000000",
            raw_segment_ref="a.md#0",
            relation_type="primary",
        )
        assert sm.canonical_key == "c000000"
        assert sm.raw_segment_ref == "a.md#0"
        assert sm.relation_type == "primary"
        assert sm.is_primary is False
        assert sm.priority == 100
        assert sm.similarity_score is None
        assert sm.diff_summary is None
        assert sm.metadata_json == {}

    def test_all_relation_types(self):
        for rt in (
            "primary", "exact_duplicate", "normalized_duplicate",
            "near_duplicate", "scope_variant", "conflict_candidate",
        ):
            sm = SourceMappingData(
                canonical_key="c",
                raw_segment_ref="x#0",
                relation_type=rt,
            )
            assert sm.relation_type == rt

    def test_frozen(self):
        sm = SourceMappingData(
            canonical_key="c", raw_segment_ref="x#0",
            relation_type="primary",
        )
        with pytest.raises(FrozenInstanceError):
            sm.priority = 1  # type: ignore[misc]
