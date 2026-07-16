"""Mining run routes — CRUD and async execution."""
from __future__ import annotations

import logging
import re
import threading
from pathlib import Path
from typing import Any

from fastapi import APIRouter, HTTPException, Query, Request
from fastapi.responses import HTMLResponse, PlainTextResponse
from pydantic import BaseModel, Field

from knowledge_mining.mining.api.domain_scope import require_domain
from knowledge_mining.mining.infra.pg_config import MiningDbConfig

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/runs", tags=["runs"])

# Mutex to prevent concurrent mining runs
_run_lock = threading.Lock()


# ── Request / Response models ──

class CreateRunRequest(BaseModel):
    input_path: str
    domain: str
    domain_pack: str | None = None
    max_workers: int | None = None
    phase1_only: bool = False
    publish_on_partial_failure: bool = False
    llm_base_url: str | None = None


class RunResponse(BaseModel):
    run_id: str
    status: str
    started_at: str | None = None


class CancelRunResponse(BaseModel):
    run_id: str
    status: str
    message: str


async def _require_run_domain(pool, run_id: str, domain: str) -> dict:
    """Return the run only when it belongs to the requested domain."""
    requested = require_domain(domain)
    async with pool.connection() as conn:
        cur = await conn.execute(
            "SELECT id, domain, status FROM mining_runs "
            "WHERE id = %s AND domain = %s",
            [run_id, requested],
        )
        row = await cur.fetchone()
    if row is None:
        raise HTTPException(404, f"Run {run_id} not found")
    return dict(row)


# ── Routes ──

@router.post("", response_model=RunResponse, status_code=202)
async def create_run(body: CreateRunRequest, request: Request) -> dict:
    """Submit a mining run (async, returns immediately)."""
    pool = request.app.state.pg_pool
    db_config: MiningDbConfig = request.app.state.db_config

    from knowledge_mining.mining.infra.mining_config import MiningConfig
    cfg = MiningConfig()
    resolved_domain = require_domain(body.domain)

    llm_base_url = body.llm_base_url or cfg.llm_service_url

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
                max_workers=body.max_workers,
                domain=resolved_domain,
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
                "WHERE domain = %s ORDER BY started_at DESC LIMIT 1",
                [resolved_domain],
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
    domain: str = Query(..., min_length=1),
    status: str | None = None,
    limit: int = Query(20, ge=1, le=500),
    offset: int = Query(0, ge=0),
) -> dict:
    """List mining runs in one domain."""
    pool = request.app.state.pg_pool

    async with pool.connection() as conn:
        conds: list[str] = ["domain = %s"]
        params: list[str] = [require_domain(domain)]
        if status:
            conds.append("status = %s")
            params.append(status)
        where = f"WHERE {' AND '.join(conds)}" if conds else ""

        count_cur = await conn.execute(
            f"SELECT COUNT(*) as c FROM mining_runs {where}", params
        )
        total = (await count_cur.fetchone())["c"]

        cur = await conn.execute(
            f"SELECT id, status, input_path, domain, total_documents, "
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
async def get_run(run_id: str, request: Request, domain: str = Query(..., min_length=1)) -> dict:
    """Get run details."""
    pool = request.app.state.pg_pool
    await _require_run_domain(pool, run_id, domain)

    async with pool.connection() as conn:
        cur = await conn.execute(
            "SELECT id, source_batch_id, input_path, domain, status, build_id, "
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
async def get_run_stages(run_id: str, request: Request, domain: str = Query(..., min_length=1)) -> dict:
    """Get stage timeline for a run."""
    pool = request.app.state.pg_pool
    await _require_run_domain(pool, run_id, domain)

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
async def get_run_documents(
    run_id: str,
    request: Request,
    domain: str = Query(..., min_length=1),
    status: str | None = None,
    action: str | None = None,
    has_error: bool | None = None,
    page: int = Query(1, ge=1),
    page_size: int = Query(50, ge=1, le=200),
) -> dict:
    """Get document processing results for a run with pagination and filtering."""
    pool = request.app.state.pg_pool
    await _require_run_domain(pool, run_id, domain)

    async with pool.connection() as conn:
        # Build WHERE conditions
        conds: list[str] = ["d.run_id = %s"]
        params: list[Any] = [run_id]
        if status:
            conds.append("d.status = %s")
            params.append(status)
        if action:
            conds.append("d.action = %s")
            params.append(action)
        if has_error is True:
            conds.append("d.error_message IS NOT NULL AND d.error_message != ''")
        where = " AND ".join(conds)

        # Count
        count_cur = await conn.execute(
            f"SELECT COUNT(*) as c FROM mining_run_documents d WHERE {where}", params
        )
        total = (await count_cur.fetchone())["c"]

        # Fetch page
        offset = (page - 1) * page_size
        cur = await conn.execute(
            f"SELECT d.id, d.run_id, d.document_key, d.action, d.status, "
            f"d.document_id, d.document_snapshot_id, d.error_message, "
            f"d.raw_content_hash, d.normalized_content_hash, d.metadata_json "
            f"FROM mining_run_documents d WHERE {where} "
            f"ORDER BY d.document_key LIMIT %s OFFSET %s",
            params + [page_size, offset],
        )
        rows = await cur.fetchall()

        # Batch enrichment: fetch latest stage and duration for all doc IDs
        doc_ids = [r["id"] for r in rows]
        stage_lookup: dict[str, str | None] = {}
        duration_lookup: dict[str, int | None] = {}

        if doc_ids:
            # Latest stage per document (single batch query)
            placeholders = ",".join(["%s"] * len(doc_ids))
            stage_cur = await conn.execute(
                f"SELECT DISTINCT ON (run_document_id) run_document_id, stage "
                f"FROM mining_run_stage_events "
                f"WHERE run_id = %s AND run_document_id IN ({placeholders}) "
                f"ORDER BY run_document_id, created_at DESC",
                [run_id, *doc_ids],
            )
            for sr in await stage_cur.fetchall():
                stage_lookup[sr["run_document_id"]] = sr["stage"]

            # Duration per document (computed in SQL to avoid TEXT type issues)
            dur_cur = await conn.execute(
                f"SELECT run_document_id, "
                f"EXTRACT(EPOCH FROM (MAX(created_at::timestamp) - MIN(created_at::timestamp))) * 1000 as duration_ms "
                f"FROM mining_run_stage_events "
                f"WHERE run_id = %s AND run_document_id IN ({placeholders}) "
                f"AND status IN ('started', 'completed', 'failed') "
                f"GROUP BY run_document_id",
                [run_id, *doc_ids],
            )
            for dr in await dur_cur.fetchall():
                if dr["duration_ms"] is not None:
                    duration_lookup[dr["run_document_id"]] = int(dr["duration_ms"])

        # Enrich documents with computed fields
        documents = []
        for r in rows:
            doc = dict(r)
            # document_name: strip "doc:/" prefix from document_key
            dk = doc.get("document_key", "")
            doc["document_name"] = dk.replace("doc:/", "", 1) if dk.startswith("doc:/") else dk
            doc["current_stage"] = stage_lookup.get(doc["id"])
            doc["duration_ms"] = duration_lookup.get(doc["id"])
            # file_size: 摄取时存进 metadata_json 的原始文件字节大小（JSONB → dict）
            meta = doc.pop("metadata_json", None) or {}
            doc["file_size"] = meta.get("file_size") if isinstance(meta, dict) else None
            documents.append(doc)

    return {
        "run_id": run_id,
        "total": total,
        "page": page,
        "page_size": page_size,
        "documents": documents,
    }


@router.get("/{run_id}/progress")
async def get_run_progress(run_id: str, request: Request, domain: str = Query(..., min_length=1)) -> dict:
    """Get run progress — aggregated from mining_run_documents + mining_run_stage_events."""
    pool = request.app.state.pg_pool
    await _require_run_domain(pool, run_id, domain)

    async with pool.connection() as conn:
        # Verify run exists
        run_cur = await conn.execute(
            "SELECT id, status, total_documents FROM mining_runs WHERE id = %s", [run_id]
        )
        run = await run_cur.fetchone()
        if not run:
            raise HTTPException(404, f"Run {run_id} not found")

        # Document status counts
        doc_cur = await conn.execute(
            "SELECT status, COUNT(*) as cnt FROM mining_run_documents "
            "WHERE run_id = %s GROUP BY status",
            [run_id],
        )
        doc_rows = await doc_cur.fetchall()
        status_counts = {r["status"]: r["cnt"] for r in doc_rows}

        # Stage summary: for each stage, count completed/failed
        stage_cur = await conn.execute(
            "SELECT stage, status, COUNT(*) as cnt FROM mining_run_stage_events "
            "WHERE run_id = %s AND run_document_id IS NOT NULL "
            "GROUP BY stage, status",
            [run_id],
        )
        stage_rows = await stage_cur.fetchall()

        # Build stage_summary
        stage_summary: dict[str, dict[str, int]] = {}
        for r in stage_rows:
            stage_summary.setdefault(r["stage"], {"done": 0, "failed": 0})
            if r["status"] == "completed":
                stage_summary[r["stage"]]["done"] += r["cnt"]
            elif r["status"] == "failed":
                stage_summary[r["stage"]]["failed"] += r["cnt"]

        # Determine current stage: latest started event without a matching completed
        current_stage_cur = await conn.execute(
            "SELECT e.stage FROM mining_run_stage_events e "
            "WHERE e.run_id = %s AND e.run_document_id IS NOT NULL AND e.status = 'started' "
            "AND NOT EXISTS ("
            "  SELECT 1 FROM mining_run_stage_events e2 "
            "  WHERE e2.run_id = e.run_id AND e2.run_document_id = e.run_document_id "
            "  AND e2.stage = e.stage AND e2.status IN ('completed', 'failed') "
            "  AND e2.created_at > e.created_at"
            ") ORDER BY e.created_at DESC LIMIT 1",
            [run_id],
        )
        current_stage_row = await current_stage_cur.fetchone()
        current_stage = current_stage_row["stage"] if current_stage_row else None

        # 全局尾段（run_document_id IS NULL）：落图 + 建库/发布。这些阶段在所有文档
        # 提交之后才整体跑一次，进度条必须把它们算进去——否则会出现"文档 100%、整轮
        # 其实还在落图/构建"的误导性满格。
        global_cur = await conn.execute(
            "SELECT stage FROM mining_run_stage_events "
            "WHERE run_id = %s AND run_document_id IS NULL AND status = 'completed' "
            "GROUP BY stage",
            [run_id],
        )
        global_done_stages = {r["stage"] for r in await global_cur.fetchall()}

    total = run["total_documents"] or 0
    completed = status_counts.get("committed", 0)
    failed = status_counts.get("failed", 0)
    skipped = status_counts.get("skipped", 0)
    processing = status_counts.get("processing", 0) + status_counts.get("pending", 0)

    # 进度 = 文档单元 + 全局尾段单元。每篇文档算 1 个单元，每个全局尾段也算 1 个单元，
    # 这样"18 篇全提交"只到 ~82%，落图/建库/发布各自完成才继续往上爬到 100%。
    GLOBAL_TAIL_STAGES = ("graph_write", "assemble_build", "validate_build", "publish_release")
    done_global = sum(1 for s in GLOBAL_TAIL_STAGES if s in global_done_stages)
    total_units = total + len(GLOBAL_TAIL_STAGES)
    done_units = completed + failed + skipped + done_global
    progress_percent = round(done_units / total_units * 100, 1) if total_units else 0.0
    # 只有整轮真正结束（status=completed）才显示 100%；尾段还在跑、或尾段被跳过
    # （如无 active 本体跳过落图）导致分子凑不满时，封顶在 99.9% 以免误导。
    if run["status"] == "completed":
        progress_percent = 100.0
    elif progress_percent >= 100.0:
        progress_percent = 99.9

    return {
        "run_id": run_id,
        "total": total,
        "completed": completed,
        "failed": failed,
        "skipped": skipped,
        "processing": processing,
        "progress_percent": progress_percent,
        "current_stage": current_stage,
        "stage_summary": stage_summary,
        "global_done_stages": sorted(global_done_stages),
    }


@router.get("/{run_id}/documents/{doc_id}")
async def get_run_document(
    run_id: str, doc_id: str, request: Request,
    domain: str = Query(..., min_length=1),
) -> dict:
    """Get single document detail within a run."""
    pool = request.app.state.pg_pool
    await _require_run_domain(pool, run_id, domain)

    async with pool.connection() as conn:
        cur = await conn.execute(
            "SELECT d.id, d.run_id, d.document_key, d.action, d.status, "
            "d.document_id, d.document_snapshot_id, d.error_message, "
            "d.raw_content_hash, d.normalized_content_hash, d.started_at, d.finished_at "
            "FROM mining_run_documents d "
            "WHERE d.id = %s AND d.run_id = %s",
            [doc_id, run_id],
        )
        doc = await cur.fetchone()
        if not doc:
            raise HTTPException(404, f"Document {doc_id} not found in run {run_id}")

        result = dict(doc)
        # Compute document_name
        dk = result.get("document_key", "")
        result["document_name"] = dk.replace("doc:/", "", 1) if dk.startswith("doc:/") else dk

    return result


_RENDERABLE_EXTS = {".md", ".markdown", ".txt", ".html", ".htm"}
_MAX_RAW_CONTENT_SIZE = 10 * 1024 * 1024  # 10 MB


def _decode_html_bytes(raw: bytes) -> str:
    """Decode HTML bytes to UTF-8 string, handling GBK/GB2312/GB18030."""
    if raw[:3] == b'\xef\xbb\xbf':
        return raw[3:].decode("utf-8", errors="replace")
    head = raw[:4000].lower()
    charset_match = re.search(rb'charset=["\']?\s*([a-z0-9_-]+)', head)
    if charset_match:
        charset = charset_match.group(1).decode("ascii")
        try:
            return raw.decode(charset, errors="replace")
        except (LookupError, UnicodeDecodeError):
            pass
    try:
        raw.decode("utf-8")
        return raw.decode("utf-8", errors="replace")
    except UnicodeDecodeError:
        return raw.decode("gbk", errors="replace")


def _find_file_in_uploads(relative_path: str) -> Path | None:
    """Search UPLOAD_ROOT/domain/*/relative_path for a file."""
    from knowledge_mining.mining.infra.upload_config import UploadConfig
    upload_root = UploadConfig().upload_root_path
    if not relative_path or not upload_root.is_dir():
        return None
    for domain_dir in upload_root.iterdir():
        if not domain_dir.is_dir():
            continue
        for batch_dir in domain_dir.iterdir():
            if not batch_dir.is_dir():
                continue
            candidate = batch_dir / relative_path
            if candidate.is_file():
                return candidate
    return None


@router.get("/{run_id}/documents/{doc_id}/raw-content")
async def get_run_document_raw_content(run_id: str, doc_id: str, request: Request):
    """Return the original file content for a run document (md/txt/html)."""
    pool = request.app.state.pg_pool

    async with pool.connection() as conn:
        # Get document_key and run's input_path
        cur = await conn.execute(
            "SELECT d.document_key, r.input_path "
            "FROM mining_run_documents d "
            "JOIN mining_runs r ON r.id = d.run_id "
            "WHERE d.id = %s AND d.run_id = %s",
            [doc_id, run_id],
        )
        row = await cur.fetchone()
        if not row:
            raise HTTPException(404, f"Document {doc_id} not found in run {run_id}")

    document_key = row["document_key"] or ""
    input_path = row["input_path"]

    # document_key format: "doc:/relative/path/file.md" or just "relative/path/file.md"
    if document_key.startswith("doc:/"):
        rel_path = document_key[5:]
    else:
        rel_path = document_key

    file_path: Path | None = None

    # Strategy 1: input_path + rel_path (same-environment)
    if input_path and rel_path:
        base_path = Path(input_path).resolve()
        candidate = (base_path / rel_path).resolve()
        if candidate.is_file() and candidate.is_relative_to(base_path):
            file_path = candidate

    # Strategy 2: Search UPLOAD_ROOT for relative_path (cross-environment fallback)
    if file_path is None and rel_path:
        file_path = _find_file_in_uploads(rel_path)

    if file_path is None:
        raise HTTPException(404, f"Source file not found: {rel_path}")

    ext = file_path.suffix.lower()
    if ext not in _RENDERABLE_EXTS:
        raise HTTPException(
            400,
            f"File type '{ext}' is not renderable. Supported: {', '.join(sorted(_RENDERABLE_EXTS))}",
        )

    file_size = file_path.stat().st_size
    if file_size > _MAX_RAW_CONTENT_SIZE:
        raise HTTPException(413, "File too large for inline rendering")

    try:
        content_bytes = file_path.read_bytes()
    except OSError as exc:
        logger.error("Failed to read file %s: %s", file_path, exc)
        raise HTTPException(500, "Failed to read source file") from exc

    if ext in (".html", ".htm"):
        html_text = _decode_html_bytes(content_bytes)
        return HTMLResponse(
            content=html_text.encode("utf-8"),
            status_code=200,
            headers={"X-Content-Format": "html"},
        )

    content = content_bytes.decode("utf-8", errors="replace")

    if ext in (".md", ".markdown"):
        return PlainTextResponse(
            content=content,
            status_code=200,
            headers={"X-Content-Format": "markdown"},
        )

    return PlainTextResponse(content=content, status_code=200)


@router.get("/{run_id}/documents/{doc_id}/stages")
async def get_run_document_stages(
    run_id: str, doc_id: str, request: Request,
    domain: str = Query(..., min_length=1),
) -> dict:
    """Get stage timeline for a single document within a run."""
    pool = request.app.state.pg_pool
    await _require_run_domain(pool, run_id, domain)

    async with pool.connection() as conn:
        # Verify doc belongs to run
        check_cur = await conn.execute(
            "SELECT id FROM mining_run_documents WHERE id = %s AND run_id = %s",
            [doc_id, run_id],
        )
        if not await check_cur.fetchone():
            raise HTTPException(404, f"Document {doc_id} not found in run {run_id}")

        cur = await conn.execute(
            "SELECT id, stage, status, created_at, duration_ms, "
            "output_summary, error_message "
            "FROM mining_run_stage_events "
            "WHERE run_id = %s AND run_document_id = %s "
            "ORDER BY created_at",
            [run_id, doc_id],
        )
        rows = await cur.fetchall()

    return {"run_id": run_id, "document_id": doc_id, "stages": [dict(r) for r in rows]}


@router.get("/{run_id}/documents/{doc_id}/artifacts")
async def get_run_document_artifacts(
    run_id: str, doc_id: str, request: Request,
    domain: str = Query(..., min_length=1),
) -> dict:
    """Get artifact counts for a single document (via document_snapshot_id)."""
    pool = request.app.state.pg_pool
    await _require_run_domain(pool, run_id, domain)

    async with pool.connection() as conn:
        # Get document_snapshot_id
        doc_cur = await conn.execute(
            "SELECT id, document_snapshot_id FROM mining_run_documents "
            "WHERE id = %s AND run_id = %s",
            [doc_id, run_id],
        )
        doc = await doc_cur.fetchone()
        if not doc:
            raise HTTPException(404, f"Document {doc_id} not found in run {run_id}")

        snapshot_id = doc["document_snapshot_id"]
        if not snapshot_id:
            return {"run_id": run_id, "document_id": doc_id, "snapshot_id": None,
                    "segment_count": 0, "unit_count": 0, "relation_count": 0}

        # Count segments
        seg_cur = await conn.execute(
            "SELECT COUNT(*) as c FROM asset_raw_segments WHERE document_snapshot_id = %s",
            [snapshot_id],
        )
        segment_count = (await seg_cur.fetchone())["c"]

        # Count retrieval units
        unit_cur = await conn.execute(
            "SELECT COUNT(*) as c FROM asset_retrieval_units WHERE document_snapshot_id = %s",
            [snapshot_id],
        )
        unit_count = (await unit_cur.fetchone())["c"]

        # Count relations
        rel_cur = await conn.execute(
            "SELECT COUNT(*) as c FROM asset_raw_segment_relations WHERE document_snapshot_id = %s",
            [snapshot_id],
        )
        relation_count = (await rel_cur.fetchone())["c"]

    return {
        "run_id": run_id,
        "document_id": doc_id,
        "snapshot_id": snapshot_id,
        "segment_count": segment_count,
        "unit_count": unit_count,
        "relation_count": relation_count,
    }


@router.get("/{run_id}/documents/{doc_id}/segments")
async def get_run_document_segments(
    run_id: str, doc_id: str, request: Request,
    domain: str = Query(..., min_length=1),
    limit: int = Query(100, ge=1, le=500),
    offset: int = Query(0, ge=0),
) -> dict:
    """Get segments for a single document in run context."""
    pool = request.app.state.pg_pool
    await _require_run_domain(pool, run_id, domain)

    async with pool.connection() as conn:
        doc_cur = await conn.execute(
            "SELECT document_snapshot_id FROM mining_run_documents "
            "WHERE id = %s AND run_id = %s",
            [doc_id, run_id],
        )
        doc = await doc_cur.fetchone()
        if not doc:
            raise HTTPException(404, f"Document {doc_id} not found in run {run_id}")

        snapshot_id = doc["document_snapshot_id"]
        if not snapshot_id:
            return {"run_id": run_id, "document_id": doc_id, "snapshot_id": None, "total": 0, "limit": limit, "offset": offset, "items": []}

        count_cur = await conn.execute(
            "SELECT COUNT(*) as c FROM asset_raw_segments WHERE document_snapshot_id = %s",
            [snapshot_id],
        )
        total = (await count_cur.fetchone())["c"]

        cur = await conn.execute(
            "SELECT id, segment_key, segment_index, block_type, semantic_role, "
            "section_title, raw_text, token_count "
            "FROM asset_raw_segments "
            "WHERE document_snapshot_id = %s "
            "ORDER BY segment_index LIMIT %s OFFSET %s",
            [snapshot_id, limit, offset],
        )
        rows = await cur.fetchall()

    return {
        "run_id": run_id, "document_id": doc_id, "snapshot_id": snapshot_id,
        "total": total, "limit": limit, "offset": offset,
        "items": [dict(r) for r in rows],
    }


@router.get("/{run_id}/documents/{doc_id}/units")
async def get_run_document_units(
    run_id: str, doc_id: str, request: Request,
    domain: str = Query(..., min_length=1),
    unit_type: str | None = None,
    limit: int = Query(100, ge=1, le=500),
    offset: int = Query(0, ge=0),
) -> dict:
    """Get retrieval units for a single document in run context."""
    pool = request.app.state.pg_pool
    await _require_run_domain(pool, run_id, domain)

    async with pool.connection() as conn:
        doc_cur = await conn.execute(
            "SELECT document_snapshot_id FROM mining_run_documents "
            "WHERE id = %s AND run_id = %s",
            [doc_id, run_id],
        )
        doc = await doc_cur.fetchone()
        if not doc:
            raise HTTPException(404, f"Document {doc_id} not found in run {run_id}")

        snapshot_id = doc["document_snapshot_id"]
        if not snapshot_id:
            return {"run_id": run_id, "document_id": doc_id, "snapshot_id": None, "total": 0, "limit": limit, "offset": offset, "items": []}

        where = "AND unit_type = %s" if unit_type else ""
        params: list[str] = [snapshot_id] + ([unit_type] if unit_type else [])

        count_cur = await conn.execute(
            f"SELECT COUNT(*) as c FROM asset_retrieval_units WHERE document_snapshot_id = %s {where}",
            params,
        )
        total = (await count_cur.fetchone())["c"]

        cur = await conn.execute(
            f"SELECT id, unit_key, unit_type, target_type, title, text, "
            f"block_type, semantic_role, weight, created_at "
            f"FROM asset_retrieval_units "
            f"WHERE document_snapshot_id = %s {where} "
            f"ORDER BY created_at LIMIT %s OFFSET %s",
            params + [limit, offset],
        )
        rows = await cur.fetchall()

    return {
        "run_id": run_id, "document_id": doc_id, "snapshot_id": snapshot_id,
        "total": total, "limit": limit, "offset": offset,
        "items": [dict(r) for r in rows],
    }


@router.get("/{run_id}/documents/{doc_id}/relations")
async def get_run_document_relations(
    run_id: str, doc_id: str, request: Request,
    domain: str = Query(..., min_length=1),
    limit: int = Query(100, ge=1, le=500),
    offset: int = Query(0, ge=0),
) -> dict:
    """Get segment relations for a single document in run context."""
    pool = request.app.state.pg_pool
    await _require_run_domain(pool, run_id, domain)

    async with pool.connection() as conn:
        doc_cur = await conn.execute(
            "SELECT document_snapshot_id FROM mining_run_documents "
            "WHERE id = %s AND run_id = %s",
            [doc_id, run_id],
        )
        doc = await doc_cur.fetchone()
        if not doc:
            raise HTTPException(404, f"Document {doc_id} not found in run {run_id}")

        snapshot_id = doc["document_snapshot_id"]
        if not snapshot_id:
            return {"run_id": run_id, "document_id": doc_id, "snapshot_id": None, "total": 0, "limit": limit, "offset": offset, "items": []}

        count_cur = await conn.execute(
            "SELECT COUNT(*) as c FROM asset_raw_segment_relations WHERE document_snapshot_id = %s",
            [snapshot_id],
        )
        total = (await count_cur.fetchone())["c"]

        # Join with segments to get preview text
        cur = await conn.execute(
            "SELECT r.id, r.document_snapshot_id, r.source_segment_id, "
            "r.target_segment_id, r.relation_type, r.weight, "
            "r.confidence, r.distance, "
            "s1.raw_text AS source_text, s2.raw_text AS target_text "
            "FROM asset_raw_segment_relations r "
            "LEFT JOIN asset_raw_segments s1 ON s1.id = r.source_segment_id "
            "LEFT JOIN asset_raw_segments s2 ON s2.id = r.target_segment_id "
            "WHERE r.document_snapshot_id = %s "
            "ORDER BY r.confidence DESC NULLS LAST LIMIT %s OFFSET %s",
            [snapshot_id, limit, offset],
        )
        rows = await cur.fetchall()

    return {
        "run_id": run_id, "document_id": doc_id, "snapshot_id": snapshot_id,
        "total": total, "limit": limit, "offset": offset,
        "items": [dict(r) for r in rows],
    }


@router.get("/{run_id}/artifacts")
async def get_run_artifacts(run_id: str, request: Request, domain: str = Query(..., min_length=1)) -> dict:
    """Get run-level artifact aggregation."""
    pool = request.app.state.pg_pool
    await _require_run_domain(pool, run_id, domain)

    async with pool.connection() as conn:
        # Verify run exists
        run_cur = await conn.execute(
            "SELECT id FROM mining_runs WHERE id = %s", [run_id]
        )
        if not await run_cur.fetchone():
            raise HTTPException(404, f"Run {run_id} not found")

        # Collect all snapshot IDs for this run
        snap_cur = await conn.execute(
            "SELECT document_snapshot_id FROM mining_run_documents "
            "WHERE run_id = %s AND document_snapshot_id IS NOT NULL",
            [run_id],
        )
        snap_rows = await snap_cur.fetchall()
        snapshot_ids = [r["document_snapshot_id"] for r in snap_rows]

        if not snapshot_ids:
            return {"run_id": run_id, "document_count": 0,
                    "segment_count": 0, "unit_count": 0, "relation_count": 0}

        placeholders = ",".join(["%s"] * len(snapshot_ids))

        seg_cur = await conn.execute(
            f"SELECT COUNT(*) as c FROM asset_raw_segments "
            f"WHERE document_snapshot_id IN ({placeholders})", snapshot_ids
        )
        segment_count = (await seg_cur.fetchone())["c"]

        unit_cur = await conn.execute(
            f"SELECT COUNT(*) as c FROM asset_retrieval_units "
            f"WHERE document_snapshot_id IN ({placeholders})", snapshot_ids
        )
        unit_count = (await unit_cur.fetchone())["c"]

        rel_cur = await conn.execute(
            f"SELECT COUNT(*) as c FROM asset_raw_segment_relations "
            f"WHERE document_snapshot_id IN ({placeholders})", snapshot_ids
        )
        relation_count = (await rel_cur.fetchone())["c"]

    return {
        "run_id": run_id,
        "document_count": len(snapshot_ids),
        "segment_count": segment_count,
        "unit_count": unit_count,
        "relation_count": relation_count,
    }


@router.post("/{run_id}/cancel", response_model=CancelRunResponse)
async def cancel_run(run_id: str, request: Request, domain: str = Query(..., min_length=1)) -> dict:
    """Cancel a running run (best-effort)."""
    pool = request.app.state.pg_pool
    await _require_run_domain(pool, run_id, domain)

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


class PublishRunRequest(BaseModel):
    domain: str | None = None


@router.post("/{run_id}/publish")
async def publish_run(
    run_id: str, request: Request,
    domain: str = Query(..., min_length=1),
    body: PublishRunRequest | None = None,
) -> dict:
    """Publish a completed run's build as active release."""
    db_config: MiningDbConfig = request.app.state.db_config
    pool = request.app.state.pg_pool
    await _require_run_domain(pool, run_id, domain)

    try:
        publish_domain = require_domain(domain)

        from knowledge_mining.mining.jobs.run import publish
        result = publish(run_id, domain=publish_domain, db_config=db_config)
        return result
    except ValueError as e:
        raise HTTPException(400, str(e))
    except Exception as e:
        raise HTTPException(500, f"Publish failed: {e}")


@router.get("/{run_id}/trace")
async def get_run_trace(run_id: str, request: Request, domain: str = Query(..., min_length=1)) -> dict:
    """B7 挖掘过程透视：在常规 run 详情之上叠加本体/图谱视角的概览。

    返回 run 状态（含 awaiting_review 的 subloop_stage）+ 两道检查点的待办数 +
    该 run 落图的对象/边规模，供前端"透明前端"页一屏看清这次挖掘干了什么。
    """
    pool = request.app.state.pg_pool
    await _require_run_domain(pool, run_id, domain)

    async with pool.connection() as conn:
        run_cur = await conn.execute(
            "SELECT id, domain, status, subloop_stage, ontology_version_id, "
            "total_documents, committed_count, new_count, updated_count, "
            "failed_count, skipped_count, started_at, finished_at "
            "FROM mining_runs WHERE id = %s", [run_id]
        )
        run = await run_cur.fetchone()
        if not run:
            raise HTTPException(404, f"Run {run_id} not found")
        run_domain = run["domain"]

        # 本体确认: 该领域待审本体候选数
        cand_cur = await conn.execute(
            "SELECT COUNT(*) AS n FROM ontology_candidates "
            "WHERE domain_id = %s AND status = 'proposed'", [run_domain]
        )
        proposed_candidates = (await cand_cur.fetchone())["n"]

        # 本体线 entity_extract 产出：逃生口候选数（source='escape_hatch'，含待审/已处理）
        esc_cur = await conn.execute(
            "SELECT COUNT(*) AS n FROM ontology_candidates "
            "WHERE domain_id = %s AND source = 'escape_hatch'", [run_domain]
        )
        escape_hatch_candidates = (await esc_cur.fetchone())["n"]

        # 实体确认: 该 run 处理快照下的待审 mention 数
        ment_cur = await conn.execute(
            "SELECT COUNT(*) AS n FROM asset_segment_entity_mentions m "
            "JOIN mining_run_documents d ON d.document_snapshot_id = m.document_snapshot_id "
            "WHERE d.run_id = %s AND m.resolve_status = 'pending'", [run_id]
        )
        pending_mentions = (await ment_cur.fetchone())["n"]

        # 该 run 落图规模（对象/边按 domain 计；MVP 不按 snapshot 精确切分）
        ent_cur = await conn.execute(
            "SELECT COUNT(*) AS n FROM ontology_entities WHERE domain_id = %s", [run_domain]
        )
        entity_count = (await ent_cur.fetchone())["n"]
        rel_cur = await conn.execute(
            "SELECT COUNT(*) AS n FROM ontology_entity_relations WHERE domain_id = %s", [run_domain]
        )
        relation_count = (await rel_cur.fetchone())["n"]

    return {
        "run_id": run_id,
        "domain": run_domain,
        "status": run["status"],
        "subloop_stage": run["subloop_stage"],
        "ontology_version_id": run["ontology_version_id"],
        "awaiting_review": run["status"] == "awaiting_review",
        "active_gate": run["subloop_stage"] if run["status"] == "awaiting_review" else None,
        "counts": {
            "total_documents": run["total_documents"],
            "committed": run["committed_count"],
            "new": run["new_count"],
            "updated": run["updated_count"],
            "failed": run["failed_count"],
            "skipped": run["skipped_count"],
        },
        "ontology_proposed_candidates": proposed_candidates,
        "entity_pending_mentions": pending_mentions,
        "entity_count": entity_count,
        "relation_count": relation_count,
        "escape_hatch_candidates": escape_hatch_candidates,
    }


class ResumeRunRequest(BaseModel):
    domain: str | None = None
    publish_on_partial_failure: bool = False


@router.post("/{run_id}/resume")
async def resume_run(
    run_id: str, request: Request,
    domain: str = Query(..., min_length=1),
    body: ResumeRunRequest | None = None,
) -> dict:
    """B6/B7：人审提交后续跑一个 awaiting_review 的 run。

    重新评估两道检查点：仍有待办 → 保持 awaiting_review 刷新 subloop_stage；
    都清空 → 从 graph_write 之后续跑（建库 + 发布），不重抽文档。

    **异步执行**：续跑要跑 LLM 归纳 + 建库发布，可能耗时数分钟。若同步等结果，
    上游网关会先超时（504），用户重试又撞上已变更的状态（400）。所以这里只做快速校验，
    重活丢后台线程，立即返回 status=resuming，让前端轮询 run 状态看进度（与初始挖掘一致）。
    """
    db_config: MiningDbConfig = request.app.state.db_config
    pool = request.app.state.pg_pool
    await _require_run_domain(pool, run_id, domain)

    # 快速读当前 run 状态（同时拿 domain，避免再查一次）
    async with pool.connection() as conn:
        cur = await conn.execute(
            "SELECT domain, status, subloop_stage, finished_at FROM mining_runs WHERE id = %s",
            [run_id],
        )
        row = await cur.fetchone()
    if row is None:
        raise HTTPException(404, f"Run {run_id} not found")

    resume_domain = require_domain(domain)
    status = row["status"]
    stage = row["subloop_stage"]
    finished = row["finished_at"]

    # 已完成：别报错，直接告诉前端"无需继续"——重试已跑完的 run 不应是错误。
    if status == "completed":
        return {"run_id": run_id, "status": "completed", "message": "该 run 已完成，无需继续"}

    # 可续跑：① 人审暂停；② 收尾中断卡在 running/done（finished_at 仍空）的恢复。
    resumable = status == "awaiting_review" or (status == "running" and stage == "done" and finished is None)
    if not resumable:
        raise HTTPException(
            400, f"Run {run_id} 当前状态为 {status}{f'/{stage}' if stage else ''}，无法继续挖掘")

    publish_partial = body.publish_on_partial_failure if body else False

    # 防并发：和初始挖掘共用一把锁，避免续跑与新挖掘互相踩。
    if not _run_lock.acquire(blocking=False):
        raise HTTPException(409, "已有挖掘任务在进行中，请稍候再试")

    def _resume_in_thread():
        try:
            from knowledge_mining.mining.jobs.run import resume as resume_run_job
            resume_run_job(
                run_id, domain=resume_domain, db_config=db_config,
                publish_on_partial_failure=publish_partial,
            )
        except Exception as e:
            logger.error("Resume run failed: %s", e, exc_info=True)
        finally:
            _run_lock.release()

    threading.Thread(target=_resume_in_thread, daemon=True).start()
    return {"run_id": run_id, "status": "resuming", "message": "已开始继续挖掘，请稍候查看进度"}


def _utcnow() -> str:
    from datetime import datetime, timezone
    return datetime.now(timezone.utc).isoformat()
