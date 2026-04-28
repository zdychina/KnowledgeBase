"""Segmentation module: split SectionNode tree into L0 RawSegmentData.

v1.1 key points:
- Headings become independent segments (block_type='heading') for section_header_of relations
- structure_json preserves table columns/rows from ContentBlock.structure
- source_offsets_json includes parser, block_index, line_start, line_end
- Entity extraction and role classification are NOT done here — deferred to enrich stage
"""
from __future__ import annotations

from typing import Any

from knowledge_mining.mining.models import ContentBlock, DocumentProfile, RawSegmentData, SectionNode
from knowledge_mining.mining.hash_utils import content_hash, normalized_hash
from knowledge_mining.mining.text_utils import token_count

_SCHEMA_BLOCK_TYPES = {
    "paragraph", "table", "list", "code", "blockquote",
    "html_table", "raw_html", "unknown",
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

    # Emit section title as an independent heading segment
    if node.title and node.level and node.level > 0:
        heading_block = ContentBlock(
            block_type="heading", text=node.title, level=node.level,
        )
        segments.append(
            _make_heading_segment(document_key, current_path, heading_block, block_index, parser_name)
        )
        block_index += 1

    for block in node.blocks:
        if block.block_type == "heading":
            # v1.1: heading as independent segment
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
                _make_heading_segment(document_key, current_path, block, block_index, parser_name)
            )
            block_index += 1
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


def _make_heading_segment(
    document_key: str,
    section_path: list[dict[str, Any]],
    block: ContentBlock,
    block_index: int,
    parser_name: str,
) -> RawSegmentData:
    """Create an independent heading segment for section_header_of relations."""
    raw = block.text
    offsets: dict[str, Any] = {"parser": parser_name, "block_index": block_index}
    if block.line_start is not None:
        offsets["line_start"] = block.line_start
    if block.line_end is not None:
        offsets["line_end"] = block.line_end

    return RawSegmentData(
        document_key=document_key,
        segment_index=0,
        block_type="heading",
        semantic_role="unknown",
        section_path=section_path,
        section_title=raw,
        raw_text=raw,
        normalized_text=raw.lower().strip(),
        content_hash=content_hash(raw),
        normalized_hash=normalized_hash(raw),
        token_count=token_count(raw),
        structure_json={},
        source_offsets_json=offsets,
        entity_refs_json=[],
        metadata_json={"heading_level": block.level},
    )


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
