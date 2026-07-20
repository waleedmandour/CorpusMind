"""Runtime configuration for the opt-in Cloud AI provider (OpenAI/Anthropic).

The key is held in-memory only (never written to disk, never echoed back to
the browser after saving) - same privacy posture as the existing Gemini
troubleshooting key in troubleshoot.py.
"""
from __future__ import annotations

from typing import Literal

from fastapi import APIRouter, HTTPException, Request
from pydantic import BaseModel, Field

from app.settings import get_settings

router = APIRouter()


class CloudConfigRequest(BaseModel):
    provider: Literal["anthropic", "openai"]
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
