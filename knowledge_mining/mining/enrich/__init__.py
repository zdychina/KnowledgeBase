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
from typing import Any, Protocol, runtime_checkable

from knowledge_mining.mining.extractors import (
    DefaultRoleClassifier,
    EntityExtractor,
    NoOpEntityExtractor,
    RoleClassifier,
    RuleBasedEntityExtractor,
)
from knowledge_mining.mining.models import RawSegmentData

_SCHEMA_SEMANTIC_ROLES = frozenset({
    "concept", "parameter", "example", "note", "procedure_step",
    "troubleshooting_step", "constraint", "alarm", "checklist", "unknown",
})


@runtime_checkable
class Enricher(Protocol):
    """Protocol for the enrich stage. v1.2 LLM implementation replaces this."""
    def enrich(self, segments: list[RawSegmentData], **kwargs: Any) -> list[RawSegmentData]: ...
    def enrich_batch(self, segments: list[RawSegmentData], **kwargs: Any) -> list[RawSegmentData]: ...


class RuleBasedEnricher:
    """v1.1 default: rule-based entity extraction + role classification.

    This is the formal understanding stage. It replaces the old approach where
    extraction was done during segmentation.
    """

    def __init__(
        self,
        entity_extractor: EntityExtractor | None = None,
        role_classifier: RoleClassifier | None = None,
    ) -> None:
        self._extractor = entity_extractor or RuleBasedEntityExtractor()
        self._classifier = role_classifier or DefaultRoleClassifier()

    def enrich(
        self,
        segments: list[RawSegmentData],
        **kwargs: Any,
    ) -> list[RawSegmentData]:
        """Apply entity extraction, role classification, and metadata enrichment."""
        result: list[RawSegmentData] = []
        for seg in segments:
            result.append(_enrich_one(seg, self._extractor, self._classifier))
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
    context: dict[str, Any] | None = None,
) -> list[RawSegmentData]:
    """Apply enrichment to segments using the rule-based enricher.

    This is the primary entry point for the enrich pipeline stage.
    Returns new list (immutable).
    """
    enricher = RuleBasedEnricher(
        entity_extractor=entity_extractor,
        role_classifier=role_classifier,
    )
    return enricher.enrich(segments)


def _enrich_one(
    seg: RawSegmentData,
    extractor: EntityExtractor,
    classifier: RoleClassifier,
) -> RawSegmentData:
    """Enrich a single segment: entity extraction + role classification + metadata."""
    changes: dict[str, Any] = {}
    ctx: dict[str, Any] = {"section_path": seg.section_path}

    # 1. Entity extraction (formal understanding, not in segmentation)
    structure_json = seg.structure_json
    entity_refs = extractor.extract(seg.raw_text, {**ctx, "structure": structure_json})

    # 1a. Add section-title-derived entities
    if seg.section_title:
        entity_refs = _add_section_context_entities(seg.section_title, entity_refs)

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
        meta["heading_role"] = _classify_heading_role(seg.section_title)
    if seg.block_type == "table" and structure_json:
        cols = structure_json.get("columns", [])
        if cols:
            meta["table_column_count"] = len(cols)
            meta["table_has_parameter_column"] = any("参数" in c for c in cols)

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


def _validate_semantic_role(role: str) -> str:
    if role in _SCHEMA_SEMANTIC_ROLES:
        return role
    return "unknown"


_HEADING_ROLE_KEYWORDS: list[tuple[list[str], str]] = [
    (["参数", "参数说明", "参数标识"], "parameter_definition"),
    (["使用实例", "示例", "配置示例"], "example_section"),
    (["操作步骤", "流程", "检查项"], "procedure_section"),
    (["排障", "故障"], "troubleshooting_section"),
    (["注意事项", "限制", "约束"], "constraint_section"),
    (["概述", "简介", "功能"], "overview_section"),
]


def _classify_heading_role(title: str) -> str:
    title_lower = title.lower()
    for keywords, role in _HEADING_ROLE_KEYWORDS:
        if any(kw.lower() in title_lower for kw in keywords):
            return role
    return "section"


def _add_section_context_entities(
    section_title: str,
    existing: list[dict[str, str]],
) -> list[dict[str, str]]:
    """Add section-title-derived entities if not already present."""
    refs = list(existing)  # defensive copy
    seen = {(r["type"], r["name"]) for r in refs}

    cmd_match = re.match(r"^(ADD|SHOW|MOD|DEL|DSP|LST|REG|DEREG)\s+(\S+)", section_title.upper())
    if cmd_match:
        cmd_name = f"{cmd_match.group(1)} {cmd_match.group(2)}"
        key = ("command", cmd_name)
        if key not in seen:
            refs.append({"type": "command", "name": cmd_name})

    return refs
