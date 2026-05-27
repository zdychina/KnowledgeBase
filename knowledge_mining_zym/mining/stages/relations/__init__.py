"""Relations stage: LLM-driven discourse relations (v1.2+).

build_seg_ids() assigns stable UUIDs consumed by downstream stages.
DiscourseRelationBuilder adds RST relations via LLM sliding-window analysis.
"""
from __future__ import annotations

import logging
import uuid
from typing import Any

from knowledge_mining_zym.mining.contracts.models import RawSegmentData, SegmentRelationData

logger = logging.getLogger(__name__)


def build_seg_ids(segments: list[RawSegmentData]) -> dict[str, str]:
    """Assign a stable UUID to each segment. Returns {segment_key: uuid_hex}."""
    return {_make_segment_key(seg): uuid.uuid4().hex for seg in segments}


def _make_segment_key(seg: RawSegmentData) -> str:
    return f"{seg.document_key}#{seg.segment_index}"


class DiscourseRelationBuilder:
    """LLM-driven discourse relation builder using RST analysis.

    Strategy (EVO-18 Method C):
    1. Pre-filter candidate pairs using structural relations (same_section, adjacent)
    2. Sliding window of 10-20 segments sent to LLM for batch analysis
    3. LLM outputs relation_type + confidence for each pair
    4. Results merged into the same asset_raw_segment_relations table
    """

    stage_name = "discourse_relations"
    stage_version = "1"

    _LLM_TO_DB_RELATION = {
        "ELABORATION": "elaborates",
        "SEQUENCE": "sequences",
        "CAUSATION": "causes",
        "EVIDENCE": "evidences",
        "BACKGROUND": "backgrounds",
        "EXEMPLIFICATION": "exemplifies",
        "CONTRAST": "contrasts_with",
        "CONCESSION": "concedes",
        "CONDITION": "conditions",
        "PURPOSE": "purposes",
    }
    _RST_WHITELIST = frozenset(_LLM_TO_DB_RELATION.values())
    _MIN_CONFIDENCE = 0.5

    def __init__(
        self,
        base_url: str = "http://localhost:8900",
        bypass_proxy: bool = False,
        window_size: int = 15,
    ) -> None:
        from knowledge_mining_zym.mining.infra.llm_client import LlmClient
        self._client = LlmClient(base_url=base_url, bypass_proxy=bypass_proxy)
        self._window_size = window_size

    def build(
        self,
        segments: list[RawSegmentData],
        *,
        seg_ids: dict[str, str] | None = None,
        **kwargs: Any,
    ) -> list[SegmentRelationData]:
        """Build discourse relations via LLM sliding window analysis."""
        if len(segments) < 2:
            return []

        content_segs = [s for s in segments if s.block_type != "heading"]
        if len(content_segs) < 2:
            return []

        all_relations: list[SegmentRelationData] = []

        for start in range(0, len(content_segs), self._window_size - 1):
            window = content_segs[start : start + self._window_size]
            if len(window) < 2:
                continue
            all_relations.extend(self._analyze_window(window))

        filtered = [
            r for r in all_relations
            if r.relation_type in self._RST_WHITELIST
            and (r.confidence is None or r.confidence >= self._MIN_CONFIDENCE)
        ]
        removed = len(all_relations) - len(filtered)
        if removed > 0:
            logger.info("RST whitelist: filtered %d/%d relations", removed, len(all_relations))

        return filtered

    def _analyze_window(self, segments: list[RawSegmentData]) -> list[SegmentRelationData]:
        seg_lines = []
        for i, seg in enumerate(segments):
            text_preview = seg.raw_text[:150].replace("\n", " ")
            title = seg.section_title or "无标题"
            seg_lines.append(f"[{i}] ({title}) {text_preview}")

        try:
            task_id = self._client.submit_task(
                template_key="mining-discourse-relation",
                input={"segments": "\n".join(seg_lines)},
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

            rst_label = str(relation).upper()
            if rst_label == "UNRELATED":
                continue
            db_relation = self._LLM_TO_DB_RELATION.get(rst_label)
            if db_relation is None:
                continue

            source_key = _make_segment_key(segments[source_idx])
            target_key = _make_segment_key(segments[target_idx])

            relations.append(SegmentRelationData(
                source_segment_key=source_key,
                target_segment_key=target_key,
                relation_type=db_relation,
                weight=confidence,
                confidence=confidence,
                distance=abs(source_idx - target_idx) if source_idx != target_idx else None,
                metadata_json={"source": "discourse_llm", "rst_relation": rst_label.lower()},
            ))

        return relations
