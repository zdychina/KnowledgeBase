"""Test segmentation: v0.5 field output — document_key, semantic_role, section_path, etc."""
from __future__ import annotations

from knowledge_mining.mining.document_profile import build_profile
from knowledge_mining.mining.models import ContentBlock, RawDocumentData, RawSegmentData, SectionNode
from knowledge_mining.mining.segmentation import segment_document
from knowledge_mining.mining.structure import parse_structure


def _make_segments(
    content: str,
    file_path: str = "test.md",
    relative_path: str = "test.md",
) -> list[RawSegmentData]:
    """Helper: content -> profile -> parse -> segment."""
    doc = RawDocumentData(
        file_path=file_path,
        relative_path=relative_path,
        file_name=file_path.split("/")[-1],
        file_type="markdown",
        content=content,
        content_hash="h",
    )
    profile = build_profile(doc)
    root = parse_structure(content)
    return segment_document(root, profile)


class TestSegmentationBasicOutput:
    def test_produces_segments(self):
        segs = _make_segments("# Title\n\nHello world")
        assert len(segs) >= 1

    def test_document_key_set(self):
        segs = _make_segments("# Title\n\nContent", "sub/test.md", "sub/test.md")
        for seg in segs:
            assert seg.document_key == "sub/test.md"

    def test_segment_indices_sequential(self):
        segs = _make_segments("# A\n\nPara1\n\n## B\n\nPara2\n\n## C\n\nPara3")
        for i, seg in enumerate(segs):
            assert seg.segment_index == i


class TestSegmentationV05Fields:
    def test_semantic_role_field(self):
        """v0.5 uses semantic_role (not section_role)."""
        segs = _make_segments("# Title\n\nHello")
        for seg in segs:
            assert hasattr(seg, "semantic_role")
            assert not hasattr(seg, "section_role")

    def test_no_removed_fields(self):
        segs = _make_segments("# Title\n\nContent")
        for seg in segs:
            assert not hasattr(seg, "segment_type")
            assert not hasattr(seg, "command_name")
            assert not hasattr(seg, "heading_level")

    def test_section_path_is_list_of_dicts(self):
        segs = _make_segments("# Root\n\n## Sub\n\nContent")
        sub_segs = [s for s in segs if s.section_title == "Sub"]
        assert len(sub_segs) >= 1
        sp = sub_segs[0].section_path
        assert isinstance(sp, list)
        for entry in sp:
            assert isinstance(entry, dict)
            assert "title" in entry
            assert "level" in entry

    def test_section_path_ancestry(self):
        segs = _make_segments("# Root\n\n## Child\n\nPara")
        child_segs = [s for s in segs if s.section_title == "Child"]
        assert len(child_segs) >= 1
        titles = [e["title"] for e in child_segs[0].section_path]
        assert "Root" in titles
        assert "Child" in titles


class TestSegmentationBlockTypes:
    def test_paragraph_segment(self):
        segs = _make_segments("# Title\n\nHello world")
        para_segs = [s for s in segs if s.block_type == "paragraph"]
        assert len(para_segs) >= 1

    def test_table_segment(self):
        segs = _make_segments("# Data\n\n| A | B |\n|---|---|\n| 1 | 2 |")
        table_segs = [s for s in segs if s.block_type == "table"]
        assert len(table_segs) >= 1

    def test_code_segment(self):
        segs = _make_segments("# Code\n\n```python\nprint('hi')\n```")
        code_segs = [s for s in segs if s.block_type == "code"]
        assert len(code_segs) >= 1

    def test_html_table_segment(self):
        segs = _make_segments(
            '# Table\n\n<table>\n<tr><td>A</td><td>B</td></tr>\n</table>'
        )
        html_segs = [s for s in segs if s.block_type == "html_table"]
        assert len(html_segs) >= 1

    def test_list_segment(self):
        segs = _make_segments("# List\n\n- Item 1\n- Item 2\n- Item 3")
        list_segs = [s for s in segs if s.block_type == "list"]
        assert len(list_segs) >= 1

    def test_internal_heading_block_never_persisted_as_segment_type(self):
        root = SectionNode(
            title="Root",
            level=1,
            blocks=(
                ContentBlock(block_type="heading", text="Leaked Heading", level=2),
                ContentBlock(block_type="paragraph", text="Body text"),
            ),
        )
        segs = segment_document(root, build_profile(RawDocumentData(
            file_path="test.md",
            relative_path="test.md",
            file_name="test.md",
            file_type="markdown",
            content="",
            content_hash="h",
        )))

        assert len(segs) == 1
        assert segs[0].block_type == "paragraph"

    def test_invalid_classifier_role_never_persisted(self):
        class BadRoleClassifier:
            def classify(self, text, section_title, block_type, context):
                return "overview"

        segs = segment_document(
            parse_structure("# Title\n\nContent"),
            build_profile(RawDocumentData(
                file_path="test.md",
                relative_path="test.md",
                file_name="test.md",
                file_type="markdown",
                content="",
                content_hash="h",
            )),
            role_classifier=BadRoleClassifier(),
        )

        assert len(segs) == 1
        assert segs[0].semantic_role == "unknown"


class TestSegmentationHashesAndTokens:
    def test_content_hash_populated(self):
        segs = _make_segments("# Title\n\nContent here")
        for seg in segs:
            if seg.raw_text:
                assert seg.content_hash != ""
                assert len(seg.content_hash) == 64  # sha256 hex

    def test_normalized_hash_populated(self):
        segs = _make_segments("# Title\n\nContent")
        for seg in segs:
            if seg.raw_text:
                assert seg.normalized_hash != ""

    def test_token_count_positive(self):
        segs = _make_segments("# Title\n\nHello world")
        for seg in segs:
            if seg.raw_text:
                assert seg.token_count is not None
                assert seg.token_count >= 0

    def test_normalized_text_is_lowered(self):
        segs = _make_segments("# Title\n\nHello World")
        for seg in segs:
            if seg.raw_text:
                assert seg.normalized_text == seg.raw_text.lower().strip()


class TestSegmentationStructureJson:
    def test_structure_json_populated(self):
        segs = _make_segments("# Data\n\n| A | B |\n|---|---|\n| 1 | 2 |")
        table_segs = [s for s in segs if s.block_type == "table"]
        assert len(table_segs) >= 1
        assert isinstance(table_segs[0].structure_json, dict)

    def test_source_offsets_json_populated(self):
        segs = _make_segments("# Title\n\nContent")
        for seg in segs:
            assert isinstance(seg.source_offsets_json, dict)
            assert "block_index" in seg.source_offsets_json


class TestSegmentationEntityRefs:
    def test_entity_refs_default_empty(self):
        segs = _make_segments("# Title\n\nNo entities here")
        for seg in segs:
            assert isinstance(seg.entity_refs_json, list)

    def test_metadata_json_default_empty(self):
        segs = _make_segments("# Title\n\nContent")
        for seg in segs:
            assert isinstance(seg.metadata_json, dict)
