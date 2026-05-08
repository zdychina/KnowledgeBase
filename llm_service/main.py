from __future__ import annotations

import logging
from contextlib import asynccontextmanager
from pathlib import Path
from typing import Callable

from fastapi import FastAPI
from jinja2 import Environment, FileSystemLoader

from llm_service.config import LLMServiceConfig
from llm_service.db import init_db
from llm_service.providers.bigmodel_models import BigModelProvider
from llm_service.providers.model_base import ModelProviderProtocol
from llm_service.providers.base import ProviderProtocol
from llm_service.providers.openai_compatible import OpenAICompatibleProvider
from llm_service.runtime.event_bus import EventBus
from llm_service.runtime.model_service import ModelService
from llm_service.runtime.service import LLMService
from llm_service.runtime.task_manager import TaskManager
from llm_service.runtime.template_registry import TemplateRegistry
from llm_service.runtime.worker import LeaseRecovery, Worker

_TEMPLATES_DIR = Path(__file__).resolve().parent / "templates"
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
        # API service uses its own DB connection
        db = await init_db(cfg.db_path)
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
        app.state.templates = Environment(
            loader=FileSystemLoader(str(_TEMPLATES_DIR)),
            autoescape=True,
        )

        worker = None
        recovery = None
        worker_db = None
        recovery_db = None
        try:
            if start_worker:
                # Worker gets its own DB connection to avoid concurrent commit conflicts
                worker_db = await init_db(cfg.db_path)
                worker_tmpl = TemplateRegistry(worker_db)
                worker_bus = EventBus(worker_db)
                worker_mgr = TaskManager(
                    worker_db, worker_bus,
                    max_attempts=cfg.default_max_attempts,
                    lease_duration=cfg.lease_duration,
                    backoff_base=cfg.retry_backoff_base,
                    backoff_max=cfg.retry_backoff_max,
                )
                worker = Worker(
                    db=worker_db,
                    task_manager=worker_mgr,
                    event_bus=worker_bus,
                    provider=provider,
                    model_provider=model_provider,
                    templates=worker_tmpl,
                    concurrency=cfg.worker_concurrency,
                )
                await worker.start()

                # LeaseRecovery gets its own DB connection too
                recovery_db = await init_db(cfg.db_path)
                recovery_bus = EventBus(recovery_db)
                recovery_mgr = TaskManager(
                    recovery_db, recovery_bus,
                    max_attempts=cfg.default_max_attempts,
                    lease_duration=cfg.lease_duration,
                    backoff_base=cfg.retry_backoff_base,
                    backoff_max=cfg.retry_backoff_max,
                )
                recovery = LeaseRecovery(
                    db=recovery_db,
                    task_manager=recovery_mgr,
                    event_bus=recovery_bus,
                    interval=30.0,
                )
                await recovery.start()
        except Exception:
            # Clean up partially initialized resources on startup failure
            if recovery:
                await recovery.stop()
            if worker:
                await worker.stop()
            if recovery_db:
                await recovery_db.close()
            if worker_db:
                await worker_db.close()
            await db.close()
            raise

        yield

        if recovery:
            await recovery.stop()
        if worker:
            await worker.stop()
            # Re-queue in-flight tasks so they're recoverable on next startup
            try:
                cur = await worker_db.execute(
                    "UPDATE agent_llm_tasks SET status = 'queued', lease_expires_at = NULL "
                    "WHERE status = 'running'"
                )
                await worker_db.commit()
                n = cur.rowcount
                if n:
                    logger.info("Re-queued %d in-flight tasks on shutdown", n)
            except Exception:
                logger.exception("Failed to re-queue in-flight tasks")
        if recovery_db:
            await recovery_db.close()
        if worker_db:
            await worker_db.close()
        if hasattr(provider, 'close'):
            await provider.close()
        if hasattr(model_provider, 'close'):
            await model_provider.close()
        await db.close()

    app = FastAPI(title="LLM Service", version="0.1.0", lifespan=lifespan)
    app.state.config = cfg

    from llm_service.api.health import router as health_router
    from llm_service.api.model_api import router as model_api_router
    from llm_service.api.results import router as results_router
    from llm_service.api.tasks import router as tasks_router
    from llm_service.api.templates import router as templates_router
    from llm_service.dashboard.views import router as dashboard_router

    app.include_router(health_router)
    app.include_router(model_api_router)
    app.include_router(tasks_router)
    app.include_router(results_router)
    app.include_router(templates_router)
    app.include_router(dashboard_router)

    return app
