"""Mining API — FastAPI application factory.

Start:
    python -m knowledge_mining.mining.api
    # or
    uvicorn knowledge_mining.mining.api.app:create_app --host 0.0.0.0 --port 8901 --factory
"""
from __future__ import annotations

import logging
import os
from contextlib import asynccontextmanager

from fastapi import FastAPI
from psycopg.rows import dict_row
from psycopg_pool import AsyncConnectionPool

from knowledge_mining.mining.infra.pg_config import MiningDbConfig
from knowledge_mining.mining.infra.pg_schema import ensure_schema
from knowledge_mining.mining.api.routes.health import router as health_router
from knowledge_mining.mining.api.routes.runs import router as runs_router
from knowledge_mining.mining.api.routes.knowledge import router as knowledge_router
from knowledge_mining.mining.api.routes.config import router as config_router
from knowledge_mining.mining.api.routes.builds import router as builds_router

logger = logging.getLogger(__name__)


@asynccontextmanager
async def lifespan(app: FastAPI):
    """Initialize PostgreSQL pool and ensure schema exists."""
    cfg = MiningDbConfig()

    # Ensure database + schema (sync, runs once at startup)
    ensure_schema(cfg)

    pool = AsyncConnectionPool(
        cfg.conninfo,
        min_size=cfg.pg_pool_min,
        max_size=cfg.pg_pool_max,
        open=False,
        kwargs={"row_factory": dict_row},
    )
    await pool.open()
    app.state.pg_pool = pool
    app.state.db_config = cfg

    logger.info("Mining API started — PostgreSQL %s:%d/%s", cfg.pg_host, cfg.pg_port, cfg.pg_dbname)

    yield

    await pool.close()
    logger.info("Mining API stopped")


def create_app() -> FastAPI:
    """Application factory for uvicorn --factory."""
    app = FastAPI(
        title="Mining API",
        version="3.0.0",
        description="Knowledge Mining Pipeline — REST API for triggering mining runs, "
                     "querying knowledge assets, and managing builds/releases.",
        lifespan=lifespan,
    )

    app.include_router(health_router)
    app.include_router(runs_router)
    app.include_router(knowledge_router)
    app.include_router(config_router)
    app.include_router(builds_router)

    return app


# Module-level app for `python -m knowledge_mining.mining.api`
app = create_app()


if __name__ == "__main__":
    import uvicorn
    port = int(os.environ.get("MINING_API_PORT", "8901"))
    uvicorn.run(
        "knowledge_mining.mining.api.app:app",
        host="0.0.0.0",
        port=port,
        reload=False,
    )
