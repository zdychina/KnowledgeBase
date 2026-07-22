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

import json
import logging
import uuid
from contextlib import contextmanager
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

logger = logging.getLogger(__name__)


def decide_document_lifecycle_action(
    state: dict[str, Any] | None,
    *,
    normalized_content_hash: str,
) -> str:
    """Pure NEW/SKIP/RESTORE/UPDATE decision for one domain document."""
    if state is None or not state.get("document_id"):
        return "NEW"

    active_snapshot_id = state.get("active_snapshot_id")
    if (
        active_snapshot_id
        and state.get("active_snapshot_hash") == normalized_content_hash
        and bool(state.get("active_snapshot_complete"))
    ):
        return "SKIP"

    if (
        not active_snapshot_id
        and state.get("historical_snapshot_id")
        and state.get("historical_snapshot_hash") == normalized_content_hash
        and bool(state.get("historical_snapshot_complete"))
    ):
        return "RESTORE"

    return "UPDATE"


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
from knowledge_mining.mining.infra.domain_db import (
    ResolvedDomainDatabase,
    ensure_domain_database_schema,
    resolve_domain_database,
)
from knowledge_mining.mining.infra.pg_config import MiningDbConfig
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
    parse_stage, segment_stage, enrich_stage, entity_extract_stage, resolve_stage,
    entity_relations_stage, discourse_stage, retrieval_units_stage,
    embedding_stage, db_write_stage,
)


def _create_dbs(
    resolved: ResolvedDomainDatabase,
) -> tuple[AssetCoreDB, MiningRuntimeDB]:
    """Create and open PG-backed adapters for one resolved domain database."""
    ensure_domain_database_schema(resolved)
    from psycopg_pool import ConnectionPool
    pool = ConnectionPool(
        resolved.conninfo,
        min_size=resolved.pool_min,
        max_size=resolved.pool_max,
        open=True,
        check=ConnectionPool.check_connection,
        max_idle=300.0,
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
    max_workers: int | None = None,
    domain: str | None = None,
    domain_pack: str | None = None,
    channel: str | None = None,
    run_id: str | None = None,
) -> dict[str, Any]:
    """Execute a run, reusing an API-precreated queued row when supplied."""
    import warnings as _w

    if domain_pack and not domain:
        _w.warn(
            "domain_pack is deprecated; use domain instead",
            DeprecationWarning,
            stacklevel=2,
        )
        domain = domain_pack

    from knowledge_mining.mining.infra.mining_config import MiningConfig
    cfg = MiningConfig()
    llm_base_url = llm_base_url or cfg.llm_service_url
    max_workers = max_workers or cfg.max_workers
    domain = domain or cfg.domain
    input_path = Path(input_path)
    params = batch_params or BatchParams()
    registry_entry = resolve_domain(domain)
    resolved_db = resolve_domain_database(registry_entry, db_config or MiningDbConfig())
    channel = channel or registry_entry.get("default_channel", "prod")

    asset_db, runtime_db = _create_dbs(resolved_db)
    tracker = RuntimeTracker(runtime_db)
    submitted_run_id = run_id
    run_id = run_id or uuid.uuid4().hex
    run_domain = str(registry_entry.get("id") or domain)

    try:
        if submitted_run_id is None:
            tracker.create_run(MiningRunData(
                id=run_id,
                input_path=str(input_path),
                domain=run_domain,
                channel=channel,
                status="queued",
                current_stage="queued",
                started_at=_utcnow(),
            ))
        else:
            existing = runtime_db.get_run(run_id)
            if existing is None:
                raise ValueError(f"Run {run_id} does not exist")
            if existing.get("domain") != run_domain:
                raise ValueError(f"Run {run_id} belongs to another domain")
            if Path(existing.get("input_path") or "") != input_path:
                raise ValueError(f"Run {run_id} input_path does not match submission")
            channel = existing["channel"]
            if existing.get("status") not in ("queued", "running"):
                return {"run_id": run_id, "status": existing["status"]}

        if not tracker.set_run_phase(run_id, run_domain, "ingest"):
            row = runtime_db.get_run(run_id) or {}
            return {"run_id": run_id, "status": row.get("status", "cancelled")}
        ingest_event = tracker.start_stage(run_id, "ingest")

        try:
            profile = load_domain_pack(domain)
            from knowledge_mining.mining.infra.ontology_store import OntologyStore
            ontology_store = OntologyStore(asset_db.pool)
            llm_services = _init_llm(
                llm_base_url, profile,
                knowledge_domain=profile.domain_id,
                ontology_store=ontology_store,
            )
            embedding_generator = _init_embedding(
                llm_base_url,
                knowledge_domain=profile.domain_id,
            )
            docs, ingest_summary = ingest_directory(input_path, params)
        except Exception as exc:
            if (runtime_db.get_run(run_id) or {}).get("status") == "cancelled":
                return {"run_id": run_id, "status": "cancelled"}
            tracker.end_stage(
                ingest_event, run_id, "ingest", status="failed",
                error_message=str(exc)[:500],
            )
            tracker.fail_run(
                run_id, str(exc)[:500], current_stage="ingest", domain=run_domain,
            )
            raise

        tracker.end_stage(
            ingest_event, run_id, "ingest",
            output_summary=f"documents={len(docs)}",
        )
        _check_cancelled(runtime_db, run_id)
        if not tracker.finish_ingest(run_id, run_domain, len(docs), ingest_summary):
            row = runtime_db.get_run(run_id) or {}
            return {"run_id": run_id, "status": row.get("status", "cancelled")}

        return _run_pipeline(
            asset_db, runtime_db, input_path, params, phase1_only, run_id,
            publish_on_partial_failure, llm_services, embedding_generator,
            max_workers, profile, channel=channel, llm_base_url=llm_base_url,
            docs=docs, ingest_summary=ingest_summary,
        )
    except MiningCancelled:
        return {"run_id": run_id, "status": "cancelled"}
    except Exception as exc:
        try:
            row = runtime_db.get_run(run_id) or {}
            tracker.fail_run(
                run_id, str(exc)[:500],
                current_stage=row.get("current_stage") or "mining",
                domain=run_domain,
            )
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
    registry_entry = resolve_domain(domain)
    resolved_db = resolve_domain_database(
        registry_entry, db_config or MiningDbConfig()
    )
    if channel is None:
        channel = registry_entry.get("default_channel", "prod")

    asset_db, runtime_db = _create_dbs(resolved_db)

    try:
        run_data = runtime_db.get_run(run_id)
        if run_data is None:
            raise ValueError(f"Run {run_id} not found")
        if run_data["status"] != "completed":
            raise ValueError(f"Run {run_id} status is {run_data['status']}, expected completed")
        if run_data.get("domain") != domain:
            raise ValueError(
                f"Run {run_id} belongs to domain {run_data.get('domain')!r}, "
                f"cannot publish under domain {domain!r}"
            )
        build_id = run_data["build_id"]
        if not build_id:
            raise ValueError(f"Run {run_id} has no build_id")

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


def resume(
    run_id: str,
    *,
    domain: str = "cloud_core_network",
    db_config: MiningDbConfig | None = None,
    publish_on_partial_failure: bool = False,
) -> dict[str, Any]:
    """B6：人审提交后续跑一个 awaiting_review 的 run。

    幂等地重新评估两道 Gate：
    - 仍有待审本体候选 / pending mention → 保持 awaiting_review，刷新 subloop_stage 后返回；
    - 两道 Gate 都清空 → 从 graph_write 之后续跑（建库 + 发布），不重抽文档。

    snapshot_decisions / 计数从 mining_run_documents 重建（首跑的内存态已随进程退出丢失）。
    """
    registry_entry = resolve_domain(domain)
    resolved_db = resolve_domain_database(
        registry_entry, db_config or MiningDbConfig()
    )
    asset_db, runtime_db = _create_dbs(resolved_db)
    try:
        run_data = runtime_db.get_run(run_id)
        if run_data is None:
            raise ValueError(f"Run {run_id} not found")
        # 可续跑的两种入口：
        #   ① 人审暂停（awaiting_review）——正常路径；
        #   ② 收尾阶段中断、卡在 running/done 的恢复——两道 Gate 已审完、stage 推进到 done，
        #      但 _finalize 过程中进程异常退出（finished_at 仍为空）。允许重新进来把收尾幂等地跑完。
        status = run_data["status"]
        stage = run_data.get("subloop_stage")
        is_resumable = status == "awaiting_review" or (status == "running" and stage == "done")
        if not is_resumable:
            raise ValueError(
                f"Run {run_id} status is {status}"
                f"{f'/{stage}' if stage else ''}, expected awaiting_review (or running/done for recovery)")

        domain = run_data.get("domain") or domain
        profile = load_domain_pack(domain)
        tracker = RuntimeTracker(runtime_db)
        prev_stage = run_data.get("subloop_stage")

        from knowledge_mining.mining.infra.mining_config import MiningConfig
        llm_base_url = MiningConfig().llm_service_url

        # 实体确认：仍有 pending mention → 留在 entity_review。
        if _has_pending_mentions(asset_db, run_id):
            updated = runtime_db.update_run_status(
                run_id, "awaiting_review", subloop_stage="entity_review",
                current_stage="review", domain=domain,
                expected_statuses=("awaiting_review", "running"),
            )
            if not updated:
                current = runtime_db.get_run(run_id) or {}
                return {"run_id": run_id, "status": current.get("status", "cancelled")}
            runtime_db.commit()
            logger.info("Run %s still awaiting review at gate=entity_review", run_id)
            return {"run_id": run_id, "status": "awaiting_review", "subloop_stage": "entity_review"}

        # 实体确认刚清空（上一步停在 entity_review）→ 跑全局B 归纳类型候选，再交本体确认。
        if prev_stage == "entity_review":
            _run_induction(asset_db, tracker, run_id, profile, llm_base_url)

        # 本体确认：有待审类型候选 → 留在 ontology_review。
        if _has_proposed_candidates(asset_db, domain):
            updated = runtime_db.update_run_status(
                run_id, "awaiting_review", subloop_stage="ontology_review",
                current_stage="review", domain=domain,
                expected_statuses=("awaiting_review", "running"),
            )
            if not updated:
                current = runtime_db.get_run(run_id) or {}
                return {"run_id": run_id, "status": current.get("status", "cancelled")}
            runtime_db.commit()
            logger.info("Run %s still awaiting review at gate=ontology_review", run_id)
            return {"run_id": run_id, "status": "awaiting_review", "subloop_stage": "ontology_review"}

        # 两道 Gate 清完 → 收尾建图（回贴类型 + 建边）+ 建库/发布。
        if not tracker.resume_running(run_id, subloop_stage="done", domain=domain):
            current = runtime_db.get_run(run_id) or {}
            return {"run_id": run_id, "status": current.get("status", "cancelled")}
        runtime_db.commit()
        _finalize_graph(asset_db, tracker, run_id, profile)
        snapshot_decisions, counts = _rebuild_from_run_documents(runtime_db, run_id)
        return _finalize_run(
            asset_db, runtime_db, tracker, run_id, run_data["source_batch_id"],
            snapshot_decisions, counts, run_data["total_documents"],
            False, publish_on_partial_failure, profile,
            channel=run_data["channel"],
        )
    finally:
        asset_db.close()
        runtime_db.close()


def _check_review_gate(asset_db: AssetCoreDB, run_id: str, domain_id: str) -> str | None:
    """B6/N4：返回该 run 当前命中的人审 Gate，都无则 None（快速通道放行）。

    **反转闸序（L2 §15.1）：实体确认在前，本体确认在后。**
    先把"暂无类型/有歧义"的实体让人确认干净，再用确认过的实体归纳类型给人审，
    避免在脏实体上提议类型。pending mention 清完才轮到本体候选。
    """
    if _has_pending_mentions(asset_db, run_id):
        return "entity_review"
    if _has_proposed_candidates(asset_db, domain_id):
        return "ontology_review"
    return None


def _has_pending_mentions(asset_db: AssetCoreDB, run_id: str) -> bool:
    """实体确认：该 run 是否还有待人确认的实体 mention。"""
    from knowledge_mining.mining.infra.ontology_store import GraphStore
    return GraphStore(asset_db.pool).count_pending_mentions_for_run(run_id) > 0


def _has_proposed_candidates(asset_db: AssetCoreDB, domain_id: str) -> bool:
    """本体确认：该 domain 是否还有待人确认的 node_type 候选。"""
    from knowledge_mining.mining.infra.ontology_store import OntologyStore
    return OntologyStore(asset_db.pool).count_proposed_candidates(domain_id) > 0


def _run_induction(
    asset_db: AssetCoreDB,
    tracker: Any,
    run_id: str,
    profile: DomainProfile,
    llm_base_url: str | None,
) -> dict[str, int] | None:
    """全局B（实体确认之后、本体确认之前）：从人确认的 __untyped__ 实体归纳 node_type 候选（N3）。

    无 active 本体 / 无 LLM / 确认实体太少 → 安静跳过。失败不阻断（记日志）。
    """
    if not llm_base_url:
        return None
    domain_id = profile.domain_id
    try:
        from knowledge_mining.mining.infra.ontology_store import OntologyStore, GraphStore
        from knowledge_mining.mining.stages.ontology_induction import OntologyInductor

        ostore = OntologyStore(asset_db.pool)
        if ostore.active_version(domain_id) is None:
            return None
        evt = tracker.start_stage(run_id, "ontology_induction")
        inductor = OntologyInductor(
            base_url=llm_base_url,
            graph_store=GraphStore(asset_db.pool),
            ontology_store=ostore,
            domain_id=domain_id,
            knowledge_domain=domain_id,
        )
        summary = inductor.induce()
        asset_db.commit()
        tracker.end_stage(evt, run_id, "ontology_induction", output_summary=str(summary))
        logger.info("ontology_induction done for %s: %s", domain_id, summary)
        return summary
    except Exception:
        logger.warning("ontology_induction failed for %s; continuing", domain_id, exc_info=True)
        return None


def _finalize_graph(
    asset_db: AssetCoreDB,
    tracker: Any,
    run_id: str,
    profile: DomainProfile,
) -> dict[str, int] | None:
    """收尾建图（本体确认之后，L2 §15.1 末段）：回贴类型 → 关系抽取 + 终态建边。

    1) N5 回贴：把本体确认批准类型的成员实体 __untyped__ → 正式类型名；
    2) 从 DB 已确认 mention 重聚合候选边（按 active 本体 allowed_pairs + NPMI），落事实边。
    边只连"已确认且类型已定"的 canonical 对象。无 active 本体则跳过。失败不阻断发布。
    """
    domain_id = profile.domain_id
    try:
        from knowledge_mining.mining.infra.ontology_store import OntologyStore, GraphStore
        from knowledge_mining.mining.stages.graph_write import reaggregate_edges, persist_edges

        ostore = OntologyStore(asset_db.pool)
        active = ostore.active_version(domain_id)
        if active is None:
            return None
        gstore = GraphStore(asset_db.pool)

        # 1) 回贴（N5）：成员实体补绑本体确认批准的正式类型，必须在读 mention 当前类型之前做。
        members = ostore.accepted_node_type_members(domain_id)
        n_rebound = gstore.rebind_untyped_entities(domain_id, members) if members else 0

        # 2) 终态建边：从已确认 mention 重聚合（实体当前类型已是回贴后的正式类型）。
        evt = tracker.start_stage(run_id, "graph_write_final")
        rel_builder = _init_relation_builder(asset_db, profile)
        rows = gstore.resolved_mentions_for_run(run_id)

        # 3) 计数权威重算：从全部已确认 mention（auto+human）按实体聚合，mention_count=提及行数、
        #    document_count=去重文档数，set 置准——把实体确认人审 merge/new 进来的提及也算上，
        #    并矫正 resolve_mention 的即时 +1（以这里为准，幂等）。
        n_recounted = _recount_entities(gstore, rows)

        bg, entity_ids = reaggregate_edges(rows, domain_id=domain_id, relation_builder=rel_builder)
        n_edges = persist_edges(
            gstore, bg, entity_ids,
            domain_id=domain_id, ontology_version_id=active["id"],
        )
        asset_db.commit()
        summary = {"rebound": n_rebound, "recounted": n_recounted, "edges": n_edges}
        tracker.end_stage(evt, run_id, "graph_write_final", output_summary=str(summary))
        logger.info("graph_write_final done for %s: %s", domain_id, summary)
        return summary
    except Exception:
        logger.warning("graph_write_final failed for %s; continuing", domain_id, exc_info=True)
        return None


def _recount_entities(gstore: Any, mention_rows: list[dict[str, Any]]) -> int:
    """从全部已确认 mention 按实体聚合重算计数，set 置准。返回被重算的实体数。

    mention_count = 该实体的提及行数；document_count = 去重文档快照数（同文档多条不翻倍）。
    覆盖全局A的自动计数 + 实体确认人审 merge/new 的提及，是计数的权威终态。
    """
    from collections import defaultdict
    ment: dict[str, int] = defaultdict(int)
    docs: dict[str, set] = defaultdict(set)
    for r in mention_rows:
        eid = r.get("entity_id")
        if not eid:
            continue
        ment[eid] += 1
        snap = r.get("document_snapshot_id")
        if snap:
            docs[eid].add(snap)
    for eid, mc in ment.items():
        gstore.set_entity_counts(eid, mention_count=mc, document_count=len(docs[eid]))
    return len(ment)


def _rebuild_from_run_documents(
    runtime_db: MiningRuntimeDB, run_id: str,
) -> tuple[list[dict[str, Any]], dict[str, int]]:
    """从 mining_run_documents 重建 snapshot_decisions + 计数（resume 用，内存态已丢）。"""
    snapshot_decisions: list[dict[str, Any]] = []
    committed = new = updated = failed = skipped = 0
    for rd in runtime_db.get_run_documents(run_id):
        st = rd["status"]
        raw_metadata = rd.get("metadata_json") or {}
        if isinstance(raw_metadata, str):
            try:
                parsed_metadata = json.loads(raw_metadata)
            except (TypeError, ValueError):
                parsed_metadata = {}
        else:
            parsed_metadata = raw_metadata
        metadata = parsed_metadata if isinstance(parsed_metadata, dict) else {}

        if st == "committed" and rd["document_id"] and rd["document_snapshot_id"]:
            if rd["action"] == "SKIP":
                skipped += 1
                decision = {
                    "document_id": rd["document_id"],
                    "document_snapshot_id": rd["document_snapshot_id"],
                    "document_key": rd["document_key"],
                    "lifecycle_action": metadata.get("lifecycle_action") or "SKIP",
                }
                if "source_batch_id" in metadata:
                    decision["source_batch_id"] = metadata["source_batch_id"]
                snapshot_decisions.append(decision)
                continue

            committed += 1
            if rd["action"] == "NEW":
                new += 1
            elif rd["action"] == "UPDATE":
                updated += 1
            snapshot_decisions.append({
                "document_id": rd["document_id"],
                "document_snapshot_id": rd["document_snapshot_id"],
                "document_key": rd["document_key"],
            })
        elif st == "failed":
            failed += 1
        elif st == "skipped":
            skipped += 1
    counts = {
        "committed_count": committed, "new_count": new, "updated_count": updated,
        "failed_count": failed, "skipped_count": skipped,
    }
    return snapshot_decisions, counts


# ===================================================================
# Internal pipeline implementation
# ===================================================================

def _init_llm(
    llm_base_url: str | None,
    profile: DomainProfile | None = None,
    *,
    knowledge_domain: str | None = None,
    ontology_store: Any | None = None,
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

    client = LlmClient(base_url=llm_base_url)
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
            base_url=llm_base_url, profile=profile,
            knowledge_domain=knowledge_domain,
        ),
    }

    # v1.2: Try to create LlmEnricher if available（篇章本职，不再读本体类型）
    try:
        from knowledge_mining.mining.stages.enrich import LlmEnricher
        result["enricher"] = LlmEnricher(
            base_url=llm_base_url,
            profile=profile,
            knowledge_domain=knowledge_domain,
        )
    except (ImportError, Exception):
        pass

    # L4 §15: 本体线实体抽取（独立 LLM 调用，双通道，喂 active 本体类型表）
    try:
        from knowledge_mining.mining.stages.entity_extract import EntityExtractor
        result["entity_extractor"] = EntityExtractor(
            base_url=llm_base_url,
            profile=profile,
            knowledge_domain=knowledge_domain,
            ontology_store=ontology_store,
            domain_id=knowledge_domain or (profile.domain_id if profile else None),
        )
    except (ImportError, Exception):
        pass

    # v1.2: Create DiscourseRelationBuilder
    try:
        from knowledge_mining.mining.stages.relations import DiscourseRelationBuilder
        result["discourse_relation_builder"] = DiscourseRelationBuilder(
            base_url=llm_base_url,
            knowledge_domain=knowledge_domain, profile=profile,
        )
    except (ImportError, Exception):
        pass

    # v1.2: Create LLMContextualizer (skip if contextual_retrieval is off)
    if profile.retrieval_policy.contextual_retrieval != "off":
        try:
            from knowledge_mining.mining.stages.retrieval_units import LLMContextualizer
            result["contextualizer"] = LLMContextualizer(
                base_url=llm_base_url,
                knowledge_domain=knowledge_domain,
            )
        except (ImportError, Exception):
            pass

    return result


def _init_resolver(asset_db: AssetCoreDB, profile: DomainProfile | None) -> Any | None:
    """B3 实体归一器：读领域别名词典建内存索引，与 enrich 共用 asset_db 连接池。"""
    if profile is None:
        return None
    try:
        from knowledge_mining.mining.infra.ontology_store import OntologyStore
        from knowledge_mining.mining.stages.resolve import EntityResolver
        return EntityResolver(
            ontology_store=OntologyStore(asset_db.pool),
            domain_id=profile.domain_id,
        )
    except Exception:
        logger.warning("resolver init failed; skipping entity resolution", exc_info=True)
        return None


def _init_relation_builder(asset_db: AssetCoreDB, profile: DomainProfile | None) -> Any | None:
    """B4 概念关系抽取器：读 active 本体关系类型拿 allowed_pairs，共用 asset_db 连接池。"""
    if profile is None:
        return None
    try:
        from knowledge_mining.mining.infra.ontology_store import OntologyStore
        from knowledge_mining.mining.stages.entity_relations import EntityRelationBuilder
        return EntityRelationBuilder(
            ontology_store=OntologyStore(asset_db.pool),
            domain_id=profile.domain_id,
        )
    except Exception:
        logger.warning("relation builder init failed; skipping entity relations", exc_info=True)
        return None


def _run_graph_write(
    asset_db: AssetCoreDB,
    tracker: Any,
    run_id: str,
    ctxs: list,
    domain_id: str,
) -> dict[str, int] | None:
    """B5 全局落图：聚合本 build 所有文档 → 写 canonical 实体/边/出处/mention + 候选。

    仅当该领域已引种本体（有 active 版本）才跑；未引种则跳过（本体能力未启用）。
    失败不阻断整轮（落图是增量能力，失败只记日志）。
    """
    good = [c for c in ctxs if getattr(c, "snapshot_id", None) and not getattr(c, "error", None)]
    if not good:
        return None
    try:
        from knowledge_mining.mining.infra.ontology_store import OntologyStore, GraphStore
        from knowledge_mining.mining.stages.graph_write import (
            aggregate_build, persist_entities_and_mentions,
        )

        ostore = OntologyStore(asset_db.pool)
        active = ostore.active_version(domain_id)
        if active is None:
            logger.info("no active ontology for %s; skip graph_write (B5)", domain_id)
            return None

        evt = tracker.start_stage(run_id, "graph_write")
        gstore = GraphStore(asset_db.pool)
        bg = aggregate_build(good, domain_id=domain_id)
        # 全局A（实体确认之前）：只落实体 + mention + 出处 + 关系候选，**不建边**。
        # 事实边后移到本体确认通过、类型回贴之后由 _finalize_graph 从 DB 重聚合（L2 §15.1）。
        summary, _entity_ids = persist_entities_and_mentions(
            gstore, ostore, bg,
            domain_id=domain_id, ontology_version_id=active["id"],
        )
        asset_db.commit()
        tracker.end_stage(evt, run_id, "graph_write", output_summary=str(summary))
        logger.info("graph_write (global-A) done for %s: %s", domain_id, summary)
        return summary
    except Exception:
        logger.warning("graph_write (B5) failed for %s; continuing", domain_id, exc_info=True)
        return None


def _init_embedding(
    llm_base_url: str | None,
    *,
    knowledge_domain: str | None = None,
) -> Any | None:
    """Initialize embedding via llm_service.

    Model name and dimensions are managed by llm_service — caller does not pass them.
    Returns None if llm_base_url is not configured.
    """
    if not llm_base_url:
        return None

    from knowledge_mining.mining.infra.embedding import LLMServiceEmbeddingGenerator
    return LLMServiceEmbeddingGenerator(
        base_url=llm_base_url,
        knowledge_domain=knowledge_domain,
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
    llm_base_url: str | None = None,
    docs: list[Any] | None = None,
    ingest_summary: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Core pipeline logic. Assumes DBs are already open."""
    tracker = RuntimeTracker(runtime_db)
    llm = llm_services or {}
    if profile is None:
        from knowledge_mining.mining.infra.domain_pack import get_default_profile
        profile = get_default_profile()

    docs = docs or []
    ingest_summary = ingest_summary or {}
    channel = channel or "prod"

    # Create batch in asset_core (before create_run so batch_id is available)
    batch_id = uuid.uuid4().hex

    _check_cancelled(runtime_db, run_id)
    asset_db.upsert_source_batch(
        batch_id=batch_id,
        batch_code=f"batch-{run_id[:8]}",
        source_type=params.default_source_type,
        domain=profile.domain_id,
        description=f"Mining run {run_id}",
    )
    asset_db.commit()
    runtime_db._execute(
        "UPDATE mining_runs SET source_batch_id = %s WHERE id = %s AND domain = %s "
        "AND status IN ('queued', 'running')",
        (batch_id, run_id, profile.domain_id),
    )
    _check_cancelled(runtime_db, run_id)

    # 本体线总开关（开始时检测一次）：该领域未引种本体（无 active 版本）→
    # 关掉本体线的所有阶段——每文档的 entity_extract / resolve / entity_relations，
    # 以及全局的 graph_write / ontology_induction / finalize_graph 和两道人审 Gate。
    # 篇章线（parse→segment→enrich→discourse→retrieval_units→embedding→db_write）
    # 不受影响，照常跑出检索库。
    from knowledge_mining.mining.infra.ontology_store import OntologyStore
    has_ontology = OntologyStore(asset_db.pool).active_version(profile.domain_id) is not None
    if not has_ontology:
        logger.info(
            "Domain '%s' has no active ontology; skipping all ontology-line stages "
            "(entity_extract, resolve, entity_relations, graph_write, induction, finalize, review gates).",
            profile.domain_id,
        )

    # Build pipeline config with pluggable operators (profile-driven).
    # 本体线算子在无本体时置 None：对应的 streaming 阶段自带 `if X is None: return ctx`
    # 的短路，于是退化成零成本的直通，不发起任何 LLM/DB 调用。
    pipeline_config = PipelineConfig(
        domain=profile.domain_id,
        parser_factory=create_parser,
        segmenter=DefaultSegmenter(),
        enricher=llm.get("enricher"),
        entity_extractor=llm.get("entity_extractor") if has_ontology else None,
        resolver=_init_resolver(asset_db, profile) if has_ontology else None,
        entity_relation_builder=(
            _init_relation_builder(asset_db, profile) if has_ontology else None
        ),
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
        _check_cancelled(runtime_db, run_id)
        rd_id = uuid.uuid4().hex
        doc_key = f"doc:/{doc.relative_path}"

        lifecycle_state = asset_db.get_document_lifecycle_state(
            domain=profile.domain_id,
            channel=channel,
            document_key=doc_key,
            normalized_content_hash=doc.normalized_content_hash,
        )
        lifecycle_action = decide_document_lifecycle_action(
            lifecycle_state,
            normalized_content_hash=doc.normalized_content_hash,
        )
        action = "SKIP" if lifecycle_action in ("SKIP", "RESTORE") else lifecycle_action
        existing_doc = None
        if lifecycle_state is not None:
            existing_doc = {
                "id": lifecycle_state["document_id"],
                "domain": lifecycle_state["document_domain"],
                "document_key": lifecycle_state["document_key"],
            }

        run_document_metadata: dict[str, Any] = {"file_size": doc.file_size}
        # 摄取期预处理失败（PDF 抽文本 / HTML→md / CHM 解包 / doc→docx）只被记进
        # RawFileData.metadata_json，而这类文档不会建快照 —— 不在这里带上，原因就
        # 只剩日志里有，库里查不到。
        _pre_err = (doc.metadata_json or {}).get("preprocess_error")
        if _pre_err:
            run_document_metadata["preprocess_error"] = str(_pre_err)
        if lifecycle_action == "SKIP":
            # Persist the published selection's provenance so resume can rebuild
            # the same decision after the in-memory list has been lost.
            run_document_metadata["source_batch_id"] = lifecycle_state.get(
                "active_source_batch_id"
            )
            run_document_metadata["skip_reason"] = "unchanged"
        elif lifecycle_action == "RESTORE":
            run_document_metadata.update({
                "lifecycle_action": "RESTORE",
                "source_batch_id": batch_id,
                "skip_reason": "restored",
            })

        tracker.register_document(MiningRunDocumentData(
            id=rd_id,
            run_id=run_id,
            document_key=doc_key,
            raw_content_hash=doc.raw_content_hash,
            normalized_content_hash=doc.normalized_content_hash,
            action=action,
            metadata_json=run_document_metadata,
        ))
        runtime_db.commit()

        if lifecycle_action == "SKIP" and lifecycle_state is not None:
            tracker.commit_document(
                rd_id,
                lifecycle_state["document_id"],
                lifecycle_state["active_snapshot_id"],
            )
            skipped_count += 1
            snapshot_decisions.append({
                "document_id": lifecycle_state["document_id"],
                "document_snapshot_id": lifecycle_state["active_snapshot_id"],
                "document_key": doc_key,
                "lifecycle_action": "SKIP",
                "source_batch_id": lifecycle_state.get("active_source_batch_id"),
            })
            runtime_db.commit()
            continue

        if lifecycle_action == "RESTORE" and lifecycle_state is not None:
            snapshot_id = lifecycle_state["historical_snapshot_id"]
            asset_db.insert_snapshot_link(
                domain=profile.domain_id,
                link_id=uuid.uuid4().hex,
                document_id=lifecycle_state["document_id"],
                document_snapshot_id=snapshot_id,
                source_batch_id=batch_id,
                relative_path=doc.relative_path,
                source_uri=doc.source_uri,
                title=doc.title,
                scope_json=doc.scope_json,
                tags_json=doc.tags_json,
                metadata_json=doc.metadata_json,
            )
            asset_db.commit()
            tracker.commit_document(rd_id, lifecycle_state["document_id"], snapshot_id)
            skipped_count += 1
            snapshot_decisions.append({
                "document_id": lifecycle_state["document_id"],
                "document_snapshot_id": snapshot_id,
                "document_key": doc_key,
                "lifecycle_action": "RESTORE",
                "source_batch_id": batch_id,
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
        # 本体线的逐文档阶段（entity_extract / resolve）仅在有 active 本体时入列。
        # 无本体时直接不挂这两个阶段——否则即便算子为 None 走直通，_worker 仍会发
        # start/end 事件，UI 会把它们显示成"已完成"（几百毫秒直通），与关系抽取/落图
        # 的"等待中"不一致。不入列 → 不发事件 → UI 显示"等待中"。
        ontology_stages: list[tuple] = []
        if has_ontology:
            ontology_stages = [
                ("entity_extract",   lambda ctx: entity_extract_stage(ctx, config),  max_workers),
                ("resolve",          lambda ctx: resolve_stage(ctx, config),         max_workers),
            ]
        stages = [
            ("parse",            lambda ctx: parse_stage(ctx, config),           1),
            ("segment",          lambda ctx: segment_stage(ctx, config),         1,
             lambda ctx: f"segments={len(ctx.segments or ())}"),
            ("enrich",           lambda ctx: enrich_stage(ctx, config),          max_workers),
            *ontology_stages,
            ("discourse",        lambda ctx: discourse_stage(ctx, config),       min(max_workers, 2)),
            ("retrieval_units",  lambda ctx: retrieval_units_stage(ctx, config), max_workers,
             lambda ctx: f"units={len(ctx.retrieval_units or ())}"),
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
                "lifecycle_action": action,
                "source_batch_id": batch_id,
            })
        else:
            skipped_count += 1

    # Phase 1d: 全局落图（B5）。仅当本领域已引种本体（有 active 版本）才跑，否则跳过。
    if has_ontology:
        _run_graph_write(asset_db, tracker, run_id, ctxs, profile.domain_id)

    counts = {
        "committed_count": committed_count, "new_count": new_count,
        "updated_count": updated_count, "failed_count": failed_count,
        "skipped_count": skipped_count,
    }

    # Phase 1e: 反转闸序的两检查点编排（L2 §15.1）。phase1_only 跳过全部人审，直接建库。
    # 无 active 本体时本体线整体关闭：跳过两道 Gate + 归纳 + 终态建图，直接进建库/发布。
    if not phase1_only and has_ontology:

        def _pause(gate: str) -> dict[str, Any]:
            av = OntologyStore(asset_db.pool).active_version(profile.domain_id)
            updated = tracker.pause_for_review(
                run_id, subloop_stage=gate,
                ontology_version_id=av["id"] if av else None,
                domain=profile.domain_id,
                **counts,
            )
            runtime_db.commit()
            if not updated:
                current = runtime_db.get_run(run_id) or {}
                return {"run_id": run_id, "status": current.get("status", "cancelled")}
            logger.info("Run %s paused for human review at gate=%s", run_id, gate)
            return {
                "run_id": run_id, "status": "awaiting_review", "subloop_stage": gate,
                "total_documents": len(docs), "build_id": None, "release_id": None, **counts,
            }

        # 实体确认在前：有 pending mention → 先停，等人确认"暂无类型/有歧义"的实体。
        if _has_pending_mentions(asset_db, run_id):
            return _pause("entity_review")

        # 无 pending → 直接跑全局B 归纳类型候选，再看本体确认。
        _run_induction(asset_db, tracker, run_id, profile, llm_base_url)
        if _has_proposed_candidates(asset_db, profile.domain_id):
            return _pause("ontology_review")

        # 两道 Gate 都无需人审 → 收尾建图（回贴 + 建边）后再建库。
        _finalize_graph(asset_db, tracker, run_id, profile)

    return _finalize_run(
        asset_db, runtime_db, tracker, run_id, batch_id, snapshot_decisions,
        counts, len(docs), phase1_only, publish_on_partial_failure, profile,
        channel=channel,
    )


@contextmanager
def _domain_publish_transaction(asset_db: AssetCoreDB, domain: str):
    """Open the transaction and domain lock used by automatic publication.

    The no-transaction branch keeps older structural unit-test doubles usable;
    production ``AssetCoreDB`` always exposes both required methods.
    """
    transaction = getattr(asset_db, "transaction", None)
    if transaction is None:
        yield
        return
    with transaction():
        asset_db.acquire_domain_publish_lock(domain)
        yield


def _finalize_run(
    asset_db: AssetCoreDB,
    runtime_db: MiningRuntimeDB,
    tracker: Any,
    run_id: str,
    batch_id: str,
    snapshot_decisions: list[dict[str, Any]],
    counts: dict[str, int],
    total_documents: int,
    phase1_only: bool,
    publish_on_partial_failure: bool,
    profile: DomainProfile,
    *,
    channel: str,
) -> dict[str, Any]:
    """B6：Phase 2 建库 + 发布 + 收尾。首跑无 Gate 触发、或 resume 审完两道 Gate 后都走这里。"""
    committed_count = counts["committed_count"]
    new_count = counts["new_count"]
    updated_count = counts["updated_count"]
    failed_count = counts["failed_count"]
    skipped_count = counts["skipped_count"]

    # Phase 2: Build & Publish (unless phase1_only)
    build_id = None
    release_id = None
    has_failures = failed_count > 0

    # Build is always created if there are committed documents
    if not phase1_only and snapshot_decisions:
        _check_cancelled(runtime_db, run_id)
        if not tracker.set_run_phase(run_id, profile.domain_id, "publishing"):
            return {"run_id": run_id, "status": "cancelled"}
        evt = tracker.start_stage(run_id, "assemble_build")
        should_publish = not has_failures or publish_on_partial_failure
        with _domain_publish_transaction(asset_db, profile.domain_id):
            # Re-read the parent only after acquiring the domain lock.
            snapshot_decisions = classify_documents(
                asset_db,
                snapshot_decisions,
                detect_remove=False,
                domain=profile.domain_id,
                channel=channel,
            )

            build_id = assemble_build(
                asset_db,
                run_id=run_id,
                batch_id=batch_id,
                snapshot_decisions=snapshot_decisions,
                domain=profile.domain_id,
                channel=channel,
            )

            # This read must see the build before the outer transaction commits.
            try:
                quality = demo_quality_summary(asset_db, build_id)
                logger.info("Demo quality summary: %s", quality)
            except Exception as e:
                logger.warning("Demo quality summary failed: %s", e)

            if should_publish:
                release_id = publish_release(
                    asset_db,
                    build_id=build_id,
                    released_by=f"run:{run_id}",
                    domain=profile.domain_id,
                    channel=channel,
                )

        # The asset transaction committed on context exit. Emit success only now.
        tracker.end_stage(
            evt,
            run_id,
            "assemble_build",
            output_summary=f"build_id={build_id}",
        )
        evt = tracker.start_stage(run_id, "validate_build")
        tracker.end_stage(evt, run_id, "validate_build", output_summary="passed")
        if release_id is not None:
            evt = tracker.start_stage(run_id, "publish_release")
            tracker.end_stage(
                evt,
                run_id,
                "publish_release",
                output_summary=f"release_id={release_id}",
            )
        runtime_db.commit()

    # Determine final run status (use SQL-valid values only)
    # All docs failed -> "failed"; some failed -> "completed" with has_failures metadata
    run_status = "completed"
    run_metadata = None
    if failed_count > 0 and committed_count == 0:
        run_status = "failed"
    elif failed_count > 0:
        existing_metadata = (runtime_db.get_run(run_id) or {}).get("metadata_json") or {}
        if isinstance(existing_metadata, str):
            import json
            existing_metadata = json.loads(existing_metadata)
        run_metadata = {
            **existing_metadata,
            "has_failures": True,
            "failed_count": failed_count,
        }

    if run_status == "failed":
        updated = tracker.fail_run(
            run_id,
            error_summary=f"All {failed_count} documents failed",
            current_stage=(runtime_db.get_run(run_id) or {}).get("current_stage") or "mining",
            domain=profile.domain_id,
            committed_count=committed_count,
            failed_count=failed_count,
            skipped_count=skipped_count,
            new_count=new_count,
            updated_count=updated_count,
        )
    else:
        updated = tracker.complete_run(
            run_id,
            build_id=build_id,
            domain=profile.domain_id,
            committed_count=committed_count,
            failed_count=failed_count,
            skipped_count=skipped_count,
            new_count=new_count,
            updated_count=updated_count,
            metadata_json=run_metadata,
        )
    runtime_db.commit()

    if not updated:
        current = runtime_db.get_run(run_id) or {}
        run_status = current.get("status", "cancelled")

    return {
        "run_id": run_id,
        "status": run_status,
        "total_documents": total_documents,
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
