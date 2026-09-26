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


@router.get("/health/resources")
async def resources_health() -> dict:
    """Availability of the bundled optional resources (v1.2.8, review #1).

    STATUS endpoint (always 200): reports whether the data files behind the
    USAS semantic lens, the vocabulary profile (AWL + K1 list) and the
    bundled reference corpora were found under the resolved reference-data
    directory, plus whether the optional persuasion-index package imports.

    The Settings surface and the release pipeline's post-build smoke gate
    both read this instead of having to run an analysis first.
    """
    out: dict = {
        "usas": {},
        "wordlists": {},
        "reference_corpora": {},
        "reference_data_dir": None,
        "persuasion_index": {"installed": False, "version": None},
    }

    try:
        from nlp.tagsets import load_semantic_lexicon

        for lang in ("en", "ar"):
            try:
                out["usas"][lang] = bool(load_semantic_lexicon(lang))
            except Exception:
                out["usas"][lang] = False
    except Exception:
        out["usas"] = {"en": False, "ar": False}

    try:
        from app.resource_paths import exists, reference_data_dir

        out["wordlists"] = {
            "awl": exists("wordlists", "awl-sublists.tsv"),
            "k1_top200": exists("wordlists", "en", "top200.tsv"),
        }
        out["reference_corpora"] = {
            "be06_top1000": exists("reference-corpora", "en", "be06-freq-top1000.tsv"),
        }
        try:
            out["reference_data_dir"] = str(reference_data_dir())
        except FileNotFoundError:
            out["reference_data_dir"] = None
    except Exception:
        pass

    try:
        import importlib.metadata

        import persuasion_index

        out["persuasion_index"] = {
            "installed": True,
            "version": getattr(persuasion_index, "__version__", None)
            or importlib.metadata.version("persuasion-index"),
        }
    except Exception:
        pass

    return out
