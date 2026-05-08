"""Verify structure parser: heading, table, html_table, code, list, raw_html."""
from knowledge_mining.mining.structure import parse_structure


def test_simple_heading_and_paragraph():
    root = parse_structure("# Title\n\nHello world")
    assert root.title == "Title"
    all_blocks = _collect_all_blocks(root)
    texts = [b.text for b in all_blocks]
    assert any("Hello world" in t for t in texts)


def test_nested_headings():
    root = parse_structure("# H1\n\n## H2\n\nContent\n\n### H3\n\nDeep")
    assert root.title == "H1"
    # Should have children sections
    assert len(root.children) > 0


def test_markdown_table():
    root = parse_structure(
        "# Data\n\n| A | B |\n|---|---|\n| 1 | 2 |\n\nParagraph"
    )
    all_blocks = _collect_all_blocks(root)
    table_blocks = [b for b in all_blocks if b.block_type == "table"]
    assert len(table_blocks) >= 1


def test_html_table_block():
    root = parse_structure(
        '# Table\n\n<table class="data">\n<tr><td>A</td><td>B</td></tr>\n</table>'
    )
    all_blocks = _collect_all_blocks(root)
    html_table_blocks = [b for b in all_blocks if b.block_type == "html_table"]
    assert len(html_table_blocks) >= 1
    assert "<table" in html_table_blocks[0].text


def test_code_block():
    root = parse_structure("# Code\n\n```mml\nADD APN\n```")
    all_blocks = _collect_all_blocks(root)
    code_blocks = [b for b in all_blocks if b.block_type == "code"]
    assert len(code_blocks) >= 1
    assert "ADD APN" in code_blocks[0].text


def test_list_block():
    root = parse_structure("# List\n\n- Item 1\n- Item 2\n- Item 3")
    all_blocks = _collect_all_blocks(root)
    list_blocks = [b for b in all_blocks if b.block_type == "list"]
    assert len(list_blocks) >= 1


def test_no_heading():
    root = parse_structure("Just a paragraph without headings.")
    assert root.title is None
    all_blocks = _collect_all_blocks(root)
    assert len(all_blocks) >= 1


def test_raw_html_block():
    root = parse_structure("# Page\n\n<div class='info'>Some info</div>")
    all_blocks = _collect_all_blocks(root)
    raw_html_blocks = [b for b in all_blocks if b.block_type == "raw_html"]
    assert len(raw_html_blocks) >= 1


def _collect_all_blocks(node) -> list:
    """Collect all ContentBlocks from section tree."""
    blocks = list(node.blocks)
    for child in node.children:
        blocks.extend(_collect_all_blocks(child))
    return blocks
