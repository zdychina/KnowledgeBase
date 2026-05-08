"""Mining run routes — CRUD and async execution."""
from __future__ import annotations

import logging
import threading
from typing import Any

from fastapi import APIRouter, HTTPException, Query, Request
from pydantic import BaseModel, Field

from knowledge_mining.mining.infra.pg_config import MiningDbConfig

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/runs", tags=["runs"])

# Mutex to prevent concurrent mining runs
_run_lock = threading.Lock()


# ── Request / Response models ──

class CreateRunRequest(BaseModel):
    input_path: str
    domain_pack: str = "cloud_core_network"
    max_workers: int = 4
    phase1_only: bool = False
    publish_on_partial_failure: bool = False
    llm_base_url: str | None = None
    embedding_api_key: str | None = None


class RunResponse(BaseModel):
    run_id: str
    status: str
    started_at: str | None = None


class CancelRunResponse(BaseModel):
    run_id: str
    status: str
    message: str


# ── Routes ──

@router.post("", response_model=RunResponse, status_code=202)
async def create_run(body: CreateRunRequest, request: Request) -> dict:
    """Submit a mining run (async, returns immediately)."""
    pool = request.app.state.pg_pool
    db_config: MiningDbConfig = request.app.state.db_config

    # Read embedding env vars
    import os
    embedding_api_key = body.embedding_api_key or os.environ.get("EMBEDDING_API_KEY")
    llm_base_url = body.llm_base_url or os.environ.get("LLM_SERVICE_URL", "http://localhost:8900")

    # Prevent concurrent mining runs
    if not _run_lock.acquire(blocking=False):
        raise HTTPException(409, "A mining run is already in progress. Please wait for it to complete.")

    def _run_in_thread():
        try:
            from knowledge_mining.mining.jobs.run import run as mining_run
            mining_run(
                body.input_path,
                db_config=db_config,
                phase1_only=body.phase1_only,
                publish_on_partial_failure=body.publish_on_partial_failure,
                llm_base_url=llm_base_url,
                embedding_api_key=embedding_api_key,
                max_workers=body.max_workers,
                domain_pack=body.domain_pack,
            )
        except Exception as e:
            logger.error("Mining run failed: %s", e, exc_info=True)
        finally:
            _run_lock.release()

    # Pre-create run to get run_id — but the actual run() creates its own.
    # We start the thread and query the run table after.
    thread = threading.Thread(target=_run_in_thread, daemon=True)
    thread.start()

    # Poll for the run to appear in DB (up to 10s)
    import asyncio
    for _ in range(20):
        await asyncio.sleep(0.5)
        async with pool.connection() as conn:
            cur = await conn.execute(
                "SELECT id, status, started_at FROM mining_runs "
                "ORDER BY started_at DESC LIMIT 1"
            )
            row = await cur.fetchone()
            if row:
                return {
                    "run_id": row["id"],
                    "status": row["status"],
                    "started_at": row["started_at"],
                }

    return {"run_id": "pending", "status": "starting"}


@router.get("")
async def list_runs(
    request: Request,
    status: str | None = None,
    limit: int = Query(20, ge=1, le=500),
    offset: int = Query(0, ge=0),
) -> dict:
    """List mining runs with optional status filter."""
    pool = request.app.state.pg_pool

    async with pool.connection() as conn:
        where = "WHERE status = %s" if status else ""
        params: list[str] = [status] if status else []

        count_cur = await conn.execute(
            f"SELECT COUNT(*) as c FROM mining_runs {where}", params
        )
        total = (await count_cur.fetchone())["c"]

        cur = await conn.execute(
            f"SELECT id, status, input_path, total_documents, "
            f"committed_count, failed_count, skipped_count, "
            f"new_count, updated_count, build_id, started_at, finished_at "
            f"FROM mining_runs {where} "
            f"ORDER BY started_at DESC LIMIT %s OFFSET %s",
            params + [limit, offset],
        )
        rows = await cur.fetchall()

    return {
        "total": total,
        "limit": limit,
        "offset": offset,
        "items": [dict(r) for r in rows],
    }


@router.get("/{run_id}")
async def get_run(run_id: str, request: Request) -> dict:
    """Get run details."""
    pool = request.app.state.pg_pool

    async with pool.connection() as conn:
        cur = await conn.execute(
            "SELECT id, source_batch_id, input_path, status, build_id, "
            "total_documents, new_count, updated_count, skipped_count, "
            "failed_count, committed_count, started_at, finished_at, "
            "error_summary, metadata_json "
            "FROM mining_runs WHERE id = %s", [run_id]
        )
        run = await cur.fetchone()
        if not run:
            raise HTTPException(404, f"Run {run_id} not found")
        return dict(run)


@router.get("/{run_id}/stages")
async def get_run_stages(run_id: str, request: Request) -> dict:
    """Get stage timeline for a run."""
    pool = request.app.state.pg_pool

    async with pool.connection() as conn:
        cur = await conn.execute(
            "SELECT id, run_id, stage, status, created_at, duration_ms, "
            "output_summary, error_message, run_document_id "
            "FROM mining_run_stage_events WHERE run_id = %s "
            "ORDER BY created_at",
            [run_id],
        )
        rows = await cur.fetchall()

    return {"run_id": run_id, "stages": [dict(r) for r in rows]}


@router.get("/{run_id}/documents")
async def get_run_documents(run_id: str, request: Request) -> dict:
    """Get document processing results for a run."""
    pool = request.app.state.pg_pool

    async with pool.connection() as conn:
        cur = await conn.execute(
            "SELECT id, run_id, document_key, action, status, "
            "document_id, document_snapshot_id, error_summary, "
            "raw_content_hash, normalized_content_hash "
            "FROM mining_run_documents WHERE run_id = %s "
            "ORDER BY document_key",
            [run_id],
        )
        rows = await cur.fetchall()

    return {"run_id": run_id, "documents": [dict(r) for r in rows]}


@router.post("/{run_id}/cancel", response_model=CancelRunResponse)
async def cancel_run(run_id: str, request: Request) -> dict:
    """Cancel a running run (best-effort)."""
    pool = request.app.state.pg_pool

    async with pool.connection() as conn:
        cur = await conn.execute(
            "SELECT id, status FROM mining_runs WHERE id = %s", [run_id]
        )
        run = await cur.fetchone()
        if not run:
            raise HTTPException(404, f"Run {run_id} not found")
        if run["status"] not in ("running", "pending"):
            raise HTTPException(400, f"Run {run_id} is {run['status']}, cannot cancel")

        await conn.execute(
            "UPDATE mining_runs SET status = 'cancelled', finished_at = %s WHERE id = %s",
            [_utcnow(), run_id],
        )

    return {"run_id": run_id, "status": "cancelled", "message": "Run cancellation requested"}


@router.post("/{run_id}/publish")
async def publish_run(run_id: str, request: Request) -> dict:
    """Publish a completed run's build as active release."""
    db_config: MiningDbConfig = request.app.state.db_config

    try:
        from knowledge_mining.mining.jobs.run import publish
        result = publish(run_id, db_config=db_config)
        return result
    except ValueError as e:
        raise HTTPException(400, str(e))
    except Exception as e:
        raise HTTPException(500, f"Publish failed: {e}")


def _utcnow() -> str:
    from datetime import datetime, timezone
    return datetime.now(timezone.utc).isoformat()
