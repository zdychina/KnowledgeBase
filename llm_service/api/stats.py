from __future__ import annotations

from fastapi import APIRouter, Query, Request

router = APIRouter(prefix="/api/v1")


@router.get("/stats")
async def get_stats(
    request: Request,
    domain: str = Query(None, description="Filter by knowledge_domain"),
    service: str = Query(None, description="Filter by caller_service"),
):
    """Global statistics overview — single connection, 5 queries."""
    db = request.app.state.db

    async def _queries(conn):
        conditions = []
        params = []
        if domain:
            conditions.append("knowledge_domain = %s")
            params.append(domain)
        if service:
            conditions.append("caller_service = %s")
            params.append(service)
        where = (" WHERE " + " AND ".join(conditions)) if conditions else ""

        # 1. Task aggregates
        cur = await conn.execute(
            f"SELECT status, COUNT(*) AS cnt FROM agent_llm_tasks{where} GROUP BY status",
            tuple(params),
        )
        by_status_rows = await cur.fetchall()
        cur = await conn.execute(
            f"SELECT task_type, COUNT(*) AS cnt FROM agent_llm_tasks{where} GROUP BY task_type",
            tuple(params),
        )
        by_type_rows = await cur.fetchall()

        # 2. Domain/stage + recent failures in one scan
        cur = await conn.execute(f"""
            SELECT
                COUNT(*) FILTER (WHERE status = 'failed' AND created_at > NOW() - INTERVAL '1 hour') AS recent_failures,
                array_agg(DISTINCT caller_service) FILTER (WHERE caller_service IS NOT NULL) AS services,
                array_agg(DISTINCT knowledge_domain) FILTER (WHERE knowledge_domain IS NOT NULL) AS domains,
                array_agg(DISTINCT pipeline_stage) FILTER (WHERE pipeline_stage IS NOT NULL) AS stages
            FROM agent_llm_tasks
            {where}
        """, tuple(params))
        task_agg = await cur.fetchone()

        # 3. Attempt aggregates
        attempt_conditions = []
        attempt_params = []
        if domain:
            attempt_conditions.append("t.knowledge_domain = %s")
            attempt_params.append(domain)
        if service:
            attempt_conditions.append("t.caller_service = %s")
            attempt_params.append(service)
        attempt_where = (" WHERE " + " AND ".join(attempt_conditions)) if attempt_conditions else ""

        cur = await conn.execute(f"""
            SELECT
                COUNT(*) FILTER (WHERE a.status = 'succeeded') AS succeeded_attempts,
                COALESCE(SUM(a.total_tokens), 0) AS total_tokens,
                AVG(a.latency_ms) FILTER (WHERE a.latency_ms IS NOT NULL) AS avg_latency
            FROM agent_llm_attempts a
            JOIN agent_llm_tasks t ON t.id = a.task_id
            {attempt_where}
        """, tuple(attempt_params))
        att = await cur.fetchone()

        # 4. Token by knowledge domain
        cur = await conn.execute(f"""
            SELECT t.knowledge_domain, COALESCE(SUM(a.total_tokens), 0) AS tokens
            FROM agent_llm_attempts a
            JOIN agent_llm_tasks t ON t.id = a.task_id
            {attempt_where}
            GROUP BY t.knowledge_domain
        """, tuple(attempt_params))
        token_rows = await cur.fetchall()

        return by_status_rows, by_type_rows, task_agg, att, token_rows

    by_status_rows, by_type_rows, task_agg, att, token_rows = await db.run(_queries)

    by_status = {row["status"]: row["cnt"] for row in by_status_rows}
    by_type = {row["task_type"]: row["cnt"] for row in by_type_rows}
    tokens_by_domain = {row["knowledge_domain"]: row["tokens"] for row in token_rows if row["knowledge_domain"]}

    recent_failures = (task_agg["recent_failures"] if task_agg else 0) or 0
    total_tokens = (att["total_tokens"] if att else 0) or 0
    avg_latency = (att["avg_latency"] if att else 0) or 0
    succeeded_attempts = (att["succeeded_attempts"] if att else 0) or 0
    services = sorted([s for s in (task_agg["services"] or []) if s]) if task_agg else []
    domains = sorted([d for d in (task_agg["domains"] or []) if d]) if task_agg else []
    stages = sorted([s for s in (task_agg["stages"] or []) if s]) if task_agg else []

    total_tasks = sum(by_status.values())
    success_count = by_status.get("succeeded", 0)
    success_rate = round(success_count / total_tasks, 4) if total_tasks > 0 else 0.0

    return {
        "success": True,
        "data": {
            "tasks_by_status": by_status,
            "tasks_by_type": by_type,
            "succeeded_attempts": succeeded_attempts,
            "total_tokens": total_tokens,
            "avg_latency_ms": round(float(avg_latency), 1),
            "success_rate": success_rate,
            "services": services,
            "domains": domains,
            "stages": stages,
            "recent_failures": recent_failures,
            "tokens_by_domain": tokens_by_domain,
        },
    }


@router.get("/stats/tokens")
async def get_token_stats(
    request: Request,
    domain: str = Query(None, description="Filter by knowledge_domain"),
    service: str = Query(None, description="Filter by caller_service"),
    stage: str = Query(None, description="Filter by pipeline_stage"),
):
    """Token usage statistics with optional filters."""
    db = request.app.state.db
    conditions = []
    params = []
    if domain:
        conditions.append("t.knowledge_domain = %s")
        params.append(domain)
    if service:
        conditions.append("t.caller_service = %s")
        params.append(service)
    if stage:
        conditions.append("t.pipeline_stage = %s")
        params.append(stage)

    where = (" WHERE " + " AND ".join(conditions)) if conditions else ""

    rows = await db.fetchall(
        f"""SELECT t.caller_service, t.knowledge_domain, t.pipeline_stage, t.task_type,
                   SUM(a.total_tokens) as total_tokens,
                   COUNT(*) as attempt_count,
                   AVG(a.latency_ms) as avg_latency
           FROM agent_llm_attempts a
           JOIN agent_llm_tasks t ON t.id = a.task_id
           {where}
           GROUP BY t.caller_service, t.knowledge_domain, t.pipeline_stage, t.task_type
           ORDER BY total_tokens DESC""",
        tuple(params),
    )
    return {"success": True, "data": rows}


@router.get("/tasks")
async def list_tasks(
    request: Request,
    status: str = Query(None),
    domain: str = Query(None),
    service: str = Query(None),
    stage: str = Query(None),
    task_type: str = Query(None),
    page: int = Query(1, ge=1),
    page_size: int = Query(50, ge=1, le=200),
):
    """Task list with pagination and filters."""
    db = request.app.state.db
    conditions = []
    params = []
    if status:
        conditions.append("t.status = %s")
        params.append(status)
    if domain:
        conditions.append("t.knowledge_domain = %s")
        params.append(domain)
    if service:
        conditions.append("t.caller_service = %s")
        params.append(service)
    if stage:
        conditions.append("t.pipeline_stage = %s")
        params.append(stage)
    if task_type:
        conditions.append("t.task_type = %s")
        params.append(task_type)

    where = (" WHERE " + " AND ".join(conditions)) if conditions else ""

    count_row = await db.fetchone(
        f"SELECT COUNT(*) as cnt FROM agent_llm_tasks t{where}",
        tuple(params),
    )
    total = count_row["cnt"] if count_row else 0

    offset = (page - 1) * page_size
    tasks = await db.fetchall(
        f"""SELECT t.id, t.caller_service, t.knowledge_domain,
                   t.pipeline_stage, t.status, t.task_type,
                   t.attempt_count, t.max_attempts, t.priority, t.created_at,
                   t.started_at, t.finished_at, t.metadata_json,
                   a.total_tokens, a.latency_ms
            FROM agent_llm_tasks t
            LEFT JOIN LATERAL (
                SELECT total_tokens, latency_ms
                FROM agent_llm_attempts
                WHERE task_id = t.id AND status = 'succeeded'
                ORDER BY attempt_no DESC LIMIT 1
            ) a ON true
            {where}
            ORDER BY t.created_at DESC
            LIMIT %s OFFSET %s""",
        tuple(params) + (page_size, offset),
    )

    return {
        "success": True,
        "data": {
            "total": total,
            "page": page,
            "page_size": page_size,
            "items": tasks,
        },
    }
