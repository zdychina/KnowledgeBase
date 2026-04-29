"""Enrich stage: formal pluggable understanding phase for v1.1.

v1.1 enrich is the single point where:
- Entity extraction (commands, network elements, parameters)
- Semantic role classification
- Heading role annotation
- Table metadata enrichment

are applied to segments. This stage accepts pluggable Protocol interfaces:
- EntityExtractor: extract structured entities from text
- RoleClassifier: classify segment semantic role

v1.1 provides RuleBasedEntityExtractor + DefaultRoleClassifier.
v1.2 can inject LLM-backed implementations without changing segmentation or retrieval_units.
"""
from __future__ import annotations

import re
from typing import Any, Protocol, TYPE_CHECKING, runtime_checkable

from knowledge_mining.mining.models import VALID_SEMANTIC_ROLES, RawSegmentData

if TYPE_CHECKING:
    from knowledge_mining.mining.domain_pack import DomainProfile

from knowledge_mining.mining.extractors import (
    DefaultRoleClassifier,
    EntityExtractor,
    NoOpEntityExtractor,
    RoleClassifier,
    RuleBasedEntityExtractor,
)


@runtime_checkable
class Enricher(Protocol):
    """Protocol for the enrich stage. v1.2 LLM implementation replaces this."""
    def enrich(self, segments: list[RawSegmentData], **kwargs: Any) -> list[RawSegmentData]: ...
    def enrich_batch(self, segments: list[RawSegmentData], **kwargs: Any) -> list[RawSegmentData]: ...


class RuleBasedEnricher:
    """v1.1 default: rule-based entity extraction + role classification.

    Profile-driven: entity types, role rules, heading roles come from DomainProfile.
    """

    def __init__(
        self,
        entity_extractor: EntityExtractor | None = None,
        role_classifier: RoleClassifier | None = None,
        profile: DomainProfile | None = None,
    ) -> None:
        self._profile = profile
        self._extractor = entity_extractor or RuleBasedEntityExtractor(profile=profile)
        self._classifier = role_classifier or DefaultRoleClassifier(profile=profile)

        # Load heading role keywords and parameter column names from profile
        self._heading_role_keywords = profile.heading_role_keywords if profile else ()
        self._parameter_column_names: list[str] = []
        if profile:
            self._load_extra_config(profile)

    def _load_extra_config(self, profile: DomainProfile) -> None:
        from pathlib import Path
        import yaml

        packs_root = Path(__file__).resolve().parent.parent.parent / "domain_packs"
        yaml_path = packs_root / profile.domain_id / "domain.yaml"
        if yaml_path.exists():
            with open(yaml_path, encoding="utf-8") as f:
                data = yaml.safe_load(f)
            self._parameter_column_names = data.get("parameter_column_names", [])

    def enrich(
        self,
        segments: list[RawSegmentData],
        **kwargs: Any,
    ) -> list[RawSegmentData]:
        """Apply entity extraction, role classification, and metadata enrichment."""
        result: list[RawSegmentData] = []
        for seg in segments:
            result.append(_enrich_one(
                seg, self._extractor, self._classifier,
                self._heading_role_keywords, self._parameter_column_names,
            ))
        return result

    def enrich_batch(
        self,
        segments: list[RawSegmentData],
        **kwargs: Any,
    ) -> list[RawSegmentData]:
        """Batch enrichment. Default: delegates to enrich (v1.2 LLM can override)."""
        return self.enrich(segments, **kwargs)


def enrich_segments(
    segments: list[RawSegmentData],
    *,
    entity_extractor: EntityExtractor | None = None,
    role_classifier: RoleClassifier | None = None,
    profile: DomainProfile | None = None,
    context: dict[str, Any] | None = None,
) -> list[RawSegmentData]:
    """Apply enrichment to segments using the rule-based enricher.

    This is the primary entry point for the enrich pipeline stage.
    Returns new list (immutable).
    """
    enricher = RuleBasedEnricher(
        entity_extractor=entity_extractor,
        role_classifier=role_classifier,
        profile=profile,
    )
    return enricher.enrich(segments)


class LlmEnricher:
    """v1.2: LLM-backed enrichment via llm_service HTTP API.

    Submits segments for LLM understanding, falls back to rule-based on failure.
    """

    def __init__(
        self,
        *,
        base_url: str = "http://localhost:8900",
        fallback_enricher: RuleBasedEnricher | None = None,
        bypass_proxy: bool = False,
        profile: DomainProfile | None = None,
    ) -> None:
        from knowledge_mining.mining.llm_client import LlmClient
        self._client = LlmClient(base_url=base_url, bypass_proxy=bypass_proxy)
        self._profile = profile
        self._fallback = fallback_enricher or RuleBasedEnricher(profile=profile)

    def enrich(
        self,
        segments: list[RawSegmentData],
        **kwargs: Any,
    ) -> list[RawSegmentData]:
        """Single-segment enrichment (delegates to enrich_batch)."""
        return self.enrich_batch(segments, **kwargs)

    def enrich_batch(
        self,
        segments: list[RawSegmentData],
        **kwargs: Any,
    ) -> list[RawSegmentData]:
        """Batch enrichment via LLM with rule-based fallback."""
        if not segments:
            return []

        profile = self._profile
        allowed_entity_types = profile.entity_types if profile else frozenset()

        # Phase 1: Submit all segments
        seg_tasks: dict[str, str] = {}  # str(idx) -> task_id
        for idx, seg in enumerate(segments):
            task_id = self._client.submit_task(
                template_key="mining-segment-understanding",
                input={
                    "text": seg.raw_text,
                    "section_title": seg.section_title or "",
                    "block_type": seg.block_type,
                },
                caller_domain="mining",
                pipeline_stage="enrich",
                expected_output_type="json_object",
            )
            if task_id:
                seg_tasks[str(idx)] = task_id

        # Phase 2: Poll all tasks concurrently — collect whoever finishes first
        llm_raw: dict[str, list[dict]] = self._client.poll_all(seg_tasks)
        llm_results: dict[int, dict[str, Any]] = {}
        for key, items in llm_raw.items():
            if items and isinstance(items[0], dict):
                llm_results[int(key)] = items[0]

        # Phase 3: Apply results, fallback for missing
        fallback_needed = [seg for idx, seg in enumerate(segments) if idx not in llm_results]

        result_segments: list[RawSegmentData] = []
        if fallback_needed:
            enriched_fallback = self._fallback.enrich(fallback_needed)
            fallback_idx = 0
            for idx, seg in enumerate(segments):
                if idx in llm_results:
                    result_segments.append(_apply_llm_result(seg, llm_results[idx], allowed_entity_types))
                else:
                    if fallback_idx < len(enriched_fallback):
                        result_segments.append(enriched_fallback[fallback_idx])
                        fallback_idx += 1
                    else:
                        result_segments.append(seg)
        else:
            for idx, seg in enumerate(segments):
                result_segments.append(_apply_llm_result(seg, llm_results[idx], allowed_entity_types))

        return result_segments


def _apply_llm_result(
    seg: RawSegmentData,
    result: dict[str, Any],
    allowed_entity_types: frozenset[str],
) -> RawSegmentData:
    """Apply LLM enrichment result to a segment."""
    changes: dict[str, Any] = {}

    # Extract entities from LLM result — filter to allowed types only
    entities = result.get("entities", [])
    if entities and isinstance(entities, list):
        entity_refs = [
            {"type": e.get("type", "unknown"), "name": e.get("name", "")}
            for e in entities
            if e.get("name") and (
                not allowed_entity_types or e.get("type") in allowed_entity_types
            )
        ]
        # Merge with existing entities
        existing = {(r["type"], r["name"]) for r in seg.entity_refs_json}
        for ref in entity_refs:
            key = (ref["type"], ref["name"])
            if key not in existing:
                existing.add(key)
        merged_refs = list(seg.entity_refs_json) + [
            ref for ref in entity_refs
            if (ref["type"], ref["name"]) not in {(r["type"], r["name"]) for r in seg.entity_refs_json}
        ]
        changes["entity_refs_json"] = merged_refs

    # Extract semantic role
    role = result.get("semantic_role", "")
    if role and role in VALID_SEMANTIC_ROLES and role != seg.semantic_role:
        changes["semantic_role"] = role

    # Extract document type hint + content_assessment
    doc_type = result.get("document_type", "")
    meta = dict(seg.metadata_json)
    if doc_type:
        meta["llm_document_type"] = doc_type

    # v1.5: Parse content_assessment from LLM output
    assessment = result.get("content_assessment", {})
    if assessment and isinstance(assessment, dict):
        # Only store validated fields
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


def _enrich_one(
    seg: RawSegmentData,
    extractor: EntityExtractor,
    classifier: RoleClassifier,
    heading_role_keywords: tuple[tuple[list[str], str], ...],
    parameter_column_names: list[str],
) -> RawSegmentData:
    """Enrich a single segment: entity extraction + role classification + metadata."""
    changes: dict[str, Any] = {}
    ctx: dict[str, Any] = {"section_path": seg.section_path}

    # 1. Entity extraction (formal understanding, not in segmentation)
    structure_json = seg.structure_json
    entity_refs = extractor.extract(seg.raw_text, {**ctx, "structure": structure_json})

    # 1a. Add section-title-derived entities
    if seg.section_title:
        entity_refs = _add_section_context_entities(seg.section_title, entity_refs, extractor)

    if entity_refs != list(seg.entity_refs_json):
        changes["entity_refs_json"] = entity_refs

    # 2. Role classification (formal understanding, not in segmentation)
    if seg.semantic_role == "unknown":
        classified_role = classifier.classify(
            seg.raw_text, seg.section_title, seg.block_type, ctx,
        )
        role = _validate_semantic_role(classified_role)
        if role != seg.semantic_role:
            changes["semantic_role"] = role

    # 3. Metadata enrichment
    meta = dict(seg.metadata_json)
    if seg.block_type == "heading" and seg.section_title:
        meta["heading_role"] = _classify_heading_role(seg.section_title, heading_role_keywords)
    if seg.block_type == "table" and structure_json:
        cols = structure_json.get("columns", [])
        if cols:
            meta["table_column_count"] = len(cols)
            meta["table_has_parameter_column"] = any(
                pc in c for c in cols for pc in parameter_column_names
            )

    # 4. v1.5: Rule-based content_assessment fallback (when LLM is unavailable)
    if "content_assessment" not in meta:
        meta["content_assessment"] = _rule_based_content_assessment(seg)

    if changes or meta != dict(seg.metadata_json):
        changes["metadata_json"] = meta

    if not changes:
        return seg

    # Create new frozen instance with changes
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


def _rule_based_content_assessment(seg: RawSegmentData) -> dict[str, Any]:
    """Simple heuristic content_assessment for RuleBasedEnricher fallback.

    LLM does the intelligent version; this is just a reasonable default
    when LLM is unavailable.
    """
    # Headings are structural, not content
    if seg.block_type == "heading":
        return {"is_substantive": False, "is_navigation": False, "assessment_reason": "heading block"}

    # Short list that looks like navigation (all links)
    if seg.block_type == "list":
        import re as _re
        text = seg.raw_text.strip()
        if text:
            links = _re.findall(r'\[([^\]]+)\]\(#[^)]+\)', text)
            lines = [l.strip() for l in text.split('\n') if l.strip()]
            if links and len(links) >= len(lines) * 0.8:
                return {
                    "is_substantive": False,
                    "is_navigation": True,
                    "assessment_reason": "list is mostly anchor links",
                }

    # Everything else is substantive
    return {"is_substantive": True, "is_navigation": False, "assessment_reason": "rule-based default"}


def _validate_semantic_role(role: str) -> str:
    if role in VALID_SEMANTIC_ROLES:
        return role
    return "unknown"


def _classify_heading_role(
    title: str,
    heading_role_keywords: tuple[tuple[list[str], str], ...],
) -> str:
    title_lower = title.lower()
    for keywords, role in heading_role_keywords:
        if any(kw.lower() in title_lower for kw in keywords):
            return role
    return "section"


def _add_section_context_entities(
    section_title: str,
    existing: list[dict[str, str]],
    extractor: EntityExtractor,
) -> list[dict[str, str]]:
    """Add section-title-derived entities if not already present."""
    refs = list(existing)  # defensive copy
    seen = {(r["type"], r["name"]) for r in refs}

    # Use profile-driven extraction if available
    if isinstance(extractor, RuleBasedEntityExtractor):
        result = extractor.extract_from_section_title(section_title)
        if result:
            key = (result["type"], result["name"])
            if key not in seen:
                refs.append(result)

    return refs
