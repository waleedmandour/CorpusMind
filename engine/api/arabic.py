"""Phase 3 Arabic API routes (§8.21, §8.22)."""
from __future__ import annotations

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, Field

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

router = APIRouter()


# --------------------------------------------------------------------------- #
# §8.21 Arabic morphology analysis
# --------------------------------------------------------------------------- #


class AnalyzeArabicRequest(BaseModel):
    text: str = Field(..., min_length=1, description="Arabic text to analyze")
    backend: str = Field("camel", description="camel | farasa | sinatools")
    dialect: str = Field("msa", description="msa | egy | glf | lev")
    dediacritize: bool = False


@router.post("/arabic/analyze")
async def analyze_arabic_route(body: AnalyzeArabicRequest) -> dict:
    """Full Arabic morphological analysis: tokenization + root extraction +
    pattern (وزن) identification + lemma normalization + POS + Buckwalter
    transliteration + dediacritization."""
    try:
        analysis = analyze_arabic(
            body.text, backend=body.backend, dialect=body.dialect,
            dediacritize=body.dediacritize,
        )
        return {
            "text": analysis.text,
            "backend": analysis.backend,
            "detected_dialect": analysis.detected_dialect,
            "token_count": len(analysis.tokens),
            "tokens": [
                {
                    "text": t.text,
                    "lemma": t.lemma,
                    "root": t.root,
                    "pattern": t.pattern,
                    "pos": t.pos,
                    "stem": t.stem,
                    "buckwalter": t.buckwalter,
                    "dediacritized": t.dediacritized,
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


@router.post("/arabic/dialect")
async def dialect_route(body: TranslitRequest) -> dict:
    """Identify Arabic dialect (MSA / Egyptian / Gulf / Levantine)."""
    return {"dialect_distribution": identify_arabic_dialect(body.text)}


@router.post("/arabic/register")
async def register_route(body: TranslitRequest) -> dict:
    """Detect Arabic register: Classical / MSA / Dialectal."""
    return {"register_distribution": detect_arabic_register(body.text)}


# --------------------------------------------------------------------------- #
# Backend info
# --------------------------------------------------------------------------- #


@router.get("/arabic/backends")
async def list_backends() -> dict:
    """List available Arabic NLP backends + their capabilities."""
    backends = []
    for name, available in [("camel", True), ("farasa", False), ("sinatools", False)]:
        info = {"name": name, "available": available}
        if available:
            try:
                bi = get_arabic_backend(name).info()
                info.update({
                    "version": bi.version,
                    "model": bi.model,
                    "dialects_supported": bi.dialects_supported,
                })
            except Exception:
                pass
        backends.append(info)
    return {"backends": backends}
