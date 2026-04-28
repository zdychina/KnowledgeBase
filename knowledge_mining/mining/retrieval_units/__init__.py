"""Retrieval units stage: build retrieval-ready units from segments.

v1.3 industrial-grade density (2-2.5x, down from 7.8x):

Design principles (based on Anthropic Contextual Retrieval + industrial RAG):
- raw_text units are the primary evidence layer (1:1 with segments)
- LLM context enriches raw_text.search_text (NOT a separate unit) — Anthropic pattern
- entity_card only for strong types: command/protocol/network_element/parameter
- generated_question capped at 1-2 per segment with answerability filtering
- table_row units for per-row retrieval on structured tables

Unit type hierarchy:
- raw_text (60-70%): Primary retrieval evidence, enriched with section + LLM context
- generated_question (15-20%): Recall-boosting questions (1-2 per chunk)
- entity_card (5-10%): Strong entity lookup cards only
- table_row (5-10%): Per-row retrieval for structured tables
"""
from __future__ import annotations

import logging
import uuid
from typing import Any, Protocol, runtime_checkable

from knowledge_mining.mining.models import RawSegmentData, RetrievalUnitData
from knowledge_mining.mining.text_utils import tokenize_for_search

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

# Only these entity types get dedicated cards — 5-15% of extracted entities
_STRONG_ENTITY_TYPES = frozenset({"command", "protocol", "network_element", "parameter"})

# Max generated questions per segment (down from unlimited)
MAX_QUESTIONS_PER_SEGMENT = 2


# ---------------------------------------------------------------------------
# Protocols
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


# ---------------------------------------------------------------------------
# Question Generators
# ---------------------------------------------------------------------------

class NoOpQuestionGenerator:
    """Default: no questions generated (LLM not connected)."""

    def generate(self, segment: RawSegmentData) -> list[str]:
        return []

    def generate_batch(self, segments: list[RawSegmentData]) -> dict[str, list[str]]:
        return {}


class LlmQuestionGenerator:
    """LLM-backed question generation via llm_service HTTP API.

    Batch async: submit_all -> poll_all -> return results.
    Results are capped at MAX_QUESTIONS_PER_SEGMENT.
    """

    def __init__(self, base_url: str = "http://localhost:8900", timeout: int = 120, bypass_proxy: bool = False) -> None:
        from knowledge_mining.mining.llm_client import LlmClient
        self._client = LlmClient(base_url=base_url, bypass_proxy=bypass_proxy)
        self._timeout = timeout
        self._last_task_ids: dict[str, str] = {}

    def generate(self, segment: RawSegmentData) -> list[str]:
        """Single segment submit+poll (fallback)."""
        try:
            task_id = self._client.submit_task(
                template_key="mining-question-gen",
                input={
                    "title": segment.section_title or "",
                    "content": segment.raw_text,
                },
                caller_domain="mining",
                pipeline_stage="retrieval_units",
                expected_output_type="json_array",
            )
            if task_id is None:
                return []
            items = self._client.poll_result(task_id, timeout=self._timeout)
            if items is None:
                return []
            questions = [item["question"] for item in items if "question" in item]
            return questions[:MAX_QUESTIONS_PER_SEGMENT]
        except Exception:
            return []

    @property
    def last_task_ids(self) -> dict[str, str]:
        return dict(self._last_task_ids)

    def generate_batch(self, segments: list[RawSegmentData]) -> dict[str, list[str]]:
        """Batch: submit all tasks, then poll all results concurrently."""
        if not segments:
            return {}

        # Phase 1: Submit all tasks
        seg_tasks: dict[str, str] = {}
        for seg in segments:
            seg_key = f"{seg.document_key}#{seg.segment_index}"
            task_id = self._client.submit_task(
                template_key="mining-question-gen",
                input={
                    "title": seg.section_title or "",
                    "content": seg.raw_text,
                },
                caller_domain="mining",
                pipeline_stage="retrieval_units",
                expected_output_type="json_array",
            )
            if task_id:
                seg_tasks[seg_key] = task_id

        if not seg_tasks:
            return {}

        self._last_task_ids = dict(seg_tasks)

        # Phase 2: Poll all results concurrently
        raw_results = self._client.poll_all(seg_tasks)
        results: dict[str, list[str]] = {}
        for seg_key, items in raw_results.items():
            questions = [item["question"] for item in items if "question" in item]
            # Cap at MAX_QUESTIONS_PER_SEGMENT
            if questions:
                results[seg_key] = questions[:MAX_QUESTIONS_PER_SEGMENT]

        return results


# ---------------------------------------------------------------------------
# Contextualizers
# ---------------------------------------------------------------------------

class NoOpContextualizer:
    """Fallback: returns empty context descriptions."""

    def contextualize(self, segments: list[RawSegmentData], document_text: str) -> dict[str, str]:
        return {}


class LLMContextualizer:
    """Anthropic-style contextual retrieval via LLM.

    Generates brief context descriptions per segment.
    In v1.3, the context is folded into raw_text.search_text, NOT a separate unit.
    """

    def __init__(self, base_url: str = "http://localhost:8900", timeout: int = 120, bypass_proxy: bool = False) -> None:
        from knowledge_mining.mining.llm_client import LlmClient
        self._client = LlmClient(base_url=base_url, bypass_proxy=bypass_proxy)
        self._timeout = timeout
        self._last_task_ids: dict[str, str] = {}

    @property
    def last_task_ids(self) -> dict[str, str]:
        return dict(self._last_task_ids)

    def contextualize(self, segments: list[RawSegmentData], document_text: str) -> dict[str, str]:
        """Generate context descriptions for all segments via LLM.

        Only contextualizes substantial segments (non-heading, >15 chars).
        Returns {segment_key: context_description}.
        """
        if not segments:
            return {}

        # Filter to substantial segments only — headings and tiny fragments
        # don't need LLM context (saves ~30% of LLM calls)
        substantial = [
            s for s in segments
            if s.block_type != "heading" and len(s.raw_text.strip()) > 15
        ]
        if not substantial:
            return {}

        seg_tasks: dict[str, str] = {}
        for seg in substantial:
            seg_key = f"{seg.document_key}#{seg.segment_index}"
            doc_preview = document_text[:2000] if len(document_text) > 2000 else document_text
            task_id = self._client.submit_task(
                template_key="mining-contextual-retrieval",
                input={
                    "document": doc_preview,
                    "segment": seg.raw_text[:500],
                },
                caller_domain="mining",
                pipeline_stage="contextual_retrieval",
                expected_output_type="json_object",
            )
            if task_id:
                seg_tasks[seg_key] = task_id

        self._last_task_ids = dict(seg_tasks)

        raw_results = self._client.poll_all(seg_tasks)
        results: dict[str, str] = {}
        for seg_key, items in raw_results.items():
            if not items:
                continue
            item = items[0] if isinstance(items, list) else items
            context = item.get("context", "")
            if context:
                results[seg_key] = context

        return results


# ---------------------------------------------------------------------------
# Main builder
# ---------------------------------------------------------------------------

def build_retrieval_units(
    segments: list[RawSegmentData],
    *,
    seg_ids: dict[str, str] | None = None,
    document_key: str = "",
    question_generator: QuestionGenerator | None = None,
    contextualizer: Contextualizer | None = None,
) -> list[RetrievalUnitData]:
    """Build retrieval units from segments.

    v1.3 strategy (2-2.5x density):
    1. raw_text: 1:1 with segment, search_text enriched with section + LLM context
    2. entity_card: only for strong entity types
    3. table_row: per-row for table segments
    4. generated_question: 1-2 per substantial segment

    Args:
        segments: Enriched segments to build units from.
        seg_ids: Map of segment_key -> segment UUID (from build_relations).
        document_key: Document key for unit naming.
        question_generator: Optional question generator (LLM-backed or NoOp).
        contextualizer: Optional contextualizer for search_text enrichment.
    """
    if not segments:
        return []

    qgen = question_generator or NoOpQuestionGenerator()
    ctxer = contextualizer or NoOpContextualizer()
    units: list[RetrievalUnitData] = []
    seen_entity_cards: set[str] = set()

    # Phase 1: Batch-generate all questions (submit all -> poll all)
    question_map: dict[str, list[str]] = {}
    qgen_task_ids: dict[str, str] = {}
    if qgen is not None:
        questionworthy = [s for s in segments if _is_questionworthy(s)]
        question_map = qgen.generate_batch(questionworthy)
        if hasattr(qgen, "last_task_ids"):
            qgen_task_ids = qgen.last_task_ids

    # Phase 1b: Batch-generate contextual descriptions (for search_text enrichment)
    context_map: dict[str, str] = {}
    ctxer_task_ids: dict[str, str] = {}
    document_text = "\n".join(s.raw_text for s in segments)
    try:
        context_map = ctxer.contextualize(
            [s for s in segments if s.raw_text.strip()],
            document_text,
        )
        if hasattr(ctxer, "last_task_ids"):
            ctxer_task_ids = ctxer.last_task_ids
    except Exception as e:
        logger.warning("Contextualization failed: %s", e)

    # Phase 2: Build units for each segment
    for seg in segments:
        seg_key = f"{seg.document_key}#{seg.segment_index}"
        source_seg_id = (seg_ids or {}).get(seg_key)

        # 1. raw_text unit — enriched with section context + optional LLM context
        llm_context = context_map.get(seg_key, "")
        ctx_task_id = ctxer_task_ids.get(seg_key)
        units.append(_make_raw_text_unit(seg, source_seg_id, llm_context, ctx_task_id))

        # 2. entity_card units — only strong types, deduped
        for ref in seg.entity_refs_json:
            entity_type = ref.get("type", "")
            if entity_type not in _STRONG_ENTITY_TYPES:
                continue
            entity_key = f"{entity_type}:{ref.get('name', '')}"
            if entity_key not in seen_entity_cards:
                seen_entity_cards.add(entity_key)
                units.append(_make_entity_card_unit(seg, ref, source_seg_id))

        # 3. table_row units (per-row retrieval for structured tables)
        units.extend(_make_table_row_units(seg, source_seg_id))

        # 4. generated_question units (capped at MAX_QUESTIONS_PER_SEGMENT)
        questions = question_map.get(seg_key, [])
        q_task_id = qgen_task_ids.get(seg_key)
        for qi, question in enumerate(questions):
            units.append(_make_generated_question_unit(
                seg, question, qi, source_seg_id, q_task_id,
            ))

    return units


# ---------------------------------------------------------------------------
# Unit builders
# ---------------------------------------------------------------------------

def _make_raw_text_unit(
    seg: RawSegmentData,
    source_seg_id: str | None = None,
    llm_context: str = "",
    llm_task_id: str | None = None,
) -> RetrievalUnitData:
    """Primary retrieval unit: raw_text with enriched search_text.

    search_text composition (Anthropic contextual retrieval pattern):
    1. Section title context (if not already in raw_text)
    2. LLM-generated context (if available)
    3. Original raw_text
    All tokenized for FTS5 search.
    """
    # Build enriched search text
    search_parts: list[str] = []

    # Add section context if it adds information not in raw_text
    section_titles = [
        p.get("title", "") for p in seg.section_path if p.get("title")
    ]
    extra_titles = [t for t in section_titles if t and t not in seg.raw_text]
    if extra_titles:
        search_parts.append(" > ".join(extra_titles))

    # Add LLM-generated context (Anthropic pattern: brief context prepended)
    if llm_context:
        search_parts.append(llm_context)

    # Add original text
    search_parts.append(seg.raw_text)

    enriched_search = "\n".join(search_parts)

    # Build llm_result_refs_json for provenance
    llm_refs: dict[str, Any] = {}
    if llm_task_id:
        llm_refs = {
            "source": "contextual_retrieval",
            "task_id": llm_task_id,
        }

    # Build metadata
    metadata: dict[str, Any] = {"segment_index": seg.segment_index}
    if llm_context:
        metadata["context_description"] = llm_context

    return RetrievalUnitData(
        segment_key=f"{seg.document_key}#{seg.segment_index}",
        unit_key=f"ru:{seg.document_key}#{seg.segment_index}:raw_text",
        unit_type="raw_text",
        target_type="raw_segment",
        target_ref_json={
            "document_key": seg.document_key,
            "segment_index": seg.segment_index,
        },
        title=seg.section_title,
        text=seg.raw_text,
        search_text=tokenize_for_search(enriched_search),
        block_type=seg.block_type,
        semantic_role=seg.semantic_role,
        facets_json=_build_facets(seg),
        entity_refs_json=list(seg.entity_refs_json),
        source_refs_json=_build_source_refs(seg, source_seg_id),
        llm_result_refs_json=llm_refs,
        source_segment_id=source_seg_id,
        weight=1.0,
        metadata_json=metadata,
    )


def _make_entity_card_unit(
    seg: RawSegmentData,
    ref: dict[str, str],
    source_seg_id: str | None = None,
) -> RetrievalUnitData:
    """Entity card: only for strong entity types (command/protocol/network_element/parameter)."""
    entity_type = ref.get("type", "unknown")
    entity_name = ref.get("name", "unknown")

    description = _extract_entity_context(entity_name, seg.raw_text)
    text = f"{entity_name}（{entity_type}）"
    if description:
        text += f" {description}"
    elif seg.section_title:
        text += f" — 见 {seg.section_title}"

    return RetrievalUnitData(
        segment_key=f"{seg.document_key}#{seg.segment_index}",
        unit_key=f"ru:entity:{entity_type}:{entity_name}",
        unit_type="entity_card",
        target_type="entity",
        target_ref_json={"entity_type": entity_type, "entity_name": entity_name},
        title=entity_name,
        text=text,
        search_text=tokenize_for_search(f"{entity_name} {entity_type} {description}"),
        block_type=seg.block_type,
        semantic_role=seg.semantic_role,
        facets_json={"entity_type": entity_type},
        entity_refs_json=[ref],
        source_refs_json=_build_source_refs(seg, source_seg_id),
        source_segment_id=source_seg_id,
        weight=0.5,
        metadata_json={"first_seen_in": seg.document_key},
    )


def _make_generated_question_unit(
    seg: RawSegmentData,
    question: str,
    question_index: int,
    source_seg_id: str | None = None,
    llm_task_id: str | None = None,
) -> RetrievalUnitData:
    """Generated question unit: one per LLM-generated question (max 2 per segment)."""
    title = f"Q{question_index + 1}: {question[:60]}"
    text = f"{question}\n---\n来源: {seg.section_title or '未知'}\n{seg.raw_text[:200]}"
    search_text = tokenize_for_search(f"{question} {seg.section_title or ''}")
    llm_refs: dict[str, Any] = {"source": "llm_runtime", "question_index": question_index}
    if llm_task_id:
        llm_refs["task_id"] = llm_task_id

    return RetrievalUnitData(
        segment_key=f"{seg.document_key}#{seg.segment_index}",
        unit_key=f"ru:{seg.document_key}#{seg.segment_index}:gen_q_{question_index}",
        unit_type="generated_question",
        target_type="raw_segment",
        target_ref_json={
            "document_key": seg.document_key,
            "segment_index": seg.segment_index,
            "question_index": question_index,
        },
        title=title,
        text=text,
        search_text=search_text,
        block_type=seg.block_type,
        semantic_role=seg.semantic_role,
        facets_json=_build_facets(seg),
        entity_refs_json=list(seg.entity_refs_json),
        source_refs_json=_build_source_refs(seg, source_seg_id),
        llm_result_refs_json=llm_refs,
        source_segment_id=source_seg_id,
        weight=0.7,
        metadata_json={"question_index": question_index},
    )


def _make_table_row_units(
    seg: RawSegmentData, source_seg_id: str | None = None,
) -> list[RetrievalUnitData]:
    """Generate per-row retrieval units for table segments."""
    if seg.block_type != "table":
        return []

    struct = seg.structure_json
    columns = struct.get("columns", [])
    rows = struct.get("rows", [])
    if not columns or not rows:
        return []

    units: list[RetrievalUnitData] = []
    for row_idx, row in enumerate(rows):
        parts = []
        all_values = []
        for col in columns:
            val = row.get(col, "")
            if val:
                parts.append(f"{col}为{val}")
                all_values.append(val)

        if not parts:
            continue

        text = "，".join(parts) + "。"
        search_text = tokenize_for_search(" ".join(all_values + columns))
        seg_key = f"{seg.document_key}#{seg.segment_index}"

        units.append(RetrievalUnitData(
            segment_key=seg_key,
            unit_key=f"ru:{seg.document_key}#{seg.segment_index}:table_row_{row_idx}",
            unit_type="table_row",
            target_type="raw_segment",
            target_ref_json={
                "document_key": seg.document_key,
                "segment_index": seg.segment_index,
                "row_index": row_idx,
            },
            title=f"行{row_idx + 1}: {'、'.join(all_values[:3])}",
            text=text,
            search_text=search_text,
            block_type=seg.block_type,
            semantic_role=seg.semantic_role,
            facets_json=_build_facets(seg),
            entity_refs_json=list(seg.entity_refs_json),
            source_refs_json=_build_source_refs(seg, source_seg_id),
            source_segment_id=source_seg_id,
            weight=0.8,
            metadata_json={"row_index": row_idx, "columns": columns},
        ))

    return units


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _build_facets(seg: RawSegmentData) -> dict[str, Any]:
    """Build facets from segment metadata."""
    facets: dict[str, Any] = {}
    if seg.block_type:
        facets["block_type"] = seg.block_type
    if seg.semantic_role:
        facets["semantic_role"] = seg.semantic_role
    if seg.section_path:
        facets["section_depth"] = len(seg.section_path)
    return facets


def _build_source_refs(seg: RawSegmentData, source_seg_id: str | None = None) -> dict[str, Any]:
    """Build source_refs for provenance tracing."""
    refs: dict[str, Any] = {
        "document_key": seg.document_key,
        "segment_index": seg.segment_index,
    }
    if seg.source_offsets_json:
        refs["offsets"] = seg.source_offsets_json
    if source_seg_id:
        refs["raw_segment_ids"] = [source_seg_id]
    return refs


def _is_questionworthy(seg: RawSegmentData) -> bool:
    """Filter segments that should receive question generation.

    Only substantial non-heading content gets questions.
    """
    if seg.block_type == "heading":
        return False
    if seg.token_count is not None and seg.token_count < 10:
        return False
    if len(seg.raw_text.strip()) < 15:
        return False
    return True


def _extract_entity_context(name: str, raw_text: str, window: int = 80) -> str:
    """Extract text around entity mention for context."""
    idx = raw_text.find(name)
    if idx < 0:
        return ""
    start = max(0, idx - window // 2)
    end = min(len(raw_text), idx + len(name) + window // 2)
    ctx = raw_text[start:end].strip()
    if start > 0:
        ctx = "..." + ctx
    if end < len(raw_text):
        ctx = ctx + "..."
    return ctx
