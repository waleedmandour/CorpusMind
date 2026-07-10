"""System endpoints — provider info, model listing, version."""
from __future__ import annotations

from fastapi import APIRouter, HTTPException, Request

from app import __version__
from app.settings import get_settings

router = APIRouter()


@router.get("/version")
async def version() -> dict:
    return {"version": __version__, "name": "corpusmind-engine"}


@router.get("/providers")
async def list_providers(request: Request) -> dict:
    """List configured providers and their current health status."""
    registry = request.app.state.providers
    settings = get_settings()
    info: list[dict] = []
    for name in ("ollama", "lmstudio", "cloud"):
        try:
            p = registry.get(name)
            healthy = await p.health()
        except Exception as e:
            healthy = False
            info.append({"name": name, "healthy": False, "error": str(e)})
            continue
        info.append({
            "name": name,
            "healthy": healthy,
            "base_url": getattr(p, "base_url", "") if name != "cloud" else settings.cloud_base_url,
            "default_model": getattr(p, "default_model", ""),
        })
    return {"providers": info}


@router.get("/providers/{name}/models")
async def list_models(name: str, request: Request) -> dict:
    registry = request.app.state.providers
    try:
        p = registry.get(name)
    except Exception as e:
        raise HTTPException(status_code=404, detail=str(e)) from e
    models = await p.list_models()
    return {"provider": name, "models": models}


@router.get("/settings")
async def public_settings() -> dict:
    """Subset of settings safe to expose to the UI (no secrets)."""
    s = get_settings()
    return {
        "cloud_provider": s.cloud_provider,
        "cloud_disabled_hard": s.cloud_disabled_hard,
        "ollama_base_url": s.ollama_base_url,
        "lmstudio_base_url": s.lmstudio_base_url,
        "data_dir": str(s.data_dir),
        # Smart Troubleshooting: expose whether Gemini interpretation is
        # available (key presence only — never the key itself).
        "gemini_available": bool(s.gemini_api_key),
        "gemini_model": s.gemini_model if s.gemini_api_key else "",
    }


@router.get("/encryption/status")
async def encryption_status() -> dict:
    """§13.2: At-rest encryption status (transparency endpoint)."""
    from storage.encryption import get_encryption_status
    return get_encryption_status()
