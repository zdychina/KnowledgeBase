"""Publishing stage: build + release for v1.1.

Two-phase:
- classify_documents: compare snapshots against previous active build → NEW/UPDATE/SKIP/REMOVE
- assemble_build: select snapshots, merge with previous active build (incremental or full)
- publish_release: activate a build as the current active release
"""
from __future__ import annotations

import uuid
from typing import Any

from knowledge_mining.mining.db import AssetCoreDB


def classify_documents(
    asset_db: AssetCoreDB,
    snapshot_decisions: list[dict[str, Any]],
) -> list[dict[str, Any]]:
    """Classify each document action by comparing with previous active build.

    Input: snapshot_decisions with document_id, document_snapshot_id (current run).
    Output: enriched snapshot_decisions with action, selection_status, reason.

    Actions:
    - NEW: document not in previous build
    - UPDATE: document exists but snapshot changed
    - SKIP: document exists and snapshot unchanged
    - REMOVE: document explicitly marked for removal
    """
    prev_build = asset_db.get_active_build()
    prev_snapshots: dict[str, str] = {}  # document_id -> snapshot_id

    if prev_build:
        for ps in asset_db.get_build_snapshots(prev_build["id"]):
            prev_snapshots[ps["document_id"]] = ps["document_snapshot_id"]

    for decision in snapshot_decisions:
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
    run_id: str,
    batch_id: str | None = None,
    snapshot_decisions: list[dict[str, Any]],
) -> str:
    """Assemble a new build from snapshot decisions with merge semantics.

    snapshot_decisions: list of dicts with keys:
        document_id, document_snapshot_id, action (NEW/UPDATE/SKIP/REMOVE),
        selection_status (active/removed), reason (add/update/retain/remove)

    Build mode is determined automatically:
    - "full" when no previous active build exists
    - "incremental" when merging with previous active build

    Returns build_id.
    """
    prev_build = asset_db.get_active_build()
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
    """Validate that a build has at least one active snapshot with segments."""
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
    channel: str = "default",
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

    # Get previous active release for chain
    prev_release = asset_db.get_active_release(channel)
    prev_release_id = prev_release["id"] if prev_release else None

    release_id = uuid.uuid4().hex
    release_code = f"R-{uuid.uuid4().hex[:8].upper()}"

    asset_db.insert_release(
        release_id=release_id,
        release_code=release_code,
        build_id=build_id,
        channel=channel,
        status="staging",
        previous_release_id=prev_release_id,
        released_by=released_by,
        release_notes=release_notes,
    )

    # Activate: retire old, activate new
    asset_db.activate_release(release_id)

    return release_id
