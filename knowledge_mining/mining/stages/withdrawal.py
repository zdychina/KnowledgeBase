"""Soft-withdrawal primitives for domain-scoped published knowledge assets."""
from __future__ import annotations

import uuid
from dataclasses import dataclass
from typing import Iterable

from knowledge_mining.mining.infra.db import AssetCoreDB
from knowledge_mining.mining.stages.publishing import publish_release, validate_build


class ActiveResourceNotFound(LookupError):
    """The requested document or batch has no active selection in the domain."""


@dataclass(frozen=True)
class WithdrawalResult:
    domain: str
    removed_count: int
    build_id: str
    release_id: str


def withdraw_document(
    asset_db: AssetCoreDB,
    *,
    domain: str,
    channel: str,
    document_id: str,
    actor: str,
) -> WithdrawalResult:
    return _withdraw(
        asset_db,
        domain=domain,
        channel=channel,
        document_ids={document_id},
        source_batch_id=None,
        actor=actor,
    )


def withdraw_source_batch(
    asset_db: AssetCoreDB,
    *,
    domain: str,
    channel: str,
    source_batch_id: str,
    actor: str,
) -> WithdrawalResult:
    return _withdraw(
        asset_db,
        domain=domain,
        channel=channel,
        document_ids=None,
        source_batch_id=source_batch_id,
        actor=actor,
    )


def _withdraw(
    asset_db: AssetCoreDB,
    *,
    domain: str,
    channel: str,
    document_ids: Iterable[str] | None,
    source_batch_id: str | None,
    actor: str,
) -> WithdrawalResult:
    """Clone the active build, remove targets, and atomically switch release."""
    with asset_db.transaction():
        asset_db.acquire_domain_publish_lock(domain)

        # Parent and target resolution must happen after the lock is held. This
        # makes repeated/concurrent withdrawals observe the release that won.
        parent_build = asset_db.get_active_build(domain=domain, channel=channel)
        if parent_build is None:
            raise ActiveResourceNotFound("active resource not found")
        parent_rows = asset_db.get_build_snapshots(parent_build["id"])
        active_document_ids = {
            row["document_id"]
            for row in parent_rows
            if row["selection_status"] == "active"
        }

        if source_batch_id is not None:
            requested_ids = set(
                asset_db.get_active_document_ids_by_batch(
                    domain=domain,
                    channel=channel,
                    source_batch_id=source_batch_id,
                )
            )
        else:
            requested_ids = set(document_ids or ())
        target_ids = requested_ids & active_document_ids
        if not target_ids:
            raise ActiveResourceNotFound("active resource not found")

        build_id = uuid.uuid4().hex
        build_code = f"B-{uuid.uuid4().hex[:8].upper()}"
        active_after = len(active_document_ids - target_ids)
        asset_db.insert_build(
            build_id=build_id,
            build_code=build_code,
            status="building",
            build_mode="incremental",
            domain=domain,
            source_batch_id=None,
            parent_build_id=parent_build["id"],
            mining_run_id=None,
            summary_json={
                "operation": "withdrawal",
                "snapshot_count": active_after,
                "removed_count": len(target_ids),
                "selection_count": len(parent_rows),
                "action_counts": {"REMOVE": len(target_ids)},
            },
        )

        # Preserve every parent selection and its effective provenance. Only
        # the requested active rows change lifecycle status/reason.
        for parent in parent_rows:
            is_target = parent["document_id"] in target_ids
            asset_db.upsert_build_document_snapshot(
                build_id=build_id,
                document_id=parent["document_id"],
                document_snapshot_id=parent["document_snapshot_id"],
                source_batch_id=parent.get("source_batch_id"),
                selection_status=(
                    "removed" if is_target else parent["selection_status"]
                ),
                reason="remove" if is_target else parent["reason"],
                metadata_json=parent.get("metadata_json"),
            )

        validate_build(asset_db, build_id, allow_empty=True)
        asset_db.update_build_status(build_id, "validated")
        release_id = publish_release(
            asset_db,
            build_id,
            domain=domain,
            channel=channel,
            released_by=actor,
            release_notes="Soft withdrawal",
        )

        return WithdrawalResult(
            domain=domain,
            removed_count=len(target_ids),
            build_id=build_id,
            release_id=release_id,
        )
