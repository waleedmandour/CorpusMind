"""Runtime configuration for the AI model providers.

Cloud (v1.2.1): Google Gemini, OpenAI, Anthropic, and ANY OpenAI-compatible
cloud API (DeepSeek, Mistral, Groq, OpenRouter, xAI, Together, …) via a
custom base URL. The cloud key is held in-memory only (never written to
disk, never echoed back to the browser after saving) - same privacy
posture as the existing Gemini troubleshooting key in troubleshoot.py.

LM Studio (v1.2.14-8, r8): runtime base URL + optional API key. These ARE
persisted — to <data_dir>/provider-config/settings.json on the user's own
machine via app.provider_config — and re-applied at engine startup, so a
custom port survives a restart. The key is never echoed back after
saving and never exposed through the public /settings endpoint.
"""
from __future__ import annotations

from typing import Any, Literal

from fastapi import APIRouter, HTTPException, Request
from pydantic import BaseModel, Field

from app.logging import get_logger
from app.provider_config import (
    clear_overrides,
    load_persisted_overrides,
    persist_overrides,
)
from app.settings import get_settings

router = APIRouter()

log = get_logger(__name__)


class CloudConfigRequest(BaseModel):
    provider: Literal["anthropic", "openai", "gemini", "custom"]
    api_key: str = Field(..., min_length=1)
    model: str = ""
    base_url: str = ""
    acknowledge_data_leaves_device: bool = Field(
        ...,
        description="Must be true - explicit consent that requests will leave the device.",
    )


@router.get("/ai/cloud-config")
async def get_cloud_config() -> dict:
    settings = get_settings()
    has_key = bool(settings.cloud_api_key)
    return {
        "configured": has_key and settings.cloud_provider != "none",
        "provider": settings.cloud_provider,
        "model": settings.cloud_default_model,
        "source": "env" if has_key else "none",
        "hard_disabled": settings.cloud_disabled_hard,
    }


@router.post("/ai/cloud-config")
async def set_cloud_config(req: CloudConfigRequest, request: Request) -> dict:
    if not req.acknowledge_data_leaves_device:
        raise HTTPException(
            400,
            "acknowledge_data_leaves_device must be true to enable the Cloud provider.",
        )
    settings = get_settings()
    if settings.cloud_disabled_hard:
        raise HTTPException(
            403,
            "Cloud provider is hard-disabled (CORPUSMIND_CLOUD_DISABLED_HARD=1).",
        )
    if req.provider == "custom" and not (req.base_url or settings.cloud_base_url):
        raise HTTPException(
            400,
            "The 'custom' provider requires a Base URL - any OpenAI-compatible "
            "endpoint (e.g. https://api.deepseek.com/v1).",
        )
    # Push config into the shared Settings object so the next provider
    # construction picks it up.
    settings.cloud_provider = req.provider
    settings.cloud_api_key = req.api_key.strip()
    if req.model:
        settings.cloud_default_model = req.model
    if req.base_url:
        settings.cloud_base_url = req.base_url
    # CRITICAL: invalidate the cached CloudProvider instance so the next
    # .get("cloud") rebuilds it with the new credentials.
    registry = request.app.state.providers
    registry.invalidate("cloud")
    return {
        "configured": True,
        "provider": req.provider,
        "model": req.model or settings.cloud_default_model,
    }


@router.delete("/ai/cloud-config")
async def clear_cloud_config(request: Request) -> dict:
    settings = get_settings()
    settings.cloud_provider = "none"
    settings.cloud_api_key = ""
    settings.cloud_default_model = ""
    settings.cloud_base_url = ""
    # Invalidate the cached instance.
    registry = request.app.state.providers
    registry.invalidate("cloud")
    return {"configured": False}


# --------------------------------------------------------------------------- #
# v1.2.14-8 (r8, P0-3b/c): runtime LM Studio configuration
# --------------------------------------------------------------------------- #
# The base URL used to be env-only while the desktop's Rust probe hardcoded
# 127.0.0.1:1234 — two sources of truth. The engine is now THE source: the
# URL is set here (persisted to <data_dir>/provider-config/settings.json and
# re-applied at startup), the engine uses it for every LM Studio call, and
# the UI chips read the engine's /providers surface. The optional API key
# is stored on the engine only and never echoed back after saving.


class LMStudioConfigRequest(BaseModel):
    base_url: str = Field(..., min_length=1)
    api_key: str = ""


def _lmstudio_state() -> dict[str, Any]:
    settings = get_settings()
    overrides = load_persisted_overrides()
    return {
        "base_url": settings.lmstudio_base_url,
        "has_api_key": bool(settings.lmstudio_api_key),
        "source": "runtime" if overrides.get("lmstudio_base_url") else "env",
    }


@router.get("/ai/lmstudio-config")
async def get_lmstudio_config() -> dict[str, Any]:
    return _lmstudio_state()


@router.post("/ai/lmstudio-config")
async def set_lmstudio_config(req: LMStudioConfigRequest, request: Request) -> dict[str, Any]:
    base = req.base_url.strip().rstrip("/")
    if not base.startswith(("http://", "https://")):
        raise HTTPException(
            400,
            "base_url must start with http:// or https:// "
            "(e.g. http://127.0.0.1:1234/v1).",
        )
    settings = get_settings()
    settings.lmstudio_base_url = base
    settings.lmstudio_api_key = req.api_key.strip()
    persist_overrides({
        "lmstudio_base_url": base,
        "lmstudio_api_key": settings.lmstudio_api_key,
    })
    # CRITICAL: rebuild the cached LMStudioProvider against the new URL/key.
    registry = request.app.state.providers
    registry.invalidate("lmstudio")
    log.info("lmstudio_config_updated", base_url=base, has_key=bool(settings.lmstudio_api_key))
    return {"configured": True, "base_url": base}


@router.delete("/ai/lmstudio-config")
async def clear_lmstudio_config(request: Request) -> dict[str, Any]:
    settings = get_settings()
    settings.lmstudio_base_url = "http://127.0.0.1:1234/v1"
    settings.lmstudio_api_key = ""
    clear_overrides()
    registry = request.app.state.providers
    registry.invalidate("lmstudio")
    return {"configured": False, "base_url": settings.lmstudio_base_url}
