"""Phase 5 API routes — multimodal discourse analyses (§9.11–9.18) + facial (§9.4.3)."""
from __future__ import annotations

from dataclasses import asdict
from pathlib import Path

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field
from sqlalchemy.ext.asyncio import AsyncSession

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
# §9.11 Social Semiotic
# --------------------------------------------------------------------------- #


@router.post("/images/{img_id}/social-semiotic")
async def social_semiotic_route(img_id: str, session: AsyncSession = Depends(get_session)) -> dict:
    img = await session.get(ImageModel, img_id)
    if not img:
        raise HTTPException(404, "Image not found")
    colours, composition, ocr, caption = await _get_image_sub_analyses(img)
    result = analyse_social_semiotic(colours, composition, ocr, caption)
    return asdict(result)


# --------------------------------------------------------------------------- #
# §9.12 CDA (user-selectable framework)
# --------------------------------------------------------------------------- #


class CDARequest(BaseModel):
    framework: str = Field("fairclough", description="fairclough | van_dijk | wodak | machin_mayr")


@router.post("/images/{img_id}/cda")
async def cda_route(img_id: str, body: CDARequest, session: AsyncSession = Depends(get_session)) -> dict:
    img = await session.get(ImageModel, img_id)
    if not img:
        raise HTTPException(404, "Image not found")
    if body.framework not in CDA_FRAMEWORKS:
        raise HTTPException(400, f"Unknown CDA framework: {body.framework}. Supported: {list(CDA_FRAMEWORKS.keys())}")
    colours, composition, ocr, caption = await _get_image_sub_analyses(img)
    result = analyse_cda(colours, composition, ocr, caption, framework=body.framework)  # type: ignore[arg-type]
    return asdict(result)


@router.get("/cda-frameworks")
async def list_cda_frameworks() -> dict:
    return {"frameworks": CDA_FRAMEWORKS}


# --------------------------------------------------------------------------- #
# §9.13 Persuasion
# --------------------------------------------------------------------------- #


@router.post("/images/{img_id}/persuasion")
async def persuasion_route(img_id: str, session: AsyncSession = Depends(get_session)) -> dict:
    img = await session.get(ImageModel, img_id)
    if not img:
        raise HTTPException(404, "Image not found")
    _, _, ocr, caption = await _get_image_sub_analyses(img)
    result = analyse_persuasion(ocr, caption)
    return asdict(result)


# --------------------------------------------------------------------------- #
# §9.14 Framing
# --------------------------------------------------------------------------- #


@router.post("/images/{img_id}/framing")
async def framing_route(img_id: str, session: AsyncSession = Depends(get_session)) -> dict:
    img = await session.get(ImageModel, img_id)
    if not img:
        raise HTTPException(404, "Image not found")
    _, _, ocr, caption = await _get_image_sub_analyses(img)
    result = analyse_framing(ocr, caption)
    return asdict(result)


# --------------------------------------------------------------------------- #
# §9.15 Narrative
# --------------------------------------------------------------------------- #


@router.post("/images/{img_id}/narrative")
async def narrative_route(img_id: str, session: AsyncSession = Depends(get_session)) -> dict:
    img = await session.get(ImageModel, img_id)
    if not img:
        raise HTTPException(404, "Image not found")
    _, _, ocr, caption = await _get_image_sub_analyses(img)
    result = analyse_narrative(ocr, caption)
    return asdict(result)


# --------------------------------------------------------------------------- #
# §9.16 Visual + Cross-modal Metaphor
# --------------------------------------------------------------------------- #


@router.post("/images/{img_id}/visual-metaphor")
async def visual_metaphor_route(img_id: str, session: AsyncSession = Depends(get_session)) -> dict:
    img = await session.get(ImageModel, img_id)
    if not img:
        raise HTTPException(404, "Image not found")
    colours, composition, ocr, caption = await _get_image_sub_analyses(img)
    result = analyse_visual_metaphor(colours, composition, ocr, caption)
    return asdict(result)


# --------------------------------------------------------------------------- #
# §9.17 Combined Emotion
# --------------------------------------------------------------------------- #


@router.post("/images/{img_id}/emotion")
async def emotion_route(img_id: str, session: AsyncSession = Depends(get_session)) -> dict:
    img = await session.get(ImageModel, img_id)
    if not img:
        raise HTTPException(404, "Image not found")
    colours, _, ocr, caption = await _get_image_sub_analyses(img)
    result = analyse_combined_emotion(colours, ocr, caption)
    return asdict(result)


# --------------------------------------------------------------------------- #
# §9.18 Cultural
# --------------------------------------------------------------------------- #


@router.post("/images/{img_id}/cultural")
async def cultural_route(img_id: str, session: AsyncSession = Depends(get_session)) -> dict:
    img = await session.get(ImageModel, img_id)
    if not img:
        raise HTTPException(404, "Image not found")
    colours, _, ocr, caption = await _get_image_sub_analyses(img)
    result = analyse_cultural(colours, ocr, caption)
    return asdict(result)


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
    from vision.facial import is_facial_analysis_enabled
    return {
        "enabled": is_facial_analysis_enabled(),
        "notice": (
            "Facial analysis is OFF by default (§18 Ethical Guardrails). "
            "When enabled, it performs NO identity recognition or re-identification "
            "of real individuals. Outputs are descriptive visual cues only."
        ),
    }
