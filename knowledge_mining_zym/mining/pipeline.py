"""Hot-pluggable pipeline architecture for Mining v1.2.

Defines:
- DocumentContext: per-document immutable pipeline state
- Segmenter / RelationBuilder Protocols
- PipelineConfig: composable pipeline configuration
- MiningPipeline: orchestrates per-document processing (sequential)
- StreamingPipeline: queue-based parallel pipeline (stages run concurrently)
"""
from __future__ import annotations

import logging
from dataclasses import dataclass, field
from queue import Queue
from threading import Thread
from typing import Any, Callable

from knowledge_mining_zym.mining.contracts.models import (
    DocumentProfile,
    RawFileData,
    RawSegmentData,
    RetrievalUnitData,
    SectionNode,
    SegmentRelationData,
)
from knowledge_mining_zym.mining.contracts.protocols import Segmenter

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Per-document context (immutable between stages)
# ---------------------------------------------------------------------------

@dataclass(frozen=True)
class DocumentContext:
    """Per-document pipeline state, immutable between stages."""

    raw_file: RawFileData | None = None
    profile: DocumentProfile | None = None
    tree: SectionNode | None = None
    segments: tuple[RawSegmentData, ...] = ()
    relations: tuple[SegmentRelationData, ...] = ()
    seg_ids: dict[str, str] = field(default_factory=dict)
    retrieval_units: tuple[RetrievalUnitData, ...] = ()
    error: str | None = None
    run_document_id: str | None = None
    sequence_id: int = 0

    def with_updates(self, **kwargs: Any) -> DocumentContext:
        """Return a new DocumentContext with specified fields replaced."""
        current = {
            "raw_file": self.raw_file,
            "profile": self.profile,
            "tree": self.tree,
            "segments": self.segments,
            "relations": self.relations,
            "seg_ids": self.seg_ids,
            "retrieval_units": self.retrieval_units,
            "error": self.error,
            "run_document_id": self.run_document_id,
            "sequence_id": self.sequence_id,
        }
        current.update(kwargs)
        return DocumentContext(**current)


# ---------------------------------------------------------------------------
# Operator Protocols
# ---------------------------------------------------------------------------

# ---------------------------------------------------------------------------
# Pipeline configuration
# ---------------------------------------------------------------------------

@dataclass
class PipelineConfig:
    """Composable pipeline configuration.

    Each field is a pluggable operator. Swap any operator to customize behavior.
    """

    parser_factory: Callable[[str], Any] = field(default=None)
    segmenter: Segmenter | None = None
    enricher: Any | None = None  # Enricher Protocol
    question_generator: Any | None = None  # QuestionGenerator Protocol
    embedding_generator: Any | None = None  # EmbeddingGenerator Protocol
    discourse_relation_builder: Any | None = None  # DiscourseRelationBuilder
    contextualizer: Any | None = None  # Contextualizer Protocol
    domain_profile: Any | None = None  # DomainProfile


# ---------------------------------------------------------------------------
# Mining pipeline
# ---------------------------------------------------------------------------

class MiningPipeline:
    """Orchestrates per-document processing using pluggable operators."""

    def __init__(self, config: PipelineConfig) -> None:
        self._config = config

    @property
    def config(self) -> PipelineConfig:
        return self._config

    def process_document(
        self,
        ctx: DocumentContext,
        *,
        stage_callback: Any | None = None,
    ) -> DocumentContext:
        """Run all per-document pipeline stages.

        Args:
            ctx: Initial document context (must have raw_file set).
            stage_callback: Optional callback(stage_name, ctx) for tracking.

        Returns:
            Final DocumentContext with all stages populated.
        """
        cfg = self._config

        # Stage 1: Parse
        if stage_callback:
            stage_callback("parse", ctx)
        raw = ctx.raw_file
        if raw is None:
            return ctx
        parser = cfg.parser_factory(raw.file_type) if cfg.parser_factory else None
        if parser is None:
            return ctx
        tree = parser.parse(raw.content, raw.file_name, {"file_path": raw.file_path})
        ctx = ctx.with_updates(tree=tree)

        if tree is None:
            return ctx

        # Stage 2: Segment
        if stage_callback:
            stage_callback("segment", ctx)
        seg = cfg.segmenter
        if seg is None:
            return ctx
        profile = ctx.profile
        if profile is None:
            return ctx
        segments = seg.segment(tree, profile)
        ctx = ctx.with_updates(segments=tuple(segments))

        # Stage 3: Enrich
        if stage_callback:
            stage_callback("enrich", ctx)
        enricher = cfg.enricher
        if enricher is not None and ctx.segments:
            enriched = enricher.enrich_batch(list(ctx.segments))
            ctx = ctx.with_updates(segments=tuple(enriched))

        # Stage 4: Assign segment UUIDs
        if ctx.segments:
            from knowledge_mining_zym.mining.stages.relations import build_seg_ids
            ctx = ctx.with_updates(seg_ids=build_seg_ids(list(ctx.segments)))

        # Stage 4b: Build discourse relations (LLM-driven RST analysis)
        drb = cfg.discourse_relation_builder
        if drb is not None and ctx.segments:
            if stage_callback:
                stage_callback("discourse_relations", ctx)
            discourse_relations = drb.build(list(ctx.segments), seg_ids=ctx.seg_ids)
            if discourse_relations:
                ctx = ctx.with_updates(relations=tuple(discourse_relations))

        # Stage 5: Build retrieval units
        if stage_callback:
            stage_callback("build_retrieval_units", ctx)
        if ctx.segments:
            from knowledge_mining_zym.mining.stages.retrieval_units import build_retrieval_units
            units = build_retrieval_units(
                list(ctx.segments),
                seg_ids=ctx.seg_ids,
                document_key=profile.document_key if profile else "",
                question_generator=cfg.question_generator,
                contextualizer=cfg.contextualizer,
                profile=cfg.domain_profile,
            )
            ctx = ctx.with_updates(retrieval_units=tuple(units))

        return ctx


# ---------------------------------------------------------------------------
# Streaming pipeline (queue-based parallel architecture)
# ---------------------------------------------------------------------------

_SENTINEL = object()


def _worker(
    stage_name: str,
    fn: Callable[[DocumentContext], DocumentContext],
    in_q: Queue,
    out_q: Queue,
    run_id: str | None,
    tracker: Any | None,
) -> None:
    """Worker thread: pull from in_q, run fn, emit start/end stage events, push to out_q.

    Stage events are emitted only when both run_id and tracker are provided AND
    the ctx carries a run_document_id. This keeps StreamingPipeline usable in
    test contexts where no tracker is wired.
    """
    while True:
        item = in_q.get()
        if item is _SENTINEL:
            break

        rd_id = getattr(item, "run_document_id", None)
        emit = tracker is not None and run_id is not None and rd_id is not None
        # Skip event emission if the document already errored upstream.
        if emit and item.error:
            out_q.put(item)
            continue

        evt_id = None
        if emit:
            try:
                evt_id = tracker.start_stage(run_id, stage_name, rd_id)
            except Exception:
                logger.exception("tracker.start_stage failed for stage=%s", stage_name)
                evt_id = None

        try:
            result = fn(item)
        except Exception as e:
            err_msg = str(e)[:500]
            # 同时把异常打到 stderr，便于控制台直接看到失败原因（不止落 DB）
            logger.exception(
                "stage=%s failed for run_document_id=%s: %s",
                stage_name, rd_id, err_msg,
            )
            if evt_id is not None:
                try:
                    tracker.end_stage(evt_id, run_id, stage_name,
                                      status="failed", error_message=err_msg)
                except Exception:
                    logger.exception("tracker.end_stage(failed) failed for stage=%s", stage_name)
            out_q.put(item.with_updates(error=err_msg))
            continue

        if evt_id is not None:
            try:
                tracker.end_stage(evt_id, run_id, stage_name)
            except Exception:
                logger.exception("tracker.end_stage failed for stage=%s", stage_name)
        out_q.put(result)


class StreamingPipeline:
    """Queue-based parallel pipeline. Each stage runs in its own thread(s).

    Usage::

        stages = [
            ("parse",   parse_fn,   1),
            ("enrich",  enrich_fn,  4),  # 4 concurrent workers
            ("publish", publish_fn, 1),
        ]
        pipeline = StreamingPipeline(stages)
        results = pipeline.process_all(items)
    """

    def __init__(
        self,
        stages: list[tuple[str, Callable[[DocumentContext], DocumentContext], int]],
        *,
        run_id: str | None = None,
        tracker: Any | None = None,
    ) -> None:
        self._stages = stages
        self._queues: list[Queue] = [Queue() for _ in range(len(stages) + 1)]
        self._threads: list[list[Thread]] = []

        for i, (name, fn, n) in enumerate(stages):
            stage_threads = []
            for w in range(n):
                t = Thread(
                    target=_worker,
                    args=(name, fn, self._queues[i], self._queues[i + 1], run_id, tracker),
                    name=f"mining-{name}-{w}",
                    daemon=True,
                )
                t.start()
                stage_threads.append(t)
            self._threads.append(stage_threads)

    def process_all(self, items: list[DocumentContext]) -> list[DocumentContext]:
        """Submit all items, wait for completion, return results in input order."""
        n = len(items)
        for i, item in enumerate(items):
            self._queues[0].put(item.with_updates(sequence_id=i))

        # Send sentinels stage-by-stage to shut down workers
        for i, stage_threads in enumerate(self._threads):
            for _ in stage_threads:
                self._queues[i].put(_SENTINEL)
            for t in stage_threads:
                t.join()

        results: list[DocumentContext] = []
        while len(results) < n:
            results.append(self._queues[-1].get())
        results.sort(key=lambda ctx: ctx.sequence_id)
        return results


# ---------------------------------------------------------------------------
# Stage functions for StreamingPipeline (closures bind PipelineConfig)
# ---------------------------------------------------------------------------

def parse_stage(ctx: DocumentContext, cfg: PipelineConfig) -> DocumentContext:
    """Stage 1: Parse raw file into SectionNode tree."""
    raw = ctx.raw_file
    if raw is None:
        return ctx
    parser = cfg.parser_factory(raw.file_type) if cfg.parser_factory else None
    if parser is None:
        return ctx
    tree = parser.parse(raw.content, raw.file_name, {"file_path": raw.file_path})
    return ctx.with_updates(tree=tree)


def segment_stage(ctx: DocumentContext, cfg: PipelineConfig) -> DocumentContext:
    """Stage 2: Segment tree into raw segments + assign stable seg UUIDs.

    seg_ids are computed here (not in a separate stage) because the work is
    trivial in-memory work and the DB CHECK constraint on stage_events does
    not allocate a slot for a standalone 'seg_ids' stage.
    """
    seg = cfg.segmenter
    if seg is None or ctx.tree is None or ctx.profile is None:
        return ctx
    segments = seg.segment(ctx.tree, ctx.profile)
    if not segments:
        return ctx.with_updates(segments=tuple(segments))
    from knowledge_mining_zym.mining.stages.relations import build_seg_ids
    return ctx.with_updates(
        segments=tuple(segments),
        seg_ids=build_seg_ids(list(segments)),
    )


def enrich_stage(ctx: DocumentContext, cfg: PipelineConfig) -> DocumentContext:
    """Stage 3: Enrich segments (LLM or rule-based)."""
    enricher = cfg.enricher
    if enricher is None or not ctx.segments:
        return ctx
    enriched = enricher.enrich_batch(list(ctx.segments))
    return ctx.with_updates(segments=tuple(enriched))


def discourse_stage(ctx: DocumentContext, cfg: PipelineConfig) -> DocumentContext:
    """Stage 4b: Build discourse relations (LLM-driven RST analysis)."""
    drb = cfg.discourse_relation_builder
    if drb is None or not ctx.segments:
        return ctx
    discourse_relations = drb.build(list(ctx.segments), seg_ids=ctx.seg_ids)
    if discourse_relations:
        return ctx.with_updates(relations=tuple(discourse_relations))
    return ctx


def retrieval_units_stage(ctx: DocumentContext, cfg: PipelineConfig) -> DocumentContext:
    """Stage 5: Build retrieval units."""
    if not ctx.segments:
        return ctx
    from knowledge_mining_zym.mining.stages.retrieval_units import build_retrieval_units
    profile = ctx.profile
    units = build_retrieval_units(
        list(ctx.segments),
        seg_ids=ctx.seg_ids,
        document_key=profile.document_key if profile else "",
        question_generator=cfg.question_generator,
        contextualizer=cfg.contextualizer,
        profile=cfg.domain_profile,
    )
    return ctx.with_updates(retrieval_units=tuple(units))
