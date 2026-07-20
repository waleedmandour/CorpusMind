"""FastAPI application factory."""
from __future__ import annotations

from contextlib import asynccontextmanager

from fastapi import FastAPI, Request
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
        version="0.1.10",
        license_info={"name": "AGPL-3.0-only", "url": "https://www.gnu.org/licenses/agpl-3.0.html"},
        lifespan=lifespan,
    )

    app.add_middleware(
        CORSMiddleware,
        allow_origins=settings.cors_origins,
        allow_credentials=True,
        # NOTE: When allow_credentials=True, the Fetch spec forbids "*"
        # for allow_methods and allow_headers — the wildcard is treated as
        # the literal token "*" (matching nothing), so every preflighted
        # request (POST, JSON Content-Type, Authorization header, ...) is
        # rejected. This was the root cause of the "Detected (API unreachable)"
        # amber state on Windows desktop builds. Explicit lists are required.
        # See: https://fastapi.tiangolo.com/tutorial/cors/
        allow_methods=["GET", "POST", "PUT", "PATCH", "DELETE", "OPTIONS"],
        allow_headers=["Authorization", "Content-Type", "X-Requested-With"],
    )

    # Private Network Access (PNA) preflight header.
    #
    # Chrome/WebView2's PNA spec (formerly CORS-RFC1918) requires the server
    # to send `Access-Control-Allow-Private-Network: true` on OPTIONS
    # preflight responses when a page from a less-private origin (e.g.
    # http://tauri.localhost) requests a resource on a more-private address
    # (e.g. http://127.0.0.1:8765). FastAPI's CORSMiddleware does NOT add
    # this header automatically (fastapi/fastapi#11145), so we add it here.
    #
    # As of 2026, LNA is OFF by default in WebView2 (kill-switched), but it
    # is ON in the Edge browser and will eventually ship in WebView2. Adding
    # the header now is forward-compatible and harmless.
    # See: https://developer.chrome.com/blog/private-network-access-preflight
    @app.middleware("http")
    async def add_pna_header(request: Request, call_next):
        resp = await call_next(request)
        if request.method == "OPTIONS":
            resp.headers["Access-Control-Allow-Private-Network"] = "true"
        return resp

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
    """Entry point for `corpusmind-engine` console script.

    CRITICAL PyInstaller FIX: Pass the `app` OBJECT directly to uvicorn.run()
    instead of the import string "app.main:app". In a PyInstaller frozen
    environment, the `app` package isn't on sys.path (PyInstaller bundles
    app/main.py as __main__, not as an importable package), so uvicorn's
    import-string form fails with:
      ERROR: Error loading ASGI app. Could not import module "app.main".
    Passing the object directly avoids the import entirely. This works fine
    with workers=1 and reload=False (the only two cases where the import
    string is required).

    Uvicorn config notes (per FastAPI deployment docs):
      - workers=1: single process; avoids spawn/signal issues under PyInstaller
      - loop="asyncio": Windows-safe; uvloop is Unix-only and PyInstaller-hostile
      - http="h11": pure-Python, always present, no native dep to bundle
      - ws="websockets": pure-Python websockets impl (no httptools native dep)
      - lifespan="on": enables FastAPI's startup/shutdown events
      - access_log=False: reduces noise for an internal sidecar
    """
    import uvicorn

    settings = get_settings()
    uvicorn.run(
        app,  # PASS THE OBJECT, not the import string — PyInstaller can't import "app.main"
        host=settings.host,
        port=settings.port,
        log_level=settings.log_level,
        reload=False,
        workers=1,
        loop="asyncio",
        http="h11",
        ws="websockets",
        lifespan="on",
        access_log=False,
    )


# CRITICAL: This guard is what makes the PyInstaller-bundled exe actually
# start the server. Without it, `python app/main.py` (which is what the
# PyInstaller exe does) just creates the `app` object and exits with code 0
# — the uvicorn server never starts. The `run()` function is only called via
# the `corpusmind-engine` console script (pip entry point), which PyInstaller
# doesn't use. This was the root cause of "engine dies with exit code 0 and
# empty logs" on Windows.
if __name__ == "__main__":
    # Early startup signal — with PYTHONUNBUFFERED=1, this appears in
    # engine.stdout.log immediately, confirming Python started. If this
    # line never appears, the hang/crash is happening before Python gets
    # control (native/OS-level issue).
    import sys
    print(f"CorpusMind engine starting (Python {sys.version.split()[0]})...", flush=True)
    run()
