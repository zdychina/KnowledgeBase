"""Build & Release management routes."""
from __future__ import annotations

from fastapi import APIRouter, HTTPException, Query, Request

router = APIRouter(tags=["builds"])


@router.get("/api/builds")
async def list_builds(
    request: Request,
    status: str | None = None,
    limit: int = Query(20, ge=1, le=500),
    offset: int = Query(0, ge=0),
) -> dict:
    """List builds."""
    pool = request.app.state.pg_pool

    conditions = []
    params: list[str] = []
    if status:
        conditions.append("status = %s")
        params.append(status)

    where = ("WHERE " + " AND ".join(conditions)) if conditions else ""

    async with pool.connection() as conn:
        count_cur = await conn.execute(
            f"SELECT COUNT(*) as c FROM asset_builds {where}", params
        )
        total = (await count_cur.fetchone())["c"]

        cur = await conn.execute(
            f"SELECT id, build_code, status, build_mode, source_batch_id, "
            f"parent_build_id, mining_run_id, created_at, finished_at "
            f"FROM asset_builds {where} "
            f"ORDER BY created_at DESC LIMIT %s OFFSET %s",
            params + [limit, offset],
        )
        rows = await cur.fetchall()

    return {"total": total, "limit": limit, "offset": offset, "items": [dict(r) for r in rows]}


@router.get("/api/builds/{build_id}")
async def get_build(build_id: str, request: Request) -> dict:
    """Get build detail with document snapshots."""
    pool = request.app.state.pg_pool

    async with pool.connection() as conn:
        cur = await conn.execute(
            "SELECT id, build_code, status, build_mode, source_batch_id, "
            "parent_build_id, mining_run_id, created_at, finished_at "
            "FROM asset_builds WHERE id = %s", [build_id]
        )
        build = await cur.fetchone()
        if not build:
            raise HTTPException(404, f"Build {build_id} not found")

        cur = await conn.execute(
            "SELECT build_id, document_id, document_snapshot_id, "
            "selection_status, reason FROM asset_build_document_snapshots "
            "WHERE build_id = %s",
            [build_id],
        )
        docs = [dict(r) for r in await cur.fetchall()]

    return {**dict(build), "documents": docs}


@router.get("/api/releases")
async def list_releases(
    request: Request,
    limit: int = Query(20, ge=1, le=500),
    offset: int = Query(0, ge=0),
) -> dict:
    """List releases."""
    pool = request.app.state.pg_pool

    async with pool.connection() as conn:
        count_cur = await conn.execute("SELECT COUNT(*) as c FROM asset_publish_releases")
        total = (await count_cur.fetchone())["c"]

        cur = await conn.execute(
            "SELECT id, release_code, build_id, channel, status, "
            "released_by, activated_at, deactivated_at "
            "FROM asset_publish_releases "
            "ORDER BY activated_at DESC LIMIT %s OFFSET %s",
            [limit, offset],
        )
        rows = await cur.fetchall()

    return {"total": total, "limit": limit, "offset": offset, "items": [dict(r) for r in rows]}


@router.get("/api/releases/active")
async def get_active_release(request: Request) -> dict:
    """Get current active release."""
    pool = request.app.state.pg_pool

    async with pool.connection() as conn:
        cur = await conn.execute(
            "SELECT id, release_code, build_id, channel, status, "
            "released_by, activated_at, deactivated_at "
            "FROM asset_publish_releases WHERE status = 'active' LIMIT 1"
        )
        release = await cur.fetchone()
        if not release:
            raise HTTPException(404, "No active release found")

    return dict(release)
