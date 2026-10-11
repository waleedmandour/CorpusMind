"""FastAPI application factory."""
from __future__ import annotations

import os
import threading
from contextlib import asynccontextmanager
from typing import Any

from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware

from ai import ProviderRegistry
from api import ai as ai_routes
from api import (
    ai_provider_config,
    analysis,
    arabic,
    arabic_bulk,
    arabic_data,
    cleaning,
    corpora,
    export,
    health,
    hub,
    learner,
    network,
    open_access,
    phase2,
    phase5,
    phase6,
    reference_corpus,
    research,
    system,
    troubleshoot,
    vision,
    visual_corpus,
    wordlists,
)
from api import (
    saved_queries,
    server_mode as server_mode_routes,
)
from app import __version__, server_mode
from app.logging import configure_logging, get_logger
from app.settings import get_settings
from storage.session import dispose_db, init_db


def _start_arabic_warmup(log: Any) -> threading.Thread | None:
    """v1.2.12 (field report: "sample text fails to analyze even after the
    data pack install"): pre-load the default MSA morphology backend in a
    background thread right after startup.

    Why: the first CAMeL analysis on a cold machine reads a ~400MB DB
    through real-time antivirus, which can take minutes — far past the
    interactive deadline — so the user's FIRST sample analysis failed with
    a timeout even though the pack was correctly installed. Loading it
    during app startup (while the user is still orienting) makes the first
    click warm. Never blocks startup, never raises: any failure (pack not
    provisioned, broken install) is logged and skipped — the request-path
    pre-flight and 503 installer card remain the authoritative UX.
    Disable with ``CORPUSMIND_ARABIC_WARMUP=0`` (e.g. low-RAM machines
    where 400MB resident matters more than the first-click latency).
    """
    if os.environ.get("CORPUSMIND_ARABIC_WARMUP", "1").strip() == "0":
        log.info("arabic_warmup_disabled")
        return None

    def _warm() -> None:
        try:
            from nlp.arabic.pipeline import get_arabic_backend

            get_arabic_backend("camel", "msa").info()
            log.info("arabic_warmup_ready")
        except Exception as e:  # pragma: no cover — depends on machine state
            log.info("arabic_warmup_skipped", reason=str(e))

    t = threading.Thread(target=_warm, name="arabic-warmup", daemon=True)
    t.start()
    return t


@asynccontextmanager
async def lifespan(app: FastAPI):
    """Manage provider lifecycle, DB init, and shared state."""
    configure_logging()
    log = get_logger("app.lifespan")
    settings = get_settings()
    log.info("engine_starting", host=settings.host, port=settings.port, data_dir=str(settings.data_dir))

    # v1.2.9: bridge the user-owned PI resources folder onto
    # persuasion-index's own env vars BEFORE anything scores the lens.
    # check_resources() reads the environment at call time, so running
    # this once at startup is sufficient for the health endpoint and the
    # lens alike. Never downloads anything; never overrides explicit vars.
    from discourse.pi_resources import apply_pi_resource_env

    applied = apply_pi_resource_env(settings)
    if applied:
        log.info("pi_resources_bridged", resources=applied)

    # Initialize the SQLite database (idempotent create_all)
    await init_db()
    log.info("db_ready", url=settings.sqlite_url)

    # v1.2.9 Student Mode: bridge PI resources (above), then load the
    # classroom config. Tokens persist in <data_dir>/server-mode/config.json
    # so students' QR links keep working across engine restarts.
    #
    # v1.2.10 (field report): the classroom is a SESSION-scoped feature and
    # must be OFF by default at every launch. The previous behaviour
    # auto-respawned Caddy whenever a previous session had left
    # config.enabled=true, so teachers who started the classroom once saw
    # it come back "on" on every app start with no way to expect it. Now:
    # the persisted flag is reset to False (and saved) so the UI opens
    # clean OFF; the teacher starts the classroom explicitly per session.
    sm_state = server_mode.ServerModeState(config=server_mode.load_config(settings))
    # v1.2.9: anonymous classroom audit writer — exists whenever the state
    # does; it writes nothing unless the classroom is enabled AND
    # config.audit_enabled is on (writes also fail-soft on any IO error).
    sm_state.ensure_audit(settings)
    if sm_state.config.student_token:
        settings.student_token = sm_state.config.student_token
    if server_mode.reset_session_state(settings, sm_state):
        log.info("server_mode_reset_off")
    app.state.server_mode = sm_state

    registry = ProviderRegistry(settings)
    app.state.providers = registry

    # v1.2.12: warm the Arabic morphology backend in the background so the
    # user's FIRST analysis is warm (see _start_arabic_warmup). Never during
    # tests: the suite boots many app instances and relies on simulating an
    # unprovisioned machine (resolver patches + backend-cache clears) — a
    # background warm load would pin CAMELTOOLS_DATA via the camel_tools
    # import and re-populate the backend cache behind the tests' backs
    # (observed on CI: 503-simulation tests returned 200, the 504 timing
    # test raced the warm load). _start_arabic_warmup stays directly
    # testable; only the lifespan call site is guarded.
    if "PYTEST_CURRENT_TEST" not in os.environ:
        _start_arabic_warmup(log)

    try:
        yield
    finally:
        server_mode.stop_caddy(sm_state)
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
            "polish - saved searches, bookmarks, favorites, project sharing, "
            "at-rest encryption, accessibility hardening."
        ),
        version=__version__,
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
        # v1.0.9: list_images pagination communicates the total via this
        # response header; browsers only expose non-simple headers to JS
        # when they are listed in Access-Control-Expose-Headers.
        expose_headers=["X-Total-Count"],
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

    # Issue 8: minimal shared-bearer-token auth for non-loopback deployments.
    #
    # The documented "shared lab instance" mode (infra/docker-compose.yml,
    # infra/nginx.conf) exposes the engine on a LAN. Without any auth, anyone
    # who can reach the port can read/modify/delete every researcher's data.
    # Full multi-tenant auth is a larger project; this middleware closes the
    # most dangerous gap with a shared token model:
    #   - binds to 127.0.0.1/localhost (the default) → no auth required;
    #   - CORPUSMIND_AUTH_TOKEN unset → no auth required (local-first default);
    #   - otherwise every /api request except /api/v1/health (used by the
    #     Docker healthcheck, which cannot present credentials) must send
    #     "Authorization: Bearer <CORPUSMIND_AUTH_TOKEN>".
    #
    # v1.2.9 Student Mode: requests that arrive stamped with the
    # X-CorpusMind-Classroom header (only the locally-bundled Caddy sidecar
    # injects it; the engine port itself is loopback-only and unreachable
    # from the LAN) are treated as classroom traffic. They must present a
    # bearer token: the teacher token (full access) or the student token
    # (allowlisted read/analysis routes only — app/server_mode.py). The
    # teacher's own desktop app connects directly on loopback with no
    # header, so enabling Student Mode changes nothing locally.
    @app.middleware("http")
    async def enforce_shared_token(request: Request, call_next):
        # Read the (lru-cached) settings per request — tests and runtime
        # re-configuration must be able to change auth without a re-import.
        current = get_settings()
        path = request.url.path
        sm = getattr(request.app.state, "server_mode", None)
        via_proxy = request.headers.get("X-CorpusMind-Classroom", "") == "1"

        if sm is not None and sm.config.enabled and via_proxy and path.startswith("/api/"):
            import secrets as _secrets

            from fastapi.responses import JSONResponse

            if path != "/api/v1/health":
                provided = request.headers.get("Authorization", "")
                role = None
                teacher_header = f"Bearer {sm.config.teacher_token}" if sm.config.teacher_token else None
                student_header = f"Bearer {sm.config.student_token}" if sm.config.student_token else None
                if teacher_header and _secrets.compare_digest(provided, teacher_header):
                    role = "teacher"
                elif student_header and _secrets.compare_digest(provided, student_header):
                    role = "student"
                if role is None:
                    return JSONResponse(
                        {"detail": "Unauthorized. Set Authorization: Bearer <teacher or student token>."},
                        status_code=401,
                    )
                if role == "student" and not server_mode.student_route_allowed(request.method, path):
                    # v1.2.9 audit: rejections are recorded (anonymously).
                    sm.log_denied(request, role, 403, "route_not_allowed")
                    return JSONResponse(
                        {"detail": "Forbidden: this action is not available in Student Mode."},
                        status_code=403,
                    )
                request.state.role = role
                if role == "student":
                    # v1.2.9 seat limit: the number of concurrent students is
                    # capped by the teacher's device + LM sizing (manual
                    # override or the auto RAM/VRAM estimate). Only NEW
                    # students are rejected at capacity — seats already
                    # occupied keep working, and the teacher is never capped.
                    # The auto estimate is cached (60s) so this stays cheap.
                    seats, _seats_source = await sm.effective_seats(current)
                    if sm.client_key(request) not in sm.aliases and sm.active_students() >= seats:
                        sm.log_full_deny(request, seats)
                        return JSONResponse(
                            {
                                "detail": (
                                    f"The classroom is full ({seats} seats in use). "
                                    "Please try again in a few minutes."
                                )
                            },
                            status_code=429,
                            headers={"Retry-After": "120"},
                        )
                    client_ip = request.client.host if request.client else "?"
                    sm.note_student(client_ip)
                    sm.touch_alias(sm.alias_for(request))
                import time as _time

                _t0 = _time.perf_counter()
                response = await call_next(request)
                # v1.2.9 audit: one anonymous line per classroom API call
                # (join/chat/denied events carry the detail; this is the
                # per-request access trail). Health probes stay unlogged.
                sm.log_request(
                    request,
                    role,
                    response.status_code,
                    int((_time.perf_counter() - _t0) * 1000),
                )
                return response

        token = current.auth_token
        host = current.host
        loopback = host in ("127.0.0.1", "::1", "localhost") or host.startswith("127.")
        if token and not loopback and path.startswith("/api/"):
            if path != "/api/v1/health":
                provided = request.headers.get("Authorization", "")
                import secrets as _secrets
                if not _secrets.compare_digest(provided, f"Bearer {token}"):
                    from fastapi.responses import JSONResponse
                    return JSONResponse(
                        {"detail": "Unauthorized. Set Authorization: Bearer <CORPUSMIND_AUTH_TOKEN>."},
                        status_code=401,
                    )
        return await call_next(request)

    app.include_router(health.router, prefix="/api/v1", tags=["health"])
    app.include_router(system.router, prefix="/api/v1", tags=["system"])
    app.include_router(ai_routes.router, prefix="/api/v1/ai", tags=["ai"])
    app.include_router(ai_provider_config.router, prefix="/api/v1", tags=["ai-config"])
    app.include_router(corpora.router, prefix="/api/v1", tags=["corpora"])
    app.include_router(analysis.router, prefix="/api/v1", tags=["analysis"])
    app.include_router(network.router, prefix="/api/v1", tags=["network"])
    app.include_router(phase2.router, prefix="/api/v1", tags=["phase2"])
    app.include_router(arabic.router, prefix="/api/v1", tags=["arabic"])
    # v1.2.11 follow-up: in-app Arabic data pack installer (background job,
    # status, cancel). See app/arabic_installer.py.
    app.include_router(arabic_data.router, prefix="/api/v1", tags=["arabic"])
    # v1.2.11 follow-up: chunked bulk Arabic analysis with progress + cancel
    # (500K-1M token corpora; the interactive route caps at 50k tokens).
    app.include_router(arabic_bulk.router, prefix="/api/v1", tags=["arabic"])
    app.include_router(vision.router, prefix="/api/v1", tags=["vision"])
    app.include_router(phase5.router, prefix="/api/v1", tags=["phase5"])
    app.include_router(visual_corpus.router, prefix="/api/v1", tags=["visual-corpus"])
    app.include_router(phase6.router, prefix="/api/v1", tags=["phase6"])
    app.include_router(export.router, prefix="/api/v1", tags=["export"])
    app.include_router(learner.router, prefix="/api/v1", tags=["learner"])
    app.include_router(troubleshoot.router, prefix="/api/v1", tags=["troubleshoot"])
    app.include_router(cleaning.router, prefix="/api/v1", tags=["cleaning"])
    app.include_router(hub.router, prefix="/api/v1", tags=["hub"])
    app.include_router(research.router, prefix="/api/v1", tags=["research"])
    app.include_router(reference_corpus.router, prefix="/api/v1", tags=["reference-corpus"])
    app.include_router(open_access.router, prefix="/api/v1", tags=["open-access"])
    app.include_router(wordlists.router, prefix="/api/v1", tags=["wordlists"])
    # v1.2.13-2: saved queries (teacher-only CRUD, per project).
    app.include_router(saved_queries.router, prefix="/api/v1", tags=["saved-queries"])
    # v1.2.9 Student Mode — classroom server control plane (teacher-only).
    app.include_router(server_mode_routes.router, prefix="/api/v1", tags=["server-mode"])
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
