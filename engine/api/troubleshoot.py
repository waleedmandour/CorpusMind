"""Smart Troubleshooting endpoints.

Provides:
  - GET  /api/v1/troubleshoot/status  — is Gemini interpretation available?
  - POST /api/v1/troubleshoot/interpret — ask Gemini to interpret a backend
    error and suggest a fix.
  - POST /api/v1/troubleshoot/gemini-key — set the Gemini API key at runtime
    (from the UI). The key is stored in-memory in the engine process and
    never written to disk. It takes precedence over the env-var key.
  - DELETE /api/v1/troubleshoot/gemini-key — clear the runtime-set key.

The Gemini API key can be provided two ways:
  1. CORPUSMIND_GEMINI_API_KEY environment variable (set before engine start)
  2. POST /api/v1/troubleshoot/gemini-key (set at runtime from the UI)

The runtime key takes precedence. The key is never exposed back to the
browser — only its presence (boolean) is reported via the /status endpoint.
"""
from __future__ import annotations

import json
from typing import Any

import httpx
from fastapi import APIRouter
from pydantic import BaseModel, Field

from app.settings import get_settings

router = APIRouter()

# Runtime-overridable Gemini key (set from the UI). Takes precedence over
# the env-var key. Stored in-memory only — never written to disk.
_runtime_gemini_key: str | None = None


def _get_gemini_key() -> str:
    """Return the effective Gemini key: runtime key if set, else env key."""
    if _runtime_gemini_key:
        return _runtime_gemini_key
    return get_settings().gemini_api_key

GEMINI_URL_TEMPLATE = (
    "https://generativelanguage.googleapis.com/v1beta/models/{model}:generateContent"
)

SYSTEM_INSTRUCTION = """You are CorpusMind's Smart Troubleshooting assistant.

CorpusMind is a local-first, AI-native research environment for corpus
linguistics and multimodal discourse analysis. It has three layers:
  1. A Python FastAPI engine (corpusmind-engine) on 127.0.0.1:8765
  2. A React + Vite PWA frontend
  3. A Tauri 2 desktop shell (Rust) that supervises the engine as a sidecar

The user is a linguistics researcher, NOT a developer. Your job is to
interpret backend errors in plain language and suggest actionable fixes.

Output EXACTLY this JSON shape (no markdown, no prose before or after):
{
  "severity": "info" | "warning" | "error",
  "plain_language": "<1-2 sentence explanation a non-developer can understand>",
  "likely_cause": "<1 sentence on the most probable cause>",
  "suggested_fix": "<1-3 concrete steps the user can take right now>",
  "should_report": <true if this looks like a real bug the developer should fix, false if it's a config/environment issue>
}

Common causes to recognize:
- Engine not running / connection refused → tell them to start the engine
- Ollama not running (11434) → tell them to run `ollama serve`
- spaCy model missing (E050) → tell them to run `python -m spacy download en_core_web_sm`
- CAMeL Tools missing → tell them to `pip install camel-tools` and run `camel_data -i morphology-db-msa-r13`
- File upload 400 → encoding/format issue; suggest trying a different file
- 500 Internal Server Error → likely a real bug; set should_report=true
- Timeout → suggest retrying; if persistent, set should_report=true

Keep plain_language and suggested_fix SHORT and ACTIONABLE. The user is a
researcher, not an engineer."""


class InterpretRequest(BaseModel):
    """Error context sent by the frontend for Gemini interpretation."""

    error_message: str = Field(..., description="The error message text")
    error_code: str | int | None = Field(None, description="HTTP status code or error code")
    endpoint: str | None = Field(None, description="The API endpoint that failed")
    context: str | None = Field(None, description="Additional context (e.g. what the user was doing)")
    stack_trace: str | None = Field(None, description="Optional JS/Python stack trace")


class InterpretResponse(BaseModel):
    """Gemini's interpretation of the error."""

    available: bool
    severity: str = "info"
    plain_language: str = ""
    likely_cause: str = ""
    suggested_fix: str = ""
    should_report: bool = False
    raw_error: str = ""
    model: str = ""


@router.get("/troubleshoot/status")
async def troubleshoot_status() -> dict:
    """Tell the frontend whether Gemini interpretation is available."""
    key = _get_gemini_key()
    settings = get_settings()
    return {
        "available": bool(key),
        "model": settings.gemini_model if key else "",
        "source": "ui" if _runtime_gemini_key else ("env" if settings.gemini_api_key else "none"),
    }


class GeminiKeyRequest(BaseModel):
    """Set the Gemini API key from the UI."""
    api_key: str = Field(..., min_length=1, description="Google Gemini API key")


@router.post("/troubleshoot/gemini-key")
async def set_gemini_key(req: GeminiKeyRequest) -> dict:
    """Set the Gemini API key at runtime (from the UI).

    The key is stored in-memory only — never written to disk. It takes
    precedence over the CORPUSMIND_GEMINI_API_KEY environment variable.
    The key is never exposed back to the browser.
    """
    global _runtime_gemini_key
    _runtime_gemini_key = req.api_key.strip()
    return {"ok": True, "available": True, "source": "ui"}


@router.delete("/troubleshoot/gemini-key")
async def clear_gemini_key() -> dict:
    """Clear the runtime-set Gemini key.

    After this, interpretation falls back to the env-var key (if set),
    or is disabled entirely if no env-var key exists.
    """
    global _runtime_gemini_key
    _runtime_gemini_key = None
    settings = get_settings()
    return {
        "ok": True,
        "available": bool(settings.gemini_api_key),
        "source": "env" if settings.gemini_api_key else "none",
    }


@router.post("/troubleshoot/interpret", response_model=InterpretResponse)
async def interpret_error(req: InterpretRequest) -> InterpretResponse:
    """Ask Gemini to interpret a backend error and suggest a fix.

    The Gemini API key lives in the engine (env var or runtime-set from
    the UI), so the browser never sees it. If no key is configured,
    returns available=false with a fallback message.
    """
    settings = get_settings()
    key = _get_gemini_key()

    if not key:
        return InterpretResponse(
            available=False,
            plain_language=(
                "Gemini interpretation is not configured. Enter your API key "
                "in Settings, or set the CORPUSMIND_GEMINI_API_KEY environment "
                "variable in the engine."
            ),
            likely_cause="Not configured",
            suggested_fix=(
                "Get a free key at https://aistudio.google.com/apikey, then "
                "enter it in Settings (Smart Troubleshooting section) or set "
                "CORPUSMIND_GEMINI_API_KEY in the engine environment."
            ),
            should_report=True,
            raw_error=req.error_message,
            model="",
        )

    # Build the user prompt with all available context
    parts: list[str] = [f"ERROR MESSAGE:\n{req.error_message}"]
    if req.error_code is not None:
        parts.append(f"\nERROR CODE: {req.error_code}")
    if req.endpoint:
        parts.append(f"\nENDPOINT: {req.endpoint}")
    if req.context:
        parts.append(f"\nWHAT THE USER WAS DOING: {req.context}")
    if req.stack_trace:
        parts.append(f"\nSTACK TRACE (truncated to 1500 chars):\n{req.stack_trace[:1500]}")

    user_prompt = "\n".join(parts)
    url = GEMINI_URL_TEMPLATE.format(model=settings.gemini_model)

    payload: dict[str, Any] = {
        "system_instruction": {"parts": [{"text": SYSTEM_INSTRUCTION}]},
        "contents": [{"role": "user", "parts": [{"text": user_prompt}]}],
        "generationConfig": {
            "temperature": 0.3,
            "maxOutputTokens": 800,
            "responseMimeType": "application/json",
        },
    }

    try:
        async with httpx.AsyncClient(timeout=30.0) as client:
            r = await client.post(
                url,
                params={"key": key},
                json=payload,
                headers={"Content-Type": "application/json"},
            )
    except httpx.HTTPError as e:
        return InterpretResponse(
            available=True,
            severity="error",
            plain_language="Could not reach the Gemini API to interpret this error.",
            likely_cause=f"Network error: {e}",
            suggested_fix="Check your internet connection and try again.",
            should_report=False,
            raw_error=req.error_message,
            model=settings.gemini_model,
        )

    if r.status_code != 200:
        return InterpretResponse(
            available=True,
            severity="warning",
            plain_language=(
                f"Gemini returned HTTP {r.status_code}. The error could not be "
                "auto-interpreted."
            ),
            likely_cause=f"Gemini API error: {r.text[:200]}",
            suggested_fix="Verify the Gemini API key is valid and has quota.",
            should_report=False,
            raw_error=req.error_message,
            model=settings.gemini_model,
        )

    try:
        data = r.json()
        text = data["candidates"][0]["content"]["parts"][0]["text"]
        parsed = json.loads(text)
        return InterpretResponse(
            available=True,
            severity=parsed.get("severity", "info"),
            plain_language=parsed.get("plain_language", ""),
            likely_cause=parsed.get("likely_cause", ""),
            suggested_fix=parsed.get("suggested_fix", ""),
            should_report=bool(parsed.get("should_report", False)),
            raw_error=req.error_message,
            model=settings.gemini_model,
        )
    except (KeyError, IndexError, json.JSONDecodeError) as e:
        # Gemini didn't return the expected shape — fall back gracefully
        return InterpretResponse(
            available=True,
            severity="info",
            plain_language="The error was captured but auto-interpretation returned an unexpected response.",
            likely_cause=f"Parse error: {e}",
            suggested_fix="Report this error to the developer with the raw error text.",
            should_report=True,
            raw_error=req.error_message,
            model=settings.gemini_model,
        )
