"""Retrieval units stage: build retrieval-ready units from segments.

v1.2 produces:
- raw_text: one-to-one from each segment (source_segment_id bridge)
- contextual_text: segment with section heading context prepended
- entity_card: enriched with entity context from raw_text
- generated_question: LLM-generated via LlmQuestionGenerator
- contextual_enhanced: LLM-generated context description prepended to text

v1.2 changes:
- source_segment_id strong bridge to raw_segment
- jieba pre-tokenization for search_text (FTS5 Chinese support)
- entity_card content enrichment with surrounding context
- LlmQuestionGenerator backed by llm_service
- LLMContextualizer for Anthropic-style contextual retrieval
"""
from __future__ import annotations

import logging
import uuid
from typing import Any, Protocol, runtime_checkable

from knowledge_mining.mining.models import RawSegmentData, RetrievalUnitData
from knowledge_mining.mining.text_utils import tokenize_for_search

logger = logging.getLogger(__name__)


@runtime_checkable
class QuestionGenerator(Protocol):
    """Protocol for generating retrieval questions from segments."""

    def generate(self, segment: RawSegmentData) -> list[str]:
        """Return list of generated questions for the segment."""
        ...

    def generate_batch(self, segments: list[RawSegmentData]) -> dict[str, list[str]]:
        """Return {segment_key: [questions]} for all segments. Default: call generate per segment."""
        ...


@runtime_checkable
class Contextualizer(Protocol):
    """Protocol for generating contextual descriptions for segments."""

    def contextualize(self, segments: list[RawSegmentData], document_text: str) -> dict[str, str]:
        """Return {segment_key: context_description} for segments."""
        ...


class NoOpQuestionGenerator:
    """Default: no questions generated (LLM not connected)."""

    def generate(self, segment: RawSegmentData) -> list[str]:
        return []

    def generate_batch(self, segments: list[RawSegmentData]) -> dict[str, list[str]]:
        return {}


class LlmQuestionGenerator:
    """v1.2: LLM-backed question generation via llm_service HTTP API.

    Batch async: submit_all -> poll_all -> return results.
    Worker concurrency handles parallelism on the server side.
    """

    def __init__(self, base_url: str = "http://localhost:8900", timeout: int = 120, bypass_proxy: bool = False) -> None:
        from knowledge_mining.mining.llm_client import LlmClient
        self._client = LlmClient(base_url=base_url, bypass_proxy=bypass_proxy)
        self._timeout = timeout
        # Track task_ids for provenance (seg_key -> task_id)
        self._last_task_ids: dict[str, str] = {}

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

    @property
    def last_task_ids(self) -> dict[str, str]:
        """Return task_id mapping from the most recent generate_batch call."""
        return dict(self._last_task_ids)

    def generate_batch(self, segments: list[RawSegmentData]) -> dict[str, list[str]]:
        """Batch: submit all tasks, then poll all results concurrently.

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

        # Store task_ids for provenance
        self._last_task_ids = dict(seg_tasks)

        # Phase 2: Poll all results concurrently
        raw_results = self._client.poll_all(seg_tasks)
        results: dict[str, list[str]] = {}
        for seg_key, items in raw_results.items():
            questions = [item["question"] for item in items if "question" in item]
            if questions:
                results[seg_key] = questions

        return results


class NoOpContextualizer:
    """Fallback: returns empty context descriptions."""

    def contextualize(self, segments: list[RawSegmentData], document_text: str) -> dict[str, str]:
        return {}


class LLMContextualizer:
    """v1.2: Anthropic-style contextual retrieval via LLM.

    For each segment, generates a brief context description explaining
    its position and role in the full document.
    """

    def __init__(self, base_url: str = "http://localhost:8900", timeout: int = 120, bypass_proxy: bool = False) -> None:
        from knowledge_mining.mining.llm_client import LlmClient
        self._client = LlmClient(base_url=base_url, bypass_proxy=bypass_proxy)
        self._timeout = timeout
        # Track task_ids for provenance (seg_key -> task_id)
        self._last_task_ids: dict[str, str] = {}

    @property
    def last_task_ids(self) -> dict[str, str]:
        """Return task_id mapping from the most recent contextualize call."""
        return dict(self._last_task_ids)

    def contextualize(self, segments: list[RawSegmentData], document_text: str) -> dict[str, str]:
        """Generate context descriptions for all segments via LLM.

        Returns {segment_key: context_description}.
        """
        if not segments:
            return {}

        results: dict[str, str] = {}

        # Batch: submit all, poll all
        seg_tasks: dict[str, str] = {}
        for seg in segments:
            if not seg.raw_text.strip():
                continue
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

        # Store task_ids for provenance
        self._last_task_ids = dict(seg_tasks)

        # Poll all results concurrently
        raw_results = self._client.poll_all(seg_tasks)
        for seg_key, items in raw_results.items():
            if not items:
                continue
            item = items[0] if isinstance(items, list) else items
            context = item.get("context", "")
            if context:
                results[seg_key] = context

        return results


def build_retrieval_units(
    segments: list[RawSegmentData],
    *,
    seg_ids: dict[str, str] | None = None,
    document_key: str = "",
    question_generator: QuestionGenerator | None = None,
    contextualizer: Contextualizer | None = None,
) -> list[RetrievalUnitData]:
    """Build retrieval units from segments.

    Args:
        segments: Enriched segments to build units from.
        seg_ids: Map of segment_key -> segment UUID (from build_relations).
        document_key: Document key for unit naming.
        question_generator: Optional question generator (LLM-backed or NoOp).
        contextualizer: Optional contextualizer for enhanced retrieval (LLM-backed or NoOp).
    """
    if not segments:
        return []

    qgen = question_generator or NoOpQuestionGenerator()
    ctxer = contextualizer or NoOpContextualizer()
    units: list[RetrievalUnitData] = []
    seen_entity_cards: set[str] = set()

    # Phase 1: Batch-generate all questions (submit all -> poll all)
    question_map: dict[str, list[str]] = {}
    qgen_task_ids: dict[str, str] = {}  # seg_key -> task_id for provenance
    if qgen is not None:
        questionworthy = [s for s in segments if _is_questionworthy(s)]
        question_map = qgen.generate_batch(questionworthy)
        # Extract task_ids from LLM-backed generator for provenance
        if hasattr(qgen, "last_task_ids"):
            qgen_task_ids = qgen.last_task_ids

    # Phase 1b: Batch-generate contextual descriptions
    context_map: dict[str, str] = {}
    ctxer_task_ids: dict[str, str] = {}  # seg_key -> task_id for provenance
    document_text = "\n".join(s.raw_text for s in segments)
    try:
        context_map = ctxer.contextualize(
            [s for s in segments if s.raw_text.strip()],
            document_text,
        )
        # Extract task_ids from LLM-backed contextualizer for provenance
        if hasattr(ctxer, "last_task_ids"):
            ctxer_task_ids = ctxer.last_task_ids
    except Exception as e:
        logger.warning("Contextualization failed: %s", e)

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

        # 3b. table_row units (per-row retrieval for structured tables)
        table_row_units = _make_table_row_units(seg, source_seg_id)
        units.extend(table_row_units)

        # 4. generated_question units (from batch results)
        questions = question_map.get(seg_key, [])
        q_task_id = qgen_task_ids.get(seg_key)
        for qi, question in enumerate(questions):
            units.append(_make_generated_question_unit(seg, question, qi, source_seg_id, q_task_id))

        # 5. contextual_enhanced unit (LLM-generated context prepended to text)
        if seg_key in context_map:
            ctx_desc = context_map[seg_key]
            if ctx_desc:
                c_task_id = ctxer_task_ids.get(seg_key)
                units.append(_make_contextual_enhanced_unit(seg, ctx_desc, source_seg_id, c_task_id))

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
        source_refs_json=_build_source_refs(seg, source_seg_id),
        source_segment_id=source_seg_id,
        weight=1.0,
        metadata_json={"segment_index": seg.segment_index},
    )


def _make_contextual_text_unit(
    seg: RawSegmentData, source_seg_id: str | None = None,
) -> RetrievalUnitData | None:
    """Contextual text: enriched context beyond raw_text.

    - Tables: natural language description of structure
    - Lists: hierarchical summary using items_nested
    - Paragraphs: only when section context adds info not in raw_text
    """
    if seg.block_type == "heading":
        return None

    contextual_text = _build_contextual_content(seg)
    if not contextual_text:
        return None

    section_titles = [p.get("title", "") for p in seg.section_path if p.get("title")]

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
        source_refs_json=_build_source_refs(seg, source_seg_id),
        source_segment_id=source_seg_id,
        weight=0.6,
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
    """Generated question unit: one per LLM-generated question."""
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


def _is_questionworthy(seg: RawSegmentData) -> bool:
    """Filter segments that should receive question generation.

    Skips:
    - heading-only segments (just a title, no real content)
    - very short content (< 15 chars or < 10 tokens)
    """
    if seg.block_type == "heading":
        return False
    if seg.token_count is not None and seg.token_count < 10:
        return False
    if len(seg.raw_text.strip()) < 15:
        return False
    return True


def _build_contextual_content(seg: RawSegmentData) -> str:
    """Build contextual text content based on segment type.

    - Tables: natural language description
    - Lists: hierarchical summary
    - Paragraphs: only when section context adds information
    """
    if seg.block_type == "table":
        return _build_table_contextual(seg)
    elif seg.block_type == "list":
        return _build_list_contextual(seg)
    else:
        return _build_paragraph_contextual(seg)


def _build_table_contextual(seg: RawSegmentData) -> str:
    """Generate natural language description for table segments."""
    struct = seg.structure_json
    columns = struct.get("columns", [])
    rows = struct.get("rows", [])
    if not columns:
        return ""

    section_ctx = seg.section_title or "该表"
    parts = [f"在「{section_ctx}」中，包含 {len(rows)} 行数据，列包括：{'、'.join(columns)}。"]

    # Add column value examples from first row
    if rows:
        first_row = rows[0]
        col_descs = []
        for col in columns:
            val = first_row.get(col, "")
            if val:
                col_descs.append(f"{col}：{val}")
        if col_descs:
            parts.append("例如：" + "，".join(col_descs) + "。")

    return "\n".join(parts)


def _build_list_contextual(seg: RawSegmentData) -> str:
    """Generate hierarchical summary for list segments."""
    struct = seg.structure_json
    items_nested = struct.get("items_nested", [])
    items_flat = struct.get("items", [])

    section_ctx = seg.section_title or "以下"

    if items_nested:
        # Use nested items for richer context
        top_items = [it for it in items_nested if it.get("depth", 1) == 1]
        sub_items = [it for it in items_nested if it.get("depth", 1) > 1]
        parts = [f"在「{section_ctx}」中，共 {len(top_items)} 个主要条目"]
        if sub_items:
            parts.append(f"其中包含 {len(sub_items)} 个子项详情")
        return "，".join(parts) + "。"
    elif items_flat:
        return f"在「{section_ctx}」中，包含 {len(items_flat)} 个条目：{'、'.join(items_flat[:5])}。"
    return ""


def _build_paragraph_contextual(seg: RawSegmentData) -> str:
    """Generate contextual text for paragraphs only when section adds info."""
    if not seg.section_path:
        return ""

    # Extract section titles that don't appear in raw_text
    section_titles = [p.get("title", "") for p in seg.section_path if p.get("title")]
    extra_context = [t for t in section_titles if t and t not in seg.raw_text]
    if not extra_context:
        return ""

    context_prefix = " > ".join(extra_context)
    return f"[{context_prefix}]\n{seg.raw_text}"


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
        # Build natural language: "A为xxx，B为yyy，C为zzz"
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


def _make_contextual_enhanced_unit(
    seg: RawSegmentData,
    context_description: str,
    source_seg_id: str | None = None,
    llm_task_id: str | None = None,
) -> RetrievalUnitData:
    """Contextual-enhanced unit: LLM-generated context prepended to segment text.

    Uses Anthropic-style contextual retrieval where a brief context description
    is prepended to the raw text for improved retrieval accuracy.
    """
    enhanced_text = f"[{context_description}]\n{seg.raw_text}"
    section_titles = [p.get("title", "") for p in seg.section_path if p.get("title")]

    return RetrievalUnitData(
        segment_key=f"{seg.document_key}#{seg.segment_index}",
        unit_key=f"ru:{seg.document_key}#{seg.segment_index}:contextual_enhanced",
        unit_type="contextual_text",
        target_type="raw_segment",
        target_ref_json={
            "document_key": seg.document_key,
            "segment_index": seg.segment_index,
        },
        title=seg.section_title,
        text=enhanced_text,
        search_text=tokenize_for_search(enhanced_text),
        block_type=seg.block_type,
        semantic_role=seg.semantic_role,
        facets_json=_build_facets(seg),
        entity_refs_json=list(seg.entity_refs_json),
        source_refs_json=_build_source_refs(seg, source_seg_id),
        llm_result_refs_json=({"source": "contextual_retrieval", "task_id": llm_task_id} if llm_task_id else {"source": "contextual_retrieval"}),
        source_segment_id=source_seg_id,
        weight=0.9,
        metadata_json={
            "section_titles": section_titles,
            "segment_index": seg.segment_index,
            "context_description": context_description,
        },
    )
