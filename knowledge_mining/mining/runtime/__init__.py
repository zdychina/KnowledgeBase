"""Runtime tracking for v1.1 Mining pipeline.

Wraps MiningRuntimeDB to provide stage-level tracking with automatic
timing and run-level status transitions.
"""
from __future__ import annotations

import time
from typing import Any

from knowledge_mining.mining.db import MiningRuntimeDB
from knowledge_mining.mining.models import (
    MiningRunData,
    MiningRunDocumentData,
    StageEvent,
    ResumePlan,
)


class RuntimeTracker:
    """High-level runtime state tracker for a single mining run."""

    def __init__(self, db: MiningRuntimeDB) -> None:
        self._db = db

    # -- Run lifecycle --

    def create_run(self, data: MiningRunData) -> str:
        self._db.insert_run(data)
        return data.id

    def complete_run(
        self, run_id: str, *, build_id: str | None = None, **counters: int,
    ) -> None:
        self._db.update_run_status(
            run_id, "completed", finished_at=_utcnow(), build_id=build_id, **counters,
        )

    def fail_run(self, run_id: str, error_summary: str, **counters: int) -> None:
        self._db.update_run_status(
            run_id, "failed", finished_at=_utcnow(), error_summary=error_summary, **counters,
        )

    def interrupt_run(self, run_id: str, **counters: int) -> None:
        self._db.update_run_status(run_id, "interrupted", finished_at=_utcnow(), **counters)

    # -- Run documents --

    def register_document(self, data: MiningRunDocumentData) -> str:
        now = _utcnow()
        patched = MiningRunDocumentData(
            **{k: v for k, v in data.__dict__.items() if k != "started_at"},
            started_at=now,
        )
        self._db.insert_run_document(patched)
        return patched.id

    def commit_document(
        self,
        rd_id: str,
        document_id: str,
        document_snapshot_id: str,
    ) -> None:
        self._db.update_run_document(
            rd_id,
            status="committed",
            document_id=document_id,
            document_snapshot_id=document_snapshot_id,
            finished_at=_utcnow(),
        )

    def fail_document(self, rd_id: str, error_message: str) -> None:
        self._db.update_run_document(
            rd_id, status="failed", error_message=error_message, finished_at=_utcnow(),
        )

    def skip_document(self, rd_id: str) -> None:
        self._db.update_run_document(rd_id, status="skipped", finished_at=_utcnow())

    # -- Stage events with timing --

    def start_stage(
        self,
        run_id: str,
        stage: str,
        run_document_id: str | None = None,
    ) -> str:
        """Record stage start. Returns event ID for end_stage."""
        evt_id = _new_id()
        self._db.insert_stage_event(StageEvent(
            id=evt_id,
            run_id=run_id,
            run_document_id=run_document_id,
            stage=stage,
            status="started",
            created_at=_utcnow(),
        ))
        return evt_id

    def end_stage(
        self,
        event_id: str,
        run_id: str,
        stage: str,
        status: str = "completed",
        output_summary: str | None = None,
        error_message: str | None = None,
    ) -> None:
        """Record stage completion. Re-reads the start event for duration calculation."""
        # Compute duration from start event
        duration_ms = None
        start_evt = self._db._fetchone(
            "SELECT created_at FROM mining_run_stage_events WHERE id = ?", (event_id,)
        )
        if start_evt and start_evt["created_at"]:
            try:
                from datetime import datetime, timezone
                start_time = datetime.fromisoformat(start_evt["created_at"])
                duration_ms = int((datetime.now(timezone.utc) - start_time).total_seconds() * 1000)
            except Exception:
                pass

        self._db.insert_stage_event(StageEvent(
            id=_new_id(),
            run_id=run_id,
            stage=stage,
            status=status,
            duration_ms=duration_ms,
            output_summary=output_summary,
            error_message=error_message,
            created_at=_utcnow(),
        ))

    # -- Resume support --

    def build_resume_plan(self, run_id: str) -> ResumePlan:
        """Build a resume plan for an interrupted run."""
        committed = self._db.get_committed_document_keys(run_id)
        failed = self._db.get_failed_document_keys(run_id)

        run_docs = self._db.get_run_documents(run_id)
        pending = frozenset(
            rd["document_key"] for rd in run_docs
            if rd["status"] == "pending"
        )

        # Documents that were processing/failed need to be redone
        redo = failed - committed

        return ResumePlan(
            skip_document_keys=committed,
            pending_document_keys=pending,
            redo_document_keys=redo,
            can_resume=True,
        )


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _utcnow() -> str:
    from datetime import datetime, timezone
    return datetime.now(timezone.utc).isoformat()


def _new_id() -> str:
    import uuid
    return uuid.uuid4().hex
