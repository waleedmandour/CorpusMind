"""System endpoints — provider info, model listing, version, Ollama model pull."""
from __future__ import annotations

import asyncio
import json

import httpx
from fastapi import APIRouter, HTTPException, Request
from pydantic import BaseModel, Field

from app import __version__
from app.logging import get_logger
from app.settings import get_settings

router = APIRouter()
log = get_logger(__name__)


# Curated catalogue of recommended Ollama models for CorpusMind.
# These are models that work well for the grounded-AI Assistant — small
# enough to run on consumer hardware (4-16 GB RAM), large enough to be
# useful for tool-calling and interpretation.
RECOMMENDED_OLLAMA_MODELS: list[dict] = [
    {
        "name": "llama3.2:3b",
        "size": "2.0 GB",
        "params": "3B",
        "ram": "4 GB",
        "description": "Meta Llama 3.2 — fast, capable, good default for the AI Assistant.",
        "languages": ["en"],
        "recommended": True,
    },
    {
        "name": "llama3.2:1b",
        "size": "1.3 GB",
        "params": "1B",
        "ram": "2 GB",
        "description": "Smaller Llama 3.2 — runs on minimal hardware, less capable but fast.",
        "languages": ["en"],
        "recommended": False,
    },
    {
        "name": "qwen2.5:3b",
        "size": "2.0 GB",
        "params": "3B",
        "ram": "4 GB",
        "description": "Qwen 2.5 — strong multilingual support including Arabic. Good for bilingual workflows.",
        "languages": ["en", "ar", "zh"],
        "recommended": True,
    },
    {
        "name": "qwen2.5:7b",
        "size": "4.7 GB",
        "params": "7B",
        "ram": "8 GB",
        "description": "Larger Qwen 2.5 — better quality, needs more RAM. Excellent Arabic support.",
        "languages": ["en", "ar", "zh"],
        "recommended": False,
    },
    {
        "name": "qwen2.5-coder:3b",
        "size": "2.0 GB",
        "params": "3B",
        "ram": "4 GB",
        "description": "Qwen 2.5 Coder — specialized for code generation. Useful if you want the Assistant to write Python/R snippets.",
        "languages": ["en"],
        "recommended": False,
    },
    {
        "name": "phi3.5:3.8b",
        "size": "2.5 GB",
        "params": "3.8B",
        "ram": "4 GB",
        "description": "Microsoft Phi-3.5 — small but capable, good reasoning quality for its size.",
        "languages": ["en"],
        "recommended": False,
    },
    {
        "name": "gemma2:2b",
        "size": "1.6 GB",
        "params": "2B",
        "ram": "2 GB",
        "description": "Google Gemma 2 — lightweight, fast, good for quick queries.",
        "languages": ["en"],
        "recommended": False,
    },
    {
        "name": "mistral:7b",
        "size": "4.1 GB",
        "params": "7B",
        "ram": "8 GB",
        "description": "Mistral 7B — solid all-around model, good for longer reasoning chains.",
        "languages": ["en", "fr", "de", "es"],
        "recommended": False,
    },
    {
        "name": "aya:8b",
        "size": "4.9 GB",
        "params": "8B",
        "ram": "8 GB",
        "description": "Cohere Aya — specifically designed for multilingual including Arabic. 23 languages.",
        "languages": ["en", "ar", "fr", "es"],
        "recommended": True,
    },
    # --- Google Gemma 3 (2025 release, multilingual + multimodal) ---
    {
        "name": "gemma3:1b",
        "size": "0.8 GB",
        "params": "1B",
        "ram": "1 GB",
        "description": "Google Gemma 3 1B — ultra-lightweight, runs on any machine. Multilingual including Arabic. Good for basic queries.",
        "languages": ["en", "ar", "fr", "de", "es", "ja", "ko", "zh"],
        "recommended": True,
    },
    {
        "name": "gemma3:4b",
        "size": "3.3 GB",
        "params": "4B",
        "ram": "4 GB",
        "description": "Google Gemma 3 4B — best balance of size + quality. Multilingual, handles Arabic well. Supports vision (images) in addition to text.",
        "languages": ["en", "ar", "fr", "de", "es", "ja", "ko", "zh"],
        "recommended": True,
    },
    {
        "name": "gemma3:12b",
        "size": "8.1 GB",
        "params": "12B",
        "ram": "12 GB",
        "description": "Google Gemma 3 12B — high quality, needs 12 GB+ RAM. Multilingual + multimodal (text + images). Best quality for research.",
        "languages": ["en", "ar", "fr", "de", "es", "ja", "ko", "zh"],
        "recommended": False,
    },
    {
        "name": "gemma3:27b",
        "size": "17 GB",
        "params": "27B",
        "ram": "24 GB",
        "description": "Google Gemma 3 27B — flagship quality, needs 24 GB+ RAM. Best for complex interpretive tasks. Multilingual + multimodal.",
        "languages": ["en", "ar", "fr", "de", "es", "ja", "ko", "zh"],
        "recommended": False,
    },
]


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


# --------------------------------------------------------------------------- #
# Ollama model catalogue + pull
# --------------------------------------------------------------------------- #


@router.get("/ollama/catalogue")
async def ollama_catalogue() -> dict:
    """Return the curated catalogue of recommended Ollama models.

    Each entry includes: name, size, params, RAM requirement, description,
    languages, and whether it's recommended. The frontend uses this to
    show a model-picker UI where the user can download (pull) models.
    """
    return {"models": RECOMMENDED_OLLAMA_MODELS}


class OllamaPullRequest(BaseModel):
    """Request to pull (download) an Ollama model."""
    model: str = Field(..., description="Model name, e.g. 'llama3.2:3b'")


@router.post("/ollama/pull")
async def ollama_pull(req: OllamaPullRequest) -> dict:
    """Pull (download) an Ollama model.

    This is a non-blocking endpoint — it starts the pull in a background
    task and returns immediately. The pull progress can be polled via
    /api/v1/ollama/pull/status?model=...
    """
    settings = get_settings()
    base_url = settings.ollama_base_url.rstrip("/")
    model = req.model.strip()

    if not model:
        raise HTTPException(400, "Model name is required")

    # Check Ollama is running
    try:
        async with httpx.AsyncClient(timeout=5.0) as client:
            r = await client.get(f"{base_url}/api/tags")
            if r.status_code != 200:
                raise HTTPException(503, "Ollama is not responding. Is `ollama serve` running?")
    except httpx.ConnectError as e:
        raise HTTPException(503, f"Cannot connect to Ollama at {base_url}. Is `ollama serve` running?") from e

    # Start the pull in the background
    async def _do_pull():
        try:
            async with httpx.AsyncClient(timeout=600.0) as client:
                # Ollama's /api/pull streams NDJSON progress lines
                async with client.stream("POST", f"{base_url}/api/pull", json={"name": model}) as r:
                    async for line in r.aiter_lines():
                        if not line:
                            continue
                        try:
                            data = json.loads(line)
                            _pull_status[model] = {
                                "status": data.get("status", "pulling"),
                                "completed": data.get("completed", 0),
                                "total": data.get("total", 0),
                                "error": None,
                            }
                        except Exception:
                            continue
            _pull_status[model] = {
                "status": "success",
                "completed": _pull_status.get(model, {}).get("total", 0),
                "total": _pull_status.get(model, {}).get("total", 0),
                "error": None,
            }
            log.info("ollama_pull_success", model=model)
        except Exception as e:
            _pull_status[model] = {
                "status": "error",
                "completed": 0,
                "total": 0,
                "error": str(e),
            }
            log.error("ollama_pull_failed", model=model, error=str(e))

    # Store status before starting
    _pull_status[model] = {
        "status": "starting",
        "completed": 0,
        "total": 0,
        "error": None,
    }
    # Store the task reference so it's not garbage-collected
    task = asyncio.create_task(_do_pull())
    _pull_tasks[model] = task

    return {"ok": True, "model": model, "message": f"Pulling {model} in the background. Poll /api/v1/ollama/pull/status?model={model} for progress."}


# In-memory pull status tracker (per model)
_pull_status: dict[str, dict] = {}
# In-memory pull task references (prevent garbage collection)
_pull_tasks: dict[str, asyncio.Task] = {}


@router.get("/ollama/pull/status")
async def ollama_pull_status(model: str) -> dict:
    """Get the pull progress for a model."""
    if model not in _pull_status:
        return {"model": model, "status": "not_started", "completed": 0, "total": 0, "error": None}
    return {"model": model, **_pull_status[model]}


# --------------------------------------------------------------------------- #
# Import a local .gguf model file via `ollama create`
# --------------------------------------------------------------------------- #


class OllamaImportRequest(BaseModel):
    """Import a local .gguf file as an Ollama model.

    The user picks a .gguf file on their disk. The engine calls
    `ollama create <name> -f <path>` to register it with Ollama.
    After that, the model appears in the Ollama model list and can
    be used like any other model.
    """
    model_name: str = Field(..., description="Name to register the model as (e.g. 'my-gemma-4b')")
    file_path: str = Field(..., description="Absolute path to the .gguf file on disk")


@router.post("/ollama/import")
async def ollama_import(req: OllamaImportRequest) -> dict:
    """Import a local .gguf file as an Ollama model via `ollama create`.

    This lets users download .gguf files from any source (HuggingFace,
    direct download, shared by a colleague) and register them with
    Ollama without using the Ollama registry.
    """
    import subprocess
    import tempfile

    settings = get_settings()
    base_url = settings.ollama_base_url.rstrip("/")
    model_name = req.model_name.strip()
    file_path = req.file_path.strip()

    if not model_name or not file_path:
        raise HTTPException(400, "Both model_name and file_path are required")

    # Check Ollama is running
    try:
        async with httpx.AsyncClient(timeout=5.0) as client:
            r = await client.get(f"{base_url}/api/tags")
            if r.status_code != 200:
                raise HTTPException(503, "Ollama is not responding. Is `ollama serve` running?")
    except httpx.ConnectError as e:
        raise HTTPException(503, f"Cannot connect to Ollama at {base_url}. Is `ollama serve` running?") from e

    # Check the file exists
    import os
    if not os.path.exists(file_path):
        raise HTTPException(400, f"File not found: {file_path}")

    # Create a Modelfile that points to the .gguf file
    # Ollama's `create` command reads a Modelfile that says:
    #   FROM /path/to/model.gguf
    modelfile_content = f"FROM {file_path}\n"

    try:
        # Write the Modelfile to a temp file
        with tempfile.NamedTemporaryFile(mode="w", suffix=".modelfile", delete=False) as f:
            f.write(modelfile_content)
            modelfile_path = f.name

        # Call `ollama create <name> -f <modelfile>`
        # This is a blocking call — run it in a thread pool
        result = await asyncio.to_thread(
            subprocess.run,
            ["ollama", "create", model_name, "-f", modelfile_path],
            capture_output=True,
            text=True,
            timeout=300,  # 5 min timeout for large files
        )

        # Clean up the temp file
        os.unlink(modelfile_path)

        if result.returncode != 0:
            raise HTTPException(500, f"ollama create failed: {result.stderr}")

        log.info("ollama_import_success", model=model_name, file=file_path)
        return {
            "ok": True,
            "model": model_name,
            "message": f"Model '{model_name}' imported from {file_path}. It now appears in your Ollama model list.",
        }
    except subprocess.TimeoutExpired:
        raise HTTPException(504, "ollama create timed out (5 min). The file may be too large.") from None
    except FileNotFoundError:
        raise HTTPException(500, "`ollama` command not found. Is Ollama installed and on PATH?") from None
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(500, f"Import failed: {e}") from e

