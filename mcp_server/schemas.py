"""Pydantic models for MCP tool inputs and outputs."""

from __future__ import annotations

from pydantic import BaseModel


# --- health_check output ---

class HealthResult(BaseModel):
    available: bool
    status: str = ""
    version: str = ""
    latency_ms: float = 0.0
    error: str = ""


# --- search_knowledge input ---

class EntityRef(BaseModel):
    type: str = ""
    name: str
    normalized_name: str = ""


class SearchInput(BaseModel):
    query: str
    domain: str = "cloud_core_network"
    scope: dict | None = None
    entities: list[EntityRef] | None = None
    debug: bool = False
