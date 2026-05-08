from __future__ import annotations

from fastapi import APIRouter, HTTPException, Request

from llm_service.models import EmbeddingTaskRequest, RerankTaskRequest, TaskSubmitRequest

router = APIRouter(prefix="/api/v1")


@router.post("/tasks")
async def submit_task(body: TaskSubmitRequest, request: Request):
    svc = request.app.state.llm_service
    task_id = await svc.submit(
        body.caller_domain,
        body.pipeline_stage,
        template_key=body.template_key,
        input=body.input,
        messages=body.messages,
        params=body.params,
        expected_output_type=body.expected_output_type,
        output_schema=body.output_schema,
        idempotency_key=body.idempotency_key,
        metadata=body.metadata,
        max_attempts=body.max_attempts,
        priority=body.priority,
    )
    task = await svc.get_task(task_id)
    return {
        "task_id": task_id,
        "status": task["status"],
        "idempotency_key": task.get("idempotency_key"),
        "created_at": task["created_at"],
    }


@router.post("/tasks/embed")
async def submit_embedding_task(body: EmbeddingTaskRequest, request: Request):
    svc = request.app.state.llm_service
    texts = body.input if isinstance(body.input, list) else [body.input]
    task_id = await svc.submit_embedding(
        texts,
        model=body.model,
        dimensions=body.dimensions,
        caller_domain=body.caller_domain,
        pipeline_stage=body.pipeline_stage,
        idempotency_key=body.idempotency_key,
        max_attempts=body.max_attempts,
        priority=body.priority,
    )
    task = await svc.get_task(task_id)
    return {
        "task_id": task_id,
        "status": task["status"],
        "created_at": task["created_at"],
    }


@router.post("/tasks/rerank")
async def submit_rerank_task(body: RerankTaskRequest, request: Request):
    svc = request.app.state.llm_service
    task_id = await svc.submit_rerank(
        body.query,
        body.documents,
        model=body.model,
        top_n=body.top_n,
        caller_domain=body.caller_domain,
        pipeline_stage=body.pipeline_stage,
        idempotency_key=body.idempotency_key,
        max_attempts=body.max_attempts,
        priority=body.priority,
    )
    task = await svc.get_task(task_id)
    return {
        "task_id": task_id,
        "status": task["status"],
        "created_at": task["created_at"],
    }


@router.post("/execute")
async def execute_task(body: TaskSubmitRequest, request: Request):
    svc = request.app.state.llm_service
    return await svc.execute(
        body.caller_domain,
        body.pipeline_stage,
        template_key=body.template_key,
        input=body.input,
        messages=body.messages,
        params=body.params,
        expected_output_type=body.expected_output_type,
        output_schema=body.output_schema,
        idempotency_key=body.idempotency_key,
        metadata=body.metadata,
        max_attempts=body.max_attempts,
        priority=body.priority,
    )


@router.get("/tasks/{task_id}")
async def get_task(task_id: str, request: Request):
    svc = request.app.state.llm_service
    task = await svc.get_task(task_id)
    if not task:
        raise HTTPException(status_code=404, detail="task not found")
    return dict(task)


@router.post("/tasks/{task_id}/cancel")
async def cancel_task(task_id: str, request: Request):
    svc = request.app.state.llm_service
    await svc.cancel(task_id)
    return {"task_id": task_id, "status": "cancelled"}
