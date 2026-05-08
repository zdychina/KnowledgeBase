"""Test parsers: MarkdownParser, PlainTextParser, PassthroughParser via create_parser factory."""
from __future__ import annotations

import tempfile
from pathlib import Path

from knowledge_mining.mining.models import ContentBlock, SectionNode
from knowledge_mining.mining.parsers import (
    MarkdownParser,
    PassthroughParser,
    PlainTextParser,
    create_parser,
)


class TestCreateParserFactory:
    def test_markdown_type(self):
        parser = create_parser("markdown")
        assert isinstance(parser, MarkdownParser)

    def test_txt_type(self):
        parser = create_parser("txt")
        assert isinstance(parser, PlainTextParser)

    def test_html_type_passthrough(self):
        parser = create_parser("html")
        assert isinstance(parser, PassthroughParser)

    def test_pdf_type_passthrough(self):
        parser = create_parser("pdf")
        assert isinstance(parser, PassthroughParser)

    def test_doc_type_passthrough(self):
        parser = create_parser("doc")
        assert isinstance(parser, PassthroughParser)

    def test_docx_type_passthrough(self):
        parser = create_parser("docx")
        assert isinstance(parser, PassthroughParser)

    def test_other_type_passthrough(self):
        parser = create_parser("other")
        assert isinstance(parser, PassthroughParser)

    def test_custom_chunk_params(self):
        parser = create_parser("txt", chunk_size=100, chunk_overlap=10)
        assert isinstance(parser, PlainTextParser)
        assert parser.chunk_size == 100
        assert parser.chunk_overlap == 10


class TestMarkdownParser:
    def test_basic_parse(self):
        parser = MarkdownParser()
        result = parser.parse("# Title\n\nHello world", "test.md", {})
        assert result is not None
        assert isinstance(result, SectionNode)

    def test_empty_content(self):
        parser = MarkdownParser()
        result = parser.parse("   ", "empty.md", {})
        assert result is None

    def test_heading_and_paragraph(self):
        parser = MarkdownParser()
        result = parser.parse("# My Title\n\nParagraph text", "test.md", {})
        assert result is not None
        assert result.title == "My Title"

    def test_table_block(self):
        parser = MarkdownParser()
        result = parser.parse("# Data\n\n| A | B |\n|---|---|\n| 1 | 2 |", "test.md", {})
        assert result is not None
        all_blocks = _collect_blocks(result)
        table_blocks = [b for b in all_blocks if b.block_type == "table"]
        assert len(table_blocks) >= 1

    def test_code_block(self):
        parser = MarkdownParser()
        result = parser.parse("# Code\n\n```python\nprint('hi')\n```", "test.md", {})
        assert result is not None
        all_blocks = _collect_blocks(result)
        code_blocks = [b for b in all_blocks if b.block_type == "code"]
        assert len(code_blocks) >= 1
        assert code_blocks[0].language == "python"

    def test_nested_sections(self):
        parser = MarkdownParser()
        md = "# H1\n\n## H2\n\nContent\n\n### H3\n\nDeep"
        result = parser.parse(md, "test.md", {})
        assert result is not None
        assert result.title == "H1"
        assert len(result.children) > 0


class TestPlainTextParser:
    def test_basic_parse(self):
        parser = PlainTextParser()
        result = parser.parse("Hello world this is plain text", "notes.txt", {})
        assert result is not None
        assert isinstance(result, SectionNode)
        assert len(result.blocks) >= 1

    def test_empty_content(self):
        parser = PlainTextParser()
        result = parser.parse("", "empty.txt", {})
        assert result is None

    def test_whitespace_only(self):
        parser = PlainTextParser()
        result = parser.parse("   \n\n   ", "blank.txt", {})
        assert result is None

    def test_chunking_produces_blocks(self):
        parser = PlainTextParser(chunk_size=5, chunk_overlap=1)
        long_text = " ".join(f"word{i}" for i in range(20))
        result = parser.parse(long_text, "long.txt", {})
        assert result is not None
        assert len(result.blocks) > 1  # Multiple chunks from 20 words

    def test_block_type_is_paragraph(self):
        parser = PlainTextParser()
        result = parser.parse("Some text content", "test.txt", {})
        assert result is not None
        for block in result.blocks:
            assert block.block_type == "paragraph"

    def test_title_is_file_name(self):
        parser = PlainTextParser()
        result = parser.parse("Content", "my_file.txt", {})
        assert result is not None
        assert result.title == "my_file.txt"

    def test_cjk_tokenization(self):
        parser = PlainTextParser(chunk_size=5, chunk_overlap=1)
        result = parser.parse("网络切片是5G核心技术之一", "cjk.txt", {})
        assert result is not None
        assert len(result.blocks) >= 1


class TestPassthroughParser:
    def test_returns_none(self):
        parser = PassthroughParser()
        result = parser.parse("<html><body>Hello</body></html>", "page.html", {})
        assert result is None

    def test_empty_returns_none(self):
        parser = PassthroughParser()
        result = parser.parse("", "empty.pdf", {})
        assert result is None

    def test_with_content_returns_none(self):
        parser = PassthroughParser()
        result = parser.parse("Some content", "doc.docx", {})
        assert result is None


def _collect_blocks(node: SectionNode) -> list[ContentBlock]:
    """Recursively collect all ContentBlocks from a SectionNode tree."""
    blocks = list(node.blocks)
    for child in node.children:
        blocks.extend(_collect_blocks(child))
    return blocks
