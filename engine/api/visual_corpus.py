"""
Visual corpus-linguistics API (v1.1.0 Lens round).

The annotation surface for the five research-grounded visual dimensions
(vision/annotations.py) plus the corpus-linguistics battery computed over
them. The design principle: treat annotation categories the way corpus
linguistics treats POS tags or lemmas — a categorial stream over an
ordered visual corpus — so the standard measures (frequency list,
diversity, n-grams, association, keyness, dispersion, KWIC) apply
directly, reusing the exact formulas in stats/measures.py rather than
re-inventing visual-specific statistics.

Reading order: images are ordered by ``created_at`` ASC (ingest order —
the same convention the OCR-corpus export uses). Sequence measures
(n-grams, KWIC, dispersion) take each frame's FIRST value for the chosen
dimension; images without a value for the dimension are skipped unless
``include_gaps=1`` (then they appear as ``<gap>`` so continuity breaks
are visible rather than silently merged).
"""
from __future__ import annotations

from collections import Counter
from typing import Literal

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel, Field
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm.attributes import flag_modified

from app.logging import get_logger
from stats import measures
from storage.models import Image as ImageModel
from storage.models import ImageSet
from storage.session import get_session
from vision.annotations import (
    CATEGORY_LABELS,
    DIMENSION_IDS,
    SCHEMA,
    dimension,
    normalise_annotations,
    read_annotations,
)

log = get_logger(__name__)
router = APIRouter()

GAP = "<gap>"


# --------------------------------------------------------------------------- #
# Shared helpers
# --------------------------------------------------------------------------- #


async def _get_set_or_404(session: AsyncSession, iset_id: str) -> ImageSet:
    iset = await session.get(ImageSet, iset_id)
    if not iset:
        raise HTTPException(404, "Image set not found")
    return iset


async def _sequence(
    session: AsyncSession, iset_id: str, *, include_gaps: bool = False
) -> list[ImageModel]:
    """All images of a set in reading order (created_at ASC)."""
    stmt = (
        select(ImageModel)
        .where(ImageModel.image_set_id == iset_id)
        .order_by(ImageModel.created_at.asc(), ImageModel.id.asc())
    )
    return list((await session.execute(stmt)).scalars().all())


def _dim_values(img: ImageModel, dim_id: str) -> list[str]:
    ann = read_annotations(img.meta).get("dimensions", {})
    block = ann.get(dim_id) or {}
    return list(block.get("values", []))


def _stream(
    images: list[ImageModel], dim_id: str, *, include_gaps: bool
) -> list[str | None]:
    """One token per frame: the dimension's first value (None = gap)."""
    out: list[str | None] = []
    for img in images:
        vals = _dim_values(img, dim_id)
        if vals:
            out.append(vals[0])
        elif include_gaps:
            out.append(GAP)
    return out


def _require_dim(dim_id: str) -> None:
    if dim_id not in DIMENSION_IDS:
        raise HTTPException(
            400, f"Unknown dimension '{dim_id}' (valid: {list(DIMENSION_IDS)})"
        )


# --------------------------------------------------------------------------- #
# Annotation schema + storage
# --------------------------------------------------------------------------- #


@router.get("/image-sets/{iset_id}/annotation-schema")
async def get_annotation_schema(iset_id: str) -> dict:
    """The five-dimension annotation taxonomy (EN + AR labels), served per
    set so the frontend tag pickers are schema-driven — single source of
    truth, no hardcoded taxonomy in the UI."""
    return {
        "image_set_id": iset_id,
        "dimensions": SCHEMA,
        "reading_order": "created_at ASC (ingest order)",
        "transition_semantics": (
            "path_transition values on frame i describe the shift to frame i+1"
        ),
    }


class AnnotationSaveBody(BaseModel):
    """PUT /images/{img_id}/annotations — one image's annotation state.

    ``dimensions`` is a REPLACE payload: when present (even empty) the
    image's annotations become exactly it; when ``None`` the existing
    annotations are untouched (tags-only update). Passing an explicit
    empty dict per dimension (values+note empty) is how a client clears
    one dimension.
    """

    tags: list[str] | None = Field(None, description="Free multi-value researcher tags")
    dimensions: dict[str, dict] | None = Field(
        None,
        description="Per dimension: {values: [category ids], note: str}. None = keep existing",
    )


@router.put("/images/{img_id}/annotations")
async def save_image_annotations(
    img_id: str, body: AnnotationSaveBody, session: AsyncSession = Depends(get_session)
) -> dict:
    """Save an image's tags + five-dimension annotations (replace semantics).

    Unknown category ids are rejected with 400 — a typo must never
    silently corrupt the corpus. Empty values + empty note drops the
    dimension; a note with no values is kept (negative evidence is
    evidence).
    """
    img = await session.get(ImageModel, img_id)
    if not img:
        raise HTTPException(404, "Image not found")
    try:
        payload = normalise_annotations(
            {"tags": body.tags or [], "dimensions": body.dimensions or {}}
        )
    except ValueError as e:
        raise HTTPException(400, str(e)) from e

    # Drop fully-empty blocks (no values AND no note).
    dims = {
        k: v
        for k, v in payload["dimensions"].items()
        if v["values"] or v["note"].strip()
    }

    meta = dict(img.meta or {})
    if body.tags is not None:
        meta["tags"] = payload["tags"]
    if body.dimensions is not None:
        meta["annotations"] = dims
    img.meta = meta
    flag_modified(img, "meta")
    await session.flush()
    log.info(
        "annotations_saved",
        image_id=img_id,
        dimensions=[k for k, v in dims.items() if v["values"]],
        tags=len(payload["tags"]),
    )
    ann = read_annotations(img.meta)
    return {"image_id": img_id, "tags": ann["tags"], "annotations": ann["dimensions"]}


class BulkAnnotationBody(BaseModel):
    """POST /image-sets/{iset_id}/annotations-bulk — apply to every image."""

    dimensions: dict[str, dict] | None = Field(
        None,
        description="Per dimension: {values: [...], note: str} applied to all images",
    )
    tags: list[str] | None = Field(None, description="Tags to apply")
    tag_mode: Literal["add", "replace"] = Field(
        "add", description="'add' unions with existing tags; 'replace' overwrites"
    )


@router.post("/image-sets/{iset_id}/annotations-bulk")
async def bulk_save_annotations(
    iset_id: str, body: BulkAnnotationBody, session: AsyncSession = Depends(get_session)
) -> dict:
    """Bulk-apply dimension values and tags to every image in the set (the
    visual analogue of 'Tag All Files'). Dimension values overwrite each
    image's values for those dimensions (existing untouched dimensions
    are preserved); tags add or replace per ``tag_mode``."""
    await _get_set_or_404(session, iset_id)
    try:
        normalised = normalise_annotations(
            {"tags": body.tags or [], "dimensions": body.dimensions or {}}
        )
    except ValueError as e:
        raise HTTPException(400, str(e)) from e

    apply_dims = {
        k: v for k, v in normalised["dimensions"].items() if v["values"] or v["note"].strip()
    }
    if not apply_dims and body.tags is None:
        raise HTTPException(400, "Nothing to apply — supply dimensions or tags")

    images = await _sequence(session, iset_id)
    for img in images:
        meta = dict(img.meta or {})
        ann = read_annotations(meta)
        existing_dims = dict(ann["dimensions"])
        for dim_id, block in apply_dims.items():
            existing_dims[dim_id] = block
        meta["annotations"] = existing_dims
        if body.tags is not None:
            if body.tag_mode == "replace":
                meta["tags"] = normalised["tags"]
            else:
                from vision.annotations import normalise_tags

                meta["tags"] = normalise_tags(list(ann["tags"]) + normalised["tags"])
        img.meta = meta
        flag_modified(img, "meta")
    await session.flush()
    log.info("annotations_bulk_applied", iset_id=iset_id, images=len(images))
    return {"updated": len(images), "dimensions_applied": sorted(apply_dims.keys())}


@router.get("/image-sets/{iset_id}/annotations")
async def list_annotations(
    iset_id: str,
    include_gaps: bool = False,
    session: AsyncSession = Depends(get_session),
) -> dict:
    """All annotations in the set, in reading order — the raw annotation
    table the researcher can audit or export."""
    iset = await _get_set_or_404(session, iset_id)
    images = await _sequence(session, iset_id)
    rows = []
    for idx, img in enumerate(images):
        ann = read_annotations(img.meta)
        rows.append(
            {
                "position": idx,
                "image_id": img.id,
                "filename": img.filename,
                "tags": ann["tags"],
                "dimensions": ann["dimensions"],
            }
        )
    return {
        "image_set_id": iset_id,
        "name": iset.name,
        "image_count": len(images),
        "reading_order": "created_at ASC",
        "annotations": rows,
    }


# --------------------------------------------------------------------------- #
# 1. Frequency profile (the visual word-list)
# --------------------------------------------------------------------------- #


@router.get("/image-sets/{iset_id}/visual-stats")
async def visual_stats(iset_id: str, session: AsyncSession = Depends(get_session)) -> dict:
    """Per-dimension frequency distribution + coverage — the image-corpus
    analogue of a POS frequency profile. Every tagged value counts (multi-
    value annotations contribute one token each)."""
    iset = await _get_set_or_404(session, iset_id)
    images = await _sequence(session, iset_id)
    n = len(images)
    dims_out = {}
    annotated_images = 0
    for dim_id in DIMENSION_IDS:
        counts: Counter = Counter()
        per_category_images: dict[str, set[str]] = {}
        images_with_dim = 0
        for img in images:
            vals = _dim_values(img, dim_id)
            if vals:
                images_with_dim += 1
            for v in vals:
                counts[v] += 1
                per_category_images.setdefault(v, set()).add(img.id)
        total = sum(counts.values())
        labels = CATEGORY_LABELS[dim_id]
        dims_out[dim_id] = {
            "label_en": dimension(dim_id)["label_en"],
            "label_ar": dimension(dim_id)["label_ar"],
            "images_annotated": images_with_dim,
            "coverage": round(images_with_dim / n * 100, 1) if n else 0.0,
            "total_values": total,
            "distinct": len(counts),
            "frequency": [
                {
                    "category": cat,
                    "label_en": labels.get(cat, cat),
                    "count": c,
                    "percent": round(c / total * 100, 2) if total else 0.0,
                    "images": len(per_category_images.get(cat, ())),
                }
                for cat, c in counts.most_common()
            ],
        }
    for img in images:
        if read_annotations(img.meta)["dimensions"]:
            annotated_images += 1
    return {
        "image_set_id": iset_id,
        "name": iset.name,
        "image_count": n,
        "images_annotated": annotated_images,
        "annotation_coverage": round(annotated_images / n * 100, 1) if n else 0.0,
        "dimensions": dims_out,
    }


# --------------------------------------------------------------------------- #
# 2. Diversity profile (the visual TTR battery)
# --------------------------------------------------------------------------- #


@router.get("/image-sets/{iset_id}/visual-profile")
async def visual_profile(iset_id: str, session: AsyncSession = Depends(get_session)) -> dict:
    """Lexical-diversity battery per dimension — computed over the value
    stream in reading order (every tagged value is a token). Visual
    corpora are short, so the fixed-window measures use visual-scale
    parameters: MATTR window 10, STTR chunk 20 (documented, not tunable
    by accident)."""
    iset = await _get_set_or_404(session, iset_id)
    images = await _sequence(session, iset_id)
    dims_out = {}
    for dim_id in DIMENSION_IDS:
        tokens: list[str] = []
        frames_with_values = 0
        for img in images:
            vals = _dim_values(img, dim_id)
            if vals:
                frames_with_values += 1
            tokens.extend(vals)
        dims_out[dim_id] = {
            "label_en": dimension(dim_id)["label_en"],
            "tokens": len(tokens),
            "types": len(set(tokens)),
            "frames_with_values": frames_with_values,
            "values_per_frame": round(len(tokens) / frames_with_values, 2)
            if frames_with_values
            else 0.0,
            "ttr": round(measures.type_token_ratio(tokens), 3),
            "guiraud": round(measures.guiraud(tokens), 3),
            "mattr_w10": round(measures.mattr(tokens, window=10), 3),
            "sttr_c20": round(measures.sttr(tokens, chunk_size=20), 3),
        }
    return {
        "image_set_id": iset_id,
        "name": iset.name,
        "dimensions": dims_out,
        "note": (
            "Diversity is computed over all tagged values in reading order; "
            "MATTR window = 10, STTR chunk = 20 (visual corpora are short)."
        ),
    }


# --------------------------------------------------------------------------- #
# 3. Sequence n-grams (the visual cluster/n-gram list)
# --------------------------------------------------------------------------- #


@router.get("/image-sets/{iset_id}/visual-ngrams")
async def visual_ngrams(
    iset_id: str,
    dim: str = Query(..., description="Dimension id for the value stream"),
    n: int = Query(3, ge=2, le=5, description="N-gram size"),
    include_gaps: bool = False,
    limit: int = Query(50, ge=1, le=300),
    session: AsyncSession = Depends(get_session),
) -> dict:
    """N-gram sequences over the chosen dimension's per-frame value stream
    — e.g. shot-scale chains (close_up → medium_shot → long_shot) or
    transition chains. The visual analogue of cluster/n-gram analysis."""
    _require_dim(dim)
    iset = await _get_set_or_404(session, iset_id)
    images = await _sequence(session, iset_id)
    stream = _stream(images, dim, include_gaps=include_gaps)

    grams: Counter = Counter()
    positions: dict[tuple, list[int]] = {}
    for i in range(len(stream) - n + 1):
        window = tuple(stream[i : i + n])
        if any(tok is None for tok in window):
            continue
        grams[window] += 1
        positions.setdefault(window, []).append(i)

    labels = CATEGORY_LABELS[dim]
    def _label(tok: str) -> str:
        return labels.get(tok, tok)

    rows = []
    total = sum(grams.values())
    for gram, c in grams.most_common(limit):
        rows.append(
            {
                "ngram": list(gram),
                "ngram_labels": [_label(g) for g in gram],
                "count": c,
                "percent": round(c / total * 100, 2) if total else 0.0,
                "positions": positions[gram][:10],
            }
        )
    return {
        "image_set_id": iset_id,
        "name": iset.name,
        "dimension": dim,
        "n": n,
        "include_gaps": include_gaps,
        "stream_length": len(stream),
        "ngram_total": total,
        "ngrams": rows,
    }


# --------------------------------------------------------------------------- #
# 4. Co-occurrence association (the visual collocation battery)
# --------------------------------------------------------------------------- #


_COLLOCATION_MEASURES = ("log_dice", "mi", "t_score", "dice", "ll", "delta_p")


@router.get("/image-sets/{iset_id}/visual-collocations")
async def visual_collocations(
    iset_id: str,
    dim_a: str = Query(..., description="First dimension"),
    dim_b: str = Query(..., description="Second dimension (may equal dim_a)"),
    min_freq: int = Query(2, ge=1),
    limit: int = Query(50, ge=1, le=300),
    sort: str = Query("log_dice", description="One of: " + ", ".join(_COLLOCATION_MEASURES)),
    session: AsyncSession = Depends(get_session),
) -> dict:
    """Association measures between categories of two dimensions co-
    occurring within the SAME frame — the visual analogue of collocation.

    N = frames annotated for both dimensions (the co-annotation
    opportunities). The battery is the §12 set: MI, t-score, Dice,
    log-Dice, ΔP (both directions) and G², from stats/measures.py —
    the same formulas the text side uses.
    """
    _require_dim(dim_a)
    _require_dim(dim_b)
    if sort not in _COLLOCATION_MEASURES:
        raise HTTPException(400, f"sort must be one of {list(_COLLOCATION_MEASURES)}")
    iset = await _get_set_or_404(session, iset_id)
    images = await _sequence(session, iset_id)

    # Restrict to frames annotated for both dimensions.
    frames = [
        (_dim_values(img, dim_a), _dim_values(img, dim_b))
        for img in images
        if _dim_values(img, dim_a) and _dim_values(img, dim_b)
    ]
    N = len(frames)
    if N == 0:
        return {
            "image_set_id": iset_id,
            "name": iset.name,
            "dim_a": dim_a,
            "dim_b": dim_b,
            "frames": 0,
            "rows": [],
            "note": "No frame is annotated for both dimensions yet.",
        }

    fa: Counter = Counter()
    fb: Counter = Counter()
    joint: Counter = Counter()
    for a_vals, b_vals in frames:
        for a in set(a_vals):
            fa[a] += 1
        for b in set(b_vals):
            fb[b] += 1
        for a in set(a_vals):
            for b in set(b_vals):
                joint[(a, b)] += 1

    rows = []
    for (a, b), o in joint.items():
        if o < min_freq:
            continue
        R, C = fa[a], fb[b]
        # 2×2 for LL: a=joint, b=R−joint, c=C−joint, d=neither
        d = N - R - C + o
        dp_a_b, dp_b_a = measures.delta_p(o, R, C, N)
        row = {
            "category_a": a,
            "category_b": b,
            "label_a": CATEGORY_LABELS[dim_a].get(a, a),
            "label_b": CATEGORY_LABELS[dim_b].get(b, b),
            "joint": o,
            "f_a": R,
            "f_b": C,
            "frames": N,
            "mi": round(measures.mutual_information(o, R, C, N), 3),
            "t_score": round(measures.t_score(o, R, C, N), 3),
            "dice": round(measures.dice_coefficient(o, R, C), 4),
            "log_dice": round(measures.log_dice(o, R, C), 3),
            "ll": round(measures.log_likelihood_2x2(o, R - o, C - o, d), 3),
            "delta_p_a_given_b": round(dp_b_a, 4),
            "delta_p_b_given_a": round(dp_a_b, 4),
        }
        rows.append(row)

    rows.sort(key=lambda r: r[sort], reverse=True)
    return {
        "image_set_id": iset_id,
        "name": iset.name,
        "dim_a": dim_a,
        "dim_b": dim_b,
        "frames": N,
        "sorted_by": sort,
        "rows": rows[:limit],
    }


# --------------------------------------------------------------------------- #
# 5. Keyness (set-vs-set visual keyword analysis)
# --------------------------------------------------------------------------- #


@router.get("/image-sets/{iset_id}/visual-keyness")
async def visual_keyness(
    iset_id: str,
    other_iset_id: str = Query(..., description="The comparison set (reference)"),
    dim: str = Query(..., description="Dimension to compare"),
    limit: int = Query(60, ge=1, le=300),
    session: AsyncSession = Depends(get_session),
) -> dict:
    """Set-vs-set keyness over a dimension's categories — the visual
    analogue of keyword analysis. f = value occurrences, N = total values
    in the set; full §12 battery via compute_keyness_row, ranked by
    log-likelihood (Rayson & Garside's standard)."""
    _require_dim(dim)
    if other_iset_id == iset_id:
        raise HTTPException(400, "The target and reference sets must differ")
    iset = await _get_set_or_404(session, iset_id)
    other = await _get_set_or_404(session, other_iset_id)

    async def _counts(sid: str) -> Counter:
        c: Counter = Counter()
        for img in await _sequence(session, sid):
            c.update(_dim_values(img, dim))
        return c

    f1_counts, f2_counts = await _counts(iset_id), await _counts(other_iset_id)
    n1, n2 = sum(f1_counts.values()), sum(f2_counts.values())
    if n1 == 0 or n2 == 0:
        return {
            "target": {"id": iset_id, "name": iset.name, "values": n1},
            "reference": {"id": other_iset_id, "name": other.name, "values": n2},
            "dimension": dim,
            "rows": [],
            "note": "One of the sets has no annotations for this dimension yet.",
        }

    rows = []
    for cat, f1 in f1_counts.items():
        f2 = f2_counts.get(cat, 0)
        kr = measures.compute_keyness_row(cat, f1, f2, n1, n2)
        measures_out = {
            k: round(v, 3) if isinstance(v, float) else v for k, v in kr.measures.items()
        }
        rows.append(
            {
                "category": cat,
                "label_en": CATEGORY_LABELS[dim].get(cat, cat),
                "f_target": f1,
                "f_reference": f2,
                **measures_out,
            }
        )
    rows.sort(key=lambda r: r["log_likelihood"], reverse=True)
    return {
        "target": {"id": iset_id, "name": iset.name, "values": n1},
        "reference": {"id": other_iset_id, "name": other.name, "values": n2},
        "dimension": dim,
        "rows": rows[:limit],
    }


# --------------------------------------------------------------------------- #
# 6. Dispersion across the reading order
# --------------------------------------------------------------------------- #


@router.get("/image-sets/{iset_id}/visual-dispersion")
async def visual_dispersion(
    iset_id: str,
    dim: str = Query(..., description="Dimension id"),
    bins: int = Query(10, ge=2, le=50, description="Corpus parts (equal slices)"),
    include_gaps: bool = False,
    session: AsyncSession = Depends(get_session),
) -> dict:
    """Dispersion of each category across the set's reading order — how
    evenly a visual 'word' is distributed through the corpus (Juilland's
    D, Gries' DP and DP-norm, with per-part histograms for charting)."""
    _require_dim(dim)
    iset = await _get_set_or_404(session, iset_id)
    images = await _sequence(session, iset_id)
    stream = _stream(images, dim, include_gaps=include_gaps)

    n_parts = min(bins, max(2, len(stream))) if len(stream) >= 2 else 1
    per_cat_bins: dict[str, list[int]] = {}
    part_sizes = [0] * n_parts
    for i, tok in enumerate(stream):
        if tok is None:
            continue
        b = min(i * n_parts // len(stream), n_parts - 1) if len(stream) else 0
        part_sizes[b] += 1
        per_cat_bins.setdefault(tok, [0] * n_parts)
        per_cat_bins[tok][b] += 1

    cats = []
    for cat, freqs in sorted(per_cat_bins.items()):
        total = sum(freqs)
        cats.append(
            {
                "category": cat,
                "label_en": CATEGORY_LABELS[dim].get(cat, cat),
                "total": total,
                "per_bin": freqs,
                "range": round(sum(1 for f in freqs if f > 0) / n_parts, 2),
                "juillands_d": round(measures.juillands_d(freqs), 3),
                "dp": round(measures.gries_dp(freqs, part_sizes), 3),
                "dp_norm": round(measures.gries_dp_norm(freqs, part_sizes), 3),
            }
        )
    cats.sort(key=lambda c: c["total"], reverse=True)
    return {
        "image_set_id": iset_id,
        "name": iset.name,
        "dimension": dim,
        "stream_length": len(stream),
        "bins": n_parts,
        "include_gaps": include_gaps,
        "part_sizes": part_sizes,
        "categories": cats,
    }


# --------------------------------------------------------------------------- #
# 7. Visual KWIC — sequence concordance for a category
# --------------------------------------------------------------------------- #


@router.get("/image-sets/{iset_id}/visual-kwic")
async def visual_kwic(
    iset_id: str,
    dim: str = Query(..., description="Dimension id"),
    category: str = Query(..., description="Category id to concordance"),
    context: int = Query(2, ge=1, le=5, description="Frames of left/right context"),
    limit: int = Query(50, ge=1, le=200),
    session: AsyncSession = Depends(get_session),
) -> dict:
    """KWIC for a visual category: every frame carrying the category,
    shown with its sequence context (the frames before and after it in
    reading order) — the visual analogue of a concordance line."""
    _require_dim(dim)
    if not category:
        raise HTTPException(400, "category is required")
    iset = await _get_set_or_404(session, iset_id)
    images = await _sequence(session, iset_id)

    labels = CATEGORY_LABELS[dim]

    def _ctx(tok: str | None) -> dict | None:
        if tok is None or tok == GAP:
            return {"category": tok, "label_en": tok or "—"} if tok else None
        return {"category": tok, "label_en": labels.get(tok, tok)}

    hits = []
    stream = _stream(images, dim, include_gaps=True)
    for i, tok in enumerate(stream):
        if tok != category:
            continue
        left = [_ctx(t) for t in stream[max(0, i - context) : i]]
        right = [_ctx(t) for t in stream[i + 1 : i + 1 + context]]
        img = images[i]
        hits.append(
            {
                "image_id": img.id,
                "filename": img.filename,
                "position": i,
                "left": [x for x in left if x is not None],
                "node": {"category": category, "label_en": labels.get(category, category)},
                "right": [x for x in right if x is not None],
                "tags": read_annotations(img.meta)["tags"],
            }
        )
        if len(hits) >= limit:
            break
    return {
        "image_set_id": iset_id,
        "name": iset.name,
        "dimension": dim,
        "category": category,
        "category_label": labels.get(category, category),
        "hit_count": len(hits),
        "stream_length": len(stream),
        "hits": hits,
    }
