"""Publishing stage: build + release for v1.1.

Two-phase:
- classify_documents: compare snapshots against previous active build → NEW/UPDATE/SKIP/REMOVE
- assemble_build: select snapshots, merge with previous active build (incremental or full)
- publish_release: activate a build as the current active release
"""
from __future__ import annotations

import logging
import uuid
from typing import Any

from knowledge_mining.mining.infra.db import AssetCoreDB

logger = logging.getLogger(__name__)


class PublishingStage:
    """Stage wrapper for publishing operations."""
    stage_name = "publishing"
    stage_version = "1"

    def execute(self, context: dict[str, Any], **kwargs: Any) -> dict[str, Any]:
        return context


def classify_documents(
    asset_db: AssetCoreDB,
    snapshot_decisions: list[dict[str, Any]],
    *,
    domain: str,
    detect_remove: bool = True,
) -> list[dict[str, Any]]:
    """Classify each document action by comparing with previous active build.

    Input: snapshot_decisions with document_id, document_snapshot_id (current run).
    Output: enriched snapshot_decisions with action, selection_status, reason.

    Actions:
    - NEW: document not in previous build
    - UPDATE: document exists but snapshot changed
    - SKIP: document exists and snapshot unchanged
    - REMOVE: document in previous build but not in current run (deleted file)

    Args:
        domain: Scope comparison to this domain's previous active build.
        detect_remove: When False, skip REMOVE detection. Use for incremental
            batch mining where each run only processes a subset of documents.
            Parent build snapshots are carried forward by assemble_build instead.
    """
    prev_build = asset_db.get_active_build(domain)
    prev_snapshots: dict[str, str] = {}  # document_id -> snapshot_id

    if prev_build:
        for ps in asset_db.get_build_snapshots(prev_build["id"]):
            prev_snapshots[ps["document_id"]] = ps["document_snapshot_id"]

    # Detect REMOVE: documents in prev build but not in current run
    # Skip when running incremental batches (each run = partial corpus)
    if detect_remove:
        current_doc_ids = {d["document_id"] for d in snapshot_decisions}
        for doc_id, snap_id in prev_snapshots.items():
            if doc_id not in current_doc_ids:
                snapshot_decisions.append({
                    "document_id": doc_id,
                    "document_snapshot_id": snap_id,
                    "action": "REMOVE",
                    "reason": "remove",
                    "selection_status": "removed",
                    "document_key": "",
                })

    for decision in snapshot_decisions:
        # Skip already-classified REMOVE entries
        if decision.get("action") == "REMOVE":
            continue

        doc_id = decision["document_id"]
        snap_id = decision["document_snapshot_id"]

        if decision.get("selection_status") == "removed":
            decision["action"] = "REMOVE"
            decision["reason"] = "removed"
        elif doc_id not in prev_snapshots:
            decision["action"] = "NEW"
            decision["reason"] = "add"
            decision["selection_status"] = "active"
        elif prev_snapshots[doc_id] == snap_id:
            decision["action"] = "SKIP"
            decision["reason"] = "retain"
            decision["selection_status"] = "active"
        else:
            decision["action"] = "UPDATE"
            decision["reason"] = "update"
            decision["selection_status"] = "active"

    return snapshot_decisions


def determine_build_mode(has_prev_build: bool) -> str:
    """Determine build mode based on whether a previous active build exists.

    Returns "full" if no previous build exists, otherwise "incremental".
    """
    if not has_prev_build:
        return "full"
    return "incremental"


def assemble_build(
    asset_db: AssetCoreDB,
    *,
    domain: str,
    run_id: str,
    batch_id: str | None = None,
    snapshot_decisions: list[dict[str, Any]],
) -> str:
    """Assemble a new build from snapshot decisions with merge semantics.

    snapshot_decisions: list of dicts with keys:
        document_id, document_snapshot_id, action (NEW/UPDATE/SKIP/REMOVE),
        selection_status (active/removed), reason (add/update/retain/remove)

    Build mode is determined automatically:
    - "full" when no previous active build exists for this domain
    - "incremental" when merging with previous active build for this domain

    Returns build_id.
    """
    prev_build = asset_db.get_active_build(domain)
    has_prev = prev_build is not None
    build_mode = determine_build_mode(has_prev)
    parent_build_id = prev_build["id"] if has_prev else None

    build_id = uuid.uuid4().hex
    build_code = f"B-{uuid.uuid4().hex[:8].upper()}"

    action_counts = {}
    for d in snapshot_decisions:
        action = d.get("action", "NEW")
        action_counts[action] = action_counts.get(action, 0) + 1

    asset_db.insert_build(
        build_id=build_id,
        build_code=build_code,
        status="building",
        build_mode=build_mode,
        domain=domain,
        source_batch_id=batch_id,
        parent_build_id=parent_build_id,
        mining_run_id=run_id,
        summary_json={
            "snapshot_count": len([d for d in snapshot_decisions if d.get("selection_status") == "active"]),
            "removed_count": len([d for d in snapshot_decisions if d.get("selection_status") == "removed"]),
            "action_counts": action_counts,
        },
    )

    # Incremental merge: carry forward parent snapshots not in current decisions
    if parent_build_id and has_prev:
        parent_snapshots = asset_db.get_build_snapshots(parent_build_id)
        decided_doc_ids = {d["document_id"] for d in snapshot_decisions}
        for ps in parent_snapshots:
            if ps["document_id"] not in decided_doc_ids:
                asset_db.upsert_build_document_snapshot(
                    build_id=build_id,
                    document_id=ps["document_id"],
                    document_snapshot_id=ps["document_snapshot_id"],
                    selection_status="active",
                    reason="retain",
                )

    # Add current run decisions (NEW/UPDATE/SKIP/REMOVE)
    for decision in snapshot_decisions:
        asset_db.upsert_build_document_snapshot(
            build_id=build_id,
            document_id=decision["document_id"],
            document_snapshot_id=decision["document_snapshot_id"],
            selection_status=decision.get("selection_status", "active"),
            reason=decision.get("reason", "add"),
        )

    # Validate and mark as validated
    validate_build(asset_db, build_id)
    asset_db.update_build_status(build_id, "validated")
    return build_id


def validate_build(asset_db: AssetCoreDB, build_id: str) -> None:
    """Validate that a build meets quality requirements.

    Checks:
    1. Build has at least one active snapshot
    2. Each active snapshot has at least one segment
    3. Incremental builds must have a valid parent build
    """
    build = asset_db.get_build(build_id)
    if build is None:
        raise ValueError(f"Build {build_id} not found")

    # Check parent build exists for incremental builds
    if build["build_mode"] == "incremental" and build["parent_build_id"]:
        parent = asset_db.get_build(build["parent_build_id"])
        if parent is None:
            raise ValueError(
                f"Incremental build {build_id} references missing parent {build['parent_build_id']}"
            )

    snapshots = asset_db.get_build_snapshots(build_id)
    active = [s for s in snapshots if s["selection_status"] == "active"]
    if not active:
        raise ValueError(f"Build {build_id} has no active snapshots")
    for snap in active:
        count = asset_db.count_segments_by_snapshot(snap["document_snapshot_id"])
        if count == 0:
            raise ValueError(
                f"Snapshot {snap['document_snapshot_id']} has no segments"
            )


def publish_release(
    asset_db: AssetCoreDB,
    build_id: str,
    *,
    domain: str,
    channel: str = "prod",
    released_by: str | None = None,
    release_notes: str | None = None,
) -> str:
    """Publish a validated build as the active release.

    Returns release_id.
    """
    build = asset_db.get_build(build_id)
    if build is None:
        raise ValueError(f"Build {build_id} not found")
    if build["status"] not in ("validated", "published"):
        raise ValueError(f"Build {build_id} status is {build['status']}, expected validated/published")
    if build["domain"] != domain:
        raise ValueError(
            f"Build {build_id} belongs to domain {build['domain']!r}, "
            f"cannot publish under domain {domain!r}"
        )

    # Get previous active release for chain (scoped to this domain+channel)
    prev_release = asset_db.get_active_release(domain, channel)
    prev_release_id = prev_release["id"] if prev_release else None

    release_id = uuid.uuid4().hex
    release_code = f"R-{uuid.uuid4().hex[:8].upper()}"

    asset_db.insert_release(
        release_id=release_id,
        release_code=release_code,
        build_id=build_id,
        domain=domain,
        channel=channel,
        status="staging",
        previous_release_id=prev_release_id,
        released_by=released_by,
        release_notes=release_notes,
    )

    # Activate: retire old, activate new (scoped to domain+channel inside activate_release)
    asset_db.activate_release(release_id)

    return release_id


def demo_quality_summary(asset_db: AssetCoreDB, build_id: str) -> dict[str, Any]:
    """Generate a demo quality summary for a build.

    Checks:
    - generated_question count (warns if 0)
    - Whether question titles still carry Qn prefix
    - RST discourse relation count and type distribution

    Does NOT block release. Returns a dict to merge into build metadata.
    """
    snapshots = asset_db.get_build_snapshots(build_id)
    active_snap_ids = [s["document_snapshot_id"] for s in snapshots if s["selection_status"] == "active"]

    warnings: list[str] = []
    summary: dict[str, Any] = {"build_id": build_id}

    # 1. Count retrieval units by type
    unit_counts: dict[str, int] = {}
    for snap_id in active_snap_ids:
        rows = asset_db._fetchall(
            "SELECT unit_type, COUNT(*) as cnt FROM asset_retrieval_units "
            "WHERE document_snapshot_id = %s GROUP BY unit_type",
            (snap_id,),
        )
        for r in rows:
            unit_counts[r["unit_type"]] = unit_counts.get(r["unit_type"], 0) + r["cnt"]

    summary["unit_type_counts"] = unit_counts
    q_count = unit_counts.get("generated_question", 0)
    if q_count == 0:
        warnings.append("No generated_question units found")
    summary["generated_question_count"] = q_count

    # 2. Check for Qn-prefixed question titles
    q_prefix_count = 0
    for snap_id in active_snap_ids:
        rows = asset_db._fetchall(
            "SELECT COUNT(*) as cnt FROM asset_retrieval_units "
            "WHERE document_snapshot_id = %s AND unit_type = 'generated_question' "
            "AND title LIKE 'Q%%'",
            (snap_id,),
        )
        for r in rows:
            q_prefix_count += r["cnt"]
    if q_prefix_count > 0:
        warnings.append(f"{q_prefix_count} question titles still have Qn prefix")
    summary["qn_prefix_count"] = q_prefix_count

    # 3. RST discourse relation distribution
    discourse_counts: dict[str, int] = {}
    for snap_id in active_snap_ids:
        rows = asset_db._fetchall(
            "SELECT relation_type, COUNT(*) as cnt FROM asset_raw_segment_relations "
            "WHERE document_snapshot_id = %s "
            "AND (metadata_json::jsonb)->>'source' = 'discourse_llm' "
            "GROUP BY relation_type",
            (snap_id,),
        )
        for r in rows:
            discourse_counts[r["relation_type"]] = discourse_counts.get(r["relation_type"], 0) + r["cnt"]

    summary["discourse_relation_counts"] = discourse_counts
    total_discourse = sum(discourse_counts.values())
    if total_discourse == 0:
        warnings.append("No discourse relations found")

    summary["warnings"] = warnings
    if warnings:
        logger.warning("Demo quality summary for build %s: %s", build_id[:8], warnings)

    return summary
