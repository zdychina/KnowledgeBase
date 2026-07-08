"""Enrich stage: LLM-driven segment understanding (篇章本职).

LlmEnricher submits segments to llm_service for:
- Semantic role classification
- Content quality assessment (is_substantive, is_navigation)

实体抽取已拆出到独立的 entity_extract 阶段（L4 §15）；本阶段只管段落理解，
不再读本体类型、不再产实体 / 逃生口。
"""
from __future__ import annotations

import logging
from typing import Any, TYPE_CHECKING

from knowledge_mining.mining.contracts.models import RawSegmentData

if TYPE_CHECKING:
    from knowledge_mining.mining.infra.domain_pack import DomainProfile

logger = logging.getLogger(__name__)


class LlmEnricher:
    """LLM-backed enrichment via llm_service HTTP API.

    Submits segments for LLM understanding. Segments without a successful LLM
    result are returned unchanged.
    """

    stage_name = "enrich"
    stage_version = "3"

    def __init__(
        self,
        *,
        base_url: str = "http://localhost:8900",
        profile: "DomainProfile | None" = None,
        knowledge_domain: str | None = None,
    ) -> None:
        from knowledge_mining.mining.infra.llm_client import LlmClient
        self._client = LlmClient(base_url=base_url)
        self._profile = profile
        self._knowledge_domain = knowledge_domain or (profile.domain_id if profile else None)

    def enrich(
        self,
        segments: list[RawSegmentData],
        **kwargs: Any,
    ) -> list[RawSegmentData]:
        return self.enrich_batch(segments, **kwargs)

    def enrich_batch(
        self,
        segments: list[RawSegmentData],
        **kwargs: Any,
    ) -> list[RawSegmentData]:
        """Batch enrichment via LLM. Returns original segment when LLM unavailable."""
        if not segments:
            return []

        profile = self._profile
        # Use domain-specific semantic_roles when available; empty set means no filtering
        valid_roles = profile.semantic_roles if profile and profile.semantic_roles else None
        min_enrich_tokens = (
            profile.retrieval_policy.min_enrich_tokens
            if profile and hasattr(profile, "retrieval_policy")
            else 30
        )

        # Phase 0: Split into tiny (skip LLM) and substantial (send to LLM)
        tiny_indices: set[int] = set()
        for idx, seg in enumerate(segments):
            tc = seg.token_count if seg.token_count is not None else 0
            if tc < min_enrich_tokens:
                tiny_indices.add(idx)

        substantial_segments = [seg for idx, seg in enumerate(segments) if idx not in tiny_indices]

        # Phase 1: Submit only substantial segments
        seg_tasks: dict[str, str] = {}
        for sub_idx, seg in enumerate(substantial_segments):
            task_id = self._client.submit_task(
                template_key="mining-segment-understanding",
                input={
                    "text": seg.raw_text,
                    "section_title": seg.section_title or "",
                    "block_type": seg.block_type,
                },
                knowledge_domain=self._knowledge_domain,
                pipeline_stage="enrich",
                expected_output_type="json_object",
            )
            if task_id:
                seg_tasks[str(sub_idx)] = task_id

        # Phase 2: Poll all tasks concurrently
        llm_raw: dict[str, list[dict]] = self._client.poll_all(seg_tasks)
        llm_results: dict[int, dict[str, Any]] = {}
        for key, items in llm_raw.items():
            if items and isinstance(items[0], dict):
                llm_results[int(key)] = items[0]

        # Phase 3: Apply results to substantial segments
        enriched_substantial = [
            _apply_llm_result(seg, llm_results[sub_idx], valid_roles)
            if sub_idx in llm_results
            else seg
            for sub_idx, seg in enumerate(substantial_segments)
        ]

        # Phase 4: Merge back — tiny segments get minimal default enrichment
        result: list[RawSegmentData] = []
        sub_cursor = 0
        for orig_idx, orig_seg in enumerate(segments):
            if orig_idx in tiny_indices:
                # Tiny segment: mark as non-substantive, keep original
                meta = dict(orig_seg.metadata_json)
                meta["content_assessment"] = {
                    "is_substantive": False,
                    "is_navigation": False,
                    "assessment_reason": f"segment below min_enrich_tokens ({orig_seg.token_count} tokens)",
                }
                result.append(RawSegmentData(
                    document_key=orig_seg.document_key,
                    segment_index=orig_seg.segment_index,
                    block_type=orig_seg.block_type,
                    semantic_role="note",
                    section_path=orig_seg.section_path,
                    section_title=orig_seg.section_title,
                    raw_text=orig_seg.raw_text,
                    normalized_text=orig_seg.normalized_text,
                    content_hash=orig_seg.content_hash,
                    normalized_hash=orig_seg.normalized_hash,
                    token_count=orig_seg.token_count,
                    structure_json=orig_seg.structure_json,
                    source_offsets_json=orig_seg.source_offsets_json,
                    entity_refs_json=orig_seg.entity_refs_json,
                    metadata_json=meta,
                ))
            else:
                result.append(enriched_substantial[sub_cursor])
                sub_cursor += 1

        return result


def _apply_llm_result(
    seg: RawSegmentData,
    result: dict[str, Any],
    valid_roles: frozenset[str] | None,
) -> RawSegmentData:
    """Apply LLM enrichment result to a segment（仅语义角色 + 文档类型 + 内容质量）。"""
    changes: dict[str, Any] = {}

    role = result.get("semantic_role", "")
    if role and role != seg.semantic_role:
        if valid_roles is None or role in valid_roles:
            changes["semantic_role"] = role

    doc_type = result.get("document_type", "")
    meta = dict(seg.metadata_json)
    if doc_type:
        meta["llm_document_type"] = doc_type

    assessment = result.get("content_assessment", {})
    if assessment and isinstance(assessment, dict):
        is_substantive = assessment.get("is_substantive")
        is_navigation = assessment.get("is_navigation")
        if isinstance(is_substantive, bool) or isinstance(is_navigation, bool):
            meta["content_assessment"] = {
                k: v for k, v in assessment.items()
                if k in ("is_substantive", "is_navigation", "assessment_reason")
            }

    if changes or meta != dict(seg.metadata_json):
        changes["metadata_json"] = meta

    if not changes:
        return seg

    return RawSegmentData(
        document_key=seg.document_key,
        segment_index=seg.segment_index,
        block_type=seg.block_type,
        semantic_role=changes.get("semantic_role", seg.semantic_role),
        section_path=seg.section_path,
        section_title=seg.section_title,
        raw_text=seg.raw_text,
        normalized_text=seg.normalized_text,
        content_hash=seg.content_hash,
        normalized_hash=seg.normalized_hash,
        token_count=seg.token_count,
        structure_json=seg.structure_json,
        source_offsets_json=seg.source_offsets_json,
        entity_refs_json=changes.get("entity_refs_json", seg.entity_refs_json),
        metadata_json=changes.get("metadata_json", seg.metadata_json),
    )
