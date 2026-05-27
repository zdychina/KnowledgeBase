"""v3.1 Mining pipeline orchestrator — PostgreSQL backend.

Two entry points:
- run(input_path, phase1_only=False): full or phase1-only pipeline
- publish(run_id): publish a completed run's build

StreamingPipeline stages per document:
  parse -> segment -> enrich -> discourse -> retrieval_units -> embedding -> db_write

Global stages:
  assemble_build -> validate_build -> publish_release
"""
from __future__ import annotations

import logging
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

logger = logging.getLogger(__name__)


class MiningCancelled(Exception):
    """Raised internally when a checkpoint observes mining_runs.status='cancelled'.

    Caught at the top of _run_pipeline; never propagates out of run().
    """


def _check_cancelled(runtime_db: "MiningRuntimeDB", run_id: str) -> None:
    """Cooperative cancel checkpoint.

    Reads the current run row's status from PG; raises MiningCancelled if the
    UI (or anyone else) has flipped it to 'cancelled'. Cheap (<1ms point query).
    """
    row = runtime_db._fetchone(
        "SELECT status FROM mining_runs WHERE id = %s", (run_id,)
    )
    if row and row["status"] == "cancelled":
        raise MiningCancelled()


from knowledge_mining.mining.infra.db import AssetCoreDB, MiningRuntimeDB
from knowledge_mining.mining.infra.pg_config import MiningDbConfig, conninfo_from_env
from knowledge_mining.mining.infra.pg_schema import ensure_schema
from knowledge_mining.mining.contracts.models import (
    BatchParams,
    DocumentProfile,
    MiningRunData,
    MiningRunDocumentData,
)
from knowledge_mining.mining.runtime import RuntimeTracker
from knowledge_mining.mining.ingestion import ingest_directory
from knowledge_mining.mining.stages.parse import create_parser
from knowledge_mining.mining.stages.segment import DefaultSegmenter
from knowledge_mining.mining.stages.publishing import assemble_build, classify_documents, demo_quality_summary, publish_release
from knowledge_mining.mining.infra.domain_pack import DomainProfile, load_domain_pack, resolve_domain
from knowledge_mining.mining.pipeline import (
    DocumentContext, PipelineConfig,
    StreamingPipeline,
    parse_stage, segment_stage, enrich_stage,
    discourse_stage, retrieval_units_stage,
    embedding_stage, db_write_stage,
)


def _create_dbs(
    cfg: MiningDbConfig | None = None,
    conninfo: str | None = None,
) -> tuple[AssetCoreDB, MiningRuntimeDB]:
    """Create and open PG-backed database adapters.

    Args:
        cfg: MiningDbConfig for the legacy PG_HOST/PG_PORT path.
        conninfo: Explicit psycopg conninfo string (from per-domain URL).
                  If provided, cfg is ignored for connection but still used for pool sizing.
    """
    if conninfo:
        # Per-domain connection from registry URL
        pool_min, pool_max = 2, 10
        if cfg:
            pool_min, pool_max = cfg.pg_pool_min, cfg.pg_pool_max
        from psycopg_pool import ConnectionPool
        pool = ConnectionPool(
            conninfo,
            min_size=pool_min,
            max_size=pool_max,
            open=True,
            kwargs={"row_factory": __import__("psycopg").rows.dict_row},
        )
    else:
        # Legacy path: all from MiningDbConfig
        if cfg is None:
            cfg = MiningDbConfig()
        ensure_schema(cfg)
        from psycopg_pool import ConnectionPool
        pool = ConnectionPool(
            cfg.conninfo,
            min_size=cfg.pg_pool_min,
            max_size=cfg.pg_pool_max,
            open=True,
            kwargs={"row_factory": __import__("psycopg").rows.dict_row},
        )
    asset_db = AssetCoreDB(pool)
    runtime_db = MiningRuntimeDB(pool)
    return asset_db, runtime_db


def run(
    input_path: str | Path,
    *,
    db_config: MiningDbConfig | None = None,
    batch_params: BatchParams | None = None,
    phase1_only: bool = False,
    publish_on_partial_failure: bool = False,
    llm_base_url: str | None = None,
    llm_bypass_proxy: bool | None = None,
    embedding_api_key: str | None = None,
    embedding_model: str | None = None,
    embedding_base_url: str | None = None,
    embedding_dimensions: int | None = None,
    max_workers: int | None = None,
    domain: str | None = None,
    domain_pack: str | None = None,
    channel: str | None = None,
) -> dict[str, Any]:
    """Execute the mining pipeline.

    Args:
        input_path: Directory to scan for documents
        db_config: PostgreSQL config (reads from .env if not provided)
        batch_params: Batch-level configuration
        phase1_only: If True, stop after document-level processing (no build/publish)
        publish_on_partial_failure: If True, publish even when some docs failed.
        llm_base_url: LLM service URL (e.g. "http://localhost:8900"). None = from env.
        llm_bypass_proxy: If True, bypass system proxy for LLM calls. None = from env.
        embedding_api_key: Embedding API key (only for direct Zhipu fallback).
        embedding_model: Embedding model name. None = from env.
        embedding_base_url: Direct embedding API base URL (fallback). None = from env.
        embedding_dimensions: Embedding vector dimensions. None = from env.
        domain: Domain ID to load from registry. None = from env.
        domain_pack: (Deprecated) Use domain instead.
        channel: Release channel. None = from registry default_channel.
        max_workers: Max concurrent workers for streaming pipeline. None = from env.

    Returns:
        Summary dict with run_id, counts, and status.
    """
    import warnings as _w

    # Backward compat: domain_pack → domain
    if domain_pack and not domain:
        _w.warn(
            "domain_pack is deprecated; use domain instead",
            DeprecationWarning,
            stacklevel=2,
        )
        domain = domain_pack

    from knowledge_mining.mining.infra.mining_config import MiningConfig
    cfg = MiningConfig()

    # Resolve all None params from config (explicit args take precedence)
    llm_base_url = llm_base_url or cfg.llm_service_url
    llm_bypass_proxy = llm_bypass_proxy if llm_bypass_proxy is not None else cfg.mining_llm_bypass_proxy
    embedding_model = embedding_model or cfg.embedding_model
    embedding_base_url = embedding_base_url or ""
    embedding_dimensions = embedding_dimensions or cfg.embedding_dimensions
    max_workers = max_workers or cfg.max_workers
    domain = domain or cfg.domain

    input_path = Path(input_path)
    batch_params = batch_params or BatchParams()
    params = batch_params

    # Resolve domain from registry
    conninfo: str | None = None
    try:
        registry_entry = resolve_domain(domain)
        env_var = registry_entry.get("database_url_env")
        if env_var:
            conninfo = conninfo_from_env(env_var)
        if channel is None:
            channel = registry_entry.get("default_channel", "prod")
    except (FileNotFoundError, KeyError, ValueError) as e:
        logger.warning("Registry resolution failed for domain '%s': %s; using fallback config", domain, e)
        if channel is None:
            channel = "prod"

    # Load domain profile
    profile = load_domain_pack(domain)

    # Open databases (PostgreSQL) — per-domain conninfo if available
    asset_db, runtime_db = _create_dbs(db_config, conninfo=conninfo)

    # Pre-generate run_id so we can fail_run on global exception
    run_id = uuid.uuid4().hex

    # LLM integration: create question generator if URL provided
    llm_services = _init_llm(llm_base_url, llm_bypass_proxy, profile, knowledge_domain=profile.domain_id)

    # Embedding integration: prefer llm_service, fallback to direct Zhipu
    embedding_generator = _init_embedding(
        llm_base_url, embedding_api_key, embedding_model, embedding_base_url, embedding_dimensions,
        knowledge_domain=profile.domain_id,
    )

    try:
        return _run_pipeline(
            asset_db, runtime_db, input_path, params, phase1_only, run_id,
            publish_on_partial_failure, llm_services, embedding_generator,
            max_workers, profile, channel=channel,
        )
    except MiningCancelled:
        return {"run_id": run_id, "status": "cancelled"}
    except Exception as e:
        try:
            tracker = RuntimeTracker(runtime_db)
            tracker.fail_run(run_id, error_summary=str(e)[:500])
        except Exception:
            pass
        raise
    finally:
        asset_db.close()
        runtime_db.close()


def publish(
    run_id: str,
    *,
    domain: str = "cloud_core_network",
    db_config: MiningDbConfig | None = None,
    channel: str | None = None,
    released_by: str | None = None,
) -> dict[str, Any]:
    """Publish a completed run's build as an active release.

    Args:
        run_id: Mining run ID to publish.
        domain: Domain ID (used to resolve per-domain DB connection).
        db_config: PostgreSQL config (fallback if registry URL unavailable).
        channel: Release channel. None = from registry default_channel.
        released_by: Who triggered the publish.
    """
    # Resolve per-domain connection
    conninfo: str | None = None
    try:
        registry_entry = resolve_domain(domain)
        env_var = registry_entry.get("database_url_env")
        if env_var:
            conninfo = conninfo_from_env(env_var)
        if channel is None:
            channel = registry_entry.get("default_channel", "prod")
    except (FileNotFoundError, KeyError, ValueError):
        if channel is None:
            channel = "prod"

    asset_db, runtime_db = _create_dbs(db_config, conninfo=conninfo)

    try:
        run_data = runtime_db.get_run(run_id)
        if run_data is None:
            raise ValueError(f"Run {run_id} not found")
        if run_data["status"] != "completed":
            raise ValueError(f"Run {run_id} status is {run_data['status']}, expected completed")
        build_id = run_data["build_id"]
        if not build_id:
            raise ValueError(f"Run {run_id} has no build_id")

        # Read domain from build row for domain isolation
        build_row = asset_db._fetchone(
            "SELECT domain FROM asset_builds WHERE id = %s", (build_id,)
        )
        domain = build_row["domain"] if build_row else None

        release_id = publish_release(
            asset_db,
            build_id=build_id,
            channel=channel,
            released_by=released_by,
            release_notes=f"Published from run {run_id}",
            domain=domain,
        )

        return {"run_id": run_id, "build_id": build_id, "release_id": release_id}
    finally:
        asset_db.close()
        runtime_db.close()


# ===================================================================
# Internal pipeline implementation
# ===================================================================

def _init_llm(
    llm_base_url: str | None,
    bypass_proxy: bool = False,
    profile: DomainProfile | None = None,
    *,
    knowledge_domain: str | None = None,
) -> dict[str, Any] | None:
    """Initialize LLM services if URL provided.

    Registers templates from profile if llm_service is reachable.
    Returns dict with question_generator, enricher, discourse_relation_builder, contextualizer, or None.
    """
    if not llm_base_url:
        return None

    from knowledge_mining.mining.infra.llm_client import LlmClient
    from knowledge_mining.mining.infra.llm_templates import build_templates_from_profile
    from knowledge_mining.mining.stages.retrieval_units import LlmQuestionGenerator

    client = LlmClient(base_url=llm_base_url, bypass_proxy=bypass_proxy)
    if not client.health_check():
        logger.warning("LLM service at %s unreachable, proceeding without LLM", llm_base_url)
        return None

    # Register templates from profile (idempotent)
    if profile is None:
        from knowledge_mining.mining.infra.domain_pack import get_default_profile
        profile = get_default_profile()
    templates = build_templates_from_profile(profile, domain_id=knowledge_domain or profile.domain_id)
    for tpl in templates:
        client.register_template(tpl)

    result: dict[str, Any] = {
        "question_generator": LlmQuestionGenerator(
            base_url=llm_base_url, bypass_proxy=bypass_proxy, profile=profile,
            knowledge_domain=knowledge_domain,
        ),
    }

    # v1.2: Try to create LlmEnricher if available
    try:
        from knowledge_mining.mining.stages.enrich import LlmEnricher
        result["enricher"] = LlmEnricher(
            base_url=llm_base_url,
            bypass_proxy=bypass_proxy,
            profile=profile,
            knowledge_domain=knowledge_domain,
        )
    except (ImportError, Exception):
        pass

    # v1.2: Create DiscourseRelationBuilder
    try:
        from knowledge_mining.mining.stages.relations import DiscourseRelationBuilder
        result["discourse_relation_builder"] = DiscourseRelationBuilder(
            base_url=llm_base_url, bypass_proxy=bypass_proxy,
            knowledge_domain=knowledge_domain, profile=profile,
        )
    except (ImportError, Exception):
        pass

    # v1.2: Create LLMContextualizer (skip if contextual_retrieval is off)
    if profile.retrieval_policy.contextual_retrieval != "off":
        try:
            from knowledge_mining.mining.stages.retrieval_units import LLMContextualizer
            result["contextualizer"] = LLMContextualizer(
                base_url=llm_base_url, bypass_proxy=bypass_proxy,
                knowledge_domain=knowledge_domain,
            )
        except (ImportError, Exception):
            pass

    return result


def _init_embedding(
    llm_base_url: str | None,
    api_key: str | None,
    model: str,
    base_url: str,
    dimensions: int | None,
    *,
    knowledge_domain: str | None = None,
) -> Any | None:
    """Prefer shared llm_service embedding endpoint, fallback to direct Zhipu client.

    All params are resolved by the caller (run()) from MiningConfig — no defaults here.
    """
    if llm_base_url:
        from knowledge_mining.mining.infra.embedding import LLMServiceEmbeddingGenerator

        return LLMServiceEmbeddingGenerator(
            base_url=llm_base_url,
            model=model,
            dimensions=dimensions,
            knowledge_domain=knowledge_domain,
        )

    if not api_key:
        return None

    from knowledge_mining.mining.infra.embedding import ZhipuEmbeddingGenerator
    return ZhipuEmbeddingGenerator(
        api_key=api_key,
        model=model,
        base_url=base_url,
        dimensions=dimensions,
    )


def _run_pipeline(
    asset_db: AssetCoreDB,
    runtime_db: MiningRuntimeDB,
    input_path: Path,
    params: BatchParams,
    phase1_only: bool,
    run_id: str,
    publish_on_partial_failure: bool = False,
    llm_services: dict[str, Any] | None = None,
    embedding_generator: Any | None = None,
    max_workers: int = 4,
    profile: DomainProfile | None = None,
    channel: str | None = None,
) -> dict[str, Any]:
    """Core pipeline logic. Assumes DBs are already open."""
    tracker = RuntimeTracker(runtime_db)
    llm = llm_services or {}
    if profile is None:
        from knowledge_mining.mining.infra.domain_pack import get_default_profile
        profile = get_default_profile()

    now = _utcnow()

    # Phase 1: Ingest
    docs, ingest_summary = ingest_directory(input_path, params)

    # Create batch in asset_core (before create_run so batch_id is available)
    batch_id = uuid.uuid4().hex

    tracker.create_run(MiningRunData(
        id=run_id,
        source_batch_id=batch_id,
        input_path=str(input_path),
        domain=profile.domain_id,
        channel=channel,
        status="running",
        total_documents=len(docs),
        started_at=now,
        metadata_json={"ingest_summary": ingest_summary},
    ))
    runtime_db.commit()
    asset_db.upsert_source_batch(
        batch_id=batch_id,
        batch_code=f"batch-{run_id[:8]}",
        source_type=params.default_source_type,
        domain=profile.domain_id,
        description=f"Mining run {run_id}",
    )
    asset_db.commit()

    # Build pipeline config with pluggable operators (profile-driven)
    pipeline_config = PipelineConfig(
        parser_factory=create_parser,
        segmenter=DefaultSegmenter(),
        enricher=llm.get("enricher"),
        question_generator=llm.get("question_generator"),
        embedding_generator=embedding_generator,
        discourse_relation_builder=llm.get("discourse_relation_builder"),
        contextualizer=llm.get("contextualizer"),
        domain_profile=profile,
        asset_db=asset_db,
        runtime_db=runtime_db,
        tracker=tracker,
        batch_id=batch_id,
    )

    committed_count = 0
    new_count = 0
    updated_count = 0
    failed_count = 0
    skipped_count = 0
    snapshot_decisions: list[dict[str, Any]] = []

    # -- Phase 1a: Classify all docs, register in runtime, handle SKIP --
    _check_cancelled(runtime_db, run_id)
    work_items: list[dict[str, Any]] = []  # docs that need pipeline processing

    for doc in docs:
        rd_id = uuid.uuid4().hex
        doc_key = f"doc:/{doc.relative_path}"

        existing_doc = asset_db.get_document_by_key(doc_key)
        if existing_doc is None:
            action = "NEW"
        else:
            # Compare against active snapshot's hash (not asset_documents)
            active_link = asset_db._fetchone(
                "SELECT ds.normalized_content_hash "
                "FROM asset_document_snapshot_links dsl "
                "JOIN asset_document_snapshots ds ON dsl.document_snapshot_id = ds.id "
                "WHERE dsl.document_id = %s ORDER BY dsl.linked_at DESC LIMIT 1",
                (existing_doc["id"],),
            )
            if active_link and active_link["normalized_content_hash"] == doc.normalized_content_hash:
                action = "SKIP"
            else:
                action = "UPDATE"

        tracker.register_document(MiningRunDocumentData(
            id=rd_id,
            run_id=run_id,
            document_key=doc_key,
            raw_content_hash=doc.raw_content_hash,
            normalized_content_hash=doc.normalized_content_hash,
            action=action,
        ))
        runtime_db.commit()

        # SKIP: content unchanged
        if action == "SKIP" and existing_doc is not None:
            existing_link = asset_db._fetchone(
                "SELECT document_snapshot_id FROM asset_document_snapshot_links "
                "WHERE document_id = %s ORDER BY linked_at DESC LIMIT 1",
                (existing_doc["id"],),
            )
            if existing_link:
                tracker.commit_document(rd_id, existing_doc["id"], existing_link["document_snapshot_id"])
                skipped_count += 1
                snapshot_decisions.append({
                    "document_id": existing_doc["id"],
                    "document_snapshot_id": existing_link["document_snapshot_id"],
                    "document_key": doc_key,
                })
                runtime_db.commit()
                continue

        # Queue for streaming pipeline
        tracker.start_document(rd_id)
        runtime_db.commit()
        doc_profile = DocumentProfile(
            document_key=doc_key,
            source_type=doc.source_type or params.default_source_type,
            document_type=doc.document_type or params.default_document_type,
            scope_json=doc.scope_json,
            tags_json=doc.tags_json,
            title=doc.title,
        )
        ctx = DocumentContext(
            raw_file=doc, profile=doc_profile, run_document_id=rd_id,
            action=action, existing_doc=existing_doc,
        )
        work_items.append({
            "doc": doc,
            "rd_id": rd_id,
            "doc_key": doc_key,
            "action": action,
            "existing_doc": existing_doc,
            "doc_profile": doc_profile,
            "ctx": ctx,
        })

    # -- Phase 1b: Run streaming pipeline (all non-SKIP docs concurrently) --
    _check_cancelled(runtime_db, run_id)
    ctxs: list[DocumentContext] = []
    if work_items:
        config = pipeline_config
        stages = [
            ("parse",            lambda ctx: parse_stage(ctx, config),           1),
            ("segment",          lambda ctx: segment_stage(ctx, config),         1),
            ("enrich",           lambda ctx: enrich_stage(ctx, config),          max_workers),
            ("discourse",        lambda ctx: discourse_stage(ctx, config),       min(max_workers, 2)),
            ("retrieval_units",  lambda ctx: retrieval_units_stage(ctx, config), max_workers),
            ("embedding",        lambda ctx: embedding_stage(ctx, config),       max_workers),
            ("db_write",         lambda ctx: db_write_stage(ctx, config),        1),
        ]

        pipeline = StreamingPipeline(stages, run_id=run_id, tracker=tracker)
        ctxs = pipeline.process_all([item["ctx"] for item in work_items])

    # -- Aggregate results from pipeline (Phase 1c is now inside db_write_stage) --
    for ctx in ctxs:
        action = ctx.action or "NEW"
        rd_id = ctx.run_document_id
        doc_key = ctx.profile.document_key if ctx.profile else ""

        if ctx.error:
            failed_count += 1
        elif ctx.document_id and ctx.snapshot_id:
            committed_count += 1
            if action == "NEW":
                new_count += 1
            elif action == "UPDATE":
                updated_count += 1
            snapshot_decisions.append({
                "document_id": ctx.document_id,
                "document_snapshot_id": ctx.snapshot_id,
                "document_key": doc_key,
            })
        else:
            skipped_count += 1

    # Phase 2: Build & Publish (unless phase1_only)
    build_id = None
    release_id = None
    has_failures = failed_count > 0

    # Build is always created if there are committed documents
    if not phase1_only and snapshot_decisions:
        # Classify documents: NEW/UPDATE/SKIP against previous active build
        # REMOVE detection disabled — incremental batches only process a subset,
        # parent build snapshots are carried forward by assemble_build instead.
        snapshot_decisions = classify_documents(asset_db, snapshot_decisions, detect_remove=False, domain=profile.domain_id)

        # Stage 7: Assemble build (auto-selects full vs incremental)
        evt = tracker.start_stage(run_id, "assemble_build")
        build_id = assemble_build(
            asset_db,
            run_id=run_id,
            batch_id=batch_id,
            snapshot_decisions=snapshot_decisions,
            domain=profile.domain_id,
        )
        tracker.end_stage(evt, run_id, "assemble_build", output_summary=f"build_id={build_id}")
        asset_db.commit()
        runtime_db.commit()

        # Demo quality summary (non-blocking, writes to build metadata)
        try:
            quality = demo_quality_summary(asset_db, build_id)
            logger.info("Demo quality summary: %s", quality)
        except Exception as e:
            logger.warning("Demo quality summary failed: %s", e)

        # Stage 8: Validate (already done inside assemble_build)
        evt = tracker.start_stage(run_id, "validate_build")
        tracker.end_stage(evt, run_id, "validate_build", output_summary="passed")
        runtime_db.commit()

        # Stage 9: Publish release — only if no failures or explicitly allowed
        if not has_failures or publish_on_partial_failure:
            evt = tracker.start_stage(run_id, "publish_release")
            release_id = publish_release(
                asset_db,
                build_id=build_id,
                released_by=f"run:{run_id}",
                domain=profile.domain_id,
            )
            tracker.end_stage(evt, run_id, "publish_release", output_summary=f"release_id={release_id}")
            asset_db.commit()
            runtime_db.commit()

    # Determine final run status (use SQL-valid values only)
    # All docs failed -> "failed"; some failed -> "completed" with has_failures metadata
    run_status = "completed"
    run_metadata = None
    if failed_count > 0 and committed_count == 0:
        run_status = "failed"
    elif failed_count > 0:
        run_metadata = {"has_failures": True, "failed_count": failed_count}

    if run_status == "failed":
        tracker.fail_run(
            run_id,
            error_summary=f"All {failed_count} documents failed",
            committed_count=committed_count,
            failed_count=failed_count,
            skipped_count=skipped_count,
            new_count=new_count,
            updated_count=updated_count,
        )
    else:
        tracker.complete_run(
            run_id,
            build_id=build_id,
            committed_count=committed_count,
            failed_count=failed_count,
            skipped_count=skipped_count,
            new_count=new_count,
            updated_count=updated_count,
            metadata_json=run_metadata,
        )
    runtime_db.commit()

    return {
        "run_id": run_id,
        "status": run_status,
        "total_documents": len(docs),
        "committed_count": committed_count,
        "new_count": new_count,
        "updated_count": updated_count,
        "failed_count": failed_count,
        "skipped_count": skipped_count,
        "build_id": build_id,
        "release_id": release_id,
    }


def _utcnow() -> str:
    from datetime import timezone
    return datetime.now(timezone.utc).isoformat()
