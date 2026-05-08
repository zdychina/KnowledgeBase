"""Segmentation module: split SectionNode tree into L0 RawSegmentData (v0.5 fix).

Key fixes:
- structure_json preserves table columns/rows from ContentBlock.structure
- source_offsets_json includes parser, block_index, line_start, line_end
"""
from __future__ import annotations

from typing import Any

from knowledge_mining.mining.extractors import (
    DefaultRoleClassifier,
    EntityExtractor,
    NoOpEntityExtractor,
    RoleClassifier,
)
from knowledge_mining.mining.models import ContentBlock, DocumentProfile, RawSegmentData, SectionNode
from knowledge_mining.mining.text_utils import (
    content_hash,
    normalized_hash,
    token_count,
)

_SCHEMA_BLOCK_TYPES = {
    "paragraph",
    "table",
    "list",
    "code",
    "blockquote",
    "html_table",
    "raw_html",
    "unknown",
}

_SCHEMA_SEMANTIC_ROLES = {
    "concept",
    "parameter",
    "example",
    "note",
    "procedure_step",
    "troubleshooting_step",
    "constraint",
    "alarm",
    "checklist",
    "unknown",
}


def segment_document(
    doc_root: SectionNode,
    profile: DocumentProfile,
    *,
    role_classifier: RoleClassifier | None = None,
    entity_extractor: EntityExtractor | None = None,
    parser_name: str = "unknown",
) -> list[RawSegmentData]:
    """Split document section tree into raw segments."""
    classifier = role_classifier or DefaultRoleClassifier()
    extractor = entity_extractor or NoOpEntityExtractor()

    segments: list[RawSegmentData] = []
    _walk_sections(doc_root, profile.document_key, [], segments, classifier, extractor, parser_name)
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
    classifier: RoleClassifier,
    extractor: EntityExtractor,
    parser_name: str,
) -> None:
    """Recursively walk section tree, creating segments."""
    current_path = list(parent_path)
    if node.title:
        current_path.append({"title": node.title, "level": node.level})

    context: dict[str, Any] = {"section_path": current_path}
    current_group: list[ContentBlock] = []
    block_index = 0

    for block in node.blocks:
        if block.block_type in ("table", "html_table", "code", "list", "blockquote"):
            # Flush pending grouped blocks
            if current_group:
                segments.append(
                    _make_segment(
                        document_key, current_path, node, current_group,
                        block_index, classifier, extractor, context, parser_name,
                    )
                )
                block_index += 1
                current_group = []
            segments.append(
                _make_segment(
                    document_key, current_path, node, [block],
                    block_index, classifier, extractor, context, parser_name,
                )
            )
            block_index += 1
        else:
            current_group.append(block)

    if current_group:
        segments.append(
            _make_segment(
                document_key, current_path, node, current_group,
                block_index, classifier, extractor, context, parser_name,
            )
        )

    for child in node.children:
        _walk_sections(child, document_key, current_path, segments, classifier, extractor, parser_name)


def _make_segment(
    document_key: str,
    section_path: list[dict[str, Any]],
    section: SectionNode,
    blocks: list[ContentBlock],
    block_index: int,
    classifier: RoleClassifier,
    extractor: EntityExtractor,
    context: dict[str, Any],
    parser_name: str,
) -> RawSegmentData:
    """Create a RawSegmentData from a group of content blocks."""
    primary_block = next((b for b in blocks if b.block_type != "heading"), None)
    if primary_block is None:
        primary_block = blocks[0] if blocks else None
    block_type = _schema_block_type(primary_block.block_type if primary_block else "unknown")

    raw_text = "\n\n".join(b.text for b in blocks)
    norm_text = raw_text.lower().strip()

    semantic_role = _schema_semantic_role(classifier.classify(
        raw_text, section.title, block_type, context,
    ))

    structure_json = _extract_structure_info(blocks)

    entity_refs = extractor.extract(raw_text, {**context, "structure": structure_json})

    # Build source_offsets_json with line info from blocks
    line_start = None
    line_end = None
    for b in blocks:
        if b.line_start is not None:
            if line_start is None or b.line_start < line_start:
                line_start = b.line_start
        if b.line_end is not None:
            if line_end is None or b.line_end > line_end:
                line_end = b.line_end

    source_offsets: dict[str, Any] = {
        "parser": parser_name,
        "block_index": block_index,
    }
    if line_start is not None:
        source_offsets["line_start"] = line_start
    if line_end is not None:
        source_offsets["line_end"] = line_end

    return RawSegmentData(
        document_key=document_key,
        segment_index=0,
        block_type=block_type,
        semantic_role=semantic_role,
        section_path=section_path,
        section_title=section.title,
        raw_text=raw_text,
        normalized_text=norm_text,
        content_hash=content_hash(raw_text),
        normalized_hash=normalized_hash(raw_text),
        token_count=token_count(raw_text),
        structure_json=structure_json,
        source_offsets_json=source_offsets,
        entity_refs_json=entity_refs,
        metadata_json={},
    )


def _extract_structure_info(blocks: list[ContentBlock]) -> dict:
    """Extract structural metadata from blocks.

    For tables: use ContentBlock.structure if available (from parser),
    otherwise fall back to basic estimation.
    """
    info: dict = {}
    for block in blocks:
        if block.block_type == "table":
            if block.structure:
                # Use structured data from parser directly
                info.update(block.structure)
            else:
                # Fallback for tables without structure info
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
    """Map parser-internal block types to asset schema block_type values."""
    if block_type in _SCHEMA_BLOCK_TYPES:
        return block_type
    if block_type == "heading":
        return "paragraph"
    return "unknown"


def _schema_semantic_role(semantic_role: str) -> str:
    """Map classifier/plugin output to asset schema semantic_role values."""
    if semantic_role in _SCHEMA_SEMANTIC_ROLES:
        return semantic_role
    return "unknown"
