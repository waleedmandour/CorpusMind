"""FastAPI application factory."""
from __future__ import annotations

from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from ai import ProviderRegistry
from api import ai as ai_routes
from api import (
    analysis,
    arabic,
    cleaning,
    corpora,
    export,
    health,
    hub,
    open_access,
    phase2,
    phase5,
    phase6,
    research,
    system,
    troubleshoot,
    vision,
)
from app.logging import configure_logging, get_logger
from app.settings import get_settings
from storage.session import dispose_db, init_db


@asynccontextmanager
async def lifespan(app: FastAPI):
    """Manage provider lifecycle, DB init, and shared state."""
    configure_logging()
    log = get_logger("app.lifespan")
    settings = get_settings()
    log.info("engine_starting", host=settings.host, port=settings.port, data_dir=str(settings.data_dir))

    # Initialize the SQLite database (idempotent create_all)
    await init_db()
    log.info("db_ready", url=settings.sqlite_url)

    registry = ProviderRegistry(settings)
    app.state.providers = registry

    try:
        yield
    finally:
        await registry.aclose()
        await dispose_db()
        log.info("engine_stopped")


def create_app() -> FastAPI:
    settings = get_settings()
    app = FastAPI(
        title="CorpusMind Engine",
        description=(
            "Local-first, AI-native research environment for corpus linguistics and "
            "multimodal discourse analysis. Phase 6: collaboration, self-hosting, "
            "polish — saved searches, bookmarks, favorites, project sharing, "
            "at-rest encryption, accessibility hardening."
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
    app.include_router(corpora.router, prefix="/api/v1", tags=["corpora"])
    app.include_router(analysis.router, prefix="/api/v1", tags=["analysis"])
    app.include_router(phase2.router, prefix="/api/v1", tags=["phase2"])
    app.include_router(arabic.router, prefix="/api/v1", tags=["arabic"])
    app.include_router(vision.router, prefix="/api/v1", tags=["vision"])
    app.include_router(phase5.router, prefix="/api/v1", tags=["phase5"])
    app.include_router(phase6.router, prefix="/api/v1", tags=["phase6"])
    app.include_router(export.router, prefix="/api/v1", tags=["export"])
    app.include_router(troubleshoot.router, prefix="/api/v1", tags=["troubleshoot"])
    app.include_router(cleaning.router, prefix="/api/v1", tags=["cleaning"])
    app.include_router(hub.router, prefix="/api/v1", tags=["hub"])
    app.include_router(research.router, prefix="/api/v1", tags=["research"])
    app.include_router(open_access.router, prefix="/api/v1", tags=["open-access"])
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
