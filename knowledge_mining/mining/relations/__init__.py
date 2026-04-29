"""Relations stage: build structural + discourse segment relations for v1.1/v1.2.

v1.1 builds structural relations:
- previous/next: sequential ordering
- same_section: segments sharing a section
- section_header_of: heading -> content segments
- same_parent_section: siblings under the same parent

v1.2 adds discourse relations (LLM-driven RST analysis):
- Uses sliding window to analyze segment pairs
- Identifies rhetorical structure (ELABORATES, EVIDENCES, etc.)

v1.5 adds reference relations:
- references: TOC/anchor links -> referenced headings (from content_assessment.is_navigation)
"""
from __future__ import annotations

import json
import logging
import re
import uuid
from typing import Any

from knowledge_mining.mining.models import RawSegmentData, SegmentRelationData

logger = logging.getLogger(__name__)


class DefaultRelationBuilder:
    """Default relation builder wrapping build_relations() for PipelineConfig."""

    def build(
        self,
        segments: list[RawSegmentData],
        **kwargs: Any,
    ) -> tuple[list[SegmentRelationData], dict[str, str]]:
        return build_relations(
            segments,
            document_snapshot_id=kwargs.get("document_snapshot_id", ""),
            max_distance=kwargs.get("max_distance", 5),
        )


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

    # 5. Reference relations: TOC/anchor links -> referenced headings (v1.5)
    # Only for segments that LLM/enrichment assessed as navigation content
    for seg in segments:
        assessment = seg.metadata_json.get("content_assessment", {})
        if not assessment.get("is_navigation"):
            continue
        # Parse [text](#anchor) links from navigation segments
        link_texts = re.findall(r'\[([^\]]+)\]\(#[^)]+\)', seg.raw_text)
        for link_text in link_texts:
            target = _find_heading_by_title(segments, link_text)
            if target:
                relations.append(SegmentRelationData(
                    source_segment_key=_make_segment_key(seg),
                    target_segment_key=_make_segment_key(target),
                    relation_type="references",
                    metadata_json={"source": "toc_link", "link_text": link_text},
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


def _find_heading_by_title(
    segments: list[RawSegmentData], target_title: str,
) -> RawSegmentData | None:
    """Find a heading segment whose section_title matches the link text."""
    target_lower = target_title.lower().strip()
    for seg in segments:
        if seg.block_type == "heading" and seg.section_title:
            if seg.section_title.lower().strip() == target_lower:
                return seg
    # Fallback: partial match
    for seg in segments:
        if seg.block_type == "heading" and seg.section_title:
            if target_lower in seg.section_title.lower():
                return seg
    return None


class DiscourseRelationBuilder:
    """LLM-driven discourse relation builder using RST analysis.

    Strategy (EVO-18 Method C):
    1. Pre-filter candidate pairs using structural relations (same_section, adjacent)
    2. Sliding window of 10-20 segments sent to LLM for batch analysis
    3. LLM outputs relation_type + confidence for each pair
    4. Results merged into the same asset_raw_segment_relations table
    """

    def __init__(
        self,
        base_url: str = "http://localhost:8900",
        bypass_proxy: bool = False,
        window_size: int = 15,
    ) -> None:
        from knowledge_mining.mining.llm_client import LlmClient
        self._client = LlmClient(base_url=base_url, bypass_proxy=bypass_proxy)
        self._window_size = window_size

    def build(
        self,
        segments: list[RawSegmentData],
        *,
        seg_ids: dict[str, str] | None = None,
        **kwargs: Any,
    ) -> list[SegmentRelationData]:
        """Build discourse relations via LLM sliding window analysis.

        Returns list of additional SegmentRelationData to merge with structural relations.
        """
        if len(segments) < 2:
            return []

        # Filter out heading-only segments for analysis
        content_segs = [s for s in segments if s.block_type != "heading"]
        if len(content_segs) < 2:
            return []

        all_relations: list[SegmentRelationData] = []

        # Sliding window analysis
        for start in range(0, len(content_segs), self._window_size - 1):
            window = content_segs[start : start + self._window_size]
            if len(window) < 2:
                continue

            window_relations = self._analyze_window(window)
            all_relations.extend(window_relations)

        return all_relations

    def _analyze_window(self, segments: list[RawSegmentData]) -> list[SegmentRelationData]:
        """Send a window of segments to LLM for discourse analysis."""
        # Build numbered segment text for prompt
        seg_lines = []
        for i, seg in enumerate(segments):
            text_preview = seg.raw_text[:150].replace("\n", " ")
            title = seg.section_title or "无标题"
            seg_lines.append(f"[{i}] ({title}) {text_preview}")

        segments_text = "\n".join(seg_lines)

        try:
            task_id = self._client.submit_task(
                template_key="mining-discourse-relation",
                input={"segments": segments_text},
                caller_domain="mining",
                pipeline_stage="discourse_relations",
                expected_output_type="json_array",
            )
            if task_id is None:
                return []

            items = self._client.poll_all({"0": task_id})
            items = items.get("0")
            if items is None:
                return []

            return self._parse_llm_results(items, segments)

        except Exception as e:
            logger.warning("Discourse analysis failed: %s", e)
            return []

    def _parse_llm_results(
        self, items: list[dict], segments: list[RawSegmentData],
    ) -> list[SegmentRelationData]:
        """Parse LLM output into SegmentRelationData."""
        relations: list[SegmentRelationData] = []
        for item in items:
            source_idx = item.get("source")
            target_idx = item.get("target")
            relation = item.get("relation", "other")
            confidence = float(item.get("confidence", 0.5))

            if source_idx is None or target_idx is None:
                continue
            if source_idx >= len(segments) or target_idx >= len(segments):
                continue
            if relation == "UNRELATED":
                continue

            source_seg = segments[source_idx]
            target_seg = segments[target_idx]
            source_key = _make_segment_key(source_seg)
            target_key = _make_segment_key(target_seg)

            relations.append(SegmentRelationData(
                source_segment_key=source_key,
                target_segment_key=target_key,
                relation_type=relation.lower(),
                weight=confidence,
                confidence=confidence,
                distance=abs(source_idx - target_idx) if source_idx != target_idx else None,
                metadata_json={"source": "discourse_llm", "rst_relation": relation.lower()},
            ))

        return relations
