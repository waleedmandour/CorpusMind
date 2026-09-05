"""Phase 3 Arabic API routes (§8.21, §8.22)."""

from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field
from sqlalchemy.ext.asyncio import AsyncSession

from app.logging import get_logger
from nlp.arabic.bilingual import (
    align_parallel_corpora,
    lookup_translation,
    parallel_concordance,
)
from nlp.arabic.pipeline import (
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
    transliteration + dediacritization."""
    try:
        analysis = analyze_arabic(
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
                f"Unknown tagset '{body.tagset}' — valid: calima, upos.",
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
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Arabic analysis failed: {e}") from e


class RootsRequest(BaseModel):
    text: str = Field(..., min_length=1)


@router.post("/arabic/roots")
async def roots_route(body: RootsRequest) -> dict:
    """Extract roots (الجذر) + patterns (الوزن) from Arabic text."""
    return {"roots": extract_arabic_roots(body.text)}


class CliticsRequest(BaseModel):
    text: str = Field(..., min_length=1)


@router.post("/arabic/clitics")
async def clitics_route(body: CliticsRequest) -> dict:
    """Segment Arabic clitics (التصاق الضمائر والات)."""
    return {"segments": segment_arabic_clitics(body.text)}


class TranslitRequest(BaseModel):
    text: str = Field(..., min_length=1)


@router.post("/arabic/buckwalter")
async def buckwalter_route(body: TranslitRequest) -> dict:
    """Transliterate Arabic to Buckwalter encoding (Latin)."""
    return {"buckwalter": transliterate_buckwalter(body.text), "original": body.text}


@router.post("/arabic/dediacritize")
async def dediacritize_route(body: TranslitRequest) -> dict:
    """Remove Arabic diacritics (التشكيل)."""
    return {"dediacritized": dediacritize_arabic(body.text), "original": body.text}


@router.post("/arabic/normalize")
async def normalize_route(body: TranslitRequest) -> dict:
    """Normalize Arabic text (alef variants, teh marbuta, alef maksura)."""
    return {"normalized": normalize_arabic(body.text), "original": body.text}


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
    return identify_arabic_dialect(body.text, include_cities=body.include_cities)


@router.post("/arabic/register")
async def register_route(body: TranslitRequest) -> dict:
    """Detect Arabic register: Classical / MSA / Dialectal."""
    return {"register_distribution": detect_arabic_register(body.text)}


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
                bi = get_arabic_backend(name).info()
                info.update(
                    {
                        "version": bi.version,
                        "model": bi.model,
                        "dialects_supported": bi.dialects_supported,
                    }
                )
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
