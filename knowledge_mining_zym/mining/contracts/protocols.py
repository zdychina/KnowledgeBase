"""Consolidated Protocol interfaces for the Mining pipeline.

All Protocol definitions live here. Stages import from this module;
infra/ layers use models from contracts.models.

Consolidated from:
- pipeline.py: Segmenter, RelationBuilder
- extractors.py: EntityExtractor, RoleClassifier
- enrich/__init__.py: Enricher
- retrieval_units/__init__.py: QuestionGenerator, Contextualizer
"""
from __future__ import annotations

from typing import Any, Protocol, runtime_checkable

from knowledge_mining.mining.contracts.models import (
    DocumentProfile,
    RawSegmentData,
    RetrievalUnitData,
    SectionNode,
    SegmentRelationData,
)


# ---------------------------------------------------------------------------
# Base Stage Protocol
# ---------------------------------------------------------------------------

@runtime_checkable
class Stage(Protocol):
    """Base protocol for all pipeline stages.

    Every stage must have a name and version for discovery and hot-swapping.
    """

    stage_name: str
    stage_version: str

    def execute(self, context: dict[str, Any], **kwargs: Any) -> dict[str, Any]:
        """Execute the stage, returning updated context."""
        ...


# ---------------------------------------------------------------------------
# Parse & Segment Protocols
# ---------------------------------------------------------------------------

@runtime_checkable
class Segmenter(Protocol):
    """Protocol for splitting a SectionNode tree into segments."""

    def segment(
        self, tree: SectionNode, profile: DocumentProfile, **kwargs: Any,
    ) -> list[RawSegmentData]: ...


# ---------------------------------------------------------------------------
# Relation Protocols
# ---------------------------------------------------------------------------

@runtime_checkable
class RelationBuilder(Protocol):
    """Protocol for building segment relations."""

    def build(
        self, segments: list[RawSegmentData], **kwargs: Any,
    ) -> tuple[list[SegmentRelationData], dict[str, str]]: ...


# ---------------------------------------------------------------------------
# Enrich Protocols
# ---------------------------------------------------------------------------

@runtime_checkable
class Enricher(Protocol):
    """Protocol for the enrich stage. v1.2 LLM implementation replaces this."""

    def enrich(self, segments: list[RawSegmentData], **kwargs: Any) -> list[RawSegmentData]: ...
    def enrich_batch(self, segments: list[RawSegmentData], **kwargs: Any) -> list[RawSegmentData]: ...


# ---------------------------------------------------------------------------
# Extractor Protocols
# ---------------------------------------------------------------------------

@runtime_checkable
class EntityExtractor(Protocol):
    """Protocol for extracting entities from text."""

    def extract(self, text: str, context: dict[str, Any]) -> list[dict[str, str]]: ...


@runtime_checkable
class RoleClassifier(Protocol):
    """Protocol for classifying semantic roles."""

    def classify(
        self,
        text: str,
        section_title: str | None,
        block_type: str,
        context: dict[str, Any],
    ) -> str: ...


# ---------------------------------------------------------------------------
# Retrieval Unit Protocols
# ---------------------------------------------------------------------------

@runtime_checkable
class QuestionGenerator(Protocol):
    """Protocol for generating retrieval questions from segments."""

    def generate(self, segment: RawSegmentData) -> list[str]:
        """Return list of generated questions for the segment."""
        ...

    def generate_batch(self, segments: list[RawSegmentData]) -> dict[str, list[str]]:
        """Return {segment_key: [questions]} for all segments."""
        ...


@runtime_checkable
class Contextualizer(Protocol):
    """Protocol for generating contextual descriptions for segments."""

    def contextualize(self, segments: list[RawSegmentData], document_text: str) -> dict[str, str]:
        """Return {segment_key: context_description} for segments."""
        ...
