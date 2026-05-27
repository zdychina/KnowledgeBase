"""Structural PDF parser using pdfminer.six layout API.

Strategy:
1. Extract per-page text blocks with median font size + coords.
2. Drop blocks whose normalized text recurs on most pages near a page edge
   (page headers / footers).
3. Drop table-of-contents noise (lines ending with dot leaders + page number).
4. Classify each block:
   - First line matches `1.1.1 TITLE` numbering, block is short, font >= body
     size → heading (level = dots + 1). Any remainder becomes a paragraph.
   - First line starts with `Tabelle N` / `Abbildung N` → block_type='table'.
   - Otherwise → paragraph.
5. Build a SectionNode tree by stacking on heading levels.
"""
from __future__ import annotations

import logging
import re
from collections import Counter
from dataclasses import dataclass

from knowledge_mining.mining.contracts.models import ContentBlock, SectionNode

logger = logging.getLogger(__name__)


HEADING_RE = re.compile(r"^(\d+(?:\.\d+){0,4})[\u00a0\s]+(\S.{0,200})$")
TOC_DOT_LEADER_RE = re.compile(r"\.{4,}\s*\d+\s*$")
TABLE_CAPTION_RE = re.compile(
    r"^(Tabelle|Table|Abbildung|Figure|Bild)\s+\d+(?:\.\d+)?\b",
    re.IGNORECASE,
)


@dataclass(frozen=True)
class _PdfBlock:
    page_no: int
    text: str
    font_size: float
    x0: float
    y0: float
    page_height: float


def parse_pdf_to_section_tree(
    pdf_path: str, doc_title: str | None = None,
) -> SectionNode:
    """Parse a PDF file into a SectionNode tree."""
    blocks = _extract_blocks(pdf_path)
    blocks = _drop_repeated_headers_footers(blocks)
    content_blocks = _classify_blocks(blocks)
    if not content_blocks:
        return SectionNode(title=doc_title, level=0)
    return _build_section_tree(content_blocks, doc_title)


def _extract_blocks(pdf_path: str) -> list[_PdfBlock]:
    """Yield one _PdfBlock per LTTextContainer in reading order."""
    from pdfminer.high_level import extract_pages
    from pdfminer.layout import LTChar, LTTextContainer

    out: list[_PdfBlock] = []
    for page_no, page in enumerate(extract_pages(pdf_path), start=1):
        page_height = float(getattr(page, "height", 0.0) or 0.0)
        for el in page:
            if not isinstance(el, LTTextContainer):
                continue
            text = el.get_text().strip()
            if not text:
                continue
            sizes: list[float] = []
            for line in el:
                for ch in line:
                    if isinstance(ch, LTChar):
                        sizes.append(ch.size)
            if sizes:
                sizes.sort()
                font_size = sizes[len(sizes) // 2]
            else:
                font_size = 0.0
            out.append(_PdfBlock(
                page_no=page_no,
                text=text,
                font_size=round(font_size, 2),
                x0=float(el.x0),
                y0=float(el.y0),
                page_height=page_height,
            ))
    return out


def _normalize_for_recurrence(text: str) -> str:
    """Collapse digits so 'Seite 3 von 35' matches 'Seite 12 von 35'."""
    return re.sub(r"\d+", "N", text)


def _drop_repeated_headers_footers(blocks: list[_PdfBlock]) -> list[_PdfBlock]:
    if not blocks:
        return blocks
    page_count = max(b.page_no for b in blocks)
    if page_count < 3:
        return blocks
    threshold = max(3, page_count // 2)

    counter: Counter[str] = Counter(_normalize_for_recurrence(b.text) for b in blocks)
    repeated = {t for t, c in counter.items() if c >= threshold}
    if not repeated:
        return blocks

    out: list[_PdfBlock] = []
    for b in blocks:
        if _normalize_for_recurrence(b.text) not in repeated:
            out.append(b)
            continue
        if b.page_height <= 0:
            continue
        top_dist = b.page_height - b.y0
        bottom_dist = b.y0
        near_top = top_dist < b.page_height * 0.15
        near_bottom = bottom_dist < b.page_height * 0.12
        if near_top or near_bottom:
            continue
        out.append(b)
    return out


def _classify_blocks(blocks: list[_PdfBlock]) -> list[ContentBlock]:
    if not blocks:
        return []

    size_counter = Counter(b.font_size for b in blocks if b.font_size > 0)
    body_size = size_counter.most_common(1)[0][0] if size_counter else 10.0

    result: list[ContentBlock] = []
    for b in blocks:
        first_line, _, rest = b.text.partition("\n")
        first_line = first_line.strip()
        rest = rest.strip()

        if TOC_DOT_LEADER_RE.search(first_line):
            continue

        m = HEADING_RE.match(first_line)
        if m:
            number = m.group(1)
            title = m.group(2).strip()
            level = number.count(".") + 1
            looks_like_toc = "...." in title or TOC_DOT_LEADER_RE.search(title)
            is_short = len(first_line) <= 200 and len(b.text) <= 400
            font_ok = b.font_size + 0.1 >= body_size
            if not looks_like_toc and is_short and font_ok and 1 <= level <= 6:
                result.append(ContentBlock(
                    block_type="heading",
                    text=f"{number} {title}",
                    level=level,
                ))
                if rest:
                    result.append(ContentBlock(
                        block_type="paragraph",
                        text=rest,
                    ))
                continue

        if TABLE_CAPTION_RE.match(first_line):
            result.append(ContentBlock(
                block_type="table",
                text=b.text,
            ))
            continue

        result.append(ContentBlock(
            block_type="paragraph",
            text=b.text,
        ))
    return result


def _build_section_tree(
    blocks: list[ContentBlock], doc_title: str | None,
) -> SectionNode:
    """Stack-based builder: pop ancestors with level >= current heading level."""
    root = _mutable_node(title=doc_title, level=0)
    stack: list[dict] = [root]

    for block in blocks:
        if block.block_type == "heading" and block.level:
            level = block.level
            while len(stack) > 1 and stack[-1]["level"] >= level:
                stack.pop()
            new_node = _mutable_node(title=block.text, level=level)
            stack[-1]["children"].append(new_node)
            stack.append(new_node)
        else:
            stack[-1]["blocks"].append(block)

    return _freeze(root)


def _mutable_node(title: str | None, level: int) -> dict:
    return {"title": title, "level": level, "children": [], "blocks": []}


def _freeze(node: dict) -> SectionNode:
    return SectionNode(
        title=node["title"],
        level=node["level"],
        blocks=tuple(node["blocks"]),
        children=tuple(_freeze(c) for c in node["children"]),
    )
