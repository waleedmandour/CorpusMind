"""Phase 5 API routes — multimodal discourse analyses (§9.11–9.18) + facial (§9.4.3)."""
from __future__ import annotations

from dataclasses import asdict
from pathlib import Path
from typing import Literal

from fastapi import APIRouter, Depends, HTTPException, Request
from pydantic import BaseModel, Field
from sqlalchemy.ext.asyncio import AsyncSession

from ai.providers import ModelProviderError
from app.logging import get_logger
from multimodal.discourse import (
    CDA_FRAMEWORKS,
    analyse_cda,
    analyse_combined_emotion,
    analyse_cultural,
    analyse_framing,
    analyse_narrative,
    analyse_persuasion,
    analyse_social_semiotic,
    analyse_visual_metaphor,
)
from multimodal.discourse_llm import run_llm_discourse_analysis
from storage.models import Image as ImageModel
from storage.session import get_session
from vision.facial import FacialAnalysisDisabledError, analyse_faces
from vision.pipeline import ColourAnalysis, CompositionAnalysis, OCRResult, load_image

log = get_logger(__name__)
router = APIRouter()


# --------------------------------------------------------------------------- #
# Helper: reconstruct sub-analyses from cached image analysis
# --------------------------------------------------------------------------- #


async def _get_image_sub_analyses(img: ImageModel) -> tuple[ColourAnalysis, CompositionAnalysis, OCRResult, str]:
    if not img.analysis:
        raise HTTPException(400, "Image has no cached analysis. Re-ingest first.")
    a = img.analysis
    ocr_data = a.get("ocr", {})
    colours_data = a.get("colours", {})
    comp_data = a.get("composition", {})
    ocr = OCRResult(
        text=ocr_data.get("text", ""),
        confidence=ocr_data.get("confidence", 0.0),
        word_count=ocr_data.get("word_count", 0),
        engine=ocr_data.get("engine", "none"),
        language=ocr_data.get("language", "auto"),
    )
    colours = ColourAnalysis(
        dominant_colours=colours_data.get("dominant_colours", []),
        warm_cold_balance=colours_data.get("warm_cold_balance", 0.0),
        brightness=colours_data.get("brightness", 0.0),
        contrast=colours_data.get("contrast", 0.0),
        saturation=colours_data.get("saturation", 0.0),
        colour_symbolism_notes=colours_data.get("colour_symbolism_notes", []),
    )
    composition = CompositionAnalysis(
        information_value=comp_data.get("information_value", {}),
        rule_of_thirds_intersections=comp_data.get("rule_of_thirds_intersections", []),
        salience_centre=tuple(comp_data.get("salience_centre", [0.5, 0.5])),
        visual_balance=comp_data.get("visual_balance", 0.0),
        framing_balance=comp_data.get("framing_balance", 0.0),
        vectors=comp_data.get("vectors", []),
    )
    return colours, composition, ocr, img.caption


# --------------------------------------------------------------------------- #
# Vision-LM mode helper (CorpusMind Lens build step 4)
#
# Each of the eight discourse routes below accepts a ?mode= query param:
#   - mode=heuristic (default): the existing purely-heuristic path
#     (colour/geometry/OCR/caption). No LLM dependency. Fast, model-free.
#   - mode=llm: sends the actual image bytes + the framework's
#     theoretical lens to a local vision-LM, so the analysis can look
#     at what the image actually depicts. Falls back to heuristic with
#     a fallback_reason if no provider is available/healthy or the LLM
#     call fails. Never an error state.
#
# The LLM path is implemented in multimodal/discourse_llm.py. This
# helper handles the dispatch + fallback so each route stays a one-liner.
# --------------------------------------------------------------------------- #


class LLMModeRequest(BaseModel):
    """Common query params for the LLM mode of every discourse route.

    Each route accepts these as query params (?mode=llm&model=moondream).
    The route's existing body (e.g. CDARequest.framework) still applies
    in both modes.
    """
    mode: Literal["heuristic", "llm"] = Field(
        default="heuristic",
        description=(
            "heuristic (default): existing colour/geometry/OCR/caption path. "
            "llm: send the image to a vision-LM with the framework's lens. "
            "Falls back to heuristic if no provider is available."
        ),
    )
    model: str | None = Field(
        default=None,
        description="Model name for LLM mode. If None, uses the provider's default.",
    )
    provider: str = Field(
        default="ollama",
        description="Provider name for LLM mode: ollama | lmstudio | cloud",
    )
    refresh: bool = Field(
        default=False,
        description="If True, re-run the LLM analysis even if cached.",
    )


async def _try_llm_discourse(
    request: Request,
    img: ImageModel,
    framework_key: str,
    mode_params: LLMModeRequest,
    session: AsyncSession,
) -> dict | None:
    """Try to run the LLM discourse analysis. Returns None if the
    caller should fall back to the heuristic path.

    On success, returns the LLM result as a dict (with provenance).
    On fallback, returns None and logs the reason — the caller runs
    the heuristic path and includes fallback_reason in the response.

    Never raises — the caller's heuristic path is always available.
    """
    if mode_params.mode != "llm":
        return None

    try:
        provider = request.app.state.providers.get(mode_params.provider)
    except Exception as e:
        log.warning(
            "discourse_llm_provider_error",
            framework=framework_key,
            error=str(e),
        )
        return None

    if provider is None:
        log.warning(
            "discourse_llm_no_provider",
            framework=framework_key,
            provider=mode_params.provider,
        )
        return None

    # Health check before the call so we fall back cleanly instead of
    # timing out.
    try:
        is_healthy = await provider.health()
    except Exception:
        is_healthy = False
    if not is_healthy:
        log.warning(
            "discourse_llm_provider_unhealthy",
            framework=framework_key,
            provider=mode_params.provider,
        )
        return None

    try:
        result = await run_llm_discourse_analysis(
            img,
            framework_key,
            provider,
            model=mode_params.model,
            refresh=mode_params.refresh,
        )
    except ModelProviderError as e:
        log.warning(
            "discourse_llm_call_failed",
            framework=framework_key,
            error=str(e),
        )
        return None

    # Commit the cached analysis (run_llm_discourse_analysis mutates
    # img.analysis via full reassignment, but the session commit has
    # to happen here in the route layer).
    await session.commit()

    # Step 5: filter person-descriptive content through the consent gate
    # BEFORE returning. The gate is enforced at response-shaping time,
    # not at prompt time — see vision/consent_gate.py. Also filter the
    # summary (vision-LMs sometimes put person descriptions there too).
    from vision.consent_gate import filter_discourse_claims, filter_person_descriptive
    claim_filter = filter_discourse_claims(result.claims)
    summary_filter = filter_person_descriptive(result.summary)

    return {
        "analysis_type": result.analysis_type,
        "framework": result.framework,
        "claims": claim_filter["claims"],
        "summary": summary_filter.filtered_text,
        "provenance": {
            "mode": result.provenance.mode,
            "model": result.provenance.model,
            "provider": result.provenance.provider,
            "prompt_hash": result.provenance.prompt_hash,
            "timestamp": result.provenance.timestamp,
            "cached": result.provenance.cached,
        } if result.provenance else None,
        "person_descriptive_redacted": claim_filter["person_descriptive_redacted"] or summary_filter.was_filtered,
    }


def _heuristic_response_with_fallback(
    heuristic_result,
    *,
    fallback_reason: str | None = None,
) -> dict:
    """Wrap a heuristic DiscourseAnalysisResult as a dict, adding
    mode + fallback_reason fields so the UI can show which path
    produced the output."""
    d = asdict(heuristic_result)
    d["provenance"] = {"mode": "heuristic"}
    if fallback_reason:
        d["fallback_reason"] = fallback_reason
    return d


# --------------------------------------------------------------------------- #
# §9.11 Social Semiotic
# --------------------------------------------------------------------------- #


@router.post("/images/{img_id}/social-semiotic")
async def social_semiotic_route(
    img_id: str,
    request: Request,
    mode_params: LLMModeRequest = Depends(),
    session: AsyncSession = Depends(get_session),
) -> dict:
    img = await session.get(ImageModel, img_id)
    if not img:
        raise HTTPException(404, "Image not found")

    # Vision-LM mode (build step 4): send the actual image bytes to a
    # vision-LM with the social semiotic lens. Falls back to heuristic
    # if no provider is available.
    llm_result = await _try_llm_discourse(
        request, img, "social_semiotic", mode_params, session,
    )
    if llm_result is not None:
        return llm_result

    colours, composition, ocr, caption = await _get_image_sub_analyses(img)
    result = analyse_social_semiotic(colours, composition, ocr, caption)
    fallback = "LLM mode requested but unavailable — using heuristic." if mode_params.mode == "llm" else None
    return _heuristic_response_with_fallback(result, fallback_reason=fallback)


# --------------------------------------------------------------------------- #
# §9.12 CDA (user-selectable framework)
# --------------------------------------------------------------------------- #


class CDARequest(BaseModel):
    framework: str = Field("fairclough", description="fairclough | van_dijk | wodak | machin_mayr")


@router.post("/images/{img_id}/cda")
async def cda_route(
    img_id: str,
    body: CDARequest,
    request: Request,
    mode_params: LLMModeRequest = Depends(),
    session: AsyncSession = Depends(get_session),
) -> dict:
    img = await session.get(ImageModel, img_id)
    if not img:
        raise HTTPException(404, "Image not found")
    if body.framework not in CDA_FRAMEWORKS:
        raise HTTPException(400, f"Unknown CDA framework: {body.framework}. Supported: {list(CDA_FRAMEWORKS.keys())}")

    # Vision-LM mode: the framework_key includes the CDA sub-framework
    # (e.g. "cda_fairclough") so each sub-framework gets its own cache key.
    if mode_params.mode == "llm":
        llm_framework_key = f"cda_{body.framework}"
        llm_result = await _try_llm_discourse(
            request, img, llm_framework_key, mode_params, session,
        )
        if llm_result is not None:
            return llm_result

    colours, composition, ocr, caption = await _get_image_sub_analyses(img)
    result = analyse_cda(colours, composition, ocr, caption, framework=body.framework)  # type: ignore[arg-type]
    fallback = "LLM mode requested but unavailable — using heuristic." if mode_params.mode == "llm" else None
    return _heuristic_response_with_fallback(result, fallback_reason=fallback)


@router.get("/cda-frameworks")
async def list_cda_frameworks() -> dict:
    return {"frameworks": CDA_FRAMEWORKS}


# --------------------------------------------------------------------------- #
# §9.13 Persuasion
# --------------------------------------------------------------------------- #


@router.post("/images/{img_id}/persuasion")
async def persuasion_route(
    img_id: str,
    request: Request,
    mode_params: LLMModeRequest = Depends(),
    session: AsyncSession = Depends(get_session),
) -> dict:
    img = await session.get(ImageModel, img_id)
    if not img:
        raise HTTPException(404, "Image not found")

    llm_result = await _try_llm_discourse(
        request, img, "persuasion", mode_params, session,
    )
    if llm_result is not None:
        return llm_result

    _, _, ocr, caption = await _get_image_sub_analyses(img)
    result = analyse_persuasion(ocr, caption)
    fallback = "LLM mode requested but unavailable — using heuristic." if mode_params.mode == "llm" else None
    return _heuristic_response_with_fallback(result, fallback_reason=fallback)


# --------------------------------------------------------------------------- #
# §9.14 Framing
# --------------------------------------------------------------------------- #


@router.post("/images/{img_id}/framing")
async def framing_route(
    img_id: str,
    request: Request,
    mode_params: LLMModeRequest = Depends(),
    session: AsyncSession = Depends(get_session),
) -> dict:
    img = await session.get(ImageModel, img_id)
    if not img:
        raise HTTPException(404, "Image not found")

    llm_result = await _try_llm_discourse(
        request, img, "framing", mode_params, session,
    )
    if llm_result is not None:
        return llm_result

    _, _, ocr, caption = await _get_image_sub_analyses(img)
    result = analyse_framing(ocr, caption)
    fallback = "LLM mode requested but unavailable — using heuristic." if mode_params.mode == "llm" else None
    return _heuristic_response_with_fallback(result, fallback_reason=fallback)


# --------------------------------------------------------------------------- #
# §9.15 Narrative
# --------------------------------------------------------------------------- #


@router.post("/images/{img_id}/narrative")
async def narrative_route(
    img_id: str,
    request: Request,
    mode_params: LLMModeRequest = Depends(),
    session: AsyncSession = Depends(get_session),
) -> dict:
    img = await session.get(ImageModel, img_id)
    if not img:
        raise HTTPException(404, "Image not found")

    llm_result = await _try_llm_discourse(
        request, img, "narrative", mode_params, session,
    )
    if llm_result is not None:
        return llm_result

    _, _, ocr, caption = await _get_image_sub_analyses(img)
    result = analyse_narrative(ocr, caption)
    fallback = "LLM mode requested but unavailable — using heuristic." if mode_params.mode == "llm" else None
    return _heuristic_response_with_fallback(result, fallback_reason=fallback)


# --------------------------------------------------------------------------- #
# §9.16 Visual + Cross-modal Metaphor
# --------------------------------------------------------------------------- #


@router.post("/images/{img_id}/visual-metaphor")
async def visual_metaphor_route(
    img_id: str,
    request: Request,
    mode_params: LLMModeRequest = Depends(),
    session: AsyncSession = Depends(get_session),
) -> dict:
    img = await session.get(ImageModel, img_id)
    if not img:
        raise HTTPException(404, "Image not found")

    llm_result = await _try_llm_discourse(
        request, img, "visual_metaphor", mode_params, session,
    )
    if llm_result is not None:
        return llm_result

    colours, composition, ocr, caption = await _get_image_sub_analyses(img)
    result = analyse_visual_metaphor(colours, composition, ocr, caption)
    fallback = "LLM mode requested but unavailable — using heuristic." if mode_params.mode == "llm" else None
    return _heuristic_response_with_fallback(result, fallback_reason=fallback)


# --------------------------------------------------------------------------- #
# §9.17 Combined Emotion
# --------------------------------------------------------------------------- #


@router.post("/images/{img_id}/emotion")
async def emotion_route(
    img_id: str,
    request: Request,
    mode_params: LLMModeRequest = Depends(),
    session: AsyncSession = Depends(get_session),
) -> dict:
    img = await session.get(ImageModel, img_id)
    if not img:
        raise HTTPException(404, "Image not found")

    llm_result = await _try_llm_discourse(
        request, img, "emotion", mode_params, session,
    )
    if llm_result is not None:
        return llm_result

    colours, _, ocr, caption = await _get_image_sub_analyses(img)
    result = analyse_combined_emotion(colours, ocr, caption)
    fallback = "LLM mode requested but unavailable — using heuristic." if mode_params.mode == "llm" else None
    return _heuristic_response_with_fallback(result, fallback_reason=fallback)


# --------------------------------------------------------------------------- #
# §9.18 Cultural
# --------------------------------------------------------------------------- #


@router.post("/images/{img_id}/cultural")
async def cultural_route(
    img_id: str,
    request: Request,
    mode_params: LLMModeRequest = Depends(),
    session: AsyncSession = Depends(get_session),
) -> dict:
    img = await session.get(ImageModel, img_id)
    if not img:
        raise HTTPException(404, "Image not found")

    llm_result = await _try_llm_discourse(
        request, img, "cultural", mode_params, session,
    )
    if llm_result is not None:
        return llm_result

    colours, _, ocr, caption = await _get_image_sub_analyses(img)
    result = analyse_cultural(colours, ocr, caption)
    fallback = "LLM mode requested but unavailable — using heuristic." if mode_params.mode == "llm" else None
    return _heuristic_response_with_fallback(result, fallback_reason=fallback)


# --------------------------------------------------------------------------- #
# §9.4.3 Facial Analysis (opt-in, §18)
# --------------------------------------------------------------------------- #


@router.post("/images/{img_id}/facial-analysis")
async def facial_analysis_route(img_id: str, session: AsyncSession = Depends(get_session)) -> dict:
    """§9.4.3 Facial analysis — OFF by default (§18).

    To enable: set CORPUSMIND_FACIAL_ANALYSIS_ENABLED=1 or toggle in
    Settings → Ethics → Facial Analysis. This module NEVER performs
    identity recognition or re-identification of real individuals.
    """
    img = await session.get(ImageModel, img_id)
    if not img:
        raise HTTPException(404, "Image not found")
    if not img.storage_path or not Path(img.storage_path).exists():
        raise HTTPException(400, "Image file not found on disk. Re-ingest.")

    try:
        pil_img = load_image(Path(img.storage_path).read_bytes())
        result = analyse_faces(pil_img)
        return {
            "image_id": img.id,
            "face_count": result.face_count,
            "model": result.model,
            "consent_verified": result.consent_verified,
            "ethics_notice": result.ethics_notice,
            "faces": [asdict(f) for f in result.faces],
        }
    except FacialAnalysisDisabledError as e:
        raise HTTPException(403, str(e)) from e
    except Exception as e:
        log.error("facial_analysis_failed", image_id=img_id, error=str(e))
        raise HTTPException(500, f"Facial analysis failed: {e}") from e


@router.get("/facial-analysis/status")
async def facial_analysis_status() -> dict:
    """Check whether facial analysis is enabled (§18 transparency)."""
    import os
    from vision.facial import is_facial_analysis_enabled
    return {
        "enabled": is_facial_analysis_enabled(),
        "env_override": os.environ.get("CORPUSMIND_FACIAL_ANALYSIS_ENABLED", "0") == "1",
        "notice": (
            "Facial analysis is OFF by default (§18 Ethical Guardrails). "
            "When enabled, it performs NO identity recognition or re-identification "
            "of real individuals. Outputs are descriptive visual cues only."
        ),
    }


class FacialOptInBody(BaseModel):
    enabled: bool


@router.post("/facial-analysis/enabled")
async def set_facial_analysis_enabled_route(body: FacialOptInBody) -> dict:
    """v1.0.9 — persist the user's §18 opt-in decision (Settings toggle).

    The decision is stored as a marker file in the data directory (not env),
    so it survives restarts while staying with the user's data. The module
    itself NEVER performs identity recognition — see vision/facial.py."""
    from vision.facial import is_facial_analysis_enabled, set_facial_analysis_enabled
    set_facial_analysis_enabled(body.enabled)
    return {"enabled": is_facial_analysis_enabled()}
