from __future__ import annotations

from fastapi import APIRouter, HTTPException, Request

router = APIRouter(prefix="/api/v1")


@router.get("/tasks/{task_id}/result")
async def get_result(task_id: str, request: Request):
    svc = request.app.state.llm_service
    result = await svc.get_result(task_id)
    if not result:
        raise HTTPException(status_code=404, detail="result not found")
    return {"success": True, "data": dict(result)}


@router.get("/tasks/{task_id}/request")
async def get_request(task_id: str, request: Request):
    db = request.app.state.db
    row = await db.fetchone("SELECT * FROM agent_llm_requests WHERE task_id = %s", (task_id,))
    if not row:
        raise HTTPException(status_code=404, detail="request not found")
    data = dict(row)
    # JSONB columns are already parsed by psycopg; no need to json.loads
    return {"success": True, "data": data}


@router.get("/tasks/{task_id}/attempts")
async def get_attempts(task_id: str, request: Request):
    svc = request.app.state.llm_service
    attempts = await svc.get_attempts(task_id)
    return {"success": True, "data": attempts}


@router.get("/tasks/{task_id}/events")
async def get_events(task_id: str, request: Request):
    svc = request.app.state.llm_service
    events = await svc.get_events(task_id)
    return {"success": True, "data": events}
