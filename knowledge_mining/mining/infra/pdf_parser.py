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

# Chinese heading patterns
CN_CHAPTER_RE = re.compile(r"^第[一二三四五六七八九十百千零\d]+[章部篇]")
CN_SECTION_RE = re.compile(r"^第[一二三四五六七八九十百千零\d]+[节条款]")
CN_ENUM_RE = re.compile(r"^[（(][一二三四五六七八九十\d]+[）)]\s*\S")
CN_DASH_ENUM_RE = re.compile(r"^[一二三四五六七八九十]+[、．.]\s*\S")

# --- New rejection rules (Problem C: false-positive headings) ---
# Numeric ranges like "1 to 32767" / "1 – 4294967295" / "0.00 to 100.00" /
# "0 to 100,000,000" — handle decimals, thousands separators, and dash variants.
NUMERIC_RANGE_RE = re.compile(
    r"^\d+(?:\.\d+)?\s*(?:to|to\s+|–|—|-|~)\s*\d[\d,]*(?:\.\d+)?$",
    re.IGNORECASE,
)
# Numeric heading whose title part is itself a range continuation
# (e.g. HEADING_RE matches "0.00 to 100.00" with number=0.00, title="to 100.00").
HEADING_RANGE_TITLE_RE = re.compile(r"^to\s+\d", re.IGNORECASE)
# Platform / model strings like "7450 ESS, 7750 SR, 7750 SR-e, 7750 SR-s, VSR"
PLATFORM_LIST_RE = re.compile(
    r"^[\dA-Z][\dA-Z\s,/+()\-]*\b(?:ESS|SR|VSR|series|Series)\b",
)

# --- Position-based noise filter thresholds ---
_POSITIONAL_TOP_FRAC = 0.08      # top 8% of page
_POSITIONAL_BOTTOM_FRAC = 0.06   # bottom 6% of page
_POSITIONAL_MAX_LEN = 80         # only short blocks are noise

# --- Postprocess thresholds ---
_RECURRING_HEADING_MIN_COUNT = 3  # headings appearing >=3 times get demoted
_SHORT_HEADING_MAX_LEN = 80       # "short" heading threshold for running-header check


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
    blocks = _drop_positional_noise(blocks)
    blocks = _drop_command_running_headers(blocks)
    blocks = _split_long_blocks(blocks)
    content_blocks = _classify_blocks(blocks)
    if not content_blocks:
        return SectionNode(title=doc_title, level=0)
    tree = _build_section_tree(content_blocks, doc_title)
    return _postprocess_tree(tree)


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


def _drop_positional_noise(blocks: list[_PdfBlock]) -> list[_PdfBlock]:
    """Drop short blocks in page top/bottom margin regardless of recurrence.

    Complements _drop_repeated_headers_footers (which needs ≥50% recurrence).
    Catches one-off page numbers, per-chapter running titles, and other short
    edge-of-page noise that recurrence detection misses.
    """
    out: list[_PdfBlock] = []
    for b in blocks:
        if b.page_height <= 0 or len(b.text) > _POSITIONAL_MAX_LEN:
            out.append(b)
            continue
        top_dist = b.page_height - b.y0
        bottom_dist = b.y0
        near_top = top_dist < b.page_height * _POSITIONAL_TOP_FRAC
        near_bottom = bottom_dist < b.page_height * _POSITIONAL_BOTTOM_FRAC
        if near_top or near_bottom:
            continue
        out.append(b)
    return out


def _drop_command_running_headers(blocks: list[_PdfBlock]) -> list[_PdfBlock]:
    """Drop running headers that restate an identified numeric heading's title.

    Pattern: PDF page top repeats the current command/section name (e.g. an
    `aa-sub` block at top of page 2 of section `5.4 aa-sub`). Pre-scans blocks
    for HEADING_RE matches to collect known titles, then drops short blocks
    near page top whose text matches one of those titles.
    """
    # Collect candidate command names from numeric headings.
    known_titles: set[str] = set()
    for b in blocks:
        first_line = b.text.partition("\n")[0].strip()
        m = HEADING_RE.match(first_line)
        if m:
            title = m.group(2).strip()
            if 1 <= len(title) <= _SHORT_HEADING_MAX_LEN:
                known_titles.add(title)
    if not known_titles:
        return blocks

    out: list[_PdfBlock] = []
    for b in blocks:
        first_line = b.text.partition("\n")[0].strip()
        # Only filter short blocks near page top (running header zone).
        if (
            len(first_line) <= _SHORT_HEADING_MAX_LEN
            and b.page_height > 0
            and (b.page_height - b.y0) < b.page_height * _POSITIONAL_TOP_FRAC
            and first_line in known_titles
        ):
            continue
        out.append(b)
    return out


def _split_long_blocks(blocks: list[_PdfBlock]) -> list[_PdfBlock]:
    """Split blocks with multi-line text at blank-line boundaries.

    When a PDF has no detectable headings, entire pages can become single
    giant blocks. Splitting at double-newlines (or single newlines when
    the block is very large) gives the classifier more granularity.
    """
    out: list[_PdfBlock] = []
    for b in blocks:
        # Only split blocks with multiple lines that are reasonably large
        if "\n" not in b.text:
            out.append(b)
            continue

        # Try splitting at double-newline (paragraph boundary)
        parts = re.split(r"\n\s*\n", b.text)
        if len(parts) <= 1:
            # No double-newlines: try single newline for very large blocks
            if len(b.text) > 1000:
                parts = b.text.split("\n")
            else:
                out.append(b)
                continue

        for part in parts:
            part = part.strip()
            if part:
                out.append(_PdfBlock(
                    page_no=b.page_no,
                    text=part,
                    font_size=b.font_size,
                    x0=b.x0,
                    y0=b.y0,
                    page_height=b.page_height,
                ))
    return out


def _classify_blocks(blocks: list[_PdfBlock]) -> list[ContentBlock]:
    if not blocks:
        return []

    size_counter = Counter(b.font_size for b in blocks if b.font_size > 0)
    body_size = size_counter.most_common(1)[0][0] if size_counter else 10.0

    # Collect distinct font sizes sorted descending for level mapping
    distinct_sizes = sorted(set(b.font_size for b in blocks if b.font_size > 0), reverse=True)

    result: list[ContentBlock] = []
    last_numeric_title: str | None = None  # for running-header suppression
    for b in blocks:
        first_line, _, rest = b.text.partition("\n")
        first_line = first_line.strip()
        rest = rest.strip()

        if TOC_DOT_LEADER_RE.search(first_line):
            continue

        # --- Reject obvious non-headings up front (Problem C mitigation) ---
        # These short strings get caught by font-size heuristic later; reject
        # them before any heading branch runs so they fall through to paragraph.
        is_numeric_range = bool(NUMERIC_RANGE_RE.match(first_line))
        is_platform_list = bool(PLATFORM_LIST_RE.match(first_line))
        # Running header that restates the previous numeric heading title
        # (e.g. an `aa-sub` block on page 2 of section `5.4 aa-sub`).
        is_running_header = (
            last_numeric_title is not None
            and first_line == last_numeric_title
            and len(first_line) <= _SHORT_HEADING_MAX_LEN
        )

        # --- Chinese heading detection ---
        if not (is_numeric_range or is_platform_list or is_running_header):
            cn_heading = _try_cn_heading(first_line)
            if cn_heading:
                is_short = len(b.text) <= 400
                font_ok = b.font_size + 0.1 >= body_size
                if is_short and font_ok:
                    result.append(ContentBlock(
                        block_type="heading",
                        text=first_line,
                        level=cn_heading,
                    ))
                    if rest:
                        result.append(ContentBlock(block_type="paragraph", text=rest))
                    continue

        # --- Numeric heading detection (existing logic) ---
        if not (is_numeric_range or is_platform_list or is_running_header):
            m = HEADING_RE.match(first_line)
            if m:
                number = m.group(1)
                title = m.group(2).strip()
                level = number.count(".") + 1
                looks_like_toc = "...." in title or TOC_DOT_LEADER_RE.search(title)
                # Reject numeric ranges that HEADING_RE misfires on
                # (e.g. "0.00 to 100.00" matches HEADING_RE with title="to 100.00").
                looks_like_range = bool(HEADING_RANGE_TITLE_RE.match(title))
                is_short = len(first_line) <= 200 and len(b.text) <= 400
                font_ok = b.font_size + 0.1 >= body_size
                if (not looks_like_toc and not looks_like_range
                        and is_short and font_ok and 1 <= level <= 6):
                    result.append(ContentBlock(
                        block_type="heading",
                        text=f"{number} {title}",
                        level=level,
                    ))
                    last_numeric_title = title  # remember for running-header check
                    if rest:
                        result.append(ContentBlock(
                            block_type="paragraph",
                            text=rest,
                        ))
                    continue

        # --- Font-size heuristic heading detection ---
        if not (is_numeric_range or is_platform_list or is_running_header):
            if b.font_size > body_size * 1.2 and len(first_line) < 200 and len(b.text) <= 400:
                level = _font_size_to_level(b.font_size, distinct_sizes)
                if 1 <= level <= 6:
                    result.append(ContentBlock(
                        block_type="heading",
                        text=first_line,
                        level=level,
                    ))
                    if rest:
                        result.append(ContentBlock(block_type="paragraph", text=rest))
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


def _try_cn_heading(text: str) -> int | None:
    """Detect Chinese heading patterns. Returns heading level or None."""
    if CN_CHAPTER_RE.match(text):
        return 1
    if CN_SECTION_RE.match(text):
        return 2
    if CN_ENUM_RE.match(text):
        return 3
    if CN_DASH_ENUM_RE.match(text):
        return 3
    return None


def _font_size_to_level(font_size: float, distinct_sizes: list[float]) -> int:
    """Map a font size to a heading level based on rank among distinct sizes.

    Largest size → level 1, second largest → level 2, etc.
    """
    for idx, size in enumerate(distinct_sizes):
        if abs(font_size - size) < 0.5:
            return min(idx + 1, 6)
    return 4  # default for unrecognized large sizes


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


# ---------------------------------------------------------------------------
# Postprocessing passes (run after _build_section_tree)
#
# Order: C (demote recurring false headings) → B (reattach orphan content)
# → A (merge cross-page same-title siblings).
# ---------------------------------------------------------------------------

_NUMBER_PREFIX_RE = re.compile(r"^\d+(?:\.\d+)*\s+\S")
# Strict section-number shape: 1-3 digits per level, up to 6 levels (matches
# the classifier ceiling of `1 <= level <= 6` in _classify_blocks).
# Rejects 4+ digit model numbers like "7450 ESS...".
_SECTION_NUMBER_RE = re.compile(r"^\d{1,3}(?:\.\d{1,3}){0,5}$")


def _normalize_title(title: str | None) -> str:
    """Normalize a section title for cross-page merge comparison.

    Strips leading numbering (`5.4 aa-sub` → `aa-sub`), lowercases, collapses
    whitespace. Returns "" for None/empty.
    """
    if not title:
        return ""
    t = title.strip()
    if _title_number(t) is not None:
        # Drop the leading "N.N " prefix.
        t = t.split(None, 1)[1] if " " in t else t
    return re.sub(r"\s+", " ", t).strip().lower()


def _title_number(title: str | None) -> str | None:
    """Extract the leading number from a title (`5.4 aa-sub` → `5.4`).

    Returns None unless the prefix looks like a real section number (1-3 digits
    per level) AND the remaining text is not a numeric range. This prevents
    false positives like `7450 ESS...` (model number) or `1 to 32767` (range).
    """
    if not title:
        return None
    t = title.strip()
    m = _NUMBER_PREFIX_RE.match(t)
    if not m:
        return None
    first = t.split(None, 1)[0]
    if not _SECTION_NUMBER_RE.match(first):
        return None
    # Reject numeric ranges (e.g. "1 to 32767", "0.00 to 100.00").
    if NUMERIC_RANGE_RE.match(t):
        return None
    return first


def _unfreeze(node: SectionNode) -> dict:
    return {
        "title": node.title,
        "level": node.level,
        "blocks": list(node.blocks),
        "children": [_unfreeze(c) for c in node.children],
    }


def _postprocess_tree(tree: SectionNode) -> SectionNode:
    """Run the three cleanup passes. Each pass is wrapped to never crash the parse."""
    root = _unfreeze(tree)
    for fn in (_demote_recurring_headings, _reattach_orphan_content, _merge_same_title_siblings):
        try:
            fn(root)
        except Exception:
            logger.warning("postprocess pass %s failed; continuing", fn.__name__, exc_info=True)
    return _freeze(root)


def _collect_heading_counts(node: dict, counts: Counter) -> None:
    """Populate `counts` with occurrences of each normalized heading title."""
    title = _normalize_title(node.get("title"))
    if title and node.get("level", 0) > 0:
        counts[title] += 1
    for c in node.get("children", []):
        _collect_heading_counts(c, counts)


def _collect_numbered_anchors(node: dict, anchors: set[str]) -> None:
    """Collect normalized title-parts of all NUMBERED headings.

    A title like '5.4 aa-sub' contributes 'aa-sub' to the anchor set. This lets
    Pass C distinguish legitimate cross-page fragments (whose title matches a
    numbered anchor) from recurring false headings (platform strings etc).
    """
    title = node.get("title") or ""
    if node.get("level", 0) > 0 and _title_number(title) is not None:
        # Extract the part after the leading number.
        parts = title.strip().split(None, 1)
        if len(parts) == 2:
            anchors.add(_normalize_title(parts[1]))
    for c in node.get("children", []):
        _collect_numbered_anchors(c, anchors)


def _demote_recurring_headings(node: dict, recurring: set[str] | None = None) -> None:
    """Pass C: demote headings whose normalized title appears >= N times.

    Platform strings like '7450 ESS, 7750 SR...' recur under every command and
    get misclassified as headings. Demote them to paragraphs attached to the
    parent (blocks preserved, title prepended as paragraph).

    Skips any title that is also the title-part of a numbered heading (e.g.
    standalone 'aa-sub' fragments when '5.4 aa-sub' exists) — those are
    legitimate cross-page fragments handled by Pass A, not recurring noise.

    `recurring` is the precomputed set of titles to demote. When None, this
    call computes it from `node` (and assumes callers do not re-call on
    subtrees — doing so would be quadratic on large trees).
    """
    if recurring is None:
        counts: Counter = Counter()
        _collect_heading_counts(node, counts)
        anchors: set[str] = set()
        _collect_numbered_anchors(node, anchors)
        recurring = {
            t for t, c in counts.items()
            if c >= _RECURRING_HEADING_MIN_COUNT and t not in anchors
        }
    if not recurring:
        return

    new_children: list[dict] = []
    for c in node.get("children", []):
        norm = _normalize_title(c.get("title"))
        if norm in recurring and c.get("children"):
            # Heading with children — recurse into it first, then preserve.
            # Demotion of "has-children" recurring nodes is intentionally
            # conservative: we keep them to avoid orphaning legitimate nested
            # sections. Block-level filters upstream already prevent the most
            # common case (platform string L1 with L2 children).
            _demote_recurring_headings(c, recurring)
            new_children.append(c)
        elif norm in recurring:
            # Leaf heading whose title recurs — demote to paragraph in parent,
            # preserving the title text and any blocks the leaf already had.
            if c.get("title"):
                node["blocks"].append(ContentBlock(block_type="paragraph", text=c["title"]))
            node["blocks"].extend(c.get("blocks", []))
        else:
            _demote_recurring_headings(c, recurring)
            new_children.append(c)
    node["children"] = new_children


def _reattach_orphan_content(node: dict) -> None:
    """Pass B: attach orphan content section to preceding empty numbered heading.

    Pattern:
        [L2] 5.1 aa-admit-deny   blocks=0           <- empty numbered heading
        [L2] aa-admit-deny       blocks=9 chars=…   <- content, title restated
    Action: move content blocks into the empty heading; drop the orphan.
    """
    children = node.get("children", [])
    if not children:
        return
    # Recurse first so deeper levels are clean before this level merges.
    for c in children:
        _reattach_orphan_content(c)

    new_children: list[dict] = []
    i = 0
    while i < len(children):
        cur = children[i]
        cur_title = cur.get("title") or ""
        cur_is_empty = not cur.get("blocks") and not cur.get("children")
        cur_numbered = _title_number(cur_title) is not None
        attached = False
        if cur_is_empty and cur_numbered:
            # Look at next sibling (skip nothing — list is index-addressable).
            if i + 1 < len(children):
                nxt = children[i + 1]
                nxt_title = nxt.get("title") or ""
                # Require EXACT normalized-title equality. Substring containment
                # would over-merge `5.1 aa-sub` with `aa-sub-attributes`.
                cur_title_part = cur_title.split(None, 1)[1] if " " in cur_title else cur_title
                norm_cur = _normalize_title(cur_title_part)
                norm_nxt = _normalize_title(nxt_title)
                if norm_cur and norm_cur == norm_nxt:
                    # Move next sibling's blocks/children into cur.
                    cur["blocks"].extend(nxt.get("blocks", []))
                    cur["children"].extend(nxt.get("children", []))
                    new_children.append(cur)
                    i += 2  # skip the orphan we just absorbed
                    attached = True
        if not attached:
            new_children.append(cur)
            i += 1
    node["children"] = new_children


def _merge_same_title_siblings(node: dict) -> None:
    """Pass A: merge adjacent siblings whose normalized titles match.

    Cross-page fragmentation produces multiple siblings with the same title
    (`aa-sub` x4). Merge them into a single section, concatenating blocks and
    children. Iterates until stable (merges can chain).
    """
    for c in node.get("children", []):
        _merge_same_title_siblings(c)

    if not node.get("children"):
        return
    merged = True
    while merged:
        merged = False
        new_children: list[dict] = []
        i = 0
        while i < len(node["children"]):
            cur = node["children"][i]
            if i + 1 < len(node["children"]):
                nxt = node["children"][i + 1]
                if _normalize_title(cur.get("title")) and (
                    _normalize_title(cur.get("title")) == _normalize_title(nxt.get("title"))
                ) and cur.get("level") == nxt.get("level"):
                    cur["blocks"].extend(nxt.get("blocks", []))
                    cur["children"].extend(nxt.get("children", []))
                    new_children.append(cur)
                    i += 2
                    merged = True
                    continue
            new_children.append(cur)
            i += 1
        node["children"] = new_children
