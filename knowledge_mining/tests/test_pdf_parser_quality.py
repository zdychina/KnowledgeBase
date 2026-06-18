"""Unit tests for PDF parser quality improvements (v1.3).

Covers:
- _drop_positional_noise: short edge-of-page blocks dropped
- _drop_command_running_headers: restated heading title near page top dropped
- _classify_blocks: NUMERIC_RANGE / PLATFORM_LIST / running-header rejections
- _postprocess_tree: 3 passes (C demote recurring, B reattach orphan, A merge siblings)
"""
from __future__ import annotations

import pytest

from knowledge_mining.mining.contracts.models import ContentBlock, SectionNode
from knowledge_mining.mining.infra.pdf_parser import (
    HEADING_RANGE_TITLE_RE,
    NUMERIC_RANGE_RE,
    PLATFORM_LIST_RE,
    _classify_blocks,
    _drop_command_running_headers,
    _drop_positional_noise,
    _merge_same_title_siblings,
    _demote_recurring_headings,
    _normalize_title,
    _PdfBlock,
    _postprocess_tree,
    _reattach_orphan_content,
    _title_number,
)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _block(
    text: str, *, page_no: int = 1, font_size: float = 10.0,
    x0: float = 100.0, y0: float = 400.0, page_height: float = 800.0,
) -> _PdfBlock:
    return _PdfBlock(
        page_no=page_no, text=text, font_size=font_size,
        x0=x0, y0=y0, page_height=page_height,
    )


def _node(title, level=1, blocks=None, children=None):
    return {
        "title": title, "level": level,
        "blocks": list(blocks or []),
        "children": list(children or []),
    }


def _cb(text: str, block_type: str = "paragraph", level: int | None = None) -> ContentBlock:
    if block_type == "heading":
        return ContentBlock(block_type="heading", text=text, level=level or 1)
    return ContentBlock(block_type=block_type, text=text)


# ---------------------------------------------------------------------------
# Regex rejection rules (Problem C source-level)
# ---------------------------------------------------------------------------

class TestRegexRejections:
    def test_numeric_range_matches(self):
        assert NUMERIC_RANGE_RE.match("1 to 32767")
        assert NUMERIC_RANGE_RE.match("1 to 4294967295")
        assert NUMERIC_RANGE_RE.match("0.00 to 100.00")
        assert NUMERIC_RANGE_RE.match("0 to 100,000,000")
        assert NUMERIC_RANGE_RE.match("1 – 10")

    def test_numeric_range_rejects_real_headings(self):
        assert not NUMERIC_RANGE_RE.match("5.4 aa-sub")
        assert not NUMERIC_RANGE_RE.match("第一章 概述")

    def test_platform_list_matches(self):
        assert PLATFORM_LIST_RE.match("7450 ESS, 7750 SR, 7750 SR-s, VSR")
        assert PLATFORM_LIST_RE.match("7750 SR series")

    def test_platform_list_rejects_real_headings(self):
        assert not PLATFORM_LIST_RE.match("5.1 aa-admit-deny")
        assert not PLATFORM_LIST_RE.match("aa-sub")

    def test_heading_range_title_rejects(self):
        assert HEADING_RANGE_TITLE_RE.match("to 100.00")
        assert HEADING_RANGE_TITLE_RE.match("to 32767")
        assert not HEADING_RANGE_TITLE_RE.match("aa-admit-deny")


# ---------------------------------------------------------------------------
# _drop_positional_noise (Step 1.5)
# ---------------------------------------------------------------------------

class TestDropPositionalNoise:
    def test_drops_short_block_near_top(self):
        # page_height=800, y0=780 → top_dist=20 → 20/800=2.5% < 8%
        b = _block("page header", y0=780, page_height=800)
        assert _drop_positional_noise([b]) == []

    def test_drops_short_block_near_bottom(self):
        # y0=20 → bottom_dist=20 → 20/800=2.5% < 6%
        b = _block("page footer", y0=20, page_height=800)
        assert _drop_positional_noise([b]) == []

    def test_drops_page_number(self):
        b = _block("470", y0=15, page_height=800)
        assert _drop_positional_noise([b]) == []

    def test_keeps_body_paragraph(self):
        # y0=400 → mid-page
        b = _block("a" * 200, y0=400, page_height=800)
        assert _drop_positional_noise([b]) == [b]

    def test_keeps_long_block_even_at_edge(self):
        # 200 chars at top — too long to be noise
        b = _block("a" * 200, y0=780, page_height=800)
        assert _drop_positional_noise([b]) == [b]

    def test_keeps_block_without_page_height(self):
        b = _block("text", page_height=0)
        assert _drop_positional_noise([b]) == [b]


# ---------------------------------------------------------------------------
# _drop_command_running_headers (Step 1.6)
# ---------------------------------------------------------------------------

class TestDropCommandRunningHeaders:
    def test_drops_running_header_matching_known_title(self):
        # First block establishes the numeric heading
        heading = _block("5.4 aa-sub", font_size=14, y0=700, page_height=800)
        # Subsequent page top: restated command name
        running = _block("aa-sub", font_size=12, y0=780, page_height=800)
        result = _drop_command_running_headers([heading, running])
        assert running not in result
        assert heading in result

    def test_keeps_unrelated_short_block(self):
        heading = _block("5.4 aa-sub", font_size=14, y0=700, page_height=800)
        body = _block("some other text", font_size=10, y0=400, page_height=800)
        result = _drop_command_running_headers([heading, body])
        assert body in result

    def test_no_numeric_headings_passes_through(self):
        b = _block("just a paragraph", y0=400, page_height=800)
        assert _drop_command_running_headers([b]) == [b]


# ---------------------------------------------------------------------------
# _classify_blocks rejection of false headings
# ---------------------------------------------------------------------------

class TestClassifyRejections:
    def test_numeric_range_not_classified_as_heading(self):
        # Font is large (would normally trigger heading) but text is numeric range
        b = _block("1 to 32767", font_size=18, y0=400, page_height=800)
        result = _classify_blocks([b])
        assert len(result) == 1
        assert result[0].block_type == "paragraph"

    def test_platform_list_not_classified_as_heading(self):
        b = _block("7450 ESS, 7750 SR, 7750 SR-s, VSR", font_size=14, y0=400, page_height=800)
        result = _classify_blocks([b])
        # Should be paragraph (or fall through), NOT heading
        assert all(r.block_type != "heading" for r in result)

    def test_running_header_after_numeric_heading_demoted(self):
        # First block: legitimate numeric heading
        h = _block("5.4 aa-sub", font_size=14, y0=400, page_height=800)
        # Second block: same title, large font — would be heading without guard
        running = _block("aa-sub", font_size=14, y0=400, page_height=800)
        result = _classify_blocks([h, running])
        headings = [r for r in result if r.block_type == "heading"]
        # Only the first numeric heading should remain
        assert len(headings) == 1
        assert "5.4 aa-sub" in headings[0].text

    def test_numeric_range_in_heading_form_rejected(self):
        # "0.00 to 100.00" matches HEADING_RE (number=0.00, title="to 100.00")
        # but should be rejected as a range
        b = _block("0.00 to 100.00", font_size=14, y0=400, page_height=800)
        result = _classify_blocks([b])
        headings = [r for r in result if r.block_type == "heading"]
        assert headings == []


# ---------------------------------------------------------------------------
# Title helpers
# ---------------------------------------------------------------------------

class TestTitleHelpers:
    def test_normalize_strips_number_prefix(self):
        assert _normalize_title("5.4 aa-sub") == "aa-sub"
        assert _normalize_title("aa-sub") == "aa-sub"

    def test_normalize_lowercases_and_collapses(self):
        assert _normalize_title("5.1 AA-Admit-Deny") == "aa-admit-deny"
        assert _normalize_title("  Multiple   Spaces  ") == "multiple spaces"

    def test_normalize_empty(self):
        assert _normalize_title(None) == ""
        assert _normalize_title("") == ""

    def test_title_number_extracted(self):
        assert _title_number("5.4 aa-sub") == "5.4"
        assert _title_number("5 aa-sub") == "5"

    def test_title_number_absent(self):
        assert _title_number("aa-sub") is None
        assert _title_number(None) is None

    def test_title_number_rejects_model_numbers(self):
        # 4-digit model numbers like "7450" are NOT section numbers
        assert _title_number("7450 ESS, 7750 SR") is None
        assert _title_number("100 to 32767") is None  # also a numeric range

    def test_title_number_supports_six_levels(self):
        # Classifier ceiling is `1 <= level <= 6`; title_number must keep parity.
        assert _title_number("1.2.3.4.5.6 deep-title") == "1.2.3.4.5.6"
        # 7 levels is past the classifier ceiling — title_number returns None.
        assert _title_number("1.2.3.4.5.6.7 too-deep") is None


# ---------------------------------------------------------------------------
# Pass A: _merge_same_title_siblings
# ---------------------------------------------------------------------------

class TestMergeSameTitleSiblings:
    def test_merges_adjacent_same_title(self):
        root = _node("root", level=0, children=[
            _node("aa-sub", level=2, blocks=[_cb("content1")]),
            _node("aa-sub", level=2, blocks=[_cb("content2")]),
        ])
        _merge_same_title_siblings(root)
        assert len(root["children"]) == 1
        assert len(root["children"][0]["blocks"]) == 2

    def test_merges_four_cross_page_fragments(self):
        root = _node("root", level=0, children=[
            _node("aa-sub", level=2, blocks=[_cb("p1")]),
            _node("aa-sub", level=2, blocks=[_cb("p2")]),
            _node("aa-sub", level=2, blocks=[_cb("p3")]),
            _node("aa-sub", level=2, blocks=[_cb("p4")]),
        ])
        _merge_same_title_siblings(root)
        assert len(root["children"]) == 1
        assert len(root["children"][0]["blocks"]) == 4

    def test_does_not_merge_different_titles(self):
        root = _node("root", level=0, children=[
            _node("5.4 aa-sub", level=2),
            _node("5.5 aa-sub-attributes", level=2),
        ])
        _merge_same_title_siblings(root)
        assert len(root["children"]) == 2

    def test_does_not_merge_different_levels(self):
        root = _node("root", level=0, children=[
            _node("intro", level=1),
            _node("intro", level=2),
        ])
        _merge_same_title_siblings(root)
        assert len(root["children"]) == 2

    def test_merges_normalized_titles(self):
        # 5.4 aa-sub and aa-sub normalize to the same thing
        root = _node("root", level=0, children=[
            _node("5.4 aa-sub", level=2, blocks=[_cb("a")]),
            _node("aa-sub", level=2, blocks=[_cb("b")]),
        ])
        _merge_same_title_siblings(root)
        assert len(root["children"]) == 1


# ---------------------------------------------------------------------------
# Pass B: _reattach_orphan_content
# ---------------------------------------------------------------------------

class TestReattachOrphanContent:
    def test_reattach_numbered_heading_with_restated_content(self):
        root = _node("root", level=0, children=[
            _node("5.1 aa-admit-deny", level=2),  # empty numbered heading
            _node("aa-admit-deny", level=2, blocks=[_cb("content")]),
        ])
        _reattach_orphan_content(root)
        assert len(root["children"]) == 1
        assert root["children"][0]["title"] == "5.1 aa-admit-deny"
        assert len(root["children"][0]["blocks"]) == 1

    def test_does_not_reattach_when_titles_differ(self):
        root = _node("root", level=0, children=[
            _node("5.1 aa-admit-deny", level=2),
            _node("aa-interface", level=2, blocks=[_cb("content")]),
        ])
        _reattach_orphan_content(root)
        assert len(root["children"]) == 2

    def test_does_not_reattach_non_empty_numbered_heading(self):
        root = _node("root", level=0, children=[
            _node("5.1 foo", level=2, blocks=[_cb("has content")]),
            _node("foo", level=2, blocks=[_cb("more content")]),
        ])
        _reattach_orphan_content(root)
        # First has content, so no reattach — both stay
        assert len(root["children"]) == 2

    def test_does_not_reattach_on_substring_match(self):
        """Regression: substring containment over-merges prefix-sharing titles.

        `5.1 aa-sub` followed by `aa-sub-attributes` must NOT be reattached
        just because 'aa-sub' is a substring of 'aa-sub-attributes'.
        """
        root = _node("root", level=0, children=[
            _node("5.1 aa-sub", level=2),
            _node("aa-sub-attributes", level=2, blocks=[_cb("content")]),
        ])
        _reattach_orphan_content(root)
        assert len(root["children"]) == 2
        titles = [c["title"] for c in root["children"]]
        assert "5.1 aa-sub" in titles
        assert "aa-sub-attributes" in titles


# ---------------------------------------------------------------------------
# Pass C: _demote_recurring_headings
# ---------------------------------------------------------------------------

class TestDemoteRecurringHeadings:
    def test_demotes_high_frequency_heading(self):
        # 3+ occurrences of same title → demote
        root = _node("root", level=0, children=[
            _node("7450 ESS, 7750 SR", level=1),
            _node("5.1 aa", level=2, blocks=[_cb("c1")]),
            _node("7450 ESS, 7750 SR", level=1),
            _node("5.2 bb", level=2, blocks=[_cb("c2")]),
            _node("7450 ESS, 7750 SR", level=1),
        ])
        _demote_recurring_headings(root)
        platform_children = [c for c in root["children"]
                             if "7450" in (c.get("title") or "")]
        assert platform_children == []

    def test_keeps_unique_headings(self):
        root = _node("root", level=0, children=[
            _node("5.1 aa", level=2, blocks=[_cb("c1")]),
            _node("5.2 bb", level=2, blocks=[_cb("c2")]),
        ])
        _demote_recurring_headings(root)
        assert len(root["children"]) == 2

    def test_keeps_recurring_heading_with_children(self):
        # A heading that recurs but has children (real section) is preserved
        root = _node("root", level=0, children=[
            _node("chapter", level=1, children=[_node("5.1 x", level=2)]),
            _node("chapter", level=1, children=[_node("5.2 y", level=2)]),
            _node("chapter", level=1, children=[_node("5.3 z", level=2)]),
        ])
        _demote_recurring_headings(root)
        assert len(root["children"]) == 3  # all kept

    def test_demote_preserves_leaf_blocks_in_parent(self):
        """Regression: demoting a leaf recurring heading must not drop its blocks.

        Previously the demoted leaf was removed from children without moving
        its blocks anywhere, losing content entirely.
        """
        root = _node("root", level=0, children=[
            _node("7450 ESS, 7750 SR", level=1, blocks=[_cb("payload1")]),
            _node("7450 ESS, 7750 SR", level=1, blocks=[_cb("payload2")]),
            _node("7450 ESS, 7750 SR", level=1, blocks=[_cb("payload3")]),
        ])
        _demote_recurring_headings(root)
        # Headings removed from children
        assert root["children"] == []
        # But payloads (plus demoted title paragraphs) preserved in root blocks
        block_texts = [b.text for b in root["blocks"]]
        assert "payload1" in block_texts
        assert "payload2" in block_texts
        assert "payload3" in block_texts
        # Each demoted leaf also contributes its title as a paragraph
        assert sum(1 for t in block_texts if "7450 ESS" in t) == 3


# ---------------------------------------------------------------------------
# _postprocess_tree end-to-end
# ---------------------------------------------------------------------------

class TestPostprocessTreeEndToEnd:
    def _freeze_tree(self, node_dict):
        return SectionNode(
            title=node_dict["title"],
            level=node_dict["level"],
            blocks=tuple(node_dict["blocks"]),
            children=tuple(self._freeze_tree(c) for c in node_dict["children"]),
        )

    def test_three_passes_clean_up_real_world_pattern(self):
        """Simulates the cli_guide PDF pattern: cross-page + orphan + recurring."""
        tree_dict = _node("doc", level=0, children=[
            _node("5 a Commands", level=1, children=[
                # Empty numbered heading + orphan content (B)
                _node("5.1 aa-admit-deny", level=2),
                _node("aa-admit-deny", level=2, blocks=[_cb("intro")]),
                # Cross-page fragmentation (A)
                _node("5.4 aa-sub", level=2, blocks=[_cb("p1")]),
                _node("aa-sub", level=2, blocks=[_cb("p2")]),
                _node("aa-sub", level=2, blocks=[_cb("p3")]),
            ]),
            # Recurring false heading (C)
            _node("7450 ESS, 7750 SR", level=1),
            _node("7450 ESS, 7750 SR", level=1),
            _node("7450 ESS, 7750 SR", level=1),
        ])
        tree = self._freeze_tree(tree_dict)
        result = _postprocess_tree(tree)

        # C: platform headings demoted
        platform_headings = [c for c in result.children
                             if "7450" in (c.title or "")]
        assert platform_headings == []

        # Find the L1 "5 a Commands" section
        cmd_section = next(c for c in result.children if "Commands" in (c.title or ""))
        # B + A: 5.1 should have content, aa-sub siblings merged into 5.4
        titles = [c.title for c in cmd_section.children]
        assert "5.1 aa-admit-deny" in titles
        five_one = next(c for c in cmd_section.children if c.title == "5.1 aa-admit-deny")
        assert len(five_one.blocks) >= 1
        # 5.4 aa-sub: only one, with all content
        aa_subs = [c for c in cmd_section.children if "aa-sub" == _normalize_title(c.title)]
        assert len(aa_subs) == 1
        assert len(aa_subs[0].blocks) >= 3

    def test_postprocess_does_not_crash_on_empty_tree(self):
        empty = SectionNode(title=None, level=0)
        result = _postprocess_tree(empty)
        assert result.title is None
        assert result.children == ()
