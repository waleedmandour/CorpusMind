"""
Multimodal image-text alignment (§9.8) — the flagship feature of Suite B.

Per §16: "this is the highest-risk, most novel piece; validate it thoroughly
before adding more frameworks."

Phase 4 ships a scaffold that:
  - Takes an image + a co-occurring text span (e.g. a caption)
  - Extracts image regions via simple grid-based segmentation
  - Computes per-region visual features (colour, position, salience)
  - Extracts text spans (noun phrases + key words)
  - Aligns regions ↔ text spans using a heuristic similarity score
    (Phase 5 swaps in proper CLIP-style embeddings behind the same interface)
  - Surfaces each alignment with a confidence score + the exact spans/regions linked
  - Every alignment is inspectable (§9.8: "not a black box")

§9.9 Cross-modal meaning (reinforcement, complementarity, contradiction,
irony, mismatch, amplification, silence, redundancy) is built on top of
the alignment — each cross-modal relation is labeled with which alignment
it is based on.
"""
from __future__ import annotations

import math
from dataclasses import dataclass
from typing import Any

from app.logging import get_logger

log = get_logger(__name__)


# --------------------------------------------------------------------------- #
# §9.8 Image-text alignment
# --------------------------------------------------------------------------- #


@dataclass(frozen=True, slots=True)
class ImageRegion:
    """A detected region in an image (Phase 4: grid-based; Phase 5: object-detector-based)."""
    region_id: str             # e.g. "r0", "r1"
    bbox: tuple[float, float, float, float]   # (x, y, w, h) normalized 0–1
    centroid: tuple[float, float]
    mean_colour: tuple[int, int, int]
    salience: float            # 0–1
    descriptor: str            # human-readable description


@dataclass(frozen=True, slots=True)
class TextSpan:
    """A text span extracted for alignment."""
    span_id: str               # e.g. "s0", "s1"
    text: str
    start: int                 # character offset in source text
    end: int
    pos_hint: str              # noun_phrase | keyword | entity


@dataclass(frozen=True, slots=True)
class Alignment:
    """One region ↔ text-span alignment."""
    region_id: str
    span_id: str
    confidence: float          # 0–1
    match_reason: str          # e.g. "colour-term match" or "positional hint"
    region_descriptor: str
    span_text: str


@dataclass(frozen=True, slots=True)
class AlignmentResult:
    alignments: list[Alignment]
    regions: list[ImageRegion]
    spans: list[TextSpan]
    method: str                # "heuristic-colour-positional" (Phase 4)
    note: str = "Phase 4 scaffold: heuristic similarity. Phase 5 swaps in CLIP-style embeddings."


# Colour-term lexicon for heuristic alignment
COLOUR_TERMS = {
    "red": (220, 50, 50), "crimson": (220, 20, 60), "scarlet": (255, 36, 0),
    "blue": (50, 50, 220), "navy": (0, 0, 128), "azure": (0, 127, 255),
    "green": (50, 180, 50), "olive": (128, 128, 0), "lime": (191, 255, 0),
    "yellow": (255, 255, 0), "gold": (255, 215, 0),
    "orange": (255, 165, 0), "amber": (255, 191, 0),
    "purple": (128, 0, 128), "violet": (238, 130, 238), "magenta": (255, 0, 255),
    "pink": (255, 192, 203),
    "white": (255, 255, 255), "black": (0, 0, 0), "grey": (128, 128, 128), "gray": (128, 128, 128),
    "brown": (139, 69, 19), "tan": (210, 180, 140),
}

# Positional terms for heuristic alignment
POSITIONAL_TERMS = {
    "left": lambda cx: cx < 0.4,
    "right": lambda cx: cx > 0.6,
    "top": lambda cy: cy < 0.4,
    "bottom": lambda cy: cy > 0.6,
    "center": lambda cx, cy: 0.3 < cx < 0.7 and 0.3 < cy < 0.7,
    "centre": lambda cx, cy: 0.3 < cx < 0.7 and 0.3 < cy < 0.7,
    "middle": lambda cx, cy: 0.3 < cx < 0.7 and 0.3 < cy < 0.7,
}


def _colour_distance(c1: tuple[int, int, int], c2: tuple[int, int, int]) -> float:
    """Euclidean distance in RGB space, normalized to 0–1."""
    return math.sqrt(sum((a - b) ** 2 for a, b in zip(c1, c2, strict=True))) / (math.sqrt(3) * 255)


def extract_regions(img: Any, *, grid_size: int = 3) -> list[ImageRegion]:
    """Phase 4: grid-based region extraction. Phase 5 will swap in an
    open-vocabulary object detector (§9.4.1)."""
    import numpy as np
    arr = np.array(img)
    h, w = arr.shape[:2]

    # Compute per-cell salience (variance from blurred)
    from PIL import ImageFilter
    grey = img.convert("L")
    blurred = grey.filter(ImageFilter.GaussianBlur(radius=5))
    saliency = np.abs(np.array(grey, dtype=float) - np.array(blurred, dtype=float))
    max_sal = float(saliency.max()) or 1.0

    regions: list[ImageRegion] = []
    cell_w = w / grid_size
    cell_h = h / grid_size
    for ry in range(grid_size):
        for rx in range(grid_size):
            x0, x1 = int(rx * cell_w), int((rx + 1) * cell_w)
            y0, y1 = int(ry * cell_h), int((ry + 1) * cell_h)
            cell = arr[y0:y1, x0:x1]
            mean_rgb = tuple(int(c) for c in cell.reshape(-1, 3).mean(axis=0))
            cell_salience = float(saliency[y0:y1, x0:x1].mean() / max_sal)
            cx = (x0 + x1) / 2 / w
            cy = (y0 + y1) / 2 / h
            # Descriptor: position + dominant colour
            pos_desc = []
            if cx < 0.4:
                pos_desc.append("left")
            elif cx > 0.6:
                pos_desc.append("right")
            if cy < 0.4:
                pos_desc.append("top")
            elif cy > 0.6:
                pos_desc.append("bottom")
            if not pos_desc:
                pos_desc.append("centre")
            colour_name = _name_colour(mean_rgb)
            regions.append(ImageRegion(
                region_id=f"r{len(regions)}",
                bbox=(round(x0 / w, 3), round(y0 / h, 3),
                      round((x1 - x0) / w, 3), round((y1 - y0) / h, 3)),
                centroid=(round(cx, 3), round(cy, 3)),
                mean_colour=mean_rgb,
                salience=round(cell_salience, 3),
                descriptor=f"{', '.join(pos_desc)} region, {colour_name}-dominant, salience={cell_salience:.2f}",
            ))
    return regions


def _name_colour(rgb: tuple[int, int, int]) -> str:
    """Find the closest named colour."""
    closest = min(COLOUR_TERMS.items(), key=lambda kv: sum((a - b) ** 2 for a, b in zip(rgb, kv[1], strict=True)))
    return closest[0]


def extract_text_spans(text: str) -> list[TextSpan]:
    """Extract noun phrases + keywords from text for alignment.

    Phase 4: simple keyword extraction (lowercased tokens ≥ 4 chars,
    excluding stopwords). Phase 5 will use a proper NP chunker.
    """
    STOPWORDS = {"the", "this", "that", "these", "those", "and",
                 "with", "for", "from", "into", "onto", "over", "under",
                 "image", "picture", "photo", "shows", "depicts", "seen"}
    spans: list[TextSpan] = []
    for tok in text.split():
        # Strip punctuation
        clean = "".join(c for c in tok if c.isalpha())
        # Allow shorter words if they're colour or positional terms
        is_colour = clean.lower() in COLOUR_TERMS
        is_positional = clean.lower() in POSITIONAL_TERMS
        if len(clean) < 4 and not (is_colour or is_positional):
            continue
        if clean.lower() in STOPWORDS:
            continue
        start = text.find(tok)
        end = start + len(tok)
        # Check if it's a colour or positional term
        pos_hint = "keyword"
        if clean.lower() in COLOUR_TERMS:
            pos_hint = "colour_term"
        elif clean.lower() in POSITIONAL_TERMS:
            pos_hint = "positional_term"
        spans.append(TextSpan(
            span_id=f"s{len(spans)}",
            text=tok,
            start=start,
            end=end,
            pos_hint=pos_hint,
        ))
    return spans


def align_image_text(
    img: Any,
    text: str,
) -> AlignmentResult:
    """Align image regions with text spans (§9.8).

    Phase 4: heuristic similarity based on colour-term matching + positional
    hints. Phase 5 will swap in CLIP-style embeddings behind the same
    interface — results stay comparable because the model + version is
    pinned per project (§4 Principle 8).
    """
    regions = extract_regions(img)
    spans = extract_text_spans(text)
    alignments: list[Alignment] = []

    for region in regions:
        for span in spans:
            conf = 0.0
            reasons = []
            if span.pos_hint == "colour_term":
                # Match colour term to region's mean colour
                term_rgb = COLOUR_TERMS[span.text.lower()]
                dist = _colour_distance(term_rgb, region.mean_colour)
                conf = max(0.0, 1.0 - dist * 2)
                reasons.append(f"colour-term '{span.text.lower()}' matches region colour ({_name_colour(region.mean_colour)})")
            elif span.pos_hint == "positional_term":
                # Match positional term to region's centroid
                term = span.text.lower()
                cx, cy = region.centroid
                if term in ("center", "centre", "middle"):
                    if 0.3 < cx < 0.7 and 0.3 < cy < 0.7:
                        conf = 0.7
                        reasons.append(f"positional term '{term}' matches centre region")
                elif term in POSITIONAL_TERMS:
                    checker = POSITIONAL_TERMS[term]
                    try:
                        if checker(cx, cy):
                            conf = 0.7
                            reasons.append(f"positional term '{term}' matches region at ({cx:.2f}, {cy:.2f})")
                    except TypeError:
                        pass
            else:
                # Generic keyword: low confidence baseline (Phase 5: embedding similarity)
                conf = 0.2
                reasons.append("generic keyword (Phase 5 will use embedding similarity)")

            if conf > 0.1:
                alignments.append(Alignment(
                    region_id=region.region_id,
                    span_id=span.span_id,
                    confidence=round(conf, 3),
                    match_reason="; ".join(reasons),
                    region_descriptor=region.descriptor,
                    span_text=span.text,
                ))

    # Sort by confidence descending
    alignments.sort(key=lambda a: a.confidence, reverse=True)

    return AlignmentResult(
        alignments=alignments,
        regions=regions,
        spans=spans,
        method="heuristic-colour-positional",
    )


# --------------------------------------------------------------------------- #
# §9.9 Cross-modal meaning
# --------------------------------------------------------------------------- #


@dataclass(frozen=True, slots=True)
class CrossModalRelation:
    """A cross-modal meaning relation between image and text (§9.9)."""
    relation_type: str         # reinforcement | complementarity | contradiction | etc.
    alignment_refs: list[str]  # which alignments this is based on
    description: str
    confidence: float


def detect_cross_modal_relations(alignment_result: AlignmentResult) -> list[CrossModalRelation]:
    """Detect cross-modal meaning relations (§9.9).

    Each relation is labeled with which alignment(s) it is based on, per §9.9.
    """
    relations: list[CrossModalRelation] = []
    if not alignment_result.alignments:
        relations.append(CrossModalRelation(
            relation_type="silence",
            alignment_refs=[],
            description="No image-text alignments found — the image and text may not reference each other.",
            confidence=0.6,
        ))
        return relations

    high_conf = [a for a in alignment_result.alignments if a.confidence > 0.5]
    if high_conf:
        relations.append(CrossModalRelation(
            relation_type="reinforcement",
            alignment_refs=[f"{a.region_id}↔{a.span_id}" for a in high_conf],
            description=(
                f"{len(high_conf)} high-confidence alignment(s) suggest the text "
                f"reinforces the image's visual content — both modalities convey "
                f"overlapping information."
            ),
            confidence=min(1.0, len(high_conf) / 5.0),
        ))

    low_conf = [a for a in alignment_result.alignments if a.confidence <= 0.3]
    if len(low_conf) > len(high_conf) * 2:
        relations.append(CrossModalRelation(
            relation_type="complementarity",
            alignment_refs=[f"{a.region_id}↔{a.span_id}" for a in low_conf[:3]],
            description=(
                "Most alignments are low-confidence — the text and image may "
                "complement rather than reinforce each other, contributing "
                "different information."
            ),
            confidence=0.5,
        ))

    return relations
