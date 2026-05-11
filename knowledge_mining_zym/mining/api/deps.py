"""Dependency injection for Mining API."""
from __future__ import annotations

from functools import lru_cache
from typing import Any

from fastapi import Request

from knowledge_mining.mining.infra.db import AssetCoreDB, MiningRuntimeDB
from knowledge_mining.mining.infra.pg_config import MiningDbConfig


def get_pool(request: Request) -> Any:
    """Get PostgreSQL connection pool from app state."""
    return request.app.state.pg_pool


def get_config(request: Request) -> MiningDbConfig:
    """Get current MiningDbConfig from app state."""
    return request.app.state.db_config


def get_asset_db(request: Request) -> AssetCoreDB:
    """Create a read-only AssetCoreDB adapter from the shared pool."""
    return AssetCoreDB(request.app.state.pg_pool)


def get_runtime_db(request: Request) -> MiningRuntimeDB:
    """Create a read-only MiningRuntimeDB adapter from the shared pool."""
    return MiningRuntimeDB(request.app.state.pg_pool)
