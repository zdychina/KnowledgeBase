from __future__ import annotations

import logging
from contextlib import asynccontextmanager
from typing import Callable

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from llm_service.config import LLMServiceConfig
from llm_service.db import LlmRuntimeDB
from llm_service.pg_config import LlmDbConfig
from llm_service.pg_schema import ensure_schema
from llm_service.providers.bigmodel_models import BigModelProvider
from llm_service.providers.model_base import ModelProviderProtocol
from llm_service.providers.base import ProviderProtocol
from llm_service.providers.openai_compatible import OpenAICompatibleProvider
from llm_service.runtime.model_service import ModelService
from llm_service.runtime.service import LLMService
from llm_service.runtime.worker import LeaseRecovery, Worker

logger = logging.getLogger(__name__)


def create_app(
    config: LLMServiceConfig | None = None,
    provider_factory: Callable[[], ProviderProtocol] | None = None,
    model_provider_factory: Callable[[], ModelProviderProtocol] | None = None,
    *,
    start_worker: bool = True,
) -> FastAPI:
    cfg = config or LLMServiceConfig()
    if not cfg.provider_api_key and not provider_factory:
        raise ValueError(
            "LLM_SERVICE_PROVIDER_API_KEY is required. "
            "Set it in .env or as an environment variable."
        )
    _factory = provider_factory

    @asynccontextmanager
    async def lifespan(app: FastAPI):
        # PostgreSQL initialization
        pg_cfg = LlmDbConfig()
        logger.info("Ensuring database schema for %s @ %s:%s", pg_cfg.pg_dbname, pg_cfg.pg_host, pg_cfg.pg_port)
        ensure_schema(pg_cfg)

        db = LlmRuntimeDB.from_conninfo(
            pg_cfg.conninfo,
            pool_min=pg_cfg.pg_pool_min,
            pool_max=pg_cfg.pg_pool_max,
        )
        await db.open()

        # Startup health check
        health = await db.health_check()
        if not health.get("connected"):
            await db.close()
            raise RuntimeError(f"Database health check failed: {health.get('error', 'cannot connect')}")
        if not health.get("tables_ok"):
            logger.warning("Database tables check: %s", health)
        logger.info(
            "Database health check passed (connected=%s, tables=%s, tasks=%s)",
            health["connected"], health["tables_ok"], health.get("task_count", "?"),
        )

        provider = _factory() if _factory else OpenAICompatibleProvider(
            base_url=cfg.provider_base_url,
            api_key=cfg.provider_api_key,
            model=cfg.provider_model,
            headers={**cfg.provider_headers, **cfg.model_extra_headers},
            timeout=cfg.provider_timeout,
            bypass_proxy=cfg.provider_bypass_proxy,
        )
        model_provider = (
            model_provider_factory()
            if model_provider_factory
            else BigModelProvider(
                embedding_api_key=cfg.embedding_api_key,
                embedding_url=cfg.embedding_base_url,
                embedding_model=cfg.embedding_model,
                rerank_api_key=cfg.rerank_api_key,
                rerank_url=cfg.rerank_base_url,
                rerank_model=cfg.rerank_model,
                timeout=cfg.model_timeout,
                bypass_proxy=cfg.model_bypass_proxy,
                extra_headers=cfg.model_extra_headers,
            )
        )
        svc = LLMService(db=db, provider=provider, config=cfg, model_provider=model_provider)
        model_svc = ModelService(
            model_provider, db=db,
            default_embedding_model=cfg.embedding_model,
            default_rerank_model=cfg.rerank_model,
        )
        app.state.llm_service = svc
        app.state.model_service = model_svc
        app.state.db = db

        worker = None
        recovery = None
        try:
            if start_worker:
                # Share LLMService's bus and mgr — single source of truth
                worker = Worker(
                    db=db,
                    task_manager=svc._mgr,
                    event_bus=svc._bus,
                    provider=provider,
                    model_provider=model_provider,
                    templates=svc._templates,
                    concurrency=cfg.worker_concurrency,
                    llm_service=svc,
                )
                await worker.start()

                recovery = LeaseRecovery(
                    db=db,
                    task_manager=svc._mgr,
                    event_bus=svc._bus,
                    interval=30.0,
                )
                await recovery.start()
        except Exception:
            if recovery:
                await recovery.stop()
            if worker:
                await worker.stop()
            await db.close()
            raise

        yield

        if recovery:
            await recovery.stop()
        if worker:
            await worker.stop()
            # Re-queue in-flight tasks so they're recoverable on next startup
            try:
                await db.execute(
                    "UPDATE agent_llm_tasks SET status = 'queued', lease_expires_at = NULL "
                    "WHERE status = 'running'"
                )
                logger.info("Re-queued in-flight tasks on shutdown")
            except Exception:
                logger.exception("Failed to re-queue in-flight tasks")
        if hasattr(provider, 'close'):
            await provider.close()
        if hasattr(model_provider, 'close'):
            await model_provider.close()
        await db.close()

    app = FastAPI(title="LLM Service", version="0.1.0", lifespan=lifespan)
    app.state.config = cfg

    app.add_middleware(
        CORSMiddleware,
        allow_origins=["*"],
        allow_credentials=True,
        allow_methods=["*"],
        allow_headers=["*"],
    )

    from llm_service.api.health import router as health_router
    from llm_service.api.model_api import router as model_api_router
    from llm_service.api.results import router as results_router
    from llm_service.api.stats import router as stats_router
    from llm_service.api.tasks import router as tasks_router
    from llm_service.api.templates import router as templates_router

    app.include_router(health_router)
    app.include_router(model_api_router)
    app.include_router(tasks_router)
    app.include_router(results_router)
    app.include_router(templates_router)
    app.include_router(stats_router)

    return app
