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
from app.classroom_audit import audit_dir
from app.server_mode import (
    ServerModeConfig,
    caddy_version,
    classroom_urls,
    config_path,
    ensure_tokens,
    find_caddy_binary,
    find_web_dist,
    lan_ips,
    ollama_model_size,
    save_config,
    spawn_caddy,
    stop_caddy,
)

router = APIRouter()

# v1.2.10 (5a): probe port is a module constant so tests can point the
# LAN-exposure probe at a socket they control instead of a real Ollama.
_OLLAMA_PORT = 11434


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
    # v1.2.9 seat limit + audit: None (or omitted) keeps the current value;
    # max_students=null means "auto — size the cap from this device + LM".
    max_students: int | None = Field(default=None, ge=1, le=99)
    audit_enabled: bool | None = None


class ConfigUpdate(BaseModel):
    student_model: str | None = None
    num_parallel: int | None = Field(default=None, ge=1, le=16)
    max_students: int | None = Field(default=None, ge=1, le=99)
    audit_enabled: bool | None = None


def _status_payload(
    settings: Any,
    state: sm.ServerModeState,
    seats: tuple[int, str] | None = None,
) -> dict[str, Any]:
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
        # v1.2.9 seat limit + audit surfaces (teacher-only endpoint).
        "max_students": cfg.max_students,
        "students_max": seats[0] if seats else None,
        "students_cap_source": seats[1] if seats else "unknown",
        "students_joined_total": state.joined_total,
        "chats_total": state.chats_total,
        "audit_enabled": cfg.audit_enabled,
        "audit_dir": str(audit_dir(settings)),
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


async def _ollama_lan_exposure() -> dict[str, Any]:
    """v1.2.10 (5a): is Ollama on this machine reachable beyond loopback?

    Student Mode runs on the teacher's machine, where a LAN-facing Ollama
    means every joined student device (and anything else on the network)
    can reach the model server unprompted. BUILD_GUIDE.md used to tell
    deployers to open 11434 "if remote" — the exact opposite of safe — so
    the detection lives here, and BUILD_GUIDE / the server card / Settings
    all share one canonical warning sentence instead of paraphrases.

    Two independent signals, both about THIS machine:
      1. OLLAMA_HOST set to something other than loopback — that is the
         bind Ollama itself was started with.
      2. A live TCP probe of this machine's LAN IPs (app.server_mode.lan_ips)
         on port 11434. A loopback-bound Ollama never answers on the LAN
         address, so an answer proves a LAN-facing listener regardless of
         how it was configured (env var, systemd unit, ``docker -p`` ...).
    The probe runs in a worker thread (0.3 s timeout per candidate, a
    handful of interfaces at most) so the status poll never stalls the
    event loop. Returns ``{"exposed": bool, "source": "env"|"probe"|None,
    "addr": str|None}`` — ``addr`` feeds the UI warning verbatim.
    """
    import asyncio as _asyncio
    import os
    import socket

    def _env_host_off_loopback() -> str | None:
        raw = os.environ.get("OLLAMA_HOST", "").strip()
        if not raw:
            return None
        # OLLAMA_HOST forms: "host:port", ":port", "[::1]:port", bare host.
        host = raw
        if host.startswith("["):
            host = host[1 : host.index("]")]
        elif host.count(":") == 1:
            host = host.rsplit(":", 1)[0]
        host = host.strip() or "127.0.0.1"
        if host == "localhost" or host.startswith("127.") or host in ("::1", "::"):
            return None
        return host

    def _probe_lan() -> str | None:
        for ip in lan_ips():
            try:
                with socket.create_connection((ip, _OLLAMA_PORT), timeout=0.3):
                    return ip
            except OSError:
                continue
        return None

    env_host = _env_host_off_loopback()
    if env_host:
        return {"exposed": True, "source": "env", "addr": env_host}
    hit = await _asyncio.to_thread(_probe_lan)
    if hit:
        return {"exposed": True, "source": "probe", "addr": hit}
    return {"exposed": False, "source": None, "addr": None}


@router.get("/server-mode/status")
async def server_mode_status(request: Request) -> dict:
    """Live classroom status (teacher-only)."""
    require_teacher(request)
    from app.settings import get_settings

    settings = get_settings()
    state: sm.ServerModeState = request.app.state.server_mode
    seats = await state.effective_seats(settings) if state.config.enabled else None
    payload = _status_payload(settings, state, seats)
    # v1.2.10 (5a): loopback-vs-LAN Ollama exposure, probed on every status
    # poll so the teacher sees the warning the moment the bind changes.
    payload["ollama_exposure"] = await _ollama_lan_exposure()
    return payload


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
    # v1.2.9: explicit enable-body values for the seat cap / audit toggle.
    if "max_students" in body.model_fields_set and body.max_students is not None:
        cfg.max_students = body.max_students
    if "audit_enabled" in body.model_fields_set and body.audit_enabled is not None:
        cfg.audit_enabled = body.audit_enabled
    cfg.sanitize()
    settings.student_token = cfg.student_token
    # Fresh anonymous numbering + counters for every classroom session.
    state.reset_classroom_session()
    audit = state.ensure_audit(settings)
    audit.write(
        "classroom_started",
        mode=cfg.mode,
        https_port=cfg.https_port,
        http_port=cfg.http_port,
        student_model=cfg.student_model,
        num_parallel=cfg.num_parallel,
        max_students=cfg.max_students,
        audit_enabled=cfg.audit_enabled,
    )

    # Fail BEFORE persisting enabled=True if the classroom can't come up.
    try:
        spawn_caddy(settings, state)
        state.caddy_error = ""
    except Exception as exc:
        cfg.enabled = False
        settings.student_token = ""
        state.caddy_error = str(exc)
        audit.write("classroom_start_failed", error=str(exc))
        raise HTTPException(500, f"Could not start the classroom server: {exc}") from exc

    save_config(settings, cfg)
    seats = await state.effective_seats(settings)
    return _status_payload(settings, state, seats)


@router.post("/server-mode/disable")
async def server_mode_disable(request: Request) -> dict:
    """Disable the classroom server (stops Caddy, keeps config for re-enable)."""
    require_teacher(request)
    from app.settings import get_settings

    settings = get_settings()
    state: sm.ServerModeState = request.app.state.server_mode
    state.config.enabled = False
    settings.student_token = ""
    if state.audit is not None:
        state.audit.write(
            "classroom_stopped",
            students_joined_total=state.joined_total,
            chats_total=state.chats_total,
        )
    stop_caddy(state)
    save_config(settings, state.config)
    seats = await state.effective_seats(settings)
    return _status_payload(settings, state, seats)


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
    # model_fields_set distinguishes "field omitted" from an explicit null
    # (explicit null on max_students = back to the auto device-sized cap).
    if "max_students" in body.model_fields_set:
        state.config.max_students = body.max_students
    if "audit_enabled" in body.model_fields_set and body.audit_enabled is not None:
        state.config.audit_enabled = body.audit_enabled
    state.config.sanitize()
    state.ensure_audit(settings)  # picks up audit_enabled changes
    state._cap_cache = None  # seat override / model changes take effect now
    save_config(settings, state.config)
    seats = await state.effective_seats(settings)
    return _status_payload(settings, state, seats)


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

    size, resolved = await ollama_model_size(settings.ollama_base_url, wanted)

    estimate = sm.estimate_students(size, state.config.num_parallel)
    estimate["model"] = resolved
    estimate["model_size_bytes"] = size
    return estimate


@router.get("/server-mode/audit")
async def server_mode_audit(request: Request, limit: int = 200) -> dict:
    """Anonymous classroom audit tail + summary (teacher-only).

    Returns the most recent ``limit`` events (oldest-first) plus session
    counters. Entries carry anonymous aliases (S-1, S-2, …) — never IPs,
    session IDs or tokens, by construction (app/classroom_audit.py).
    """
    require_teacher(request)
    from app.settings import get_settings

    settings = get_settings()
    state: sm.ServerModeState = request.app.state.server_mode
    limit = max(1, min(int(limit), 1000))
    audit = state.audit
    seats = await state.effective_seats(settings) if state.config.enabled else None
    return {
        "enabled": state.config.enabled,
        "audit_enabled": state.config.audit_enabled,
        "dir": str(audit_dir(settings)),
        "file": str(audit.current_file()) if audit else None,
        "students_active": state.active_students(),
        "students_max": seats[0] if seats else None,
        "students_cap_source": seats[1] if seats else "unknown",
        "students_joined_total": state.joined_total,
        "chats_total": state.chats_total,
        "summary": audit.summarize() if audit else {},
        "entries": audit.read_tail(limit) if audit else [],
    }
