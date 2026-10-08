"""Phase 3 Arabic API routes (§8.21, §8.22).

v1.2.11 (Arabic Tools hang fix): every CAMeL-backed handler here is CPU-
bound, synchronous code (morphology analyzer, DIDModel6 loader). Running it
inline in these ``async def`` handlers blocked the single event loop, so a
slow/hung analysis froze the ENTIRE engine, /health included. Two rules now
apply to every route in this module:

  1. sync work runs in a worker thread via ``asyncio.to_thread``;
  2. sync work is bounded by ``ARABIC_TIMEOUT_S`` — on timeout the client
     gets HTTP 504 with a hint while the worker thread finishes in the
     background (a running thread cannot be killed; the loop stays free).
"""

from __future__ import annotations

import asyncio
import os

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field
from sqlalchemy.ext.asyncio import AsyncSession

from app.arabic_concurrency import ArabicBusyError, gate
from app.logging import get_logger
from nlp.arabic.bilingual import (
    align_parallel_corpora,
    lookup_translation,
    parallel_concordance,
)
from nlp.arabic.pipeline import (
    ArabicDataMissingError,
    analyze_arabic,
    dediacritize_arabic,
    detect_arabic_register,
    extract_arabic_roots,
    get_arabic_backend,
    identify_arabic_dialect,
    normalize_arabic,
    segment_arabic_clitics,
    transliterate_buckwalter,
)
from storage.session import get_session

log = get_logger(__name__)

router = APIRouter()


# Hard ceiling for one Arabic Tools request (worker-thread time). Env-
# overridable so tests can exercise the 504 path without waiting.
# v1.2.12 (field report): 30s assumed a cold calima-msa-r13 load in "tens of
# seconds with cold disk + antivirus" — real Windows machines with real-time
# Defender scanning exceeded that EVERY first run, so the sample sentence
# failed with 504 even though the pack was correctly installed. 120s covers
# measured slow-disk loads (the loader thread also finishes in the
# background after a 504, so the retry hits the warm cache); a genuinely
# stuck load must still not pin the request forever.
ARABIC_TIMEOUT_S = float(os.environ.get("CORPUSMIND_ARABIC_TIMEOUT_S", "120"))

# v1.2.11 follow-up: measured ceiling for the INTERACTIVE analyze route.
# scripts/benchmark_arabic_corpus.py measured ~3,950 tokens/s on the dev
# reference machine (calima-msa-r13, warm cache): 100K tokens ≈ 25s, 500K ≈
# 126s, 1M ≈ 253s. A 50k-token cap keeps even the 30s class of machines
# comfortably inside the default 120s deadline; anything larger answers 413
# and points at the chunked bulk job (POST /arabic/analyze/job) which
# streams progress instead of holding one HTTP request for minutes.
ARABIC_INLINE_MAX_TOKENS = int(os.environ.get("CORPUSMIND_ARABIC_INLINE_MAX_TOKENS", "50000"))


async def _run_camel(fn, /, *args, **kwargs):
    """Run a CAMeL-backed sync callable off the event loop, with a deadline.

    - HTTP 429 + Retry-After when the process-wide Arabic concurrency cap
      (v1.2.11 follow-up: ``CORPUSMIND_ARABIC_CONCURRENCY``, 1..2, default
      1) is fully used. The slot is taken NON-blocking on the event loop
      thread, so a busy engine answers instantly instead of queueing an
      unbounded number of hidden analyses.
    - HTTP 503 + hint when the morphology data is not provisioned (the
      pre-flight raises ``ArabicDataMissingError``; the engine refuses fast
      instead of attempting camel_tools' timeout-less data download).
    - HTTP 504 + hint when the deadline expires. The worker thread keeps
      running in the background; the loop and every other route stay live.
    """
    if not gate.acquire():
        log.warning(
            "arabic_route_busy",
            route=fn.__name__,
            cap=gate.cap,
        )
        raise HTTPException(
            429,
            ArabicBusyError().args[0],
            headers={"Retry-After": "2"},
        )
    try:
        return await asyncio.wait_for(
            asyncio.to_thread(fn, *args, **kwargs), timeout=ARABIC_TIMEOUT_S
        )
    except TimeoutError as e:
        log.warning("arabic_route_timeout", route=fn.__name__, timeout_s=ARABIC_TIMEOUT_S)
        raise HTTPException(
            504,
            f"Arabic analysis did not finish within {ARABIC_TIMEOUT_S:g}s. "
            "The first run after installing CAMeL data loads a large "
            "morphology database; try again, or use a shorter text.",
        ) from e
    except ArabicDataMissingError as e:
        raise HTTPException(status_code=503, detail=str(e)) from e
    finally:
        gate.release()


# --------------------------------------------------------------------------- #
# §8.21 Arabic morphology analysis
# --------------------------------------------------------------------------- #


class AnalyzeArabicRequest(BaseModel):
    text: str = Field(..., min_length=1, description="Arabic text to analyze")
    backend: str = Field("camel", description="camel | farasa | sinatools")
    dialect: str = Field("msa", description="msa | egy | glf | lev")
    dediacritize: bool = False
    tagset: str = Field(
        "calima",
        description="v1.2.0: 'calima' (native CAMeL tags, default) or 'upos' (Universal Dependencies)",
    )


@router.post("/arabic/analyze")
async def analyze_arabic_route(body: AnalyzeArabicRequest) -> dict:
    """Full Arabic morphological analysis: tokenization + root extraction +
    pattern (وزن) identification + lemma normalization + POS + Buckwalter
    transliteration + dediacritization.

    v1.2.11 follow-up: corpus-sized input (> ARABIC_INLINE_MAX_TOKENS
    whitespace-delimited tokens, default 50,000) answers HTTP 413 with the
    measured numbers and points at the bulk job endpoint instead of
    holding one request for minutes.
    """
    # Cheap guard BEFORE the worker slot is taken: len(split()) on even a
    # 5MB text is single-digit milliseconds, never a blocking risk.
    if len(body.text.split()) > ARABIC_INLINE_MAX_TOKENS:
        raise HTTPException(
            413,
            f"This text is larger than the interactive analysis limit "
            f"({ARABIC_INLINE_MAX_TOKENS} tokens). Measured throughput of the "
            f"morphology analyzer is ~3,950 tokens/s, so 500K tokens takes "
            f"~2 minutes and 1M ~4 minutes. Use the chunked bulk job instead: "
            f"POST /api/v1/arabic/analyze/job (progress via "
            f"/arabic/analyze/job/status, result download via "
            f"/arabic/analyze/job/result, cancel supported).",
        )
    try:
        analysis = await _run_camel(
            analyze_arabic,
            body.text,
            backend=body.backend,
            dialect=body.dialect,
            dediacritize=body.dediacritize,
        )
        # v1.2.0 (Issue 4): tagset selection — 'calima' returns the native
        # CAMeL tags (default, unchanged behavior); 'upos' maps them to
        # Universal Dependencies for cross-language comparability.
        if body.tagset not in ("calima", "upos"):
            raise HTTPException(
                422,
                f"Unknown tagset '{body.tagset}' - valid: calima, upos.",
            )
        from nlp.arabic.pipeline import ArabicPipeline

        def _display_pos(raw: str) -> str:
            if body.tagset == "upos":
                return ArabicPipeline._map_pos(raw)
            return raw

        return {
            "text": analysis.text,
            "backend": analysis.backend,
            "detected_dialect": analysis.detected_dialect,
            "tagset": body.tagset,
            "token_count": len(analysis.tokens),
            "tokens": [
                {
                    "text": t.text,
                    "lemma": t.lemma,
                    "root": t.root,
                    "pattern": t.pattern,
                    "pos": _display_pos(t.pos),
                    "stem": t.stem,
                    "buckwalter": t.buckwalter,
                    "dediacritized": t.dediacritized,
                    "number": t.number,
                    "gender": t.gender,
                    "is_broken_plural": t.is_broken_plural,
                }
                for t in analysis.tokens
            ],
        }
    except NotImplementedError as e:
        raise HTTPException(status_code=501, detail=str(e)) from e
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Arabic analysis failed: {e}") from e


# --------------------------------------------------------------------------- #
# v1.2.11 follow-up: in-app Arabic data pack installer (background job).
# Routes live in api/arabic_data.py; the 503 hint text lives in
# nlp/arabic/pipeline.py (INSTALL_HINT) next to the error it annotates.
# --------------------------------------------------------------------------- #


class RootsRequest(BaseModel):
    text: str = Field(..., min_length=1)


@router.post("/arabic/roots")
async def roots_route(body: RootsRequest) -> dict:
    """Extract roots (الجذر) + patterns (الوزن) from Arabic text."""
    return {"roots": await _run_camel(extract_arabic_roots, body.text)}


class CliticsRequest(BaseModel):
    text: str = Field(..., min_length=1)


@router.post("/arabic/clitics")
async def clitics_route(body: CliticsRequest) -> dict:
    """Segment Arabic clitics (التصاق الضمائر والات)."""
    return {"segments": await _run_camel(segment_arabic_clitics, body.text)}


class TranslitRequest(BaseModel):
    text: str = Field(..., min_length=1)


@router.post("/arabic/buckwalter")
async def buckwalter_route(body: TranslitRequest) -> dict:
    """Transliterate Arabic to Buckwalter encoding (Latin)."""
    return {
        "buckwalter": await _run_camel(transliterate_buckwalter, body.text),
        "original": body.text,
    }


@router.post("/arabic/dediacritize")
async def dediacritize_route(body: TranslitRequest) -> dict:
    """Remove Arabic diacritics (التشكيل)."""
    return {
        "dediacritized": await _run_camel(dediacritize_arabic, body.text),
        "original": body.text,
    }


@router.post("/arabic/normalize")
async def normalize_route(body: TranslitRequest) -> dict:
    """Normalize Arabic text (alef variants, teh marbuta, alef maksura)."""
    return {"normalized": await _run_camel(normalize_arabic, body.text), "original": body.text}


# --------------------------------------------------------------------------- #
# §8.21 Dialect + register detection
# --------------------------------------------------------------------------- #


class DialectRequest(BaseModel):
    text: str = Field(..., min_length=1)
    include_cities: bool = Field(
        False, description="Include raw city-level scores (Beirut, Cairo, Doha, MSA, Rabat, Tunis)"
    )


@router.post("/arabic/dialect")
async def dialect_route(body: DialectRequest) -> dict:
    """Identify Arabic dialect (MSA / Egyptian / Gulf / Levantine).

    With `include_cities=True`, also returns the raw city-level scores from
    the CAMeL DIDModel6 (Beirut, Cairo, Doha, MSA, Rabat, Tunis).
    """
    return await _run_camel(identify_arabic_dialect, body.text, include_cities=body.include_cities)


@router.post("/arabic/register")
async def register_route(body: TranslitRequest) -> dict:
    """Detect Arabic register: Classical / MSA / Dialectal."""
    return {"register_distribution": await _run_camel(detect_arabic_register, body.text)}


# --------------------------------------------------------------------------- #
# Backend info
# --------------------------------------------------------------------------- #


@router.get("/arabic/backends")
async def list_backends() -> dict:
    """List available Arabic NLP backends + their capabilities.

    A backend is only reported as ``available`` if its ``.info()`` call
    succeeds — i.e. the package is installed AND its morphological
    database loads correctly. If the load fails, the backend is reported
    as ``available=False`` with an ``error`` field explaining why, instead
    of the previous behavior of silently reporting ``available=True`` with
    no version/dialect info. That bare ``except Exception: pass`` made
    broken camel_tools installs look healthy from the outside, hiding the
    real reason Arabic analysis wasn't working for the user.
    """
    backends = []
    for name, available in [("camel", True), ("farasa", False), ("sinatools", False)]:
        info = {"name": name, "available": available}
        if available:
            try:
                # info() triggers the (pre-flight-guarded) DB load in a
                # worker thread. Missing data lands as HTTPException(503)
                # from _run_camel; any other load failure propagates as-is.
                # Both mean "nominally installed but not actually usable",
                # so this endpoint reports available=False + the reason in
                # the error field rather than failing the whole status call.
                bi = await _run_camel(get_arabic_backend(name).info)
                info.update(
                    {
                        "version": bi.version,
                        "model": bi.model,
                        "dialects_supported": bi.dialects_supported,
                    }
                )
            except HTTPException as e:
                info["available"] = False
                info["error"] = str(e.detail)
                log.warning("arabic_backend_unavailable", backend=name, error=str(e.detail))
            except Exception as e:
                # A backend that can't actually load isn't available,
                # regardless of whether the package is nominally installed.
                # Flip available to False and surface the error so the
                # caller (and the log) can see WHY it's broken.
                info["available"] = False
                info["error"] = str(e)
                log.warning("arabic_backend_unavailable", backend=name, error=str(e))
        backends.append(info)
    return {"backends": backends}


# --------------------------------------------------------------------------- #
# §8.22 Bilingual corpus tools — Arabic↔English alignment + parallel concordance
# --------------------------------------------------------------------------- #


class AlignRequest(BaseModel):
    ar_corpus_id: str = Field(..., description="Arabic corpus ID")
    en_corpus_id: str = Field(..., description="English corpus ID")


@router.post("/bilingual/align")
async def align_route(body: AlignRequest, session: AsyncSession = Depends(get_session)) -> dict:
    """Sentence-align two parallel corpora (Arabic + English) using the
    Gale-Church (1993) length-based algorithm."""
    result = await align_parallel_corpora(session, body.ar_corpus_id, body.en_corpus_id)
    return {
        "method": result.method,
        "ar_doc_count": result.ar_doc_count,
        "en_doc_count": result.en_doc_count,
        "pair_count": len(result.pairs),
        "pairs": [
            {
                "ar_sentence": p.ar_sentence,
                "en_sentence": p.en_sentence,
                "ar_sent_idx": p.ar_sent_idx,
                "en_sent_idx": p.en_sent_idx,
                "confidence": p.confidence,
                "pair_type": p.pair_type,
            }
            for p in result.pairs
        ],
    }


class ParallelConcordanceRequest(BaseModel):
    ar_corpus_id: str
    en_corpus_id: str
    query: str = Field(..., min_length=1)
    level: str = "lemma"
    window: int = Field(5, ge=1, le=20)
    limit: int = Field(50, ge=1, le=200)


@router.post("/bilingual/parallel-concordance")
async def parallel_concordance_route(
    body: ParallelConcordanceRequest, session: AsyncSession = Depends(get_session)
) -> dict:
    """Parallel concordance: search Arabic, return each hit paired with its
    English translation (per the sentence alignment)."""
    result = await parallel_concordance(
        session,
        body.ar_corpus_id,
        body.en_corpus_id,
        body.query,
        level=body.level,
        window=body.window,
        limit=body.limit,
    )
    return {
        "query": result.query,
        "total": result.total,
        "pairs": result.pairs,
    }


class TranslationRequest(BaseModel):
    word: str = Field(..., min_length=1)
    direction: str = Field("ar-en", description="ar-en or en-ar")


@router.post("/bilingual/translate")
async def translate_route(body: TranslationRequest) -> dict:
    """Look up translation equivalents for a word.

    Phase 3 uses a small starter dictionary. Phase 4 will integrate a proper
    bilingual word-alignment model (fast_align or similar) behind the same
    interface (§4 Principle 8: model + version pinned per project).
    """
    result = lookup_translation(body.word, body.direction)
    return {
        "word": result.word,
        "direction": result.direction,
        "equivalents": result.equivalents,
        "source": result.source,
    }
