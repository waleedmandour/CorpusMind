"""Health-check endpoints."""
from __future__ import annotations

from fastapi import APIRouter, Request

from app import __version__

router = APIRouter()


@router.get("/health")
async def health(request: Request) -> dict:
    """Liveness probe — used by Tauri sidecar supervisor and Docker healthcheck."""
    return {
        "status": "ok",
        "engine": "corpusmind-engine",
        "version": __version__,
    }


@router.get("/health/ready")
async def ready(request: Request) -> dict:
    """Readiness probe — also probes registered model providers."""
    registry = request.app.state.providers
    providers: dict[str, bool] = {}
    for name in ("ollama", "lmstudio", "cloud"):
        try:
            p = registry.get(name)
            providers[name] = await p.health()
        except Exception:
            providers[name] = False
    return {
        "status": "ok",
        "providers": providers,
    }
