"""Student Mode — classroom server control plane (teacher-only, v1.2.9).

These endpoints are how the Settings UI enables/disables the classroom
server and how it renders the QR/URL/token panel and the live status.
Every route here is teacher-gated twice:

  1. the auth middleware denies the student role for ANY /server-mode/*
     path (not on the student allowlist);
  2. the ``require_teacher`` dependency below denies proxied requests
     that did not present the teacher token (defense in depth), while
     direct loopback access — the teacher's own desktop app — is
     trusted by definition.
"""

from __future__ import annotations

from datetime import UTC
from typing import Any, Literal

from fastapi import APIRouter, HTTPException, Request
from pydantic import BaseModel, Field

from app import server_mode as sm
from app.server_mode import (
    ServerModeConfig,
    caddy_version,
    classroom_urls,
    config_path,
    ensure_tokens,
    find_caddy_binary,
    find_web_dist,
    lan_ips,
    save_config,
    spawn_caddy,
    stop_caddy,
)

router = APIRouter()


def require_teacher(request: Request) -> None:
    """Deny proxied non-teacher callers; direct loopback is the teacher."""
    via_proxy = request.headers.get(sm.STUDENT_PROXY_HEADER, "") == "1"
    if via_proxy:
        role = getattr(request.state, "role", None)
        if role != "teacher":
            raise HTTPException(403, "Teacher access required")


class EnableRequest(BaseModel):
    mode: Literal["secure", "simple"] = "secure"
    https_port: int | None = Field(default=None, ge=1024, le=65535)
    http_port: int | None = Field(default=None, ge=1024, le=65535)
    student_model: str | None = None
    num_parallel: int | None = Field(default=None, ge=1, le=16)
    rotate: bool = False  # regenerate both tokens


class ConfigUpdate(BaseModel):
    student_model: str | None = None
    num_parallel: int | None = Field(default=None, ge=1, le=16)


def _status_payload(settings: Any, state: sm.ServerModeState) -> dict[str, Any]:
    cfg = state.config
    caddy_bin = find_caddy_binary(settings)
    running = bool(state.caddy_proc and state.caddy_proc.poll() is None)
    payload: dict[str, Any] = {
        "enabled": cfg.enabled,
        "mode": cfg.mode,
        "https_port": cfg.https_port,
        "http_port": cfg.http_port,
        "caddy_running": running,
        "caddy_binary_found": caddy_bin is not None,
        "caddy_version": caddy_version(caddy_bin),
        "caddy_error": state.caddy_error,
        "web_dist_bundled": find_web_dist(settings) is not None,
        "lan_ips": lan_ips(),
        "urls": classroom_urls(settings, cfg) if cfg.enabled else {},
        "student_model": cfg.student_model,
        "num_parallel": cfg.num_parallel,
        "students_active": state.active_students(),
        "ollama_queue_depth": None,  # Ollama does not expose a queue; see ollama_running_models
        "ollama_running_models": _ollama_running_models(settings),
        "config_path": str(config_path(settings)),
    }
    if cfg.enabled:
        # Teacher-only endpoint — include the tokens so the UI can re-render
        # the QR codes and the teacher's own join link after a restart.
        payload["student_token"] = cfg.student_token
        payload["teacher_token"] = cfg.teacher_token
    return payload


def _ollama_running_models(settings: Any) -> int | None:
    """Best-effort count of models currently loaded in Ollama (/api/ps)."""
    import httpx

    base = settings.ollama_base_url.rstrip("/")
    try:
        r = httpx.get(f"{base}/api/ps", timeout=3.0)
        if r.status_code == 200:
            return len(r.json().get("models", []))
    except Exception:
        pass
    return None


@router.get("/server-mode/status")
async def server_mode_status(request: Request) -> dict:
    """Live classroom status (teacher-only)."""
    require_teacher(request)
    from app.settings import get_settings

    return _status_payload(get_settings(), request.app.state.server_mode)


@router.post("/server-mode/enable")
async def server_mode_enable(request: Request, body: EnableRequest) -> dict:
    """Enable the classroom server (writes config, spawns Caddy)."""
    require_teacher(request)
    from app.settings import get_settings

    settings = get_settings()
    state: sm.ServerModeState = request.app.state.server_mode
    cfg: ServerModeConfig = state.config
    cfg.enabled = True
    cfg.mode = body.mode
    if body.https_port:
        cfg.https_port = body.https_port
    if body.http_port:
        cfg.http_port = body.http_port
    if body.student_model:
        cfg.student_model = body.student_model.strip()
    if body.num_parallel:
        cfg.num_parallel = body.num_parallel
    cfg.sanitize()
    ensure_tokens(cfg, rotate=body.rotate)
    from datetime import datetime

    cfg.enabled_at = datetime.now(UTC).isoformat(timespec="seconds")
    settings.student_token = cfg.student_token

    # Fail BEFORE persisting enabled=True if the classroom can't come up.
    try:
        spawn_caddy(settings, state)
        state.caddy_error = ""
    except Exception as exc:
        cfg.enabled = False
        settings.student_token = ""
        state.caddy_error = str(exc)
        raise HTTPException(500, f"Could not start the classroom server: {exc}") from exc

    save_config(settings, cfg)
    return _status_payload(settings, state)


@router.post("/server-mode/disable")
async def server_mode_disable(request: Request) -> dict:
    """Disable the classroom server (stops Caddy, keeps config for re-enable)."""
    require_teacher(request)
    from app.settings import get_settings

    settings = get_settings()
    state: sm.ServerModeState = request.app.state.server_mode
    state.config.enabled = False
    settings.student_token = ""
    stop_caddy(state)
    save_config(settings, state.config)
    return _status_payload(settings, state)


@router.post("/server-mode/config")
async def server_mode_config(request: Request, body: ConfigUpdate) -> dict:
    """Update classroom settings that do not require a Caddy restart."""
    require_teacher(request)
    from app.settings import get_settings

    settings = get_settings()
    state: sm.ServerModeState = request.app.state.server_mode
    if body.student_model is not None:
        state.config.student_model = body.student_model.strip()
    if body.num_parallel is not None:
        state.config.num_parallel = body.num_parallel
    state.config.sanitize()
    save_config(settings, state.config)
    return _status_payload(settings, state)


@router.get("/server-mode/capacity")
async def server_mode_capacity(request: Request, model: str | None = None) -> dict:
    """Estimate 'up to N students' for a classroom model (teacher-only).

    Reuses the HF GGUF explorer's machine memory probe; model size comes
    from Ollama's /api/tags (on-disk size of the requested model).
    """
    require_teacher(request)
    from app.settings import get_settings

    settings = get_settings()
    state: sm.ServerModeState = request.app.state.server_mode
    wanted = (model or state.config.student_model).strip()

    import httpx

    base = settings.ollama_base_url.rstrip("/")
    size = 0
    resolved = None
    try:
        r = httpx.get(f"{base}/api/tags", timeout=5.0)
        if r.status_code == 200:
            for m in r.json().get("models", []):
                name = m.get("name", "")
                if name == wanted or name.split(":")[0] == wanted.split(":")[0]:
                    size = int(m.get("size", 0))
                    resolved = name
                    if name == wanted:
                        break
    except Exception:
        pass

    estimate = sm.estimate_students(size, state.config.num_parallel)
    estimate["model"] = resolved
    estimate["model_size_bytes"] = size
    return estimate
