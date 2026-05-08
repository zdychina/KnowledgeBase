"""Knowledge asset read-only query routes."""
from __future__ import annotations

from fastapi import APIRouter, HTTPException, Query, Request

router = APIRouter(prefix="/api/knowledge", tags=["knowledge"])


@router.get("/stats")
async def knowledge_stats(request: Request) -> dict:
    """Global statistics across all asset tables."""
    pool = request.app.state.pg_pool

    async with pool.connection() as conn:
        counts = {}
        tables = [
            ("documents", "asset_documents"),
            ("snapshots", "asset_document_snapshots"),
            ("segments", "asset_raw_segments"),
            ("relations", "asset_raw_segment_relations"),
            ("retrieval_units", "asset_retrieval_units"),
            ("embeddings", "asset_retrieval_embeddings"),
            ("builds", "asset_builds"),
            ("releases", "asset_publish_releases"),
        ]
        for key, table in tables:
            cur = await conn.execute(f"SELECT COUNT(*) as c FROM {table}")
            counts[key] = (await cur.fetchone())["c"]

        # Retrieval units by type
        cur = await conn.execute(
            "SELECT unit_type, COUNT(*) as c FROM asset_retrieval_units GROUP BY unit_type"
        )
        type_dist = {r["unit_type"]: r["c"] for r in await cur.fetchall()}

        # Active release
        cur = await conn.execute(
            "SELECT id FROM asset_publish_releases WHERE status = 'active' LIMIT 1"
        )
        active = await cur.fetchone()
        active_release = active["id"] if active else None

    return {
        **counts,
        "retrieval_units_by_type": type_dist,
        "active_release": active_release,
    }


@router.get("/documents")
async def list_documents(
    request: Request,
    type: str | None = None,
    limit: int = Query(20, ge=1, le=500),
    offset: int = Query(0, ge=0),
) -> dict:
    """List documents with optional type filter."""
    pool = request.app.state.pg_pool

    async with pool.connection() as conn:
        where = "WHERE document_type = %s" if type else ""
        params: list[str] = [type] if type else []

        count_cur = await conn.execute(
            f"SELECT COUNT(*) as c FROM asset_documents {where}", params
        )
        total = (await count_cur.fetchone())["c"]

        cur = await conn.execute(
            f"SELECT d.id, d.document_key, d.document_name, d.document_type, d.created_at "
            f"FROM asset_documents d {where} "
            f"ORDER BY d.created_at DESC LIMIT %s OFFSET %s",
            params + [limit, offset],
        )
        rows = await cur.fetchall()

    return {
        "total": total,
        "limit": limit,
        "offset": offset,
        "items": [dict(r) for r in rows],
    }


@router.get("/documents/{document_id}")
async def get_document(document_id: str, request: Request) -> dict:
    """Get document detail with snapshot history."""
    pool = request.app.state.pg_pool

    async with pool.connection() as conn:
        cur = await conn.execute(
            "SELECT id, document_key, document_name, document_type, "
            "source_uri, created_at "
            "FROM asset_documents WHERE id = %s", [document_id]
        )
        doc = await cur.fetchone()
        if not doc:
            raise HTTPException(404, f"Document {document_id} not found")

        cur = await conn.execute(
            "SELECT ds.id, ds.title, ds.normalized_content_hash, ds.mime_type, "
            "ds.created_at, dsl.linked_at, dsl.relative_path, dsl.source_uri "
            "FROM asset_document_snapshot_links dsl "
            "JOIN asset_document_snapshots ds ON dsl.document_snapshot_id = ds.id "
            "WHERE dsl.document_id = %s "
            "ORDER BY dsl.linked_at DESC",
            [document_id],
        )
        snapshots = [dict(r) for r in await cur.fetchall()]

    return {**dict(doc), "snapshots": snapshots}


@router.get("/documents/{document_id}/segments")
async def get_document_segments(
    document_id: str,
    request: Request,
    limit: int = Query(100, ge=1, le=500),
    offset: int = Query(0, ge=0),
) -> dict:
    """Get segments for a document (via latest snapshot)."""
    pool = request.app.state.pg_pool

    async with pool.connection() as conn:
        # Find latest snapshot
        cur = await conn.execute(
            "SELECT document_snapshot_id FROM asset_document_snapshot_links "
            "WHERE document_id = %s ORDER BY linked_at DESC LIMIT 1",
            [document_id],
        )
        link = await cur.fetchone()
        if not link:
            raise HTTPException(404, f"No snapshots found for document {document_id}")

        snapshot_id = link["document_snapshot_id"]
        cur = await conn.execute(
            "SELECT id, segment_key, segment_index, block_type, semantic_role, "
            "section_title, raw_text, token_count "
            "FROM asset_raw_segments "
            "WHERE document_snapshot_id = %s "
            "ORDER BY segment_index LIMIT %s OFFSET %s",
            [snapshot_id, limit, offset],
        )
        rows = await cur.fetchall()

    return {"document_id": document_id, "snapshot_id": snapshot_id, "items": [dict(r) for r in rows]}


@router.get("/documents/{document_id}/units")
async def get_document_units(
    document_id: str,
    request: Request,
    unit_type: str | None = None,
    limit: int = Query(100, ge=1, le=500),
    offset: int = Query(0, ge=0),
) -> dict:
    """Get retrieval units for a document (via latest snapshot)."""
    pool = request.app.state.pg_pool

    async with pool.connection() as conn:
        cur = await conn.execute(
            "SELECT document_snapshot_id FROM asset_document_snapshot_links "
            "WHERE document_id = %s ORDER BY linked_at DESC LIMIT 1",
            [document_id],
        )
        link = await cur.fetchone()
        if not link:
            raise HTTPException(404, f"No snapshots found for document {document_id}")

        snapshot_id = link["document_snapshot_id"]
        where = "AND unit_type = %s" if unit_type else ""
        params: list[str] = [snapshot_id] + ([unit_type] if unit_type else [])

        cur = await conn.execute(
            f"SELECT id, unit_key, unit_type, target_type, title, text, "
            f"block_type, semantic_role, weight, created_at "
            f"FROM asset_retrieval_units "
            f"WHERE document_snapshot_id = %s {where} "
            f"ORDER BY created_at LIMIT %s OFFSET %s",
            params + [limit, offset],
        )
        rows = await cur.fetchall()

    return {"document_id": document_id, "snapshot_id": snapshot_id, "items": [dict(r) for r in rows]}


@router.get("/segments")
async def list_segments(
    request: Request,
    role: str | None = None,
    type: str | None = None,
    limit: int = Query(50, ge=1, le=500),
    offset: int = Query(0, ge=0),
) -> dict:
    """List segments across all documents."""
    pool = request.app.state.pg_pool

    conditions = []
    params: list[str] = []
    if role:
        conditions.append("semantic_role = %s")
        params.append(role)
    if type:
        conditions.append("block_type = %s")
        params.append(type)

    where = ("WHERE " + " AND ".join(conditions)) if conditions else ""

    async with pool.connection() as conn:
        count_cur = await conn.execute(
            f"SELECT COUNT(*) as c FROM asset_raw_segments {where}", params
        )
        total = (await count_cur.fetchone())["c"]

        cur = await conn.execute(
            f"SELECT id, document_snapshot_id, segment_key, segment_index, "
            f"block_type, semantic_role, section_title, "
            f"LEFT(raw_text, 200) as raw_text_preview, token_count "
            f"FROM asset_raw_segments {where} "
            f"ORDER BY document_snapshot_id, segment_index LIMIT %s OFFSET %s",
            params + [limit, offset],
        )
        rows = await cur.fetchall()

    return {"total": total, "limit": limit, "offset": offset, "items": [dict(r) for r in rows]}


@router.get("/units")
async def list_units(
    request: Request,
    unit_type: str | None = None,
    limit: int = Query(50, ge=1, le=500),
    offset: int = Query(0, ge=0),
) -> dict:
    """List retrieval units across all documents."""
    pool = request.app.state.pg_pool

    conditions = []
    params: list[str] = []
    if unit_type:
        conditions.append("unit_type = %s")
        params.append(unit_type)

    where = ("WHERE " + " AND ".join(conditions)) if conditions else ""

    async with pool.connection() as conn:
        count_cur = await conn.execute(
            f"SELECT COUNT(*) as c FROM asset_retrieval_units {where}", params
        )
        total = (await count_cur.fetchone())["c"]

        cur = await conn.execute(
            f"SELECT id, document_snapshot_id, unit_key, unit_type, target_type, "
            f"title, LEFT(text, 200) as text_preview, block_type, semantic_role, "
            f"weight, created_at "
            f"FROM asset_retrieval_units {where} "
            f"ORDER BY created_at DESC LIMIT %s OFFSET %s",
            params + [limit, offset],
        )
        rows = await cur.fetchall()

    return {"total": total, "limit": limit, "offset": offset, "items": [dict(r) for r in rows]}


@router.get("/relations")
async def list_relations(
    request: Request,
    type: str | None = None,
    limit: int = Query(50, ge=1, le=500),
    offset: int = Query(0, ge=0),
) -> dict:
    """List segment relations."""
    pool = request.app.state.pg_pool

    conditions = []
    params: list[str] = []
    if type:
        conditions.append("relation_type = %s")
        params.append(type)

    where = ("WHERE " + " AND ".join(conditions)) if conditions else ""

    async with pool.connection() as conn:
        count_cur = await conn.execute(
            f"SELECT COUNT(*) as c FROM asset_raw_segment_relations {where}", params
        )
        total = (await count_cur.fetchone())["c"]

        cur = await conn.execute(
            f"SELECT id, document_snapshot_id, source_segment_id, "
            f"target_segment_id, relation_type, weight, confidence, distance "
            f"FROM asset_raw_segment_relations {where} "
            f"ORDER BY document_snapshot_id LIMIT %s OFFSET %s",
            params + [limit, offset],
        )
        rows = await cur.fetchall()

    return {"total": total, "limit": limit, "offset": offset, "items": [dict(r) for r in rows]}
