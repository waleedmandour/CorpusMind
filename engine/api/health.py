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
    USAS semantic lens, the vocabulary profile (AWL + K1 list), the bundled
    reference corpora and the discourse framework YAMLs were found under the
    resolved reference-data directory, plus whether the optional
    persuasion-index package imports.

    v1.2.10: this endpoint is now the SINGLE asserted registry for the
    release pipeline's post-build smoke gates (ci_smoke_engine.sh/.ps1) and
    the Docker CI job — every key a build contractually ships must be true
    here, so a new bundled resource cannot regress silently the way the
    v1.2.8 PyInstaller bundle did. Report-only (non-contractual) keys are
    also present: user-supplied resources (NRC EmoLex) and environment-
    dependent facts (spaCy model installs) are reported, never asserted.

    The Settings surface and the release pipeline's post-build smoke gate
    both read this instead of having to run an analysis first.
    """
    out: dict = {
        "usas": {},
        "wordlists": {},
        "reference_corpora": {},
        "frameworks": {},
        "spacy_model": {},
        "wordfreq": {},
        "sentiment": {},
        "languages": {},
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
        # v1.2.10: every bundled reference corpus is registered, not just
        # the one that regressed in v1.2.8 — a missing file anywhere in the
        # pack is a bundle defect the smoke gate must catch.
        out["reference_corpora"] = {
            "be06_top1000": exists("reference-corpora", "en", "be06-freq-top1000.tsv"),
            "leipzig_news_top100": exists(
                "reference-corpora", "en", "leipzig-english-news-top100.tsv"
            ),
            "ellipse_learner_top1000": exists(
                "reference-corpora", "en", "ellipse-learner-top1000.tsv"
            ),
            "pd_persuasive_top1000": exists(
                "reference-corpora", "en", "pd-persuasive-top1000.tsv"
            ),
            "camel_arabic_top1000": exists(
                "reference-corpora", "ar", "camel-arabic-top1000.tsv"
            ),
            "quranic_arabic_freq": exists(
                "reference-corpora", "ar", "quranic-arabic-freq.tsv"
            ),
            "dialectal_tweets_top1000": exists(
                "reference-corpora", "ar", "dialectal-arabic-tweets-top1000.tsv"
            ),
            # v1.2.11: Urdu / Hindi / Farsi keyness baselines (wordfreq
            # 3.1.1-derived, CC BY-SA 4.0 data) — contractual in the bundle.
            "urdu_freq_top1000": exists(
                "reference-corpora", "ur", "urdu-freq-top1000.tsv"
            ),
            "hindi_freq_top1000": exists(
                "reference-corpora", "hi", "hindi-freq-top1000.tsv"
            ),
            "farsi_freq_top1000": exists(
                "reference-corpora", "fa", "farsi-freq-top1000.tsv"
            ),
        }
        # v1.2.10: framework YAML catalogue (12 bundled definitions).
        try:
            fw_dir = reference_data_dir() / "frameworks"
            out["frameworks"] = {
                "count": len(list(fw_dir.glob("*.yaml"))) if fw_dir.is_dir() else 0
            }
        except Exception:
            out["frameworks"] = {"count": 0}
        try:
            out["reference_data_dir"] = str(reference_data_dir())
        except FileNotFoundError:
            out["reference_data_dir"] = None
    except Exception:
        pass

    # v1.2.10: the desktop bundle CONTRACTUALLY ships the model (spec
    # collects it; Windows verify step + release smoke gate assert it), so
    # this key is asserted for the sidecar. The probe MUST mirror the
    # pipeline's real load paths — spacy.util.is_package alone is blind to
    # the frozen bundle's collected package data and made the registry
    # report a healthy bundle as model-less (caught by the v1.2.10
    # release gate on Linux/macOS).
    try:
        from app.resource_paths import spacy_model_available

        out["spacy_model"] = {
            "en_core_web_sm": bool(spacy_model_available("en_core_web_sm"))
        }
    except Exception:
        out["spacy_model"] = {"en_core_web_sm": False}

    try:
        import importlib.util

        out["wordfreq"] = {
            "installed": importlib.util.find_spec("wordfreq") is not None
        }
    except Exception:
        out["wordfreq"] = {"installed": False}

    # Sentiment: the curated starter lexicons ship as engine code (always
    # available); the full NRC EmoLex is user-supplied (license forbids
    # redistribution) — report whether the operator configured it.
    out["sentiment"] = {"starter_lexicons": True, "nrc_configured": False}
    try:
        from sentiment.lexicons import _lexicon_dirs

        out["sentiment"]["nrc_configured"] = bool(_lexicon_dirs())
    except Exception:
        pass

    # v1.2.11: per-language capability summary (bundled stopword lists per
    # language and whether the optional Stanza backend is importable).
    languages_report: dict = {"stopwords": {}, "stanza": {}}
    try:
        from nlp.stopwords import get_stopwords

        for lang in ("en", "ar", "ur", "hi", "fa"):
            languages_report["stopwords"][lang] = len(get_stopwords(lang)) > 0
    except Exception:
        pass
    try:
        import importlib.util as _ilu

        languages_report["stanza"] = {
            "installed": _ilu.find_spec("stanza") is not None,
            "note": "optional backend for ur/hi/fa POS/lemma/parse",
        }
    except Exception:
        pass
    out["languages"] = languages_report

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
