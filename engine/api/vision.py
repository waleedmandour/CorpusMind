"""Phase 4 Vision API routes (§9.1–9.10)."""
from __future__ import annotations

import os
from dataclasses import asdict
from pathlib import Path

from fastapi import APIRouter, Depends, File, Form, HTTPException, UploadFile
from pydantic import BaseModel, Field
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.logging import get_logger
from app.settings import get_settings
from multimodal.alignment import (
    align_image_text,
    detect_cross_modal_relations,
)
from multimodal.visual_grammar import analyse_visual_grammar
from storage.models import Corpus, ImageSet
from storage.models import Image as ImageModel
from storage.session import get_session
from vision.pipeline import (
    analyse_image,
    detect_image_format,
    get_image_info,
    load_image,
)

log = get_logger(__name__)
router = APIRouter()


# --------------------------------------------------------------------------- #
# §9.1 Image set management
# --------------------------------------------------------------------------- #


class ImageSetCreate(BaseModel):
    name: str = Field(..., min_length=1, max_length=255)


class ImageSetOut(BaseModel):
    id: str
    corpus_id: str
    name: str
    image_count: int = 0
    created_at: str


@router.post("/corpora/{cid}/image-sets", response_model=ImageSetOut)
async def create_image_set(cid: str, body: ImageSetCreate,
                            session: AsyncSession = Depends(get_session)) -> ImageSetOut:
    if not await session.get(Corpus, cid):
        raise HTTPException(404, "Corpus not found")
    iset = ImageSet(corpus_id=cid, name=body.name)
    session.add(iset)
    await session.flush()
    return ImageSetOut(id=iset.id, corpus_id=iset.corpus_id, name=iset.name,
                        image_count=0, created_at=iset.created_at.isoformat())


@router.get("/corpora/{cid}/image-sets", response_model=list[ImageSetOut])
async def list_image_sets(cid: str, session: AsyncSession = Depends(get_session)) -> list[ImageSetOut]:
    from sqlalchemy import func
    stmt = select(ImageSet).where(ImageSet.corpus_id == cid).order_by(ImageSet.created_at.desc())
    sets = (await session.execute(stmt)).scalars().all()
    out = []
    for s in sets:
        n = await session.scalar(select(func.count(ImageModel.id)).where(ImageModel.image_set_id == s.id)) or 0
        out.append(ImageSetOut(id=s.id, corpus_id=s.corpus_id, name=s.name,
                                image_count=n, created_at=s.created_at.isoformat()))
    return out


# --------------------------------------------------------------------------- #
# §9.2 Image upload + ingestion
# --------------------------------------------------------------------------- #


class ImageOut(BaseModel):
    id: str
    image_set_id: str
    filename: str
    format: str
    width: int
    height: int
    size_bytes: int
    caption: str
    created_at: str


def _image_storage_dir() -> Path:
    settings = get_settings()
    p = Path(settings.data_dir) / "images"
    p.mkdir(parents=True, exist_ok=True)
    return p


@router.post("/image-sets/{iset_id}/images", response_model=list[ImageOut])
async def upload_images(
    iset_id: str,
    files: list[UploadFile] = File(...),
    captions: str | None = Form(None),
    session: AsyncSession = Depends(get_session),
) -> list[ImageOut]:
    """Upload one or more images into an image set. Each is parsed, analysed
    (colour, composition, OCR), and the analysis is cached in the DB."""
    iset = await session.get(ImageSet, iset_id)
    if not iset:
        raise HTTPException(404, "Image set not found")

    caption_list = captions.split("\n") if captions else []
    storage_dir = _image_storage_dir()
    out: list[ImageOut] = []

    for i, f in enumerate(files):
        raw = await f.read()
        if not raw:
            continue
        try:
            fmt = detect_image_format(f.filename or "image.jpg")
            info = get_image_info(raw, f.filename or "image.jpg")
            # Run full analysis
            analysis = analyse_image(raw, f.filename or "image.jpg")
            # Persist image bytes to disk
            img_id = ImageModel.id.default.arg.__wrapped__() if hasattr(ImageModel.id.default, 'arg') else None
            import uuid
            img_id = uuid.uuid4().hex[:16]
            storage_path = storage_dir / f"{img_id}.{fmt}"
            storage_path.write_bytes(raw)
            caption = caption_list[i] if i < len(caption_list) else ""

            img = ImageModel(
                id=img_id,
                image_set_id=iset_id,
                filename=f.filename or "image.jpg",
                format=fmt,
                width=info.width,
                height=info.height,
                size_bytes=info.size_bytes,
                storage_path=str(storage_path),
                analysis={
                    "ocr": asdict(analysis.ocr),
                    "colours": asdict(analysis.colours),
                    "composition": asdict(analysis.composition),
                },
                caption=caption,
            )
            session.add(img)
            await session.flush()
            out.append(ImageOut(
                id=img.id, image_set_id=img.image_set_id, filename=img.filename,
                format=img.format, width=img.width, height=img.height,
                size_bytes=img.size_bytes, caption=img.caption,
                created_at=img.created_at.isoformat(),
            ))
        except Exception as e:
            log.error("image_ingest_failed", filename=f.filename, error=str(e))
            raise HTTPException(400, f"Failed to ingest '{f.filename}': {e}") from e
    return out


@router.get("/image-sets/{iset_id}/images", response_model=list[ImageOut])
async def list_images(iset_id: str, session: AsyncSession = Depends(get_session)) -> list[ImageOut]:
    stmt = select(ImageModel).where(ImageModel.image_set_id == iset_id).order_by(ImageModel.created_at.desc())
    imgs = (await session.execute(stmt)).scalars().all()
    return [ImageOut(
        id=i.id, image_set_id=i.image_set_id, filename=i.filename,
        format=i.format, width=i.width, height=i.height,
        size_bytes=i.size_bytes, caption=i.caption,
        created_at=i.created_at.isoformat(),
    ) for i in imgs]


# --------------------------------------------------------------------------- #
# §9.4 Image analysis (retrieve cached)
# --------------------------------------------------------------------------- #


@router.get("/images/{img_id}/analysis")
async def get_image_analysis(img_id: str, session: AsyncSession = Depends(get_session)) -> dict:
    """Retrieve the cached image analysis (colour, composition, OCR)."""
    img = await session.get(ImageModel, img_id)
    if not img:
        raise HTTPException(404, "Image not found")
    return {
        "image_id": img.id,
        "filename": img.filename,
        "dimensions": f"{img.width}x{img.height}",
        "analysis": img.analysis,
        "caption": img.caption,
    }


# --------------------------------------------------------------------------- #
# §9.10 Visual Grammar analysis
# --------------------------------------------------------------------------- #


@router.post("/images/{img_id}/visual-grammar")
async def visual_grammar_route(img_id: str, session: AsyncSession = Depends(get_session)) -> dict:
    """Analyse an image against Kress & van Leeuwen's Visual Grammar (§9.10).

    Every claim is framework-attributed and phrased as a hypothesis per §4
    Principle 5: 'Under a Kress & van Leeuwen reading, X may indicate Y.'
    """
    img = await session.get(ImageModel, img_id)
    if not img:
        raise HTTPException(404, "Image not found")
    if not img.analysis:
        raise HTTPException(400, "Image has no cached analysis. Re-ingest first.")

    # Reconstruct the sub-analyses from the cached data
    from vision.pipeline import ColourAnalysis, CompositionAnalysis, ImageInfo, OCRResult
    info = ImageInfo(width=img.width, height=img.height, format=img.format, mode="RGB", size_bytes=img.size_bytes)
    ocr_data = img.analysis.get("ocr", {})
    ocr = OCRResult(
        text=ocr_data.get("text", ""),
        confidence=ocr_data.get("confidence", 0.0),
        word_count=ocr_data.get("word_count", 0),
        engine=ocr_data.get("engine", "none"),
        language=ocr_data.get("language", "auto"),
    )
    colours_data = img.analysis.get("colours", {})
    colours = ColourAnalysis(
        dominant_colours=colours_data.get("dominant_colours", []),
        warm_cold_balance=colours_data.get("warm_cold_balance", 0.0),
        brightness=colours_data.get("brightness", 0.0),
        contrast=colours_data.get("contrast", 0.0),
        saturation=colours_data.get("saturation", 0.0),
        colour_symbolism_notes=colours_data.get("colour_symbolism_notes", []),
    )
    comp_data = img.analysis.get("composition", {})
    composition = CompositionAnalysis(
        information_value=comp_data.get("information_value", {}),
        rule_of_thirds_intersections=comp_data.get("rule_of_thirds_intersections", []),
        salience_centre=tuple(comp_data.get("salience_centre", [0.5, 0.5])),
        visual_balance=comp_data.get("visual_balance", 0.0),
        framing_balance=comp_data.get("framing_balance", 0.0),
        vectors=comp_data.get("vectors", []),
    )

    vg = analyse_visual_grammar(info, ocr, colours, composition)
    return {
        "image_id": img.id,
        "framework": vg.framework,
        "claims": [asdict(c) for c in vg.claims],
        "scores": {
            "representational": vg.representational_score,
            "interactive": vg.interactive_score,
            "compositional": vg.compositional_score,
        },
    }


# --------------------------------------------------------------------------- #
# §9.8 Image-text alignment (flagship)
# --------------------------------------------------------------------------- #


class AlignmentRequest(BaseModel):
    text: str = Field(..., description="Co-occurring text (caption, article body, etc.)")


@router.post("/images/{img_id}/align")
async def align_route(img_id: str, body: AlignmentRequest,
                       session: AsyncSession = Depends(get_session)) -> dict:
    """Align image regions with text spans (§9.8) — the flagship feature.

    Returns each alignment with a confidence score + the exact spans/regions
    linked. Every alignment is inspectable, not a black box.
    """
    img = await session.get(ImageModel, img_id)
    if not img:
        raise HTTPException(404, "Image not found")
    if not img.storage_path or not os.path.exists(img.storage_path):
        raise HTTPException(400, "Image file not found on disk. Re-ingest.")

    pil_img = load_image(Path(img.storage_path).read_bytes())
    result = align_image_text(pil_img, body.text)
    cross_modal = detect_cross_modal_relations(result)

    return {
        "image_id": img.id,
        "text": body.text,
        "method": result.method,
        "note": result.note,
        "regions": [asdict(r) for r in result.regions],
        "spans": [asdict(s) for s in result.spans],
        "alignments": [asdict(a) for a in result.alignments],
        "cross_modal_relations": [asdict(r) for r in cross_modal],
    }
