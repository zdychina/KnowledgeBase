"""Relations stage: LLM-driven discourse relations (v1.2+).

build_seg_ids() assigns stable UUIDs consumed by downstream stages.
DiscourseRelationBuilder adds RST relations via LLM sliding-window analysis.
"""
from __future__ import annotations

import logging
import uuid
from typing import Any, TYPE_CHECKING

from knowledge_mining.mining.contracts.models import RawSegmentData, SegmentRelationData
from knowledge_mining.mining.contracts.rst_relations import (
    LLM_TO_DB_RELATION,
    MONO_POST,
    MONO_PREV,
    MULTINUCLEAR,
    RST_DB_VALUES,
    RST_NUCLEARITY,
)

if TYPE_CHECKING:
    from knowledge_mining.mining.infra.domain_pack import DomainProfile

logger = logging.getLogger(__name__)


def build_seg_ids(segments: list[RawSegmentData]) -> dict[str, str]:
    """Assign a stable UUID to each segment. Returns {segment_key: uuid_hex}."""
    return {_make_segment_key(seg): uuid.uuid4().hex for seg in segments}


def _make_segment_key(seg: RawSegmentData) -> str:
    return f"{seg.document_key}#{seg.segment_index}"


def _segment_index_of(seg_key: str) -> int:
    """Recover segment_index from a '{document_key}#{segment_index}' key."""
    return int(seg_key.rsplit("#", 1)[-1])


def infer_discourse_roles(
    segments: list[RawSegmentData],
    relations: list[SegmentRelationData],
) -> dict[str, str]:
    """Derive each segment's discourse role from RST relations.

    Returns {segment_key: 'nucleus' | 'satellite' | 'standalone'}.
    Aggregation: a segment that is a nucleus in ANY relation is 'nucleus';
    otherwise 'satellite' if it appears as a satellite; 'standalone' if it never
    participates in an RST relation. Direction is resolved by segment order, not
    the LLM source/target labels.
    """
    roles: dict[str, str] = {_make_segment_key(seg): "standalone" for seg in segments}

    for rel in relations:
        nuc = RST_NUCLEARITY.get(rel.relation_type)
        if nuc is None:
            continue  # structural edges (previous/next/...) carry no discourse role
        src, tgt = rel.source_segment_key, rel.target_segment_key
        if src not in roles or tgt not in roles:
            continue

        if nuc == MULTINUCLEAR:
            nucleus_keys: tuple[str, ...] = (src, tgt)
            satellite_keys: tuple[str, ...] = ()
        else:
            earlier, later = (
                (src, tgt) if _segment_index_of(src) <= _segment_index_of(tgt) else (tgt, src)
            )
            if nuc == MONO_PREV:
                nucleus_keys, satellite_keys = (earlier,), (later,)
            else:  # MONO_POST
                nucleus_keys, satellite_keys = (later,), (earlier,)

        for k in nucleus_keys:
            roles[k] = "nucleus"
        for k in satellite_keys:
            if roles[k] != "nucleus":
                roles[k] = "satellite"

    return roles


class DiscourseRelationBuilder:
    """LLM-driven discourse relation builder using RST analysis.

    Strategy (EVO-18 Method C):
    1. Filter out heading-only segments
    2. Sliding window of N segments sent to LLM for batch analysis
    3. LLM outputs relation_type + confidence for each pair
    4. Results filtered by RST whitelist and min_confidence threshold
    """

    stage_name = "discourse_relations"
    stage_version = "1"

    _LLM_TO_DB_RELATION = LLM_TO_DB_RELATION
    _RST_WHITELIST = RST_DB_VALUES

    def __init__(
        self,
        base_url: str = "http://localhost:8900",
        window_size: int | None = None,
        knowledge_domain: str | None = None,
        profile: "DomainProfile | None" = None,
    ) -> None:
        from knowledge_mining.mining.infra.llm_client import LlmClient
        self._client = LlmClient(base_url=base_url)
        self._knowledge_domain = knowledge_domain
        # Read thresholds from profile when available, else use constructor arg or default
        rp = profile.retrieval_policy if profile else None
        self._window_size = (
            window_size if window_size is not None
            else (rp.discourse_window_size if rp else 15)
        )
        self._min_confidence = rp.min_confidence if rp else 0.5
        self._max_distance = rp.max_distance if rp else 5

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
            and (r.confidence is None or r.confidence >= self._min_confidence)
        ]
        removed = len(all_relations) - len(filtered)
        if removed > 0:
            logger.info("RST whitelist: filtered %d/%d relations", removed, len(all_relations))

        # Deduplicate by (source, target, relation_type) — keep highest confidence
        seen: dict[tuple[str, str, str], SegmentRelationData] = {}
        for r in filtered:
            key = (r.source_segment_key, r.target_segment_key, r.relation_type)
            existing = seen.get(key)
            if existing is None or (r.confidence is not None and (existing.confidence is None or r.confidence > existing.confidence)):
                seen[key] = r
        deduped = list(seen.values())
        if len(deduped) < len(filtered):
            logger.info("RST dedup: removed %d duplicate relations", len(filtered) - len(deduped))

        return deduped

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
                knowledge_domain=self._knowledge_domain,
                pipeline_stage="discourse_relations",
                expected_output_type="json_object",
            )
            if task_id is None:
                return []

            items = self._client.poll_all({"0": task_id})
            items = items.get("0")
            if items is None:
                return []

            # Unwrap {"relations": [...]} wrapper (llm_client wraps dict into [dict])
            if items and isinstance(items[0], dict) and "relations" in items[0]:
                items = items[0]["relations"]

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
