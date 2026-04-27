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
from typing import Any, Callable, Protocol, runtime_checkable

from knowledge_mining.mining.models import (
    DocumentProfile,
    RawFileData,
    RawSegmentData,
    RetrievalUnitData,
    SectionNode,
    SegmentRelationData,
)

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
        }
        current.update(kwargs)
        return DocumentContext(**current)


# ---------------------------------------------------------------------------
# Operator Protocols
# ---------------------------------------------------------------------------

@runtime_checkable
class Segmenter(Protocol):
    """Protocol for splitting a SectionNode tree into segments."""

    def segment(
        self, tree: SectionNode, profile: DocumentProfile, **kwargs: Any,
    ) -> list[RawSegmentData]: ...


@runtime_checkable
class RelationBuilder(Protocol):
    """Protocol for building segment relations."""

    def build(
        self, segments: list[RawSegmentData], **kwargs: Any,
    ) -> tuple[list[SegmentRelationData], dict[str, str]]: ...


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
    relation_builder: RelationBuilder | None = None
    question_generator: Any | None = None  # QuestionGenerator Protocol
    embedding_generator: Any | None = None  # EmbeddingGenerator Protocol
    discourse_relation_builder: Any | None = None  # DiscourseRelationBuilder
    contextualizer: Any | None = None  # Contextualizer Protocol


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
        tree = parser.parse(raw.content, raw.file_name, {})
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

        # Stage 4: Build relations
        if stage_callback:
            stage_callback("build_relations", ctx)
        rb = cfg.relation_builder
        if rb is not None and ctx.segments:
            relations, seg_ids = rb.build(list(ctx.segments))
            ctx = ctx.with_updates(
                relations=tuple(relations),
                seg_ids=seg_ids,
            )

        # Stage 4b: Build discourse relations (LLM-driven RST analysis)
        drb = cfg.discourse_relation_builder
        if drb is not None and ctx.segments and ctx.seg_ids:
            if stage_callback:
                stage_callback("discourse_relations", ctx)
            extra_relations = drb.build(list(ctx.segments), seg_ids=ctx.seg_ids)
            if extra_relations:
                all_relations = list(ctx.relations) + extra_relations
                ctx = ctx.with_updates(relations=tuple(all_relations))

        # Stage 5: Build retrieval units
        if stage_callback:
            stage_callback("build_retrieval_units", ctx)
        if ctx.segments:
            from knowledge_mining.mining.retrieval_units import build_retrieval_units
            units = build_retrieval_units(
                list(ctx.segments),
                seg_ids=ctx.seg_ids,
                document_key=profile.document_key if profile else "",
                question_generator=cfg.question_generator,
                contextualizer=cfg.contextualizer,
            )
            ctx = ctx.with_updates(retrieval_units=tuple(units))

        return ctx


# ---------------------------------------------------------------------------
# Streaming pipeline (queue-based parallel architecture)
# ---------------------------------------------------------------------------

_SENTINEL = object()


def _worker(fn: Callable[[DocumentContext], DocumentContext],
            in_q: Queue, out_q: Queue) -> None:
    """Worker thread: pull from in_q, call fn, push to out_q."""
    while True:
        item = in_q.get()
        if item is _SENTINEL:
            break
        try:
            result = fn(item)
            out_q.put(result)
        except Exception as e:
            logger.exception("Stage worker failed for %s", getattr(item, "raw_file", None))
            out_q.put(item.with_updates(error=str(e)[:500]))


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

    def __init__(self, stages: list[tuple[str, Callable[[DocumentContext], DocumentContext], int]]) -> None:
        self._stages = stages
        self._queues: list[Queue] = [Queue() for _ in range(len(stages) + 1)]
        self._threads: list[list[Thread]] = []

        for i, (name, fn, n) in enumerate(stages):
            stage_threads = []
            for w in range(n):
                t = Thread(
                    target=_worker,
                    args=(fn, self._queues[i], self._queues[i + 1]),
                    name=f"mining-{name}-{w}",
                    daemon=True,
                )
                t.start()
                stage_threads.append(t)
            self._threads.append(stage_threads)

    def process_all(self, items: list[DocumentContext]) -> list[DocumentContext]:
        """Submit all items, wait for completion, return results in output order."""
        n = len(items)
        for item in items:
            self._queues[0].put(item)

        # Send sentinels stage-by-stage to shut down workers
        for i, stage_threads in enumerate(self._threads):
            for _ in stage_threads:
                self._queues[i].put(_SENTINEL)
            for t in stage_threads:
                t.join()

        results: list[DocumentContext] = []
        while len(results) < n:
            results.append(self._queues[-1].get())
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
    tree = parser.parse(raw.content, raw.file_name, {})
    return ctx.with_updates(tree=tree)


def segment_stage(ctx: DocumentContext, cfg: PipelineConfig) -> DocumentContext:
    """Stage 2: Segment tree into raw segments."""
    seg = cfg.segmenter
    if seg is None or ctx.tree is None or ctx.profile is None:
        return ctx
    segments = seg.segment(ctx.tree, ctx.profile)
    return ctx.with_updates(segments=tuple(segments))


def enrich_stage(ctx: DocumentContext, cfg: PipelineConfig) -> DocumentContext:
    """Stage 3: Enrich segments (LLM or rule-based)."""
    enricher = cfg.enricher
    if enricher is None or not ctx.segments:
        return ctx
    enriched = enricher.enrich_batch(list(ctx.segments))
    return ctx.with_updates(segments=tuple(enriched))


def relations_stage(ctx: DocumentContext, cfg: PipelineConfig) -> DocumentContext:
    """Stage 4: Build structural relations."""
    rb = cfg.relation_builder
    if rb is None or not ctx.segments:
        return ctx
    relations, seg_ids = rb.build(list(ctx.segments))
    return ctx.with_updates(relations=tuple(relations), seg_ids=seg_ids)


def discourse_stage(ctx: DocumentContext, cfg: PipelineConfig) -> DocumentContext:
    """Stage 4b: Build discourse relations (LLM-driven RST analysis)."""
    drb = cfg.discourse_relation_builder
    if drb is None or not ctx.segments or not ctx.seg_ids:
        return ctx
    extra_relations = drb.build(list(ctx.segments), seg_ids=ctx.seg_ids)
    if extra_relations:
        all_relations = list(ctx.relations) + extra_relations
        return ctx.with_updates(relations=tuple(all_relations))
    return ctx


def retrieval_units_stage(ctx: DocumentContext, cfg: PipelineConfig) -> DocumentContext:
    """Stage 5: Build retrieval units."""
    if not ctx.segments:
        return ctx
    from knowledge_mining.mining.retrieval_units import build_retrieval_units
    profile = ctx.profile
    units = build_retrieval_units(
        list(ctx.segments),
        seg_ids=ctx.seg_ids,
        document_key=profile.document_key if profile else "",
        question_generator=cfg.question_generator,
        contextualizer=cfg.contextualizer,
    )
    return ctx.with_updates(retrieval_units=tuple(units))
