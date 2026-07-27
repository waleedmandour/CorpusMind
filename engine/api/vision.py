"""Phase 4 Vision API routes (§9.1–9.10)."""
from __future__ import annotations

import hashlib
import os
from dataclasses import asdict
from datetime import UTC, datetime
from pathlib import Path

from fastapi import APIRouter, Depends, File, Form, HTTPException, Request, UploadFile
from pydantic import BaseModel, Field
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from ai.providers import Message, ModelProviderError
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
from vision.consent_gate import filter_describe_response
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


# --------------------------------------------------------------------------- #
# §9.x Vision-LM image description (CorpusMind Lens build step 3)
#
# This is the first route that actually uses the Message.images extension
# from build step 1 to send image bytes to a local vision-LM. Every
# discourse-framework route in api/phase5.py is purely heuristic — they
# look at colour statistics, composition geometry, and OCR text, never at
# what the image actually depicts. This route closes that gap: it sends
# the real image bytes to a vision-LM (default: Ollama with moondream or
# similar) and returns the model's grounded description.
#
# Provenance: the response includes model, provider, prompt, prompt_hash,
# and timestamp so a researcher can reproduce a description in a
# manuscript (§4 Principle 8 — Reproducibility).
#
# OCR disagreement: if the vision-LM's text-reading disagrees with the
# Tesseract OCR pass already cached in img.analysis["ocr"], both are
# returned — the cached OCR is NOT silently overwritten. The user
# decides which to trust.
#
# Caching: results are cached in img.analysis["vision_llm"][f"{model}:
# {prompt_hash}"] using full reassignment (img.analysis = {**img.analysis,
# ...}), never in-place mutation — that JSON column isn't change-tracked
# for in-place mutation without MutableDict.as_mutable(), and this
# project has shipped that exact bug twice already (delete_document,
# recompile_corpus in api/corpora.py). Full reassignment is the safe
# pattern that works regardless.
#
# Consent gate (§3.4): NOT enforced here. A vision-LM asked to describe a
# photo will volunteer age/emotion/gender-presentation commentary about
# people in it whether or not anyone asked. Build step 5 wires the
# vision/facial.py consent gate across all person-descriptive vision-LM
# output. For now, the route returns whatever the model says — step 5
# will add the post-processing filter.
# --------------------------------------------------------------------------- #


class DescribeRequest(BaseModel):
    prompt: str = Field(
        default="Describe this image.",
        description=(
            "The prompt to send to the vision-LM along with the image. "
            "Keep it short — small vision models (moondream, etc.) can "
            "return empty output when the prompt is too long or complex. "
            "If you need text transcription, use a dedicated prompt like "
            "'Transcribe all text visible in this image.'"
        ),
    )
    model: str | None = Field(
        default=None,
        description="Model name. If None, uses the provider's default model.",
    )
    provider: str = Field(
        default="ollama",
        description="Provider name: ollama | lmstudio | cloud",
    )
    refresh: bool = Field(
        default=False,
        description=(
            "If True, re-run even if a cached result exists for this "
            "prompt+model. If False (default), return the cached result "
            "without calling the model again."
        ),
    )


def _prompt_hash(prompt: str) -> str:
    """SHA-256 of the prompt, truncated to 16 hex chars. Used as the
    cache key suffix so re-running with a different prompt doesn't
    overwrite a previous cached result, and so the user can see which
    prompt produced which cached description."""
    return hashlib.sha256(prompt.encode("utf-8")).hexdigest()[:16]


def _detect_ocr_disagreement(vision_text: str, cached_ocr: str) -> bool:
    """Heuristic: does the vision-LM's text content materially disagree
    with the cached Tesseract OCR?

    We don't do fuzzy string matching — that's a rabbit hole. The rule
    is: if both are non-empty AND the vision-LM's text contains
    substantial text content (>20 chars) that doesn't appear in the
    cached OCR at all, flag it. The user looks at both side by side
    and decides which to trust.

    If either is empty, no disagreement is possible — return False.
    """
    if not vision_text or not cached_ocr:
        return False
    # Normalize both to lowercase + stripped for comparison.
    v = vision_text.lower().strip()
    o = cached_ocr.lower().strip()
    if len(v) < 20:
        return False  # too short to be a meaningful transcription
    # If the vision text appears verbatim in the OCR (or vice versa),
    # they agree.
    if v in o or o in v:
        return False
    # If they share >50% of words, consider them in agreement (Tesseract
    # and the vision-LM may phrase the same text slightly differently).
    v_words = set(v.split())
    o_words = set(o.split())
    if not v_words:
        return False
    overlap = len(v_words & o_words) / len(v_words)
    return overlap < 0.5


@router.post("/images/{img_id}/describe")
async def describe_image_route(
    img_id: str,
    request: Request,
    body: DescribeRequest | None = None,
    session: AsyncSession = Depends(get_session),
) -> dict:
    """Send the image to a vision-LM and return a grounded description.

    Sends the image bytes + the prompt to the configured vision-LM
    provider (default: ollama). Returns the model's description along
    with provenance metadata (model, provider, prompt, prompt_hash,
    timestamp) so the result is reproducible.

    If the vision-LM's text-reading disagrees with the cached Tesseract
    OCR pass, both are returned — the cached OCR is NOT silently
    overwritten. The user decides which to trust.

    Results are cached in img.analysis["vision_llm"] keyed on
    f"{model}:{prompt_hash}". Use refresh=True to force a re-run.

    Raises:
      404: image not found
      400: image file missing from disk (re-ingest required)
      503: no vision-LM provider available or healthy
      500: provider call failed
    """
    body = body or DescribeRequest()
    img = await session.get(ImageModel, img_id)
    if not img:
        raise HTTPException(404, "Image not found")
    if not img.storage_path or not Path(img.storage_path).exists():
        raise HTTPException(400, "Image file not found on disk. Re-ingest.")

    # --- Cache lookup ----------------------------------------------------
    cache_key = f"{body.model or 'default'}:{_prompt_hash(body.prompt)}"
    cached_vlm = (img.analysis or {}).get("vision_llm", {}).get(cache_key)
    if cached_vlm and not body.refresh:
        # Cache hit — return without calling the model.
        cached_ocr = (img.analysis or {}).get("ocr", {}).get("text", "")
        # Step 5: filter person-descriptive content through the consent
        # gate BEFORE returning. The gate is enforced at response-shaping
        # time, not at prompt time — see vision/consent_gate.py.
        gate_result = filter_describe_response(cached_vlm["description"])
        return {
            "image_id": img.id,
            "description": gate_result["description"],
            "model": cached_vlm["model"],
            "provider": cached_vlm["provider"],
            "prompt": cached_vlm["prompt"],
            "prompt_hash": cached_vlm["prompt_hash"],
            "timestamp": cached_vlm["timestamp"],
            "cached": True,
            "ocr_disagreement": _detect_ocr_disagreement(
                gate_result["description"], cached_ocr
            ),
            "cached_ocr": cached_ocr,
            "person_descriptive_redacted": gate_result["person_descriptive_redacted"],
        }

    # --- Provider lookup + health check ---------------------------------
    try:
        provider = request.app.state.providers.get(body.provider)
    except Exception as e:
        raise HTTPException(
            status_code=400,
            detail=f"Provider error: {e}",
        ) from e

    if provider is None:
        raise HTTPException(
            status_code=400,
            detail=(
                f"AI provider '{body.provider}' is not available. "
                f"Make sure Ollama or LM Studio is running, or configure "
                f"a cloud provider in Settings."
            ),
        )

    # Health check before the call so we get a clear 503 instead of a
    # confusing timeout. Same pattern as api/ai.py::chat().
    try:
        is_healthy = await provider.health()
    except Exception:
        is_healthy = False
    if not is_healthy:
        provider_name = getattr(provider, "name", body.provider)
        if provider_name == "ollama":
            raise HTTPException(
                status_code=503,
                detail=(
                    "Ollama is not running or no vision model is loaded. "
                    "Start Ollama and pull a vision model (e.g. "
                    "`ollama pull moondream` or `ollama pull llama3.2-vision`)."
                ),
            )
        elif provider_name == "lmstudio":
            raise HTTPException(
                status_code=503,
                detail=(
                    "LM Studio is not running or no vision model is loaded. "
                    "Start LM Studio, load a vision model, and enable the "
                    "local server (Developer > Start Local Server)."
                ),
            )
        else:
            raise HTTPException(
                status_code=503,
                detail=f"The {provider_name} provider is not available.",
            )

    # --- Build the prompt with context ----------------------------------
    # Send the image bytes + the user's prompt. If the image has a cached
    # OCR text or a user caption, include those as context so the model
    # can corroborate or correct them — but never overwrite the cached
    # OCR silently. The user sees both side by side in the response.
    cached_ocr = (img.analysis or {}).get("ocr", {}).get("text", "")
    caption = img.caption or ""

    context_parts: list[str] = []
    if caption:
        context_parts.append(
            f"The image has the following user-supplied caption: {caption!r}."
        )
    if cached_ocr:
        context_parts.append(
            f"A separate OCR pass (Tesseract) previously extracted this "
            f"text from the image: {cached_ocr!r}. If your reading of the "
            f"text differs, note the discrepancy in your description."
        )
    full_prompt = body.prompt
    if context_parts:
        full_prompt = body.prompt + "\n\nContext:\n" + "\n".join(context_parts)

    # --- Read image bytes + call the provider ---------------------------
    image_bytes = Path(img.storage_path).read_bytes()
    messages = [
        Message(
            role="user",
            content=full_prompt,
            images=(image_bytes,),
        ),
    ]

    model_name = body.model or getattr(provider, "default_model", None)
    if not model_name:
        # Fall back to the first available model from the provider.
        try:
            available = await provider.list_models()
            if available:
                model_name = available[0]
                log.info("vlm_auto_selected_model", model=model_name, provider=body.provider)
        except Exception as e:
            log.warning("vlm_auto_select_failed", error=str(e))

    if not model_name:
        raise HTTPException(
            status_code=400,
            detail=(
                f"No model specified and provider '{body.provider}' has no "
                f"default model. Specify a model name in the request body."
            ),
        )

    log.info(
        "vlm_describe_request",
        image_id=img.id,
        provider=body.provider,
        model=model_name,
        prompt_hash=_prompt_hash(body.prompt),
        image_bytes=len(image_bytes),
        has_ocr=bool(cached_ocr),
        has_caption=bool(caption),
        refresh=body.refresh,
        cache_hit=False,
    )

    try:
        response = await provider.chat(
            messages,
            model=model_name,
            temperature=0.1,  # low temperature for descriptive accuracy
            timeout=120.0,    # vision models are slower than text
        )
    except ModelProviderError as e:
        log.warning("vlm_describe_failed", image_id=img.id, error=str(e))
        raise HTTPException(
            status_code=500,
            detail=f"Vision-LM call failed: {e}",
        ) from e

    description = response.content.strip()
    if not description:
        raise HTTPException(
            status_code=500,
            detail=(
                f"Vision-LM returned empty content. Model: {model_name}. "
                f"This can happen with small models if the prompt doesn't "
                f"match their expected template — try a different prompt "
                f"or a larger model."
            ),
        )

    timestamp = datetime.now(UTC).isoformat()
    prompt_hash = _prompt_hash(body.prompt)

    # --- Cache the result (full reassignment per §2.4) ------------------
    # CRITICAL: img.analysis is a plain JSON column, not wrapped in
    # MutableDict.as_mutable(). In-place mutation (img.analysis["vision_llm"]
    # = ... or img.analysis.update(...)) will NOT be detected by SQLAlchemy
    # and will be silently lost on commit. This project has shipped that
    # exact bug twice already. Always reassign the full dict.
    new_analysis = dict(img.analysis or {})
    vlm_cache = dict(new_analysis.get("vision_llm", {}))
    vlm_cache[cache_key] = {
        "description": description,
        "model": response.model or model_name,
        "provider": body.provider,
        "prompt": body.prompt,
        "prompt_hash": prompt_hash,
        "timestamp": timestamp,
    }
    new_analysis["vision_llm"] = vlm_cache
    img.analysis = new_analysis  # full reassignment — triggers SQLAlchemy change detection
    await session.commit()

    log.info(
        "vlm_describe_success",
        image_id=img.id,
        model=response.model or model_name,
        description_len=len(description),
        cached=False,
    )

    # Step 5: filter person-descriptive content through the consent gate
    # BEFORE returning. The gate is enforced at response-shaping time,
    # not at prompt time — see vision/consent_gate.py.
    gate_result = filter_describe_response(description)

    return {
        "image_id": img.id,
        "description": gate_result["description"],
        "model": response.model or model_name,
        "provider": body.provider,
        "prompt": body.prompt,
        "prompt_hash": prompt_hash,
        "timestamp": timestamp,
        "cached": False,
        "ocr_disagreement": _detect_ocr_disagreement(gate_result["description"], cached_ocr),
        "cached_ocr": cached_ocr,
        "person_descriptive_redacted": gate_result["person_descriptive_redacted"],
    }
