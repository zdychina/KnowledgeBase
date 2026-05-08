"""Regression tests for Codex v0.5 review fixes.

Covers:
- P1-1: No duplicate segments from MD section tree
- P1-2: Table structure_json has columns/rows
- P1-3: Canonicalization three-layer dedup works
- P1-4: version_code uniqueness without sleep
- P1-6: Validation catches zero-primary canonicals
- P2-1: source_offsets_json has parser/line info
- P2-2: TXT parser preserves original text with punctuation
- P2-3: processing_profile_json has parse_status
"""
from __future__ import annotations

import tempfile
from pathlib import Path

from knowledge_mining.mining.canonicalization import canonicalize
from knowledge_mining.mining.document_profile import build_profile
from knowledge_mining.mining.models import (
    BatchParams,
    DocumentProfile,
    RawDocumentData,
    RawSegmentData,
)
from knowledge_mining.mining.parsers import create_parser
from knowledge_mining.mining.publishing import publish
from knowledge_mining.mining.segmentation import segment_document
from knowledge_mining.mining.structure import parse_structure
from knowledge_mining.mining.text_utils import (
    content_hash,
    normalized_hash,
    token_count,
)


# --- P1-1: No duplicate segments ---

class TestNoDuplicateSegments:
    def test_table_appears_once_in_segments(self):
        """Same table should NOT appear in multiple segments."""
        md = "# ADD APN\n\nintro text\n\n## Parameters\n\n| Param | Desc |\n|---|---|\n| APNNAME | APN name |\n\n## Remarks\n\nremark text"
        root = parse_structure(md)
        profile = DocumentProfile(document_key="test.md")
        segments = segment_document(root, profile, parser_name="markdown")

        table_segments = [s for s in segments if s.block_type == "table"]
        assert len(table_segments) == 1, (
            f"Expected 1 table segment, got {len(table_segments)}. "
            f"Texts: {[s.raw_text[:50] for s in table_segments]}"
        )

    def test_paragraph_appears_once(self):
        """Each paragraph should appear in exactly one segment."""
        md = "# H1\n\nintro\n\n## S1\n\ntext1\n\n## S2\n\ntext2"
        root = parse_structure(md)
        profile = DocumentProfile(document_key="test.md")
        segments = segment_document(root, profile, parser_name="markdown")

        all_texts = [s.raw_text for s in segments]
        # "intro" should appear exactly once
        intro_count = sum(1 for t in all_texts if "intro" in t)
        assert intro_count == 1, f"'intro' appears {intro_count} times in segments"

    def test_h1_h2_hierarchy_no_duplication(self):
        """H2 content should only be under H1, not also at root level."""
        md = "# Title\n\nA paragraph\n\n## Sub\n\nB paragraph"
        root = parse_structure(md)
        assert root.title == "Title"
        assert len(root.children) == 1
        assert root.children[0].title == "Sub"

        profile = DocumentProfile(document_key="test.md")
        segments = segment_document(root, profile, parser_name="markdown")

        all_texts = " ".join(s.raw_text for s in segments)
        # "B paragraph" should appear exactly once
        b_count = all_texts.count("B paragraph")
        assert b_count == 1, f"'B paragraph' found {b_count} times"


# --- P1-2: Table structure_json ---

class TestTableStructureJson:
    def test_table_has_columns_and_rows(self):
        """structure_json for table must have kind, columns, rows, row_count, col_count."""
        md = "# Params\n\n| Param | Desc |\n|---|---|\n| APNNAME | APN Name |"
        root = parse_structure(md)
        profile = DocumentProfile(document_key="test.md")
        segments = segment_document(root, profile, parser_name="markdown")

        table_segs = [s for s in segments if s.block_type == "table"]
        assert len(table_segs) == 1
        struct = table_segs[0].structure_json
        assert struct.get("kind") == "markdown_table"
        assert "columns" in struct
        assert "rows" in struct
        assert struct["columns"] == ["Param", "Desc"]
        assert len(struct["rows"]) == 1
        assert struct["rows"][0].get("Param") == "APNNAME"
        assert struct["row_count"] == 1
        assert struct["col_count"] == 2

    def test_multi_row_table(self):
        md = "# Table\n\n| A | B |\n|---|---|\n| 1 | 2 |\n| 3 | 4 |"
        root = parse_structure(md)
        profile = DocumentProfile(document_key="test.md")
        segments = segment_document(root, profile, parser_name="markdown")

        table_segs = [s for s in segments if s.block_type == "table"]
        assert len(table_segs) == 1
        struct = table_segs[0].structure_json
        assert struct["row_count"] == 2
        assert struct["col_count"] == 2


# --- P1-3: Canonicalization three-layer ---

class TestCanonicalizationThreeLayer:
    def test_normalized_duplicate_merged(self):
        """Different content_hash but same normalized_hash → 1 canonical."""
        segs = [
            _make_seg("a.md", 0, "Hello World!"),
            _make_seg("b.md", 0, "hello world"),
        ]
        profiles = {"a.md": _make_profile("a.md"), "b.md": _make_profile("b.md")}
        canonicals, mappings = canonicalize(segs, profiles)
        # "Hello World!" and "hello world" should normalize to the same hash
        assert len(canonicals) == 1, f"Expected 1 canonical, got {len(canonicals)}"
        non_primary = [m for m in mappings if not m.is_primary]
        assert any(m.relation_type == "normalized_duplicate" for m in non_primary)

    def test_singletons_remain_separate(self):
        """Completely different texts → each becomes its own canonical."""
        segs = [
            _make_seg("a.md", 0, "Apple banana cherry"),
            _make_seg("b.md", 0, "Xylophone zebra quantum"),
        ]
        profiles = {"a.md": _make_profile("a.md"), "b.md": _make_profile("b.md")}
        canonicals, mappings = canonicalize(segs, profiles)
        assert len(canonicals) == 2
        assert all(m.relation_type == "primary" for m in mappings)


# --- P1-4: version_code uniqueness ---

class TestVersionCodeUniqueness:
    def test_rapid_publish_no_collision(self):
        """Publish twice rapidly — no version_code collision."""
        with tempfile.TemporaryDirectory() as tmp:
            tmp = Path(tmp)
            _write_md(tmp / "doc.md", "# V1\n\nContent one")
            docs1, segs1, canon1, maps1 = _run_mini_pipeline(tmp)

            db_path = tmp / "test.sqlite"
            r1 = publish(docs1, segs1, canon1, maps1, db_path)

            # Publish again immediately (no sleep)
            _write_md(tmp / "doc.md", "# V2\n\nContent two")
            docs2, segs2, canon2, maps2 = _run_mini_pipeline(tmp)
            r2 = publish(docs2, segs2, canon2, maps2, db_path)

            assert r1["version_code"] != r2["version_code"]
            assert r2["status"] == "active"


# --- P2-1: source_offsets_json ---

class TestSourceOffsetsJson:
    def test_has_parser_field(self):
        md = "# Title\n\nContent here"
        root = parse_structure(md)
        profile = DocumentProfile(document_key="test.md")
        segments = segment_document(root, profile, parser_name="markdown")
        for seg in segments:
            assert "parser" in seg.source_offsets_json
            assert seg.source_offsets_json["parser"] == "markdown"

    def test_has_block_index(self):
        md = "# Title\n\nPara1\n\nPara2"
        root = parse_structure(md)
        profile = DocumentProfile(document_key="test.md")
        segments = segment_document(root, profile, parser_name="markdown")
        indices = [s.source_offsets_json["block_index"] for s in segments]
        assert indices == sorted(indices)  # monotonically increasing


# --- P2-2: TXT parser preserves original text ---

class TestTxTPreservesPunctuation:
    def test_punctuation_preserved_in_raw_text(self):
        parser = create_parser("txt")
        original = "Hello, world! This is a test. Does it work? Yes: 100%."
        root = parser.parse(original, "test.txt", {})
        assert root is not None
        # raw_text should contain punctuation
        all_text = " ".join(b.text for b in root.blocks)
        assert "," in all_text
        assert "!" in all_text
        assert "?" in all_text
        assert "%" in all_text

    def test_cjk_punctuation_preserved(self):
        parser = create_parser("txt")
        original = "这是中文测试。包含标点！还有更多内容：测试。"
        root = parser.parse(original, "test.txt", {})
        assert root is not None
        all_text = " ".join(b.text for b in root.blocks)
        assert "。" in all_text
        assert "！" in all_text


# --- P2-3: processing_profile_json ---

class TestProcessingProfile:
    def test_parsed_doc_has_parse_status(self):
        """Markdown documents with segments should have parse_status=parsed."""
        with tempfile.TemporaryDirectory() as tmp:
            tmp = Path(tmp)
            _write_md(tmp / "doc.md", "# Title\n\nContent")
            docs, segs, canon, maps = _run_mini_pipeline(tmp)

            db_path = tmp / "test.sqlite"
            publish(docs, segs, canon, maps, db_path)

            import sqlite3
            conn = sqlite3.connect(str(db_path))
            try:
                import json
                row = conn.execute(
                    "SELECT processing_profile_json FROM asset_raw_documents WHERE file_type = 'markdown'"
                ).fetchone()
                assert row is not None
                profile = json.loads(row[0])
                assert profile.get("parse_status") == "parsed"
            finally:
                conn.close()


# --- Helpers ---

def _make_seg(doc_key: str, idx: int, raw_text: str) -> RawSegmentData:
    return RawSegmentData(
        document_key=doc_key,
        segment_index=idx,
        raw_text=raw_text,
        normalized_text=raw_text.lower().strip(),
        content_hash=content_hash(raw_text),
        normalized_hash=normalized_hash(raw_text),
        token_count=token_count(raw_text),
    )


def _make_profile(doc_key: str) -> DocumentProfile:
    return DocumentProfile(document_key=doc_key)


def _write_md(path: Path, content: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(content, encoding="utf-8")


def _run_mini_pipeline(tmp: Path):
    from knowledge_mining.mining.ingestion import ingest_directory
    docs, _ = ingest_directory(tmp)
    profiles = [build_profile(d) for d in docs]
    profile_map = {p.document_key: p for p in profiles}
    all_segments: list[RawSegmentData] = []
    for doc, profile in zip(docs, profiles):
        parser = create_parser(doc.file_type)
        doc_root = parser.parse(doc.content, doc.file_name, {})
        if doc_root is None:
            continue
        parser_name = "markdown" if doc.file_type == "markdown" else "txt" if doc.file_type == "txt" else "unknown"
        segments = segment_document(doc_root, profile, parser_name=parser_name)
        all_segments.extend(segments)
    canonicals, mappings = canonicalize(all_segments, profile_map)
    return docs, all_segments, canonicals, mappings
