"""Hot-pluggable pipeline architecture for Mining v1.2.

Defines:
- DocumentContext: per-document immutable pipeline state
- Segmenter Protocol
- PipelineConfig: composable pipeline configuration
- MiningPipeline: orchestrates per-document processing (sequential)
- StreamingPipeline: queue-based parallel pipeline (stages run concurrently)
"""
from __future__ import annotations

import logging
import uuid
from dataclasses import dataclass, field
from queue import Queue
from threading import Thread
from typing import Any, Callable

from knowledge_mining.mining.contracts.models import (
    DocumentProfile,
    RawFileData,
    RawSegmentData,
    RetrievalUnitData,
    SectionNode,
    SegmentRelationData,
)
from knowledge_mining.mining.contracts.protocols import Segmenter
from knowledge_mining.mining.snapshot import select_or_create_snapshot

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

    # Phase 1c fields (set by Phase 1a, consumed by db_write_stage)
    action: str | None = None
    existing_doc: dict | None = None
    embeddings: tuple[dict, ...] = ()
    document_id: str | None = None
    snapshot_id: str | None = None

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
            "action": self.action,
            "existing_doc": self.existing_doc,
            "embeddings": self.embeddings,
            "document_id": self.document_id,
            "snapshot_id": self.snapshot_id,
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
    enricher: Any | None = None  # Enricher Protocol（篇章本职：语义角色 + 内容质量）
    entity_extractor: Any | None = None  # EntityExtractor（本体线：双通道实体抽取，L4 §15）
    resolver: Any | None = None  # EntityResolver (B3 实体归一 + 人审分流)
    entity_relation_builder: Any | None = None  # EntityRelationBuilder (B4 概念关系抽取)
    question_generator: Any | None = None  # QuestionGenerator Protocol
    embedding_generator: Any | None = None  # EmbeddingGenerator Protocol
    discourse_relation_builder: Any | None = None  # DiscourseRelationBuilder
    contextualizer: Any | None = None  # Contextualizer Protocol
    domain_profile: Any | None = None  # DomainProfile

    # DB handles for db_write_stage (set by run.py)
    asset_db: Any | None = None
    runtime_db: Any | None = None
    tracker: Any | None = None
    batch_id: str | None = None


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

        # Stage 3a: Entity extract (本体线：双通道实体抽取，独立 LLM 调用)
        extractor = cfg.entity_extractor
        if extractor is not None and ctx.segments:
            if stage_callback:
                stage_callback("entity_extract", ctx)
            extracted = extractor.extract_batch(list(ctx.segments))
            ctx = ctx.with_updates(segments=tuple(extracted))

        # Stage 3b: Resolve (实体归一 + 人审分流)
        resolver = cfg.resolver
        if resolver is not None and ctx.segments:
            if stage_callback:
                stage_callback("resolve", ctx)
            resolved = resolver.resolve_batch(list(ctx.segments))
            ctx = ctx.with_updates(segments=tuple(resolved))

        # Stage 3c: Entity relations (pattern 约束抽概念关系)
        rel_builder = cfg.entity_relation_builder
        if rel_builder is not None and ctx.segments:
            if stage_callback:
                stage_callback("entity_relations", ctx)
            built = rel_builder.build_batch(list(ctx.segments))
            ctx = ctx.with_updates(segments=tuple(built))

        # Stage 4: Assign segment UUIDs
        if ctx.segments:
            from knowledge_mining.mining.stages.relations import build_seg_ids
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
            from knowledge_mining.mining.stages.retrieval_units import build_retrieval_units
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
    summary_fn: Callable[[DocumentContext], str | None] | None = None,
) -> None:
    """Worker thread: pull from in_q, run fn, emit start/end stage events, push to out_q.

    Stage events are emitted only when both run_id and tracker are provided AND
    the ctx carries a run_document_id. This keeps StreamingPipeline usable in
    test contexts where no tracker is wired.

    summary_fn (optional) maps a completed stage's result ctx to a short
    output_summary string (e.g. "segments=12") recorded on the end event — used
    by the run-document detail view to show per-stage产出计数. Failures inside
    summary_fn never break the pipeline (summary falls back to None).
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
                summary = None
                if summary_fn is not None:
                    try:
                        summary = summary_fn(result)
                    except Exception:
                        summary = None
                tracker.end_stage(evt_id, run_id, stage_name, output_summary=summary)
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
        stages: list[tuple],
        *,
        run_id: str | None = None,
        tracker: Any | None = None,
    ) -> None:
        """stages 元素为 (name, fn, n_workers) 或可选带第 4 项
        (name, fn, n_workers, summary_fn)，summary_fn 把完成 ctx 映射成 output_summary。"""
        self._stages = stages
        self._queues: list[Queue] = [Queue() for _ in range(len(stages) + 1)]
        self._threads: list[list[Thread]] = []

        for i, spec in enumerate(stages):
            name, fn, n = spec[0], spec[1], spec[2]
            summary_fn = spec[3] if len(spec) > 3 else None
            stage_threads = []
            for w in range(n):
                t = Thread(
                    target=_worker,
                    args=(name, fn, self._queues[i], self._queues[i + 1], run_id, tracker, summary_fn),
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
    segments = seg.segment(ctx.tree, ctx.profile, domain_profile=cfg.domain_profile)
    if not segments:
        return ctx.with_updates(segments=tuple(segments))
    from knowledge_mining.mining.stages.relations import build_seg_ids
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


def entity_extract_stage(ctx: DocumentContext, cfg: PipelineConfig) -> DocumentContext:
    """Stage 3a: 本体线实体抽取（双通道，独立 LLM 调用，L4 §15）。"""
    extractor = cfg.entity_extractor
    if extractor is None or not ctx.segments:
        return ctx
    extracted = extractor.extract_batch(list(ctx.segments))
    return ctx.with_updates(segments=tuple(extracted))


def resolve_stage(ctx: DocumentContext, cfg: PipelineConfig) -> DocumentContext:
    """Stage 3b: 实体归一 + 人审分流（给每个 mention 打 canonical_name + resolve_status）。"""
    resolver = cfg.resolver
    if resolver is None or not ctx.segments:
        return ctx
    resolved = resolver.resolve_batch(list(ctx.segments))
    return ctx.with_updates(segments=tuple(resolved))


def entity_relations_stage(ctx: DocumentContext, cfg: PipelineConfig) -> DocumentContext:
    """Stage 3c: 概念关系抽取（pattern 约束，产候选边写进 segment metadata）。"""
    builder = cfg.entity_relation_builder
    if builder is None or not ctx.segments:
        return ctx
    built = builder.build_batch(list(ctx.segments))
    return ctx.with_updates(segments=tuple(built))


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
    from knowledge_mining.mining.stages.retrieval_units import build_retrieval_units
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


def embedding_stage(ctx: DocumentContext, cfg: PipelineConfig) -> DocumentContext:
    """Stage 6: Generate embeddings for retrieval units (parallel HTTP to embedding API).

    Designed to run with multiple workers — each invocation is stateless and only
    makes HTTP calls to the embedding service.
    """
    gen = cfg.embedding_generator
    if gen is None or not ctx.retrieval_units:
        return ctx
    try:
        texts = [ru.text for ru in ctx.retrieval_units if ru.text]
        keys = [ru.unit_key for ru in ctx.retrieval_units if ru.text]
        if not texts:
            return ctx
        embeddings = gen.embed_batch(texts)
        if embeddings and len(embeddings) == len(texts):
            emb_data = tuple(
                {"unit_key": k, "vector": v}
                for k, v in zip(keys, embeddings)
                if v
            )
            return ctx.with_updates(embeddings=emb_data)
    except Exception as e:
        logger.warning("Embedding generation failed for %s: %s",
                        getattr(ctx.raw_file, "file_path", "?"), e)
    return ctx


def db_write_stage(ctx: DocumentContext, cfg: PipelineConfig) -> DocumentContext:
    """Stage 7: Write all results to DB (serial, 1 worker for thread safety).

    Handles: select_snapshot → UPDATE cleanup → commit_segments → build_relations
    → build_retrieval_units → insert embeddings → tracker.commit_document.

    On failure, calls tracker.fail_document and returns ctx with error set.
    """
    import json as _json

    asset_db = cfg.asset_db
    tracker = cfg.tracker
    batch_id = cfg.batch_id
    run_id = None  # not available in ctx; tracker uses run_document_id

    rd_id = ctx.run_document_id
    raw = ctx.raw_file
    doc_profile = ctx.profile

    # Skip if upstream error
    if ctx.error:
        if tracker and rd_id:
            tracker.fail_document(rd_id, ctx.error)
            try:
                cfg.runtime_db.commit()
            except Exception:
                pass
        return ctx

    # Skip if no parse tree
    if ctx.tree is None:
        if tracker and rd_id:
            tracker.skip_document(rd_id)
            try:
                cfg.runtime_db.commit()
            except Exception:
                pass
        return ctx

    try:
        segments = list(ctx.segments)
        relations = list(ctx.relations)
        seg_id_map = ctx.seg_ids
        retrieval_units = list(ctx.retrieval_units)

        # --- empty-content guard: 0 segments → skip, do NOT create a snapshot ---
        # A document that parsed but produced no segments must not leave an empty
        # snapshot behind (that is exactly what triggered the "Snapshot has no
        # segments" build failure). Skip it; the runtime ledger records it.
        if not segments:
            if tracker and rd_id:
                tracker.skip_document(rd_id)
                try:
                    cfg.runtime_db.commit()
                except Exception:
                    pass
            return ctx

        # --- resolve run_id (runtime DB, outside the asset transaction) ---
        if tracker and rd_id:
            _run_id = tracker._db._fetchone(
                "SELECT run_id FROM mining_run_documents WHERE id = %s", (rd_id,)
            )
            run_id = _run_id["run_id"] if _run_id else None

        action = ctx.action
        existing_doc = ctx.existing_doc
        ru_id_map: dict[str, str] = {}  # declared before the transaction for use by embeddings

        # ===================== atomic per-document write =====================
        # Everything that lands in asset_core for this document happens inside one
        # transaction: snapshot/link, old-snapshot cleanup, segments, relations,
        # retrieval units. On any error the whole block rolls back, leaving no
        # half-written ("snapshot but no segments") state behind.
        with asset_db.transaction():
            document_id, snapshot_id, link_id = select_or_create_snapshot(
                asset_db, raw, doc_profile, batch_id=batch_id,
            )

            # --- UPDATE cleanup: remove stale snapshot data (same transaction) ---
            if action == "UPDATE" and existing_doc is not None:
                old_links = asset_db._fetchall(
                    "SELECT document_snapshot_id FROM asset_document_snapshot_links "
                    "WHERE document_id = %s ORDER BY linked_at DESC",
                    (existing_doc["id"],),
                )
                for old_link in old_links[1:] if len(old_links) > 1 else []:
                    old_snap_id = old_link["document_snapshot_id"]
                    if old_snap_id == snapshot_id:
                        continue  # never wipe the snapshot we are about to fill
                    asset_db.delete_retrieval_units_by_snapshot(old_snap_id)
                    asset_db.delete_relations_by_snapshot(old_snap_id)
                    asset_db.delete_segments_by_snapshot(old_snap_id)

            # --- only write content when the snapshot is empty ---
            # existing_count > 0 means this exact content (same hash) was already
            # ingested by another document; the snapshot is shared, so we reuse it
            # and keep only the freshly-created link. existing_count == 0 covers
            # both brand-new snapshots and self-healing of prior empty shells.
            existing_count = asset_db.count_segments_by_snapshot(snapshot_id)
            if existing_count == 0:
                # --- commit_segments ---
                for seg in segments:
                    seg_key = f"{seg.document_key}#{seg.segment_index}"
                    seg_id = seg_id_map.get(seg_key, uuid.uuid4().hex)
                    asset_db.insert_raw_segment(
                        segment_id=seg_id,
                        document_snapshot_id=snapshot_id,
                        segment_key=seg_key,
                        segment_index=seg.segment_index,
                        block_type=seg.block_type,
                        semantic_role=seg.semantic_role,
                        section_path=seg.section_path,
                        section_title=seg.section_title,
                        raw_text=seg.raw_text,
                        normalized_text=seg.normalized_text,
                        content_hash=seg.content_hash,
                        normalized_hash=seg.normalized_hash,
                        token_count=seg.token_count,
                        structure_json=seg.structure_json,
                        source_offsets_json=seg.source_offsets_json,
                        entity_refs_json=seg.entity_refs_json,
                        metadata_json=seg.metadata_json,
                    )

                # --- build_relations ---
                for rel in relations:
                    src_id = seg_id_map.get(rel.source_segment_key, "")
                    tgt_id = seg_id_map.get(rel.target_segment_key, "")
                    if src_id and tgt_id:
                        asset_db.insert_segment_relation(
                            relation_id=uuid.uuid4().hex,
                            document_snapshot_id=snapshot_id,
                            source_segment_id=src_id,
                            target_segment_id=tgt_id,
                            relation_type=rel.relation_type,
                            weight=rel.weight,
                            confidence=rel.confidence,
                            distance=rel.distance,
                            metadata_json=rel.metadata_json,
                        )

                # --- build_retrieval_units ---
                for ru in retrieval_units:
                    unit_id = uuid.uuid4().hex
                    ru_id_map[ru.unit_key] = unit_id
                    asset_db.insert_retrieval_unit(
                        unit_id=unit_id,
                        document_snapshot_id=snapshot_id,
                        unit_key=ru.unit_key,
                        unit_type=ru.unit_type,
                        target_type=ru.target_type,
                        target_ref_json=ru.target_ref_json,
                        title=ru.title,
                        text=ru.text,
                        search_text=ru.search_text,
                        block_type=ru.block_type,
                        semantic_role=ru.semantic_role,
                        facets_json=ru.facets_json,
                        entity_refs_json=ru.entity_refs_json,
                        source_refs_json=ru.source_refs_json,
                        llm_result_refs_json=ru.llm_result_refs_json,
                        source_segment_id=ru.source_segment_id,
                        weight=ru.weight,
                        metadata_json=ru.metadata_json,
                    )
        # ===================== transaction committed here ====================

        # --- insert embeddings (outside the transaction, best-effort) ---
        # Embeddings are an auxiliary product: a document is valid without them,
        # so a failure here must NOT fail the document. Skipped on snapshot reuse
        # (ru_id_map empty) because those embeddings already exist.
        if ctx.embeddings and ru_id_map:
            try:
                for emb in ctx.embeddings:
                    unit_key = emb["unit_key"]
                    embedding_vec = emb["vector"]
                    if unit_key in ru_id_map and embedding_vec:
                        asset_db.insert_retrieval_embedding(
                            embedding_id=uuid.uuid4().hex,
                            retrieval_unit_id=ru_id_map[unit_key],
                            embedding_model="managed",
                            embedding_provider="llm_service",
                            text_kind="full",
                            embedding_dim=len(embedding_vec),
                            embedding_vector=_json.dumps(embedding_vec),
                            content_hash="",
                        )
            except Exception as emb_err:
                logger.warning(
                    "Embedding insert failed for %s (document still committed): %s",
                    getattr(raw, "file_path", "?"), emb_err,
                )

        # --- commit_document (runtime ledger) ---
        if tracker and rd_id:
            tracker.commit_document(rd_id, document_id, snapshot_id)
            cfg.runtime_db.commit()

        return ctx.with_updates(
            document_id=document_id,
            snapshot_id=snapshot_id,
        )

    except Exception as e:
        err_msg = str(e)[:500]
        logger.exception("db_write_stage failed for %s: %s",
                         getattr(raw, "file_path", "?"), err_msg)
        if tracker and rd_id:
            try:
                tracker.fail_document(rd_id, err_msg)
                cfg.runtime_db.commit()
            except Exception:
                logger.exception("tracker.fail_document also failed")
        return ctx.with_updates(error=err_msg)
