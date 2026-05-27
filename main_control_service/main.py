from __future__ import annotations

from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from main_control_service.config import MainControlSettings
from main_control_service.service import YamlConfigService


def create_app(
    *,
    config_dir: Path | None = None,
    settings: MainControlSettings | None = None,
) -> FastAPI:
    cfg = settings or MainControlSettings()
    effective_config_dir = config_dir or cfg.config_dir
    service = YamlConfigService(config_dir=effective_config_dir)

    @asynccontextmanager
    async def lifespan(app: FastAPI):
        app.state.main_control = service
        yield

    app = FastAPI(
        title="Main Control Service",
        version="1.0.0",
        description="YAML read-only config center for CoreMasterKB services.",
        lifespan=lifespan,
    )
    app.add_middleware(
        CORSMiddleware,
        allow_origins=["*"],
        allow_credentials=True,
        allow_methods=["*"],
        allow_headers=["*"],
    )

    @app.get("/health")
    def health() -> dict[str, str]:
        return {"status": "ok", "mode": "yaml_readonly"}

    @app.get("/api/v1/domains")
    def list_domains() -> dict:
        return {"items": service.list_domains()}

    @app.get("/api/v1/domains/{domain_id}")
    def get_domain(domain_id: str) -> dict:
        return service.get_domain(domain_id)

    @app.get("/api/v1/domains/{domain_id}/scenario")
    def get_scenario(domain_id: str, section: str | None = None) -> dict:
        return service.get_scenario(domain_id, section)

    @app.get("/api/v1/system/{service_name}")
    def get_system_config(service_name: str) -> dict:
        return service.get_system_config(service_name)

    return app


app = create_app()


if __name__ == "__main__":
    import uvicorn

    cfg = MainControlSettings()
    uvicorn.run("main_control_service.main:app", host=cfg.host, port=cfg.port, reload=False)
