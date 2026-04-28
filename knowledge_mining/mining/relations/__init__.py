"""Relations stage: build structural segment relations for v1.1.

v1.1 builds structural relations:
- previous/next: sequential ordering
- same_section: segments sharing a section
- section_header_of: heading -> content segments
- same_parent_section: siblings under the same parent

v1.2 will add semantic relations (LLM-driven) to the same table.
"""
from __future__ import annotations

import uuid
from typing import Any

from knowledge_mining.mining.models import RawSegmentData, SegmentRelationData


def build_relations(
    segments: list[RawSegmentData],
    *,
    document_snapshot_id: str = "",
    max_distance: int = 5,
) -> tuple[list[SegmentRelationData], dict[str, str]]:
    """Build structural relations from ordered segments.

    Args:
        segments: Ordered list of segments.
        document_snapshot_id: Snapshot ID for relation context.
        max_distance: Maximum index distance for same_section relations (default 5).

    Returns (relations, segment_key_to_id_map) where the map is
    segment_key -> generated segment_id (for downstream DB writes).
    """
    if not segments:
        return [], {}

    # Assign stable IDs
    seg_ids: dict[str, str] = {}
    for seg in segments:
        # Use content_hash + index as a stable key; real ID is UUID
        seg_id = uuid.uuid4().hex
        seg_key = _make_segment_key(seg)
        seg_ids[seg_key] = seg_id

    relations: list[SegmentRelationData] = []

    # Group segments by section_path for same_section relations
    sections: dict[str, list[str]] = {}  # section_path_key -> [seg_keys]
    parent_sections: dict[str, list[str]] = {}  # parent_path_key -> [seg_keys]
    heading_by_path: dict[str, str] = {}  # section_path_key -> heading seg_key

    for seg in segments:
        seg_key = _make_segment_key(seg)
        path_key = _path_key(seg.section_path)
        parent_key = _parent_path_key(seg.section_path)

        if path_key not in sections:
            sections[path_key] = []
        sections[path_key].append(seg_key)

        if parent_key not in parent_sections:
            parent_sections[parent_key] = []
        parent_sections[parent_key].append(seg_key)

        if seg.block_type == "heading":
            heading_by_path[path_key] = seg_key

    # 1. previous/next relations (sequential)
    for i in range(len(segments) - 1):
        cur_key = _make_segment_key(segments[i])
        nxt_key = _make_segment_key(segments[i + 1])
        relations.append(SegmentRelationData(
            source_segment_key=cur_key,
            target_segment_key=nxt_key,
            relation_type="previous",
            distance=1,
        ))
        relations.append(SegmentRelationData(
            source_segment_key=nxt_key,
            target_segment_key=cur_key,
            relation_type="next",
            distance=1,
        ))

    # 2. same_section relations (v1.2: capped by max_distance to avoid O(n^2))
    for path_key, seg_keys in sections.items():
        for i in range(len(seg_keys)):
            for j in range(i + 1, min(i + max_distance + 1, len(seg_keys))):
                relations.append(SegmentRelationData(
                    source_segment_key=seg_keys[i],
                    target_segment_key=seg_keys[j],
                    relation_type="same_section",
                    distance=abs(i - j),
                ))

    # 3. section_header_of: heading -> content in same section
    for path_key, heading_key in heading_by_path.items():
        for seg_key in sections.get(path_key, []):
            if seg_key != heading_key:
                relations.append(SegmentRelationData(
                    source_segment_key=heading_key,
                    target_segment_key=seg_key,
                    relation_type="section_header_of",
                ))

    # 4. same_parent_section
    for parent_key, seg_keys in parent_sections.items():
        if len(seg_keys) > 2:  # Only worth it for larger groups
            for i in range(len(seg_keys)):
                for j in range(i + 1, len(seg_keys)):
                    relations.append(SegmentRelationData(
                        source_segment_key=seg_keys[i],
                        target_segment_key=seg_keys[j],
                        relation_type="same_parent_section",
                    ))

    return relations, seg_ids


def _make_segment_key(seg: RawSegmentData) -> str:
    """Create a unique key for a segment within a document."""
    return f"{seg.document_key}#{seg.segment_index}"


def _path_key(section_path: list[dict[str, Any]]) -> str:
    """Create a hashable key from section_path."""
    if not section_path:
        return "__root__"
    return "/".join(
        f"L{p.get('level', 0)}:{p.get('title', '')}" for p in section_path
    )


def _parent_path_key(section_path: list[dict[str, Any]]) -> str:
    """Create key for parent section (section_path minus last element)."""
    if len(section_path) <= 1:
        return "__root__"
    return _path_key(section_path[:-1])
