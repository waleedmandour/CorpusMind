"""Phase 4 Vision API routes (§9.1–9.10)."""
from __future__ import annotations

import asyncio
import hashlib
import os
import re
from dataclasses import asdict
from datetime import UTC, datetime
from pathlib import Path
from typing import Literal

from fastapi import APIRouter, Depends, File, Form, HTTPException, Request, Response, UploadFile
from fastapi.responses import StreamingResponse
from pydantic import BaseModel, Field
from sqlalchemy import delete as sa_delete
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from ai.providers import (
    Message,
    ModelProviderError,
    check_vision_capability,
    resolve_vision_model,
)
from api.export import _make_response, _serialize
from app.logging import get_logger
from app.settings import get_settings
from multimodal.alignment import (
    align_image_text,
    detect_cross_modal_relations,
)
from multimodal.alignment_llm import run_llm_alignment
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
    read_image_bytes,
    sniff_image_format,
)

log = get_logger(__name__)
router = APIRouter()

# v1.2.0 upload hardening: files were previously read whole into RAM with no
# size cap and extension-only format checks. 25 MB comfortably covers any
# scanned page or photo while preventing accidental/abusive memory blowups.
MAX_IMAGE_BYTES = 25 * 1024 * 1024
MAX_FILES_PER_UPLOAD = 50


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
    (colour, composition, OCR), and the analysis is cached in the DB.

    v1.2.0 hardening: per-file 25 MB cap (413), max 50 files per request,
    and magic-byte sniffing — a text file named .png is rejected with a
    clear 400 instead of crashing deep inside Pillow.
    """
    iset = await session.get(ImageSet, iset_id)
    if not iset:
        raise HTTPException(404, "Image set not found")

    if len(files) > MAX_FILES_PER_UPLOAD:
        raise HTTPException(
            400,
            f"Too many files in one upload ({len(files)}). Maximum is {MAX_FILES_PER_UPLOAD} — split the batch.",
        )

    caption_list = captions.split("\n") if captions else []
    storage_dir = _image_storage_dir()
    out: list[ImageOut] = []

    for i, f in enumerate(files):
        raw = await f.read()
        if not raw:
            continue
        if len(raw) > MAX_IMAGE_BYTES:
            raise HTTPException(
                413,
                f"'{f.filename}' is {len(raw) / (1024 * 1024):.1f} MB — the per-image limit is "
                f"{MAX_IMAGE_BYTES / (1024 * 1024):.0f} MB. Downscale or recompress the image and retry.",
            )
        try:
            fmt = detect_image_format(f.filename or "image.jpg")
            sniffed = sniff_image_format(raw)
            if sniffed is None:
                raise HTTPException(
                    400,
                    f"'{f.filename}' does not look like a real image (magic-byte check failed). "
                    f"Re-export it as PNG or JPEG and retry.",
                )
            if sniffed != fmt and not {fmt, sniffed} <= {"jpg", "jpeg", "tif", "tiff"}:
                raise HTTPException(
                    400,
                    f"'{f.filename}' is named .{fmt} but its content is {sniffed.upper()}. "
                    f"Rename the file to match its real format.",
                )
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


@router.get("/images/{img_id}/thumbnail")
async def get_image_thumbnail(img_id: str, session: AsyncSession = Depends(get_session)) -> Response:
    """Serve a downscaled JPEG preview (max 320px) of the stored image.

    Issue 19 fix: the Vision Suite previously had no way to SEE the image
    being analysed — the grid rendered a placeholder card. This route keeps
    the "engine doesn't serve raw files" boundary mostly intact: it returns a
    downscaled derivative, not the original bytes, and honours the at-rest
    encryption wrapper (images are encrypted when CORPUSMIND_ENCRYPTION_KEY
    is set). Requires authentication when the shared-token mode is active,
    like every other /api route.
    """
    from io import BytesIO as _BytesIO

    from PIL import Image as _PILImage

    img = await session.get(ImageModel, img_id)
    if not img:
        raise HTTPException(404, "Image not found")
    if not img.storage_path or not Path(img.storage_path).exists():
        raise HTTPException(400, "Image file not found on disk. Re-ingest.")

    # read_image_bytes is decrypt-aware (v1.2.0: single shared helper for
    # every image-bytes read in the vision subsystem).
    raw = read_image_bytes(img.storage_path)

    pil = _PILImage.open(_BytesIO(raw))
    pil.thumbnail((320, 320))
    buf = _BytesIO()
    pil.convert("RGB").save(buf, "JPEG", quality=80)
    return Response(content=buf.getvalue(), media_type="image/jpeg")


@router.get("/images/{img_id}/analysis")
async def get_image_analysis(img_id: str, session: AsyncSession = Depends(get_session)) -> dict:
    """Retrieve the cached image analysis (colour, composition, OCR)."""
    img = await session.get(ImageModel, img_id)
    if not img:
        raise HTTPException(404, "Image not found")

    analysis = img.analysis
    # Issue 6 fix: /describe stores the RAW model output in
    # analysis["vision_llm"][cache_key]["description"] and filters only its
    # own response. This read endpoint previously returned img.analysis
    # verbatim, serving the unfiltered person-descriptive text even with the
    # consent gate CLOSED — bypassing the §18 guardrails. Apply the same
    # response-shaping filter here (and to cached discourse claims below).
    if analysis and isinstance(analysis, dict):
        import copy as _copy

        from vision.consent_gate import filter_describe_response, filter_discourse_claims

        analysis = _copy.deepcopy(analysis)
        vlm_cache = analysis.get("vision_llm")
        if isinstance(vlm_cache, dict):
            for cache_key, cached in vlm_cache.items():
                if isinstance(cached, dict) and cached.get("description"):
                    vlm_cache[cache_key]["description"] = filter_describe_response(
                        cached["description"]
                    )["description"]
        discourse_cache = analysis.get("vision_llm_discourse")
        if isinstance(discourse_cache, dict):
            for cache_key, cached in discourse_cache.items():
                if isinstance(cached, dict) and isinstance(cached.get("claims"), list):
                    filtered = filter_discourse_claims(cached["claims"])
                    discourse_cache[cache_key]["claims"] = filtered["claims"]

    return {
        "image_id": img.id,
        "filename": img.filename,
        "dimensions": f"{img.width}x{img.height}",
        "analysis": analysis,
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


class AlignModeParams(BaseModel):
    """Query params for the /align route's mode selection (step 6).

    mode=heuristic (default): existing colour/positional heuristic.
    mode=llm: send the image + text to a vision-LM for alignment.
    Falls back to heuristic if no provider is available.
    """
    mode: Literal["heuristic", "llm"] = Field(
        default="heuristic",
        description="heuristic (default) or llm (vision-LM alignment).",
    )
    model: str | None = Field(default=None, description="Model name for LLM mode.")
    provider: str = Field(default="ollama", description="Provider for LLM mode.")


@router.post("/images/{img_id}/align")
async def align_route(
    img_id: str,
    body: AlignmentRequest,
    request: Request,
    mode_params: AlignModeParams = Depends(),
    session: AsyncSession = Depends(get_session),
) -> dict:
    """Align image regions with text spans (§9.8) — the flagship feature.

    Returns each alignment with a confidence score + the exact spans/regions
    linked. Every alignment is inspectable, not a black box.

    ?mode=heuristic (default): colour-term + positional heuristic.
    ?mode=llm: vision-LM looks at the image + text to identify
    correspondences. Falls back to heuristic if no provider available.
    """
    img = await session.get(ImageModel, img_id)
    if not img:
        raise HTTPException(404, "Image not found")
    if not img.storage_path or not os.path.exists(img.storage_path):
        raise HTTPException(400, "Image file not found on disk. Re-ingest.")

    # --- LLM mode (step 6) ----------------------------------------------
    if mode_params.mode == "llm":
        try:
            provider = request.app.state.providers.get(mode_params.provider)
        except Exception as e:
            log.warning("align_llm_provider_error", error=str(e))
            provider = None

        if provider is not None:
            try:
                is_healthy = await provider.health()
            except Exception:
                is_healthy = False

            if is_healthy:
                try:
                    llm_result = await run_llm_alignment(
                        img, body.text, provider,
                        model=mode_params.model,
                    )
                    return {
                        "image_id": img.id,
                        "text": body.text,
                        "method": llm_result.method,
                        "note": llm_result.note,
                        "regions": [],  # LLM mode doesn't produce grid regions
                        "spans": [],    # LLM mode doesn't produce text spans
                        "alignments": llm_result.alignments,
                        "cross_modal_relations": [],
                        "provenance": llm_result.provenance,
                        "person_descriptive_redacted": llm_result.person_descriptive_redacted,
                    }
                except ModelProviderError as e:
                    log.warning("align_llm_call_failed", error=str(e))
                    # Fall through to heuristic
            else:
                log.warning("align_llm_provider_unhealthy", provider=mode_params.provider)

    # --- Heuristic mode (default + fallback) ----------------------------
    pil_img = load_image(read_image_bytes(img.storage_path))
    result = align_image_text(pil_img, body.text)
    cross_modal = detect_cross_modal_relations(result)

    response = {
        "image_id": img.id,
        "text": body.text,
        "method": result.method,
        "note": result.note,
        "regions": [asdict(r) for r in result.regions],
        "spans": [asdict(s) for s in result.spans],
        "alignments": [asdict(a) for a in result.alignments],
        "cross_modal_relations": [asdict(r) for r in cross_modal],
        "provenance": {"mode": "heuristic"},
    }
    if mode_params.mode == "llm":
        response["fallback_reason"] = "LLM mode requested but unavailable — using heuristic."
    return response


# --------------------------------------------------------------------------- #
# §9.x Vision-LM image description (CorpusMind Lens build step 3)
#
# This is the first route that actually uses the Message.images extension
# from build step 1 to send image bytes to a local vision-LM. Every
# discourse-framework route in api/phase5.py is purely heuristic — they
# look at colour statistics, composition geometry, and OCR text, never at
# what the image actually depicts. This route closes that gap: it sends
# the real image bytes to a vision-LM (default: Ollama with a
# vision-capable model — qwen3-vl:2b/8b, llava, moondream) and returns
# the model's grounded description.
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
            "Keep it short — small vision models (qwen3-vl:2b, moondream, etc.) can "
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


async def _describe_fresh(
    img: ImageModel,
    registry,  # app.state.providers — ProviderRegistry
    session: AsyncSession,
    *,
    provider_name: str,
    prompt: str,
    model: str | None,
    refresh: bool,
) -> dict:
    """Fresh (non-cached) describe path, shared by the /describe route
    and the batch runner (v1.2.0 Lens round).

    Looks up the provider, health-checks it, resolves a vision-capable
    model, calls it with the image bytes + context, caches the result
    (full reassignment) and applies the consent gate. Raises
    HTTPException (400/503/500) on failure — the batch runner catches
    these per image so one bad image never kills the whole run.
    """
    # --- Provider lookup + health check ---------------------------------
    try:
        provider = registry.get(provider_name)
    except Exception as e:
        raise HTTPException(
            status_code=400,
            detail=f"Provider error: {e}",
        ) from e

    if provider is None:
        raise HTTPException(
            status_code=400,
            detail=(
                f"AI provider '{provider_name}' is not available. "
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
        provider_name = getattr(provider, "name", provider_name)
        if provider_name == "ollama":
            raise HTTPException(
                status_code=503,
                detail=(
                    "Ollama is not running or no vision model is loaded. "
                    "Start Ollama and pull a vision model (e.g. "
                    "`ollama pull qwen3-vl:2b` — small, multilingual OCR incl. Arabic — "
                    "or `ollama pull qwen3-vl:8b` for higher quality)."
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
    full_prompt = prompt
    if context_parts:
        full_prompt = prompt + "\n\nContext:\n" + "\n".join(context_parts)

    # --- Read image bytes + call the provider ---------------------------
    image_bytes = read_image_bytes(img.storage_path)
    messages = [
        Message(
            role="user",
            content=full_prompt,
            images=(image_bytes,),
        ),
    ]

    # v1.2.0: capability-aware model resolution. Previously this fell back
    # to provider.default_model (frequently a TEXT-ONLY model like
    # llama3.2:3b) or the first listed model — the describe call then
    # failed confusingly. Now: explicit model → provider's vision-capable
    # pick → legacy fallback, and an auto-picked model that the provider
    # knows is NOT vision-capable gets an actionable 400.
    model_name = await resolve_vision_model(provider, model)

    if not model_name:
        raise HTTPException(
            status_code=400,
            detail=(
                f"No model specified and provider '{provider_name}' has no "
                f"default model. Specify a model name in the request body."
            ),
        )

    if not model:
        vision_ok = await check_vision_capability(provider, model_name)
        if vision_ok is False:
            raise HTTPException(
                status_code=400,
                detail=(
                    f"The auto-selected model '{model_name}' does not support image input. "
                    f"Install a vision model — for Ollama: `ollama pull qwen3-vl:2b` "
                    f"(small, OCR in 32 languages incl. Arabic) or `ollama pull qwen3-vl:8b` "
                    f"(higher quality) — or specify a model name in the request."
                ),
            )

    cache_key = f"{model or 'default'}:{_prompt_hash(prompt)}"

    log.info(
        "vlm_describe_request",
        image_id=img.id,
        provider=provider_name,
        model=model_name,
        prompt_hash=_prompt_hash(prompt),
        image_bytes=len(image_bytes),
        has_ocr=bool(cached_ocr),
        has_caption=bool(caption),
        refresh=refresh,
        cache_hit=False,
    )

    try:
        response = await provider.chat(
            messages,
            model=model_name,
            temperature=0.1,  # low temperature for descriptive accuracy
            timeout=120.0,    # vision models are slower than text
            max_tokens=2048,  # v1.2.0: rich descriptions were truncated at 512
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
    prompt_hash = _prompt_hash(prompt)

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
        "provider": provider_name,
        "prompt": prompt,
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
        "provider": provider_name,
        "prompt": prompt,
        "prompt_hash": prompt_hash,
        "timestamp": timestamp,
        "cached": False,
        "ocr_disagreement": _detect_ocr_disagreement(gate_result["description"], cached_ocr),
        "cached_ocr": cached_ocr,
        "person_descriptive_redacted": gate_result["person_descriptive_redacted"],
    }



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

    # Fresh path (provider lookup, capability gate, call, cache store)
    # lives in _describe_fresh — shared with the batch runner.
    return await _describe_fresh(
        img,
        request.app.state.providers,
        session,
        provider_name=body.provider,
        prompt=body.prompt,
        model=body.model,
        refresh=body.refresh,
    )

# --------------------------------------------------------------------------- #
# §9.x Batch view — recurring themes + OCR frequency across an image set
# (CorpusMind Lens build step 7)
#
# Once several images in a set have vision-LM analysis cached, this
# endpoint surfaces:
#   1. Recurring framework themes: aggregates all cached
#      vision_llm_discourse claims across images, groups by framework,
#      counts recurring claim categories.
#   2. OCR-derived frequency list: Python-side Counter over all
#      img.analysis["ocr"]["text"] strings. We DON'T reuse the SQL-level
#      compute_frequency() in stats/service.py because OCR text is plain
#      strings, not Token rows in an AnnotationVersion — forcing it
#      through the SQL stats layer would be a bad fit (see review note
#      from the initial plan assessment).
#   3. Vision-LM description summary: aggregates all cached vision_llm
#      descriptions across images.
#
# This is a READ-ONLY aggregation endpoint — it doesn't call any model.
# It only surfaces what's already cached. If no images have cached
# vision-LM analysis, it returns empty lists with a note.
# --------------------------------------------------------------------------- #


@router.get("/image-sets/{iset_id}/batch-analysis")
async def batch_analysis_route(
    iset_id: str,
    session: AsyncSession = Depends(get_session),
) -> dict:
    """Aggregate cached vision-LM analysis across all images in a set.

    Returns:
      - image_count: total images in the set
      - images_with_vlm: how many have cached vision-LM descriptions
      - images_with_discourse: how many have cached discourse analysis
      - recurring_themes: framework → [{category, count, example_claim}]
      - ocr_frequency: [{word, count}] — Python-side Counter over OCR text
      - descriptions: [{image_id, filename, description, model}] summary
    """
    iset = await session.get(ImageSet, iset_id)
    if not iset:
        raise HTTPException(404, "Image set not found")

    # Load all images in the set.
    stmt = select(ImageModel).where(ImageModel.image_set_id == iset_id).order_by(ImageModel.created_at)
    images = (await session.execute(stmt)).scalars().all()

    # --- Aggregate cached vision-LM descriptions -----------------------
    descriptions: list[dict] = []
    images_with_vlm = 0
    for img in images:
        vlm = (img.analysis or {}).get("vision_llm", {})
        if vlm:
            images_with_vlm += 1
            # Take the first cached description (there may be multiple
            # keyed on different prompts/models — the batch view just
            # wants a representative sample).
            first = next(iter(vlm.values()), None)
            if first:
                # Issue 6 fix: route cached descriptions through the consent
                # gate — the cache holds RAW model output (see /describe).
                from vision.consent_gate import filter_describe_response

                descriptions.append({
                    "image_id": img.id,
                    "filename": img.filename,
                    "description": filter_describe_response(first.get("description", ""))["description"],
                    "model": first.get("model", ""),
                })

    # --- Aggregate cached discourse analysis (recurring themes) --------
    from collections import Counter

    # framework → Counter(category → count)
    theme_counts: dict[str, Counter] = {}
    # framework → list of (claim, image_id) for examples
    theme_examples: dict[str, list[dict]] = {}
    images_with_discourse = 0

    for img in images:
        discourse = (img.analysis or {}).get("vision_llm_discourse", {})
        if discourse:
            images_with_discourse += 1
        for cache_key, cached in discourse.items():
            # cache_key is f"{framework_key}:{model}:{prompt_hash}"
            # framework_key is the first segment
            framework_key = cache_key.split(":")[0] if ":" in cache_key else cache_key
            framework_name = cached.get("framework", framework_key)
            for claim in cached.get("claims", []):
                category = claim.get("category", "unspecified")
                theme_counts.setdefault(framework_name, Counter())[category] += 1
                # Keep up to 3 example claims per framework
                if len(theme_examples.setdefault(framework_name, [])) < 3:
                    theme_examples.setdefault(framework_name, []).append({
                        "claim": claim.get("claim", ""),
                        "image_id": img.id,
                        "filename": img.filename,
                    })

    recurring_themes: list[dict] = []
    for framework, counts in sorted(theme_counts.items()):
        categories = [
            {"category": cat, "count": cnt, "example_claim": ""}
            for cat, cnt in counts.most_common(10)
        ]
        # Attach example claims to the first category
        examples = theme_examples.get(framework, [])
        if examples and categories:
            categories[0]["example_claim"] = examples[0]["claim"]
        recurring_themes.append({
            "framework": framework,
            "total_claims": sum(counts.values()),
            "categories": categories,
        })

    # --- OCR-derived frequency list (Python-side Counter) --------------
    # We don't reuse compute_frequency() from stats/service.py because
    # OCR text is plain strings in img.analysis["ocr"]["text"], not
    # Token rows in an AnnotationVersion. A Python Counter is the right
    # tool for this — ~10 lines, no SQL gymnastics.
    ocr_counter: Counter = Counter()
    for img in images:
        ocr_text = (img.analysis or {}).get("ocr", {}).get("text", "")
        if ocr_text:
            # Simple whitespace tokenization + lowercase. This is OCR
            # text, not NLP-parsed tokens — we're counting surface word
            # forms, not lemmas. Arabic-script text works fine here too
            # (whitespace tokenization is language-agnostic).
            words = ocr_text.lower().split()
            # Filter out very short tokens (punctuation that slipped through)
            ocr_counter.update(w for w in words if len(w) > 1)

    ocr_frequency = [
        {"word": word, "count": count}
        for word, count in ocr_counter.most_common(50)
    ]

    return {
        "image_set_id": iset_id,
        "image_set_name": iset.name,
        "image_count": len(images),
        "images_with_vlm": images_with_vlm,
        "images_with_discourse": images_with_discourse,
        "recurring_themes": recurring_themes,
        "ocr_frequency": ocr_frequency,
        "descriptions": descriptions,
        "note": (
            f"Aggregated cached analysis across {len(images)} images. "
            f"{images_with_vlm} have vision-LM descriptions, "
            f"{images_with_discourse} have discourse analysis. "
            f"Use 'Analyse set' (batch runner) or run /describe and "
            f"/social-semiotic?mode=llm on individual images to populate this view."
        ) if images_with_vlm == 0 and images_with_discourse == 0 else "",
    }


# --------------------------------------------------------------------------- #
# §9.x Batch runner (v1.2.0 Lens round) — analyse a whole image set
#
# The batch view above is read-only; until now the only way to populate
# it was running /describe per image by hand. This runner loops over
# the set server-side: describe + optionally all eight discourse lenses,
# with per-image error isolation, skip-if-cached, and cancel support.
# State is in-process (single-engine deployment); poll the status route.
# --------------------------------------------------------------------------- #


DISCOURSE_LENS_KEYS = (
    "social_semiotic",
    "cda",
    "persuasion",
    "framing",
    "narrative",
    "visual_metaphor",
    "emotion",
    "cultural",
)


class BatchRunRequest(BaseModel):
    action: Literal[
        "describe",
        "all",
        "social_semiotic",
        "cda",
        "persuasion",
        "framing",
        "narrative",
        "visual_metaphor",
        "emotion",
        "cultural",
    ] = Field(
        default="describe",
        description=(
            "describe: vision-LM description per image. "
            "all: describe + all eight discourse lenses. "
            "Or a single lens key (social_semiotic, cda, ...)."
        ),
    )
    cda_framework: str = Field(
        default="fairclough",
        description="Which CDA sub-framework to use when action includes cda.",
    )
    provider: str = Field(default="ollama", description="ollama | lmstudio | cloud")
    model: str | None = Field(default=None, description="Vision model; None = capability-aware auto-pick.")
    refresh: bool = Field(default=False, description="Re-run even when a cached result exists.")
    limit: int = Field(default=0, ge=0, le=500, description="Cap the run to N images. 0 = all.")


_batch_state: dict[str, dict] = {}
_batch_tasks: dict[str, asyncio.Task] = {}
_batch_cancel: set[str] = set()


async def _batch_runner(iset_id: str, request: Request, body: BatchRunRequest) -> None:
    """Background loop — one engine pass over the image set.

    Uses its own session (session_scope) because the request's session
    closes when the POST returns. Errors are collected per image+action;
    one bad image never stops the run.
    """
    state = _batch_state.setdefault(iset_id, {})
    try:
        from storage.session import session_scope

        if body.action == "all":
            actions = ["describe", *DISCOURSE_LENS_KEYS]
        elif body.action == "describe":
            actions = ["describe"]
        else:
            actions = [body.action]

        default_prompt = DescribeRequest().prompt

        async with session_scope() as session:
            stmt = select(ImageModel).where(ImageModel.image_set_id == iset_id).order_by(ImageModel.created_at)
            images = (await session.execute(stmt)).scalars().all()
            if body.limit:
                images = images[: body.limit]
            state["total"] = len(images)

            for img in images:
                if iset_id in _batch_cancel:
                    state["status"] = "cancelled"
                    break
                for action in actions:
                    try:
                        if action == "describe":
                            cache_key = f"{body.model or 'default'}:{_prompt_hash(default_prompt)}"
                            cached = (img.analysis or {}).get("vision_llm", {}).get(cache_key)
                            if not cached or body.refresh:
                                await _describe_fresh(
                                    img,
                                    request.app.state.providers,
                                    session,
                                    provider_name=body.provider,
                                    prompt=default_prompt,
                                    model=body.model,
                                    refresh=body.refresh,
                                )
                        else:
                            from api.phase5 import LLMModeRequest, _try_llm_discourse

                            framework_key = f"cda_{body.cda_framework}" if action == "cda" else action
                            mode_params = LLMModeRequest(
                                mode="llm", provider=body.provider, model=body.model, refresh=body.refresh
                            )
                            await _try_llm_discourse(request, img, framework_key, mode_params, session)
                    except HTTPException as e:
                        state["errors"].append(
                            {"image": img.filename, "action": action, "error": str(e.detail)}
                        )
                    except Exception as e:
                        state["errors"].append(
                            {"image": img.filename, "action": action, "error": str(e)}
                        )
                state["done"] = state.get("done", 0) + 1
            else:
                if state.get("status") != "cancelled":
                    state["status"] = "done"
        state["finished_at"] = datetime.now(UTC).isoformat()
    except Exception as e:
        state["status"] = "error"
        state["error"] = str(e)
        state["finished_at"] = datetime.now(UTC).isoformat()
    finally:
        _batch_tasks.pop(iset_id, None)
        _batch_cancel.discard(iset_id)


@router.post("/image-sets/{iset_id}/run-batch")
async def run_batch_route(
    iset_id: str,
    request: Request,
    body: BatchRunRequest | None = None,
    session: AsyncSession = Depends(get_session),
) -> dict:
    """Start a batch analysis over every image in the set (fire-and-poll).

    Returns the initial state; poll GET .../run-batch/status for progress.
    Uses the vision-capable model resolution and honours the consent gate
    (the underlying describe/discourse paths filter person-descriptive
    content exactly like the single-image routes).
    """
    from multimodal.discourse import CDA_FRAMEWORKS

    body = body or BatchRunRequest()
    iset = await session.get(ImageSet, iset_id)
    if not iset:
        raise HTTPException(404, "Image set not found")
    if body.action == "cda" and body.cda_framework not in CDA_FRAMEWORKS:
        raise HTTPException(
            400,
            f"Unknown CDA framework: {body.cda_framework}. Supported: {list(CDA_FRAMEWORKS.keys())}",
        )

    existing = _batch_tasks.get(iset_id)
    if existing is not None and not existing.done():
        raise HTTPException(409, "A batch run is already in progress for this image set.")

    state = {
        "status": "running",
        "action": body.action,
        "total": 0,
        "done": 0,
        "errors": [],
        "started_at": datetime.now(UTC).isoformat(),
        "finished_at": None,
    }
    _batch_state[iset_id] = state
    _batch_tasks[iset_id] = asyncio.create_task(_batch_runner(iset_id, request, body))
    return state


@router.get("/image-sets/{iset_id}/run-batch/status")
async def run_batch_status(
    iset_id: str,
    session: AsyncSession = Depends(get_session),
) -> dict:
    """Poll batch-run progress: {status, action, total, done, errors[]}.

    status: running | done | cancelled | error.
    """
    if iset_id not in _batch_state:
        raise HTTPException(404, "No batch run has been started for this image set.")
    task = _batch_tasks.get(iset_id)
    return {
        **_batch_state[iset_id],
        "running": task is not None and not task.done(),
    }


@router.post("/image-sets/{iset_id}/run-batch/cancel")
async def run_batch_cancel(iset_id: str) -> dict:
    """Request cancellation — the loop stops before the next image."""
    if iset_id not in _batch_state:
        raise HTTPException(404, "No batch run has been started for this image set.")
    _batch_cancel.add(iset_id)
    return {"cancelling": True}


# --------------------------------------------------------------------------- #
# §9.x Deletion (v1.2.0 Lens round) — uploads were previously irreversible
# from both the API and the UI. Privacy remediation for photos of people
# requires a real delete: DB row + on-disk bytes.
# --------------------------------------------------------------------------- #


@router.delete("/images/{img_id}")
async def delete_image(
    img_id: str,
    session: AsyncSession = Depends(get_session),
) -> dict:
    """Delete one image: DB row + stored file (decrypt-agnostic unlink)."""
    img = await session.get(ImageModel, img_id)
    if not img:
        raise HTTPException(404, "Image not found")
    if img.storage_path:
        Path(img.storage_path).unlink(missing_ok=True)
    await session.delete(img)
    return {"deleted": True, "image_id": img_id}


@router.delete("/image-sets/{iset_id}")
async def delete_image_set(
    iset_id: str,
    session: AsyncSession = Depends(get_session),
) -> dict:
    """Delete an image set and every image in it (files + rows)."""
    iset = await session.get(ImageSet, iset_id)
    if not iset:
        raise HTTPException(404, "Image set not found")
    stmt = select(ImageModel).where(ImageModel.image_set_id == iset_id)
    images = (await session.execute(stmt)).scalars().all()
    for img in images:
        if img.storage_path:
            Path(img.storage_path).unlink(missing_ok=True)
    await session.execute(sa_delete(ImageModel).where(ImageModel.image_set_id == iset_id))
    await session.delete(iset)
    return {
        "deleted": True,
        "image_set_id": iset_id,
        "images_removed": len(images),
    }


# --------------------------------------------------------------------------- #
# §9.x Export (v1.2.0 Lens round) — vision results were previously locked
# inside the engine. One row per image: metadata + OCR + colour/composition
# stats + latest vision-LM description + discourse summary.
# --------------------------------------------------------------------------- #


@router.get("/image-sets/{iset_id}/export")
async def export_image_set(
    iset_id: str,
    format: Literal["xlsx", "csv", "tsv", "txt", "json"] = "xlsx",
    session: AsyncSession = Depends(get_session),
) -> StreamingResponse:
    """Export the image set's cached analysis as a spreadsheet/flat file."""
    iset = await session.get(ImageSet, iset_id)
    if not iset:
        raise HTTPException(404, "Image set not found")

    stmt = select(ImageModel).where(ImageModel.image_set_id == iset_id).order_by(ImageModel.created_at)
    images = (await session.execute(stmt)).scalars().all()

    headers = [
        "filename", "width", "height", "size_bytes", "caption", "created_at",
        "ocr_text", "ocr_confidence", "ocr_word_count", "ocr_engine",
        "dominant_colours", "brightness", "contrast", "saturation", "warm_cold_balance",
        "visual_balance", "framing_balance", "salience_centre_x", "salience_centre_y",
        "vlm_description", "vlm_model", "vlm_timestamp",
        "discourse_frameworks", "discourse_claims_count",
    ]

    rows: list[list] = []
    for img in images:
        a = img.analysis or {}
        ocr = a.get("ocr", {}) or {}
        colours = a.get("colours", {}) or {}
        comp = a.get("composition", {}) or {}
        vlm = a.get("vision_llm", {}) or {}
        latest: dict = {}
        if vlm:
            latest = max(vlm.values(), key=lambda d: d.get("timestamp", ""))
        discourse = a.get("vision_llm_discourse", {}) or {}
        frameworks = sorted({str(k).split(":")[0] for k in discourse})
        claims_count = sum(len(v.get("claims", [])) for v in discourse.values())
        top_colours = ", ".join(
            f"{c.get('hex', '?')}:{round(float(c.get('percent', 0)) * 100)}%"
            for c in (colours.get("dominant_colours", []) or [])[:3]
        )
        salience = comp.get("salience_centre", [0.0, 0.0]) or [0.0, 0.0]
        rows.append([
            img.filename,
            img.width,
            img.height,
            img.size_bytes,
            img.caption or "",
            img.created_at.isoformat() if img.created_at else "",
            ocr.get("text", ""),
            ocr.get("confidence", 0.0),
            ocr.get("word_count", 0),
            ocr.get("engine", ""),
            top_colours,
            colours.get("brightness", ""),
            colours.get("contrast", ""),
            colours.get("saturation", ""),
            colours.get("warm_cold_balance", ""),
            comp.get("visual_balance", ""),
            comp.get("framing_balance", ""),
            salience[0] if len(salience) > 0 else "",
            salience[1] if len(salience) > 1 else "",
            latest.get("description", ""),
            latest.get("model", ""),
            latest.get("timestamp", ""),
            ", ".join(frameworks),
            claims_count,
        ])

    slug = re.sub(r"[^\w-]+", "-", iset.name)[:40].strip("-") or "imageset"
    data, media_type, filename = _serialize(format, f"image-set {iset.name}", headers, rows)
    # _serialize names files after the sheet; give it a stable, set-specific name.
    filename = f"image-set-{slug}.{format}"
    return _make_response(data, media_type, filename)
