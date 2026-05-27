"""Build & Release management routes."""
from __future__ import annotations

from fastapi import APIRouter, HTTPException, Query, Request

from knowledge_mining.mining.infra.domain_pack import resolve_domain

router = APIRouter(tags=["builds"])


@router.get("/api/builds")
async def list_builds(
    request: Request,
    status: str | None = None,
    domain: str | None = None,
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
    if domain:
        conditions.append("domain = %s")
        params.append(domain)

    where = ("WHERE " + " AND ".join(conditions)) if conditions else ""

    async with pool.connection() as conn:
        count_cur = await conn.execute(
            f"SELECT COUNT(*) as c FROM asset_builds {where}", params
        )
        total = (await count_cur.fetchone())["c"]

        cur = await conn.execute(
            f"SELECT id, build_code, status, build_mode, domain, source_batch_id, "
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
            "SELECT id, build_code, status, build_mode, domain, source_batch_id, "
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
    domain: str | None = None,
    channel: str | None = None,
    limit: int = Query(20, ge=1, le=500),
    offset: int = Query(0, ge=0),
) -> dict:
    """List releases."""
    pool = request.app.state.pg_pool

    conditions = []
    params: list[str] = []
    if domain:
        conditions.append("domain = %s")
        params.append(domain)
    if channel:
        conditions.append("channel = %s")
        params.append(channel)

    where = ("WHERE " + " AND ".join(conditions)) if conditions else ""

    async with pool.connection() as conn:
        count_cur = await conn.execute(
            f"SELECT COUNT(*) as c FROM asset_publish_releases {where}", params
        )
        total = (await count_cur.fetchone())["c"]

        cur = await conn.execute(
            "SELECT id, release_code, build_id, domain, channel, status, "
            "released_by, activated_at, deactivated_at "
            f"FROM asset_publish_releases {where} "
            "ORDER BY activated_at DESC LIMIT %s OFFSET %s",
            params + [limit, offset],
        )
        rows = await cur.fetchall()

    return {"total": total, "limit": limit, "offset": offset, "items": [dict(r) for r in rows]}


@router.get("/api/releases/active")
async def get_active_release(
    request: Request,
    domain: str = Query(..., description="Domain to get active release for"),
    channel: str = Query("prod", description="Channel name"),
) -> dict:
    """Get current active release for a domain+channel."""
    # Validate domain exists and is enabled in registry
    try:
        resolve_domain(domain)
    except KeyError:
        raise HTTPException(400, f"Unknown domain: {domain}")
    except ValueError:
        raise HTTPException(400, f"Domain is disabled: {domain}")

    pool = request.app.state.pg_pool

    async with pool.connection() as conn:
        cur = await conn.execute(
            "SELECT id, release_code, build_id, domain, channel, status, "
            "released_by, activated_at, deactivated_at "
            "FROM asset_publish_releases WHERE status = 'active' "
            "AND domain = %s AND channel = %s LIMIT 1",
            [domain, channel],
        )
        release = await cur.fetchone()
        if not release:
            raise HTTPException(404, "No active release found")

    return dict(release)
