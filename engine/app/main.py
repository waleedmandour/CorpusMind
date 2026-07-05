"""FastAPI application factory."""
from __future__ import annotations

from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from ai import ProviderRegistry, ToolRegistry
from app.logging import configure_logging, get_logger
from app.settings import get_settings
from api import health, ai as ai_routes, system


@asynccontextmanager
async def lifespan(app: FastAPI):
    """Manage provider lifecycle and shared state."""
    configure_logging()
    log = get_logger("app.lifespan")
    settings = get_settings()
    log.info("engine_starting", host=settings.host, port=settings.port, data_dir=str(settings.data_dir))

    registry = ProviderRegistry(settings)
    tools = ToolRegistry()
    app.state.providers = registry
    app.state.tools = tools

    try:
        yield
    finally:
        await registry.aclose()
        log.info("engine_stopped")


def create_app() -> FastAPI:
    settings = get_settings()
    app = FastAPI(
        title="CorpusMind Engine",
        description=(
            "Local-first, AI-native research environment for corpus linguistics and "
            "multimodal discourse analysis. Phase 0: foundations — health, system, "
            "and grounded-AI round-trip."
        ),
        version="0.1.0",
        license_info={"name": "AGPL-3.0-only", "url": "https://www.gnu.org/licenses/agpl-3.0.html"},
        lifespan=lifespan,
    )

    app.add_middleware(
        CORSMiddleware,
        allow_origins=settings.cors_origins,
        allow_credentials=True,
        allow_methods=["*"],
        allow_headers=["*"],
    )

    app.include_router(health.router, prefix="/api/v1", tags=["health"])
    app.include_router(system.router, prefix="/api/v1", tags=["system"])
    app.include_router(ai_routes.router, prefix="/api/v1/ai", tags=["ai"])
    return app


app = create_app()


def run() -> None:
    """Entry point for `corpusmind-engine` console script."""
    import uvicorn

    settings = get_settings()
    uvicorn.run(
        "app.main:app",
        host=settings.host,
        port=settings.port,
        log_level=settings.log_level,
        reload=False,
    )
