from __future__ import annotations

import json
from datetime import datetime, timezone

from fastapi import APIRouter, Request
from fastapi.responses import HTMLResponse

router = APIRouter()

_ALL_STATUSES = ["queued", "running", "succeeded", "failed", "dead_letter", "cancelled"]
_ALL_TYPES = ["chat", "embedding", "rerank"]
_PAGE_SIZE = 50


@router.get("/dashboard", response_class=HTMLResponse)
async def dashboard(
    request: Request,
    status: str = "",
    domain: str = "",
    stage: str = "",
    task_type: str = "",
    page: int = 1,
):
    db = request.app.state.db

    # --- Stats (always show global) ---
    cur = await db.execute("SELECT COUNT(*) as cnt FROM agent_llm_tasks")
    total = (await cur.fetchone())["cnt"]

    cur = await db.execute("SELECT status, COUNT(*) as cnt FROM agent_llm_tasks GROUP BY status")
    by_status = {row["status"]: row["cnt"] for row in await cur.fetchall()}

    cur = await db.execute("SELECT COALESCE(SUM(total_tokens), 0) as t FROM agent_llm_attempts")
    total_tokens = (await cur.fetchone())["t"]

    # --- Model call stats (embedding / rerank) from tasks ---
    cur = await db.execute(
        "SELECT task_type, COUNT(*) as cnt FROM agent_llm_tasks WHERE task_type IN ('embedding','rerank') GROUP BY task_type"
    )
    type_stats = {row["task_type"]: row["cnt"] for row in await cur.fetchall()}
    embed_count = type_stats.get("embedding", 0)
    rerank_count = type_stats.get("rerank", 0)

    # --- Filter options (from all tasks, not filtered) ---
    cur = await db.execute("SELECT DISTINCT caller_domain FROM agent_llm_tasks ORDER BY caller_domain")
    all_domains = [row["caller_domain"] for row in await cur.fetchall()]

    cur = await db.execute("SELECT DISTINCT pipeline_stage FROM agent_llm_tasks ORDER BY pipeline_stage")
    all_stages = [row["pipeline_stage"] for row in await cur.fetchall()]

    # --- Pagination ---
    page = max(1, page)
    offset = (page - 1) * _PAGE_SIZE

    # --- Count filtered ---
    conditions = []
    params: list = []
    if status:
        conditions.append("t.status = ?")
        params.append(status)
    if domain:
        conditions.append("t.caller_domain = ?")
        params.append(domain)
    if stage:
        conditions.append("t.pipeline_stage = ?")
        params.append(stage)
    if task_type:
        conditions.append("t.task_type = ?")
        params.append(task_type)

    where = (" WHERE " + " AND ".join(conditions)) if conditions else ""

    count_sql = f"SELECT COUNT(*) as cnt FROM agent_llm_tasks t{where}"
    cur = await db.execute(count_sql, params)
    filtered_total = (await cur.fetchone())["cnt"]
    total_pages = max(1, (filtered_total + _PAGE_SIZE - 1) // _PAGE_SIZE)

    # --- Filtered task list (paginated) ---
    sql = f"""
        SELECT t.id, t.caller_domain, t.pipeline_stage, t.status, t.task_type,
               t.attempt_count, t.created_at, t.metadata_json,
               a.total_tokens, a.latency_ms
        FROM agent_llm_tasks t
        LEFT JOIN (
            SELECT task_id, total_tokens, latency_ms,
                   ROW_NUMBER() OVER (PARTITION BY task_id ORDER BY attempt_no DESC) as rn
            FROM agent_llm_attempts
        ) a ON a.task_id = t.id AND a.rn = 1
        {where}
        ORDER BY t.created_at DESC
        LIMIT ? OFFSET ?
    """
    cur = await db.execute(sql, params + [_PAGE_SIZE, offset])
    tasks = [dict(r) for r in await cur.fetchall()]

    templates = request.app.state.templates
    html = templates.get_template("dashboard.html").render(
        total=total,
        by_status=by_status,
        total_tokens=total_tokens,
        embed_count=embed_count,
        rerank_count=rerank_count,
        tasks=tasks,
        all_statuses=_ALL_STATUSES,
        all_types=_ALL_TYPES,
        all_domains=all_domains,
        all_stages=all_stages,
        filter_status=status,
        filter_domain=domain,
        filter_stage=stage,
        filter_type=task_type,
        page=page,
        total_pages=total_pages,
        filtered_total=filtered_total,
    )
    return HTMLResponse(content=html)


@router.get("/dashboard/tasks/{task_id}", response_class=HTMLResponse)
async def task_detail(request: Request, task_id: str):
    db = request.app.state.db

    # Task
    cur = await db.execute("SELECT * FROM agent_llm_tasks WHERE id = ?", (task_id,))
    row = await cur.fetchone()
    if not row:
        return HTMLResponse(content="<h1>Task not found</h1>", status_code=404)
    task = dict(row)
    task_type = task.get("task_type", "chat")

    # Duration
    duration_ms = None
    if task.get("started_at") and task.get("finished_at"):
        try:
            s = datetime.fromisoformat(task["started_at"])
            e = datetime.fromisoformat(task["finished_at"])
            duration_ms = int((e - s).total_seconds() * 1000)
        except (ValueError, TypeError):
            pass

    # Metadata
    metadata_str = ""
    try:
        metadata_str = json.dumps(json.loads(task.get("metadata_json", "{}")), indent=2, ensure_ascii=False)
    except (json.JSONDecodeError, TypeError):
        metadata_str = task.get("metadata_json", "")

    # Request
    cur = await db.execute("SELECT * FROM agent_llm_requests WHERE task_id = ?", (task_id,))
    req_row = await cur.fetchone()
    request_data = dict(req_row) if req_row else None

    messages = []
    schema_str = ""
    input_str = ""
    embed_texts = []
    rerank_query = ""
    rerank_documents = []
    rerank_results = []
    if request_data:
        try:
            messages = json.loads(request_data.get("messages_json", "[]"))
        except (json.JSONDecodeError, TypeError):
            pass
        try:
            schema_str = json.dumps(json.loads(request_data.get("output_schema_json", "{}")), indent=2, ensure_ascii=False)
        except (json.JSONDecodeError, TypeError):
            schema_str = request_data.get("output_schema_json", "")
        try:
            input_json = json.loads(request_data.get("input_json", "{}"))
            input_str = json.dumps(input_json, indent=2, ensure_ascii=False)
            # Extract type-specific fields
            if task_type == "embedding":
                embed_texts = input_json.get("texts", [])
            elif task_type == "rerank":
                rerank_query = input_json.get("query", "")
                rerank_documents = input_json.get("documents", [])
        except (json.JSONDecodeError, TypeError):
            input_str = request_data.get("input_json", "")

    # Result
    cur = await db.execute("SELECT * FROM agent_llm_results WHERE task_id = ?", (task_id,))
    res_row = await cur.fetchone()
    result = dict(res_row) if res_row else None

    parsed_str = ""
    validation_errors_str = ""
    if result:
        try:
            parsed_str = json.dumps(json.loads(result.get("parsed_output_json", "{}")), indent=2, ensure_ascii=False)
        except (json.JSONDecodeError, TypeError):
            parsed_str = result.get("parsed_output_json", "")
        try:
            validation_errors_str = json.dumps(json.loads(result.get("validation_errors_json", "[]")), indent=2, ensure_ascii=False)
        except (json.JSONDecodeError, TypeError):
            validation_errors_str = result.get("validation_errors_json", "")
        # Extract rerank results from parsed output
        if task_type == "rerank" and result.get("parsed_output_json"):
            try:
                parsed = json.loads(result["parsed_output_json"])
                rerank_results = parsed.get("results", [])
                # Normalize document: internal network returns {"text": "...", "multi_modal": null}
                for item in rerank_results:
                    doc = item.get("document")
                    if isinstance(doc, dict):
                        item["document"] = doc.get("text", "")
            except (json.JSONDecodeError, TypeError):
                pass

    # Attempts
    cur = await db.execute("SELECT * FROM agent_llm_attempts WHERE task_id = ? ORDER BY attempt_no", (task_id,))
    attempts = [dict(r) for r in await cur.fetchall()]

    # Events
    cur = await db.execute("SELECT * FROM agent_llm_events WHERE task_id = ? ORDER BY created_at", (task_id,))
    events = [dict(r) for r in await cur.fetchall()]

    # Raw task JSON
    raw_task_str = json.dumps(task, indent=2, ensure_ascii=False, default=str)

    tmpl = request.app.state.templates
    html = tmpl.get_template("task_detail.html").render(
        task=task,
        task_type=task_type,
        duration_ms=duration_ms,
        metadata_str=metadata_str,
        request=request_data,
        messages=messages,
        schema_str=schema_str,
        input_str=input_str,
        embed_texts=embed_texts,
        rerank_query=rerank_query,
        rerank_documents=rerank_documents,
        rerank_results=rerank_results,
        result=result,
        parsed_str=parsed_str,
        validation_errors_str=validation_errors_str,
        attempts=attempts,
        events=events,
        raw_task_str=raw_task_str,
    )
    return HTMLResponse(content=html)


@router.get("/dashboard/api/stats")
async def dashboard_stats(request: Request):
    db = request.app.state.db
    cur = await db.execute("SELECT status, COUNT(*) as cnt FROM agent_llm_tasks GROUP BY status")
    by_status = {row["status"]: row["cnt"] for row in await cur.fetchall()}

    cur = await db.execute("SELECT COUNT(*) as cnt FROM agent_llm_attempts WHERE status = 'succeeded'")
    succeeded = (await cur.fetchone())["cnt"]

    cur = await db.execute("SELECT SUM(total_tokens) as total FROM agent_llm_attempts")
    row = await cur.fetchone()
    total_tokens = row["total"] or 0

    cur = await db.execute("SELECT AVG(latency_ms) as avg_lat FROM agent_llm_attempts WHERE latency_ms IS NOT NULL")
    row = await cur.fetchone()
    avg_latency = row["avg_lat"] or 0

    return {
        "tasks_by_status": by_status,
        "succeeded_attempts": succeeded,
        "total_tokens": total_tokens,
        "avg_latency_ms": round(avg_latency, 1),
    }
