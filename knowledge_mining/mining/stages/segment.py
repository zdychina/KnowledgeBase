"""Segmentation module: split SectionNode tree into L0 RawSegmentData.

v1.2 key points:
- Heading text is propagated via section_title on content segments (no independent heading segments)
- Structural relations are built in relations stage from section_path hierarchy
- structure_json preserves table columns/rows from ContentBlock.structure
- source_offsets_json includes parser, block_index, line_start, line_end
- Entity extraction and role classification are NOT done here — deferred to enrich stage
- Post-processing merges small segments (<100 tokens) with adjacent intro+list/table pairs (Unstructured CompositeElement)
"""
from __future__ import annotations

from typing import Any

from knowledge_mining.mining.contracts.models import ContentBlock, DocumentProfile, RawSegmentData, SectionNode
from knowledge_mining.mining.infra.hash_utils import content_hash, normalized_hash
from knowledge_mining.mining.infra.text_utils import token_count


class DefaultSegmenter:
    """Default segmenter wrapping segment_document() for PipelineConfig."""

    stage_name = "segment"
    stage_version = "1"

    def segment(
        self,
        tree: SectionNode,
        profile: DocumentProfile,
        **kwargs: Any,
    ) -> list[RawSegmentData]:
        return segment_document(
            tree, profile,
            parser_name=kwargs.get("parser_name", "unknown"),
        )

_SCHEMA_BLOCK_TYPES = {
    "paragraph", "table", "list", "code", "blockquote",
    "html_table", "raw_html", "unknown",
}

# Merge thresholds — module-level named constants for discoverability
_MERGE_MAX_TOKENS = 512
_TABLE_MIN_INDEPENDENT_TOKENS = 300

# Block type priority for merged segments (higher = dominant)
_BLOCK_TYPE_PRIORITY: dict[str, int] = {
    "table": 4, "html_table": 4,
    "list": 3,
    "code": 2,
    "blockquote": 1,
    "paragraph": 1,
    "raw_html": 1,
    "unknown": 0,
}


def segment_document(
    doc_root: SectionNode,
    profile: DocumentProfile,
    *,
    parser_name: str = "unknown",
) -> list[RawSegmentData]:
    """Split document section tree into raw segments.

    v1.1: Headings are emitted as independent segments (block_type='heading')
    so that section_header_of relations can be built in the relations stage.

    Entity extraction and role classification are deferred to the enrich stage.
    Segments are produced with default semantic_role="unknown" and empty entity_refs_json.
    """
    segments: list[RawSegmentData] = []
    _walk_sections(doc_root, profile.document_key, [], segments, parser_name)
    segments = _merge_small_segments(segments, min_tokens=100)
    return [
        RawSegmentData(
            document_key=s.document_key,
            segment_index=idx,
            block_type=s.block_type,
            semantic_role=s.semantic_role,
            section_path=s.section_path,
            section_title=s.section_title,
            raw_text=s.raw_text,
            normalized_text=s.normalized_text,
            content_hash=s.content_hash,
            normalized_hash=s.normalized_hash,
            token_count=s.token_count,
            structure_json=s.structure_json,
            source_offsets_json=s.source_offsets_json,
            entity_refs_json=s.entity_refs_json,
            metadata_json=s.metadata_json,
        )
        for idx, s in enumerate(segments)
    ]


def _walk_sections(
    node: SectionNode,
    document_key: str,
    parent_path: list[dict[str, Any]],
    segments: list[RawSegmentData],
    parser_name: str,
) -> None:
    """Recursively walk section tree, creating segments."""
    current_path = list(parent_path)
    if node.title and node.level > 0:
        current_path.append({"title": node.title, "level": node.level})

    current_group: list[ContentBlock] = []
    block_index = 0

    for block in node.blocks:
        if block.block_type == "heading":
            # Flush current group before starting new section
            if current_group:
                segments.append(
                    _make_segment(
                        document_key, current_path, node, current_group,
                        block_index, parser_name,
                    )
                )
                block_index += 1
                current_group = []
            # Heading text is NOT emitted as a separate segment;
            # it will appear as section_title on subsequent content segments.
        elif block.block_type in ("table", "html_table", "code", "list", "blockquote"):
            if current_group:
                segments.append(
                    _make_segment(
                        document_key, current_path, node, current_group,
                        block_index, parser_name,
                    )
                )
                block_index += 1
                current_group = []
            segments.append(
                _make_segment(
                    document_key, current_path, node, [block],
                    block_index, parser_name,
                )
            )
            block_index += 1
        else:
            current_group.append(block)

    if current_group:
        segments.append(
            _make_segment(
                document_key, current_path, node, current_group,
                block_index, parser_name,
            )
        )

    for child in node.children:
        _walk_sections(child, document_key, current_path, segments, parser_name)


def _merge_small_segments(
    segments: list[RawSegmentData],
    min_tokens: int = 100,
) -> list[RawSegmentData]:
    """Merge small segments into adjacent segments (Unstructured.io CompositeElement pattern).

    Rules:
    1. Segments < min_tokens are candidates for merging
    2. A short paragraph can merge with the following list/table in the same section
       (intro paragraph + content list/table → single composite segment)
    3. A short segment can also merge into the previous segment in the same section
    4. Merged result must not exceed 512 tokens
    5. Block type priority: table > list > paragraph
    6. Tables > 300 tokens stay independent
    """
    if not segments:
        return segments

    merged: list[RawSegmentData] = [segments[0]]

    for seg in segments[1:]:
        prev = merged[-1]
        same_section = seg.section_path == prev.section_path

        if not same_section:
            merged.append(seg)
            continue

        # Guard against None token_count — treat as 0 (very short, mergeable)
        prev_tc = prev.token_count if prev.token_count is not None else 0
        seg_tc = seg.token_count if seg.token_count is not None else 0

        # Try merge: short prev-paragraph + current list/table (intro→content pattern)
        intro_merge = (
            prev.block_type == "paragraph"
            and prev_tc < min_tokens
            and seg.block_type in ("list", "table", "html_table")
            and (prev_tc + seg_tc) <= _MERGE_MAX_TOKENS
            and not (seg.block_type in ("table", "html_table") and seg_tc > _TABLE_MIN_INDEPENDENT_TOKENS)
        )

        # Try merge: short current segment into previous (paragraph/list only, never merge tables/code backward)
        backward_merge = (
            seg_tc < min_tokens
            and seg.block_type not in ("table", "html_table", "code")
            and (prev_tc + seg_tc) <= _MERGE_MAX_TOKENS
            and prev.block_type not in ("table", "html_table", "code")
        )

        if intro_merge or backward_merge:
            new_text = prev.raw_text + "\n\n" + seg.raw_text
            # Block type priority: table > list > paragraph
            new_block_type = _pick_block_type(prev.block_type, seg.block_type)
            # Structure: merge both
            new_structure = {**(prev.structure_json or {}), **(seg.structure_json or {})}
            merged[-1] = RawSegmentData(
                document_key=prev.document_key,
                segment_index=0,  # re-indexed later
                block_type=new_block_type,
                semantic_role=prev.semantic_role,
                section_path=prev.section_path,
                section_title=prev.section_title,
                raw_text=new_text,
                normalized_text=new_text.lower().strip(),
                content_hash=content_hash(new_text),
                normalized_hash=normalized_hash(new_text),
                token_count=token_count(new_text),
                structure_json=new_structure,
                source_offsets_json=prev.source_offsets_json,
                entity_refs_json=prev.entity_refs_json,
                metadata_json=prev.metadata_json,
            )
        else:
            merged.append(seg)

    return merged


def _pick_block_type(a: str, b: str) -> str:
    """Pick dominant block type using _BLOCK_TYPE_PRIORITY."""
    pa = _BLOCK_TYPE_PRIORITY.get(a, 0)
    pb = _BLOCK_TYPE_PRIORITY.get(b, 0)
    return a if pa >= pb else b


def _make_segment(
    document_key: str,
    section_path: list[dict[str, Any]],
    section: SectionNode,
    blocks: list[ContentBlock],
    block_index: int,
    parser_name: str,
) -> RawSegmentData:
    """Create a RawSegmentData from a group of content blocks.

    semantic_role defaults to "unknown" — enrich stage will assign the real role.
    entity_refs_json defaults to [] — enrich stage will populate.
    """
    primary_block = next((b for b in blocks if b.block_type != "heading"), None)
    if primary_block is None:
        primary_block = blocks[0] if blocks else None
    block_type = _schema_block_type(primary_block.block_type if primary_block else "unknown")

    raw_text = "\n\n".join(b.text for b in blocks)
    norm_text = raw_text.lower().strip()

    structure_json = _extract_structure_info(blocks)

    line_start = None
    line_end = None
    for b in blocks:
        if b.line_start is not None:
            if line_start is None or b.line_start < line_start:
                line_start = b.line_start
        if b.line_end is not None:
            if line_end is None or b.line_end > line_end:
                line_end = b.line_end

    source_offsets: dict[str, Any] = {"parser": parser_name, "block_index": block_index}
    if line_start is not None:
        source_offsets["line_start"] = line_start
    if line_end is not None:
        source_offsets["line_end"] = line_end

    return RawSegmentData(
        document_key=document_key,
        segment_index=0,
        block_type=block_type,
        semantic_role="unknown",
        section_path=section_path,
        section_title=section.title,
        raw_text=raw_text,
        normalized_text=norm_text,
        content_hash=content_hash(raw_text),
        normalized_hash=normalized_hash(raw_text),
        token_count=token_count(raw_text),
        structure_json=structure_json,
        source_offsets_json=source_offsets,
        entity_refs_json=[],
        metadata_json={},
    )


def _extract_structure_info(blocks: list[ContentBlock]) -> dict:
    """Extract structural metadata from blocks."""
    info: dict = {}
    for block in blocks:
        if block.block_type == "table":
            if block.structure:
                info.update(block.structure)
            else:
                parts = block.text.split(" | ")
                info["col_count"] = len(parts)
        elif block.block_type == "html_table":
            info["kind"] = "html_table"
            info["raw_html_preserved"] = True
            info["row_count"] = max(1, block.text.lower().count("<tr"))
            info["col_count"] = max(1, block.text.lower().count("<td") // max(1, block.text.lower().count("<tr")))
        elif block.block_type == "code":
            if block.structure:
                info.update(block.structure)
            elif block.language:
                info["kind"] = "code_block"
                info["language"] = block.language
        elif block.block_type == "list":
            if block.structure:
                info.update(block.structure)
            else:
                items = block.text.split("; ")
                info["ordered"] = False
                info["items"] = items
                info["item_count"] = len(items)
        elif block.block_type == "paragraph":
            info["paragraph_count"] = info.get("paragraph_count", 0) + 1
    return info


def _schema_block_type(block_type: str) -> str:
    if block_type in _SCHEMA_BLOCK_TYPES:
        return block_type
    return "unknown"
