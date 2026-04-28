"""Retrieval units stage: build retrieval-ready units from segments.

v1.2 produces:
- raw_text: one-to-one from each segment (source_segment_id bridge)
- contextual_text: segment with section heading context prepended
- entity_card: enriched with entity context from raw_text
- generated_question: LLM-generated via LlmQuestionGenerator

v1.2 changes:
- source_segment_id strong bridge to raw_segment
- jieba pre-tokenization for search_text (FTS5 Chinese support)
- entity_card content enrichment with surrounding context
- LlmQuestionGenerator backed by llm_service
"""
from __future__ import annotations

import uuid
from typing import Any, Protocol, runtime_checkable

from knowledge_mining.mining.models import RawSegmentData, RetrievalUnitData
from knowledge_mining.mining.text_utils import tokenize_for_search


@runtime_checkable
class QuestionGenerator(Protocol):
    """Protocol for generating retrieval questions from segments."""

    def generate(self, segment: RawSegmentData) -> list[str]:
        """Return list of generated questions for the segment."""
        ...

    def generate_batch(self, segments: list[RawSegmentData]) -> dict[str, list[str]]:
        """Return {segment_key: [questions]} for all segments. Default: call generate per segment."""
        ...


class NoOpQuestionGenerator:
    """Default: no questions generated (LLM not connected)."""

    def generate(self, segment: RawSegmentData) -> list[str]:
        return []

    def generate_batch(self, segments: list[RawSegmentData]) -> dict[str, list[str]]:
        return {}


class LlmQuestionGenerator:
    """v1.2: LLM-backed question generation via llm_service HTTP API.

    Batch async: submit_all → poll_all → return results.
    Worker concurrency handles parallelism on the server side.
    """

    def __init__(self, base_url: str = "http://localhost:8900", timeout: int = 120) -> None:
        from knowledge_mining.mining.llm_client import LlmClient
        self._client = LlmClient(base_url=base_url)
        self._timeout = timeout

    def generate(self, segment: RawSegmentData) -> list[str]:
        """Single segment submit+poll (fallback, not recommended for batch)."""
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
            return [item["question"] for item in items if "question" in item]
        except Exception:
            return []

    def generate_batch(self, segments: list[RawSegmentData]) -> dict[str, list[str]]:
        """Batch: submit all tasks, then poll all results.

        Returns {segment_key: [question_strings]}.
        Failed/empty results are omitted from the dict.
        """
        if not segments:
            return {}

        # Phase 1: Submit all tasks
        seg_tasks: dict[str, str] = {}  # segment_key -> task_id
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

        # Phase 2: Poll all results
        results: dict[str, list[str]] = {}
        for seg_key, task_id in seg_tasks.items():
            items = self._client.poll_result(task_id, timeout=self._timeout)
            if items:
                questions = [item["question"] for item in items if "question" in item]
                if questions:
                    results[seg_key] = questions

        return results


def build_retrieval_units(
    segments: list[RawSegmentData],
    *,
    seg_ids: dict[str, str] | None = None,
    document_key: str = "",
    question_generator: QuestionGenerator | None = None,
) -> list[RetrievalUnitData]:
    """Build retrieval units from segments.

    Args:
        segments: Enriched segments to build units from.
        seg_ids: Map of segment_key -> segment UUID (from build_relations).
        document_key: Document key for unit naming.
        question_generator: Optional question generator (LLM-backed or NoOp).
    """
    if not segments:
        return []

    qgen = question_generator or NoOpQuestionGenerator()
    units: list[RetrievalUnitData] = []
    seen_entity_cards: set[str] = set()

    # Phase 1: Batch-generate all questions (submit all → poll all)
    question_map: dict[str, list[str]] = {}
    if qgen is not None:
        question_map = qgen.generate_batch(segments)

    # Phase 2: Build units for each segment
    for seg in segments:
        seg_key = f"{seg.document_key}#{seg.segment_index}"
        source_seg_id = (seg_ids or {}).get(seg_key)

        # 1. raw_text unit (1:1 with segment)
        units.append(_make_raw_text_unit(seg, source_seg_id))

        # 2. contextual_text unit (segment + section context)
        ctx_unit = _make_contextual_text_unit(seg, source_seg_id)
        if ctx_unit is not None:
            units.append(ctx_unit)

        # 3. entity_card units (deduped, enriched)
        for ref in seg.entity_refs_json:
            entity_key = f"{ref.get('type', '')}:{ref.get('name', '')}"
            if entity_key not in seen_entity_cards:
                seen_entity_cards.add(entity_key)
                units.append(_make_entity_card_unit(seg, ref, source_seg_id))

        # 4. generated_question units (from batch results)
        questions = question_map.get(seg_key, [])
        for qi, question in enumerate(questions):
            units.append(_make_generated_question_unit(seg, question, qi, source_seg_id))

    return units


def _make_raw_text_unit(
    seg: RawSegmentData, source_seg_id: str | None = None,
) -> RetrievalUnitData:
    """One-to-one raw_text retrieval unit from segment."""
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
        search_text=tokenize_for_search(seg.raw_text),
        block_type=seg.block_type,
        semantic_role=seg.semantic_role,
        facets_json=_build_facets(seg),
        entity_refs_json=list(seg.entity_refs_json),
        source_refs_json=_build_source_refs(seg),
        source_segment_id=source_seg_id,
        weight=1.0,
        metadata_json={"segment_index": seg.segment_index},
    )


def _make_contextual_text_unit(
    seg: RawSegmentData, source_seg_id: str | None = None,
) -> RetrievalUnitData | None:
    """Contextual text: raw_text with section path prepended."""
    if not seg.section_path or seg.block_type == "heading":
        return None

    section_titles = [p.get("title", "") for p in seg.section_path if p.get("title")]
    context_prefix = " > ".join(section_titles)
    if not context_prefix:
        return None

    contextual_text = f"[{context_prefix}]\n{seg.raw_text}"

    return RetrievalUnitData(
        segment_key=f"{seg.document_key}#{seg.segment_index}",
        unit_key=f"ru:{seg.document_key}#{seg.segment_index}:contextual_text",
        unit_type="contextual_text",
        target_type="raw_segment",
        target_ref_json={
            "document_key": seg.document_key,
            "segment_index": seg.segment_index,
        },
        title=seg.section_title,
        text=contextual_text,
        search_text=tokenize_for_search(contextual_text),
        block_type=seg.block_type,
        semantic_role=seg.semantic_role,
        facets_json=_build_facets(seg),
        entity_refs_json=list(seg.entity_refs_json),
        source_refs_json=_build_source_refs(seg),
        source_segment_id=source_seg_id,
        weight=0.9,
        metadata_json={
            "section_titles": section_titles,
            "segment_index": seg.segment_index,
        },
    )


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


def _make_entity_card_unit(
    seg: RawSegmentData,
    ref: dict[str, str],
    source_seg_id: str | None = None,
) -> RetrievalUnitData:
    """Entity card: enriched with entity context from surrounding text."""
    entity_type = ref.get("type", "unknown")
    entity_name = ref.get("name", "unknown")

    # v1.2: extract context from raw text
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
        source_refs_json=_build_source_refs(seg),
        source_segment_id=source_seg_id,
        weight=0.5,
        metadata_json={"first_seen_in": seg.document_key},
    )


def _make_generated_question_unit(
    seg: RawSegmentData,
    question: str,
    question_index: int,
    source_seg_id: str | None = None,
) -> RetrievalUnitData:
    """Generated question unit: one per LLM-generated question."""
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
        title=question[:80],
        text=question,
        search_text=tokenize_for_search(question),
        block_type=seg.block_type,
        semantic_role=seg.semantic_role,
        facets_json=_build_facets(seg),
        entity_refs_json=list(seg.entity_refs_json),
        source_refs_json=_build_source_refs(seg),
        llm_result_refs_json={"source": "llm_runtime", "question_index": question_index},
        source_segment_id=source_seg_id,
        weight=0.7,
        metadata_json={"question_index": question_index},
    )


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


def _build_source_refs(seg: RawSegmentData) -> dict[str, Any]:
    """Build source_refs for provenance tracing."""
    refs: dict[str, Any] = {
        "document_key": seg.document_key,
        "segment_index": seg.segment_index,
    }
    if seg.source_offsets_json:
        refs["offsets"] = seg.source_offsets_json
    return refs
