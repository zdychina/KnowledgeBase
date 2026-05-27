from __future__ import annotations

import json

from fastapi import APIRouter, HTTPException, Query, Request
from pydantic import BaseModel, Field

router = APIRouter(prefix="/api/v1/templates")


def _parse_json(value: str | None, default=None):
    if not value:
        return default
    try:
        return json.loads(value)
    except (json.JSONDecodeError, TypeError):
        return default


def _map_template_row(row) -> dict:
    """Map template DB row to stable response."""
    return {
        "id": row["id"],
        "template_key": row["template_key"],
        "template_version": row["template_version"],
        "knowledge_domain": row["knowledge_domain"],
        "purpose": row["purpose"],
        "system_prompt": row["system_prompt"],
        "user_prompt_template": row["user_prompt_template"],
        "expected_output_type": row["expected_output_type"],
        "output_schema": _parse_json(row["output_schema_json"], {}),
        "status": row["status"],
        "created_at": row["created_at"],
    }


class TemplateCreateRequest(BaseModel):
    template_key: str
    template_version: str = "1"
    knowledge_domain: str | None = Field(default=None, min_length=1, max_length=128)
    purpose: str
    system_prompt: str | None = None
    user_prompt_template: str
    expected_output_type: str = Field(default="json_object", pattern=r"^(json_object|json_array|text)$")
    output_schema_json: str = "{}"
    status: str = Field(default="active", pattern=r"^(draft|active|archived)$")


class TemplateUpdateRequest(BaseModel):
    template_version: str | None = None
    knowledge_domain: str | None = Field(default=None, min_length=1, max_length=128)
    purpose: str | None = None
    system_prompt: str | None = None
    user_prompt_template: str | None = None
    expected_output_type: str | None = Field(default=None, pattern=r"^(json_object|json_array|text)$")
    output_schema_json: str | None = None
    status: str | None = Field(default=None, pattern=r"^(draft|active|archived)$")


@router.post("")
async def create_template(body: TemplateCreateRequest, request: Request):
    svc = request.app.state.llm_service
    tpl_id = await svc._templates.create(
        template_key=body.template_key,
        template_version=body.template_version,
        knowledge_domain=body.knowledge_domain,
        purpose=body.purpose,
        system_prompt=body.system_prompt,
        user_prompt_template=body.user_prompt_template,
        expected_output_type=body.expected_output_type,
        output_schema_json=body.output_schema_json,
        status=body.status,
    )
    tpl = await svc._templates.get(tpl_id)
    return _map_template_row(tpl) if tpl else None


@router.get("")
async def list_templates(
    request: Request,
    domain: str | None = Query(default=None, description="Filter to domain templates plus global fallback"),
):
    svc = request.app.state.llm_service
    return [_map_template_row(r) for r in await svc._templates.list_all(domain)]


@router.get("/{template_key}")
async def get_template(
    template_key: str,
    request: Request,
    domain: str | None = Query(default=None, description="Resolve domain-specific template with global fallback"),
):
    svc = request.app.state.llm_service
    tpl = await svc._templates.get_by_key(template_key, domain)
    if not tpl:
        raise HTTPException(status_code=404, detail="template not found")
    return _map_template_row(tpl)


@router.put("/{tpl_id}")
async def update_template(tpl_id: str, body: TemplateUpdateRequest, request: Request):
    svc = request.app.state.llm_service
    existing = await svc._templates.get(tpl_id)
    if not existing:
        raise HTTPException(status_code=404, detail="template not found")
    updates = {k: v for k, v in body.model_dump().items() if v is not None}
    if updates:
        await svc._templates.update(tpl_id, **updates)
    tpl = await svc._templates.get(tpl_id)
    return _map_template_row(tpl) if tpl else None


@router.delete("/{tpl_id}")
async def archive_template(tpl_id: str, request: Request):
    svc = request.app.state.llm_service
    existing = await svc._templates.get(tpl_id)
    if not existing:
        raise HTTPException(status_code=404, detail="template not found")
    await svc._templates.archive(tpl_id)
    return {"id": tpl_id, "status": "archived"}
