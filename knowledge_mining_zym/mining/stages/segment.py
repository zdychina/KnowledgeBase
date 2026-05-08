"""Segmentation module: split SectionNode tree into L0 RawSegmentData.

v1.1 key points:
- Headings become independent segments (block_type='heading') for section_header_of relations
- structure_json preserves table columns/rows from ContentBlock.structure
- source_offsets_json includes parser, block_index, line_start, line_end
- Entity extraction and role classification are NOT done here — deferred to enrich stage

v1.2 key points:
- Pluggable paragraph grouping: structural splitting (headings/tables/code/list) stays
  rule-based and deterministic; only the boundaries inside a run of consecutive
  paragraph blocks can be delegated to an LLM via LlmSegmenter.
- DefaultSegmenter keeps the v1.1 behavior (each paragraph run = single segment).
"""
from __future__ import annotations

import logging
from typing import Any, Callable, List, Optional, Tuple

from knowledge_mining_zym.mining.contracts.models import ContentBlock, DocumentProfile, RawSegmentData, SectionNode
from knowledge_mining_zym.mining.infra.hash_utils import content_hash, normalized_hash
from knowledge_mining_zym.mining.infra.text_utils import token_count

logger = logging.getLogger(__name__)

# A grouper takes a list of consecutive paragraph blocks and the section title,
# and returns a list of [start_idx, end_idx] inclusive groups that fully cover
# range(0, len(blocks)). Returning None signals "fall back to default (one group)".
ParagraphGrouper = Callable[[List[ContentBlock], Optional[str]], Optional[List[Tuple[int, int]]]]


def _default_paragraph_grouper(
    blocks: list[ContentBlock], section_title: str | None,
) -> list[tuple[int, int]]:
    """Default grouper: keep all paragraph blocks as a single segment."""
    return [(0, len(blocks) - 1)] if blocks else []


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


def segment_document(
    doc_root: SectionNode,
    profile: DocumentProfile,
    *,
    parser_name: str = "unknown",
    paragraph_grouper: ParagraphGrouper | None = None,
) -> list[RawSegmentData]:
    """Split document section tree into raw segments.

    v1.1: Headings are emitted as independent segments (block_type='heading')
    so that section_header_of relations can be built in the relations stage.

    Entity extraction and role classification are deferred to the enrich stage.
    Segments are produced with default semantic_role="unknown" and empty entity_refs_json.

    v1.2: paragraph_grouper allows pluggable boundary decisions inside a run of
    consecutive paragraph blocks. Default keeps the v1.1 behavior (one run = one segment).
    """
    grouper = paragraph_grouper or _default_paragraph_grouper
    segments: list[RawSegmentData] = []
    _walk_sections(doc_root, profile.document_key, [], segments, parser_name, grouper)
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
    grouper: ParagraphGrouper,
) -> None:
    """Recursively walk section tree, creating segments."""
    current_path = list(parent_path)
    if node.title and node.level > 0:
        current_path.append({"title": node.title, "level": node.level})

    current_group: list[ContentBlock] = []
    block_index = 0

    def flush_paragraphs(start_index: int) -> int:
        """Flush accumulated paragraph blocks via the grouper. Returns new block_index."""
        if not current_group:
            return start_index
        groups = _safe_group(grouper, current_group, node.title)
        idx = start_index
        for start, end in groups:
            blocks_for_seg = current_group[start:end + 1]
            segments.append(
                _make_segment(
                    document_key, current_path, node, blocks_for_seg,
                    idx, parser_name,
                )
            )
            idx += 1
        current_group.clear()
        return idx

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
            block_index = flush_paragraphs(block_index)
            segments.append(
                _make_heading_segment(document_key, current_path, block, block_index, parser_name)
            )
            block_index += 1
        elif block.block_type in ("table", "html_table", "code", "list", "blockquote"):
            block_index = flush_paragraphs(block_index)
            segments.append(
                _make_segment(
                    document_key, current_path, node, [block],
                    block_index, parser_name,
                )
            )
            block_index += 1
        else:
            current_group.append(block)

    flush_paragraphs(block_index)

    for child in node.children:
        _walk_sections(child, document_key, current_path, segments, parser_name, grouper)


def _safe_group(
    grouper: ParagraphGrouper,
    blocks: list[ContentBlock],
    section_title: str | None,
) -> list[tuple[int, int]]:
    """Invoke grouper, validate output, fall back to single-group on any issue."""
    n = len(blocks)
    if n <= 1:
        return [(0, 0)] if n == 1 else []
    try:
        result = grouper(blocks, section_title)
    except Exception as e:
        logger.warning("paragraph grouper raised, falling back: %s", e)
        return [(0, n - 1)]
    if not _validate_groups(result, n):
        return [(0, n - 1)]
    return [tuple(g) for g in result]  # type: ignore[misc]


def _validate_groups(groups: Any, n: int) -> bool:
    """Validate that groups fully cover range(0, n) without overlap or gaps."""
    if not isinstance(groups, list) or not groups:
        return False
    expected_start = 0
    for g in groups:
        if not isinstance(g, (list, tuple)) or len(g) != 2:
            return False
        start, end = g
        if not isinstance(start, int) or not isinstance(end, int):
            return False
        if start != expected_start or end < start or end >= n:
            return False
        expected_start = end + 1
    return expected_start == n


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


# ---------------------------------------------------------------------------
# v1.2: LLM-driven paragraph boundary segmentation
# ---------------------------------------------------------------------------

# Max preview chars sent to the LLM per paragraph block (avoid blowing token budget).
_PARAGRAPH_PREVIEW_CHARS = 240


class LlmSegmenter:
    """v1.2: LLM-first paragraph boundary segmenter with rule-based fallback.

    Structural splitting (headings, tables, code, lists, blockquotes) stays
    deterministic and identical to DefaultSegmenter. Only the boundaries inside
    a run of consecutive paragraph blocks are decided by the LLM.

    On any LLM failure (unreachable, malformed output, invalid grouping), the
    grouper falls back to "merge all paragraphs in the run as one segment",
    matching DefaultSegmenter's v1.1 behavior.
    """

    stage_name = "segment"
    stage_version = "2"

    def __init__(
        self,
        *,
        base_url: str = "http://localhost:8900",
        bypass_proxy: bool = False,
        min_paragraph_count_for_llm: int = 2,
        client: Any | None = None,
    ) -> None:
        if client is None:
            from knowledge_mining_zym.mining.infra.llm_client import LlmClient
            client = LlmClient(base_url=base_url, bypass_proxy=bypass_proxy)
        self._client = client
        self._min_paragraphs = max(2, min_paragraph_count_for_llm)

    def segment(
        self,
        tree: SectionNode,
        profile: DocumentProfile,
        **kwargs: Any,
    ) -> list[RawSegmentData]:
        return segment_document(
            tree, profile,
            parser_name=kwargs.get("parser_name", "unknown"),
            paragraph_grouper=self._llm_grouper,
        )

    def _llm_grouper(
        self,
        blocks: list[ContentBlock],
        section_title: str | None,
    ) -> list[tuple[int, int]] | None:
        """Ask the LLM how to group a paragraph run. Returns None on any failure."""
        n = len(blocks)
        if n < self._min_paragraphs:
            return None  # let _safe_group fall back to default single-group
        paragraphs_payload = [
            {"index": i, "preview": (b.text or "")[:_PARAGRAPH_PREVIEW_CHARS]}
            for i, b in enumerate(blocks)
        ]
        try:
            task_id = self._client.submit_task(
                template_key="mining-segment-boundary",
                input={
                    "section_title": section_title or "",
                    "paragraphs": paragraphs_payload,
                },
                caller_domain="mining",
                pipeline_stage="segment",
                expected_output_type="json_object",
            )
            if not task_id:
                return None
            result = self._client.poll_result(task_id)
        except Exception as e:
            logger.warning("LlmSegmenter LLM call raised: %s", e)
            return None
        if not result:
            return None
        # poll_result returns list[dict]; we expect a single object with "groups"
        first = result[0] if isinstance(result, list) and result else None
        if not isinstance(first, dict):
            return None
        groups = first.get("groups")
        if not isinstance(groups, list):
            return None
        # Convert and let _safe_group validate
        normalized: list[tuple[int, int]] = []
        for g in groups:
            if isinstance(g, (list, tuple)) and len(g) == 2:
                normalized.append((g[0], g[1]))
            else:
                return None
        return normalized
