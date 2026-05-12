"""Structure parser: parse Markdown into SectionNode tree with ContentBlocks.

Key design:
- Single parent-child hierarchy, no duplicate content
- Table structure preserved in ContentBlock.structure as {columns, rows}
- ContentBlock carries line_start/line_end from markdown-it token.map
- html_table blocks extracted with columns/rows via html.parser
"""
from __future__ import annotations

import re
from html.parser import HTMLParser
from typing import Any

from markdown_it import MarkdownIt

from knowledge_mining.mining.contracts.models import ContentBlock, SectionNode


def parse_structure(content: str) -> SectionNode:
    """Parse Markdown content into a SectionNode tree."""
    md = MarkdownIt().enable("table")
    tokens = md.parse(content)
    blocks = _tokens_to_blocks(tokens)
    return _build_section_tree(blocks)


def _tokens_to_blocks(tokens: list) -> list[ContentBlock]:
    """Convert markdown-it tokens into ContentBlock list with structure and line info."""
    blocks: list[ContentBlock] = []
    i = 0
    pending_paragraph_map: tuple[int | None, int | None] | None = None
    while i < len(tokens):
        tok = tokens[i]

        if tok.type == "heading_open":
            level = int(tok.tag[1])
            line_start = tok.map[0] if tok.map else None
            i += 1
            if i < len(tokens) and tokens[i].type == "inline":
                line_end = tokens[i + 1].map[0] if (i + 1) < len(tokens) and tokens[i + 1].map else line_start
                blocks.append(ContentBlock(
                    block_type="heading", text=tokens[i].content,
                    level=level, line_start=line_start, line_end=line_end,
                ))
            i += 1  # heading_close

        elif tok.type == "table_open":
            block = _parse_table(tokens, i)
            blocks.append(block)
            while i < len(tokens) and tokens[i].type != "table_close":
                i += 1
            i += 1
            continue

        elif tok.type in ("fence", "code_block"):
            lang = tok.info.strip() if tok.info else None
            line_start = tok.map[0] if tok.map else None
            line_end = tok.map[1] if tok.map else None
            blocks.append(ContentBlock(
                block_type="code", text=tok.content,
                language=lang, line_start=line_start, line_end=line_end,
            ))

        elif tok.type in ("bullet_list_open", "ordered_list_open"):
            ordered = tok.type == "ordered_list_open"
            items: list[str] = []
            items_nested: list[dict[str, Any]] = []
            line_start = tok.map[0] if tok.map else None
            j = i + 1
            depth = 1
            while j < len(tokens):
                if tokens[j].type in ("bullet_list_open", "ordered_list_open"):
                    depth += 1
                elif tokens[j].type in ("bullet_list_close", "ordered_list_close"):
                    depth -= 1
                    if depth == 0:
                        break
                if tokens[j].type == "inline":
                    items_nested.append({"text": tokens[j].content, "depth": depth})
                    if depth == 1:
                        items.append(tokens[j].content)
                j += 1
            line_end = tok.map[1] if tok.map else None
            hierarchical_text = _format_nested_items(items_nested, ordered)
            blocks.append(ContentBlock(
                block_type="list", text=hierarchical_text,
                line_start=line_start, line_end=line_end,
                structure={
                    "kind": "list",
                    "ordered": ordered,
                    "items": items,
                    "items_nested": items_nested,
                    "item_count": len(items_nested),
                },
            ))
            i = j + 1
            continue

        elif tok.type == "blockquote_open":
            bq_parts: list[str] = []
            line_start = tok.map[0] if tok.map else None
            j = i + 1
            while j < len(tokens):
                if tokens[j].type == "blockquote_close":
                    break
                if tokens[j].type == "inline":
                    bq_parts.append(tokens[j].content)
                j += 1
            line_end = tok.map[1] if tok.map else None
            blocks.append(ContentBlock(
                block_type="blockquote", text=" ".join(bq_parts),
                line_start=line_start, line_end=line_end,
            ))
            i = j + 1
            continue

        elif tok.type == "html_block":
            html_text = tok.content.strip()
            line_start = tok.map[0] if tok.map else None
            line_end = tok.map[1] if tok.map else None
            if "<table" in html_text.lower():
                structure = _parse_html_table(html_text)
                blocks.append(ContentBlock(
                    block_type="html_table", text=html_text,
                    line_start=line_start, line_end=line_end,
                    structure=structure,
                ))
            else:
                blocks.append(ContentBlock(
                    block_type="raw_html", text=html_text,
                    line_start=line_start, line_end=line_end,
                ))

        elif tok.type == "paragraph_open":
            pending_paragraph_map = (
                tok.map[0] if tok.map else None,
                tok.map[1] if tok.map else None,
            )

        elif tok.type == "inline":
            text = tok.content.strip()
            if text:
                p_start, p_end = (pending_paragraph_map or (None, None))
                blocks.append(ContentBlock(
                    block_type="paragraph", text=text,
                    line_start=p_start, line_end=p_end,
                ))
            pending_paragraph_map = None

        i += 1

    return blocks


def _parse_table(tokens: list, start: int) -> ContentBlock:
    """Parse table tokens into a ContentBlock with structured columns/rows."""
    columns: list[str] = []
    rows: list[dict[str, str]] = []
    current_row_cells: list[str] = []
    in_thead = False
    line_start = tokens[start].map[0] if tokens[start].map else None
    line_end = None

    i = start + 1
    while i < len(tokens) and tokens[i].type != "table_close":
        tok = tokens[i]
        if tok.type == "thead_open":
            in_thead = True
        elif tok.type == "thead_close":
            in_thead = False
        elif tok.type == "tr_close":
            if current_row_cells:
                if in_thead and not columns:
                    columns = list(current_row_cells)
                else:
                    if columns:
                        row_dict = {columns[j]: cell for j, cell in enumerate(current_row_cells) if j < len(columns)}
                    else:
                        row_dict = {f"col{j}": cell for j, cell in enumerate(current_row_cells)}
                    rows.append(row_dict)
                current_row_cells = []
        elif tok.type == "inline":
            current_row_cells.append(tok.content)
        if tokens[i].map:
            line_end = tokens[i].map[1]
        i += 1

    if not line_end:
        line_end = line_start

    col_count = len(columns)
    row_count = len(rows)

    if columns and rows:
        text_lines = [" | ".join(columns)]
        for row in rows:
            text_lines.append(" | ".join(row.get(col, "") for col in columns))
        readable_text = "\n".join(text_lines)
    elif columns:
        readable_text = " | ".join(columns)
    else:
        readable_text = ""

    return ContentBlock(
        block_type="table",
        text=readable_text,
        line_start=line_start,
        line_end=line_end,
        structure={
            "kind": "markdown_table",
            "columns": columns,
            "rows": rows,
            "row_count": row_count,
            "col_count": col_count,
        },
    )


def _format_nested_items(items_nested: list[dict[str, Any]], ordered: bool) -> str:
    """Format nested list items into indented hierarchical text."""
    if not items_nested:
        return ""
    lines: list[str] = []
    ordered_counter = 0
    last_depth = 0
    for item in items_nested:
        depth = item["depth"]
        text = item["text"]
        indent = "  " * (depth - 1)
        if ordered and depth == 1:
            ordered_counter += 1
            prefix = f"{ordered_counter}. "
        else:
            prefix = "- "
        lines.append(f"{indent}{prefix}{text}")
        last_depth = depth
    return "\n".join(lines)


def _build_section_tree(blocks: list[ContentBlock]) -> SectionNode:
    """Build a hierarchical section tree from flat block list."""
    if not blocks:
        return SectionNode(title=None, level=0)

    heading_indices = [i for i, b in enumerate(blocks) if b.block_type == "heading"]

    if not heading_indices:
        return SectionNode(title=None, level=0, blocks=tuple(blocks))

    min_level = min(blocks[i].level for i in heading_indices if blocks[i].level)
    pre_blocks = tuple(blocks[:heading_indices[0]])

    top_sections: list[list[ContentBlock]] = []
    current_section: list[ContentBlock] = []

    for i, b in enumerate(blocks):
        if i < heading_indices[0]:
            continue
        if b.block_type == "heading" and b.level == min_level:
            if current_section:
                top_sections.append(current_section)
            current_section = [b]
        else:
            current_section.append(b)

    if current_section:
        top_sections.append(current_section)

    children: list[SectionNode] = []
    for section_blocks in top_sections:
        if section_blocks and section_blocks[0].block_type == "heading":
            children.append(_build_nested_section(section_blocks))
        else:
            children.append(SectionNode(title=None, level=0, blocks=tuple(section_blocks)))

    if len(children) == 1 and children[0].title:
        root = children[0]
        return SectionNode(
            title=root.title,
            level=root.level,
            blocks=pre_blocks + root.blocks,
            children=root.children,
        )

    return SectionNode(title=None, level=0, blocks=pre_blocks, children=tuple(children))


def _build_nested_section(blocks: list[ContentBlock]) -> SectionNode:
    """Recursively build a section with nested sub-sections."""
    if not blocks:
        return SectionNode(title=None, level=0)

    heading = blocks[0]
    if heading.block_type != "heading":
        return SectionNode(title=None, level=0, blocks=tuple(blocks))

    heading_level = heading.level or 1
    content_blocks = blocks[1:]

    sub_heading_indices = [
        i for i, b in enumerate(content_blocks)
        if b.block_type == "heading" and (b.level or 1) > heading_level
    ]

    if not sub_heading_indices:
        return SectionNode(
            title=heading.text,
            level=heading_level,
            blocks=tuple(content_blocks),
        )

    direct_blocks: list[ContentBlock] = []
    children: list[SectionNode] = []
    sub_sections_raw = _split_sub_sections(content_blocks, heading_level)

    for sub_section_blocks in sub_sections_raw:
        if sub_section_blocks and sub_section_blocks[0].block_type == "heading":
            children.append(_build_nested_section(sub_section_blocks))
        else:
            direct_blocks.extend(sub_section_blocks)

    return SectionNode(
        title=heading.text,
        level=heading_level,
        blocks=tuple(direct_blocks),
        children=tuple(children),
    )


def _split_sub_sections(
    content_blocks: list[ContentBlock],
    parent_level: int,
) -> list[list[ContentBlock]]:
    """Split content blocks into sub-section groups."""
    result: list[list[ContentBlock]] = []
    current: list[ContentBlock] = []
    current_group_level: int | None = None

    for block in content_blocks:
        if block.block_type == "heading":
            block_level = block.level or 1
            if block_level <= parent_level:
                continue
            if current_group_level is None or block_level <= current_group_level:
                if current:
                    result.append(current)
                current = [block]
                current_group_level = block_level
            else:
                current.append(block)
        else:
            current.append(block)

    if current:
        result.append(current)

    return result


class _HtmlTableParser(HTMLParser):
    """Minimal HTML table parser to extract columns and rows."""

    def __init__(self) -> None:
        super().__init__()
        self.columns: list[str] = []
        self.rows: list[dict[str, str]] = []
        self._in_thead = False
        self._in_cell = False
        self._current_row: list[str] = []
        self._cell_text = ""

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        if tag in ("thead",):
            self._in_thead = True
        elif tag in ("tbody",):
            self._in_thead = False
        elif tag in ("th", "td"):
            self._in_cell = True
            self._cell_text = ""

    def handle_endtag(self, tag: str) -> None:
        if tag in ("thead",):
            self._in_thead = False
        elif tag in ("th", "td"):
            self._in_cell = False
            self._current_row.append(self._cell_text.strip())
        elif tag == "tr":
            if self._current_row:
                if self._in_thead and not self.columns:
                    self.columns = list(self._current_row)
                else:
                    if self.columns:
                        row_dict = {
                            self.columns[j]: cell
                            for j, cell in enumerate(self._current_row)
                            if j < len(self.columns)
                        }
                    else:
                        row_dict = {f"col{j}": cell for j, cell in enumerate(self._current_row)}
                    self.rows.append(row_dict)
                self._current_row = []

    def handle_data(self, data: str) -> None:
        if self._in_cell:
            self._cell_text += data


def _parse_html_table(html_text: str) -> dict[str, Any]:
    """Extract columns/rows structure from HTML table text."""
    parser = _HtmlTableParser()
    try:
        parser.feed(html_text)
    except Exception:
        pass

    col_count = len(parser.columns)
    row_count = len(parser.rows)

    return {
        "kind": "html_table",
        "columns": parser.columns,
        "rows": parser.rows,
        "row_count": row_count,
        "col_count": col_count,
    }
