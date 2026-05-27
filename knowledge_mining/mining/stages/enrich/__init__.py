"""Enrich stage: LLM-driven segment understanding (v1.2+).

LlmEnricher submits segments to llm_service for:
- Entity extraction (commands, network elements, parameters)
- Semantic role classification
- Content quality assessment (is_substantive, is_navigation)
"""
from __future__ import annotations

from typing import Any, TYPE_CHECKING

from knowledge_mining.mining.contracts.models import VALID_SEMANTIC_ROLES, RawSegmentData

if TYPE_CHECKING:
    from knowledge_mining.mining.infra.domain_pack import DomainProfile


class LlmEnricher:
    """LLM-backed enrichment via llm_service HTTP API.

    Submits segments for LLM understanding. Segments without a successful LLM
    result are returned unchanged.
    """

    stage_name = "enrich"
    stage_version = "2"

    def __init__(
        self,
        *,
        base_url: str = "http://localhost:8900",
        bypass_proxy: bool = False,
        profile: "DomainProfile | None" = None,
        knowledge_domain: str | None = None,
    ) -> None:
        from knowledge_mining.mining.infra.llm_client import LlmClient
        self._client = LlmClient(base_url=base_url, bypass_proxy=bypass_proxy)
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
        allowed_entity_types = profile.entity_types if profile else frozenset()
        # Use domain-specific semantic_roles when available, else fallback to global default
        valid_roles = profile.semantic_roles if profile and profile.semantic_roles else VALID_SEMANTIC_ROLES

        # Phase 1: Submit all segments
        seg_tasks: dict[str, str] = {}
        for idx, seg in enumerate(segments):
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
                seg_tasks[str(idx)] = task_id

        # Phase 2: Poll all tasks concurrently
        llm_raw: dict[str, list[dict]] = self._client.poll_all(seg_tasks)
        llm_results: dict[int, dict[str, Any]] = {}
        for key, items in llm_raw.items():
            if items and isinstance(items[0], dict):
                llm_results[int(key)] = items[0]

        # Phase 3: Apply results; return original segment when LLM had no result
        return [
            _apply_llm_result(seg, llm_results[idx], allowed_entity_types, valid_roles)
            if idx in llm_results
            else seg
            for idx, seg in enumerate(segments)
        ]


def _apply_llm_result(
    seg: RawSegmentData,
    result: dict[str, Any],
    allowed_entity_types: frozenset[str],
    valid_roles: frozenset[str],
) -> RawSegmentData:
    """Apply LLM enrichment result to a segment."""
    changes: dict[str, Any] = {}

    entities = result.get("entities", [])
    if entities and isinstance(entities, list):
        entity_refs = [
            {"type": e.get("type", "unknown"), "name": e.get("name", "")}
            for e in entities
            if e.get("name") and (
                not allowed_entity_types or e.get("type") in allowed_entity_types
            )
        ]
        existing = {(r["type"], r["name"]) for r in seg.entity_refs_json}
        merged_refs = list(seg.entity_refs_json) + [
            ref for ref in entity_refs
            if (ref["type"], ref["name"]) not in existing
        ]
        changes["entity_refs_json"] = merged_refs

    role = result.get("semantic_role", "")
    if role and role in valid_roles and role != seg.semantic_role:
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
