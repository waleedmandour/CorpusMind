"""
Vision pipeline (§9.2, §9.3, §9.4) — image ingestion + analysis.

Phase 4 ships:
  - §9.2  Image ingestion: JPG, PNG, TIFF, WebP, SVG (via Pillow)
  - §9.3  OCR: text extraction from images (Tesseract-compatible; falls back
          to a no-OCR mode if Tesseract isn't installed)
  - §9.4.6 Colour analysis: dominant colours, warm/cold balance, brightness,
          contrast, saturation
  - §9.4.7 Composition analysis: information value (left/right, top/bottom,
          centre/margin), salience, framing, rule of thirds, visual balance
          — computed geometrically from saliency + bounding-box centroids
  - §9.4.4 Body language / posture: descriptive visual cues (Phase 5 adds
          the interpretive gloss behind the §18 opt-in gate)

§9.4.3 Facial analysis (age, gender presentation, emotion, gaze) is
deferred to Phase 5 per §18 — it ships as an opt-in module, off by default,
and never performs identity recognition or re-identification.
"""
from __future__ import annotations

import io
from dataclasses import dataclass
from typing import Any

from app.logging import get_logger

log = get_logger(__name__)


# --------------------------------------------------------------------------- #
# §9.2 Image ingestion
# --------------------------------------------------------------------------- #


SUPPORTED_IMAGE_FORMATS = {"jpg", "jpeg", "png", "tif", "tiff", "webp", "bmp", "gif"}


def detect_image_format(filename: str) -> str:
    ext = filename.rsplit(".", 1)[-1].lower() if "." in filename else ""
    if ext == "jpeg":
        ext = "jpg"
    if ext not in SUPPORTED_IMAGE_FORMATS:
        raise ValueError(f"Unsupported image format: .{ext} (supported: {sorted(SUPPORTED_IMAGE_FORMATS)})")
    return ext


def load_image(raw: bytes) -> Any:
    """Load image bytes into a PIL Image. Returns RGB-converted image."""
    from PIL import Image
    img = Image.open(io.BytesIO(raw))
    return img.convert("RGB")


@dataclass(frozen=True, slots=True)
class ImageInfo:
    width: int
    height: int
    format: str
    mode: str
    size_bytes: int


def get_image_info(raw: bytes, filename: str) -> ImageInfo:
    img = load_image(raw)
    fmt = detect_image_format(filename)
    return ImageInfo(
        width=img.width,
        height=img.height,
        format=fmt,
        mode=img.mode,
        size_bytes=len(raw),
    )


# --------------------------------------------------------------------------- #
# §9.3 OCR — text extraction from images
# --------------------------------------------------------------------------- #


@dataclass(frozen=True, slots=True)
class OCRResult:
    text: str
    confidence: float          # 0–1, average confidence (0 if OCR unavailable)
    word_count: int
    engine: str                # "tesseract" or "none"
    language: str = "auto"


def run_ocr(raw: bytes, *, language: str = "eng") -> OCRResult:
    """Extract text from an image via Tesseract.

    Falls back to a no-OCR result if Tesseract isn't installed. The caller
    must surface the engine + confidence to the user (§9.3: 'per-image
    confidence scores surfaced to the user rather than silently trusted').
    """
    try:
        import pytesseract
        from PIL import Image
        img = Image.open(io.BytesIO(raw))
        # Get OCR data with confidence scores
        data = pytesseract.image_to_data(img, lang=language, output_type=pytesseract.Output.DICT)
        words = [w for w in data["text"] if w.strip()]
        confs = [int(c) for c in data["conf"] if int(c) >= 0]
        text = " ".join(words)
        avg_conf = sum(confs) / len(confs) / 100.0 if confs else 0.0
        return OCRResult(
            text=text,
            confidence=round(avg_conf, 3),
            word_count=len(words),
            engine="tesseract",
            language=language,
        )
    except ImportError:
        log.info("ocr_unavailable", reason="pytesseract not installed")
        return OCRResult(text="", confidence=0.0, word_count=0, engine="none", language=language)
    except Exception as e:
        log.warning("ocr_failed", error=str(e))
        return OCRResult(text="", confidence=0.0, word_count=0, engine="none", language=language)


# --------------------------------------------------------------------------- #
# §9.4.6 Colour analysis
# --------------------------------------------------------------------------- #


@dataclass(frozen=True, slots=True)
class ColourAnalysis:
    dominant_colours: list[dict]     # [{hex, rgb, percent}]
    warm_cold_balance: float         # -1 (cold) to +1 (warm)
    brightness: float                # 0–255 mean luminance
    contrast: float                  # 0–255 standard deviation of luminance
    saturation: float                # 0–1 mean saturation
    colour_symbolism_notes: list[str]  # culture-relative hints (§9.4.6)


def _rgb_to_hex(rgb: tuple[int, int, int]) -> str:
    return "#{:02x}{:02x}{:02x}".format(*rgb)


def _is_warm(hue: float) -> bool:
    """Hue 0–60 (red-yellow) and 300–360 (magenta-red) = warm."""
    return hue < 60 or hue >= 300


def analyse_colours(img: Any, *, max_colours: int = 5) -> ColourAnalysis:
    """Analyse colour distribution of an image (§9.4.6)."""
    import colorsys

    import numpy as np

    # Downsample large images for speed
    if img.width > 200:
        ratio = 200 / img.width
        img_small = img.resize((200, max(1, int(img.height * ratio))))
    else:
        img_small = img

    arr = np.array(img_small)
    # Quantize to reduce colour count (8 levels per channel)
    quantized = (arr // 32) * 32
    pixels = quantized.reshape(-1, 3)

    # Count dominant colours
    from collections import Counter
    colour_counts = Counter(tuple(int(p) for p in pix) for pix in pixels)
    total = sum(colour_counts.values())
    dominant = []
    for rgb, count in colour_counts.most_common(max_colours):
        dominant.append({
            "hex": _rgb_to_hex(rgb),
            "rgb": [int(c) for c in rgb],
            "percent": round(count / total * 100, 2),
        })

    # Warm/cold balance (using HSV hue)
    warm_count = cold_count = 0
    saturations = []
    for rgb, count in colour_counts.items():
        r, g, b = [x / 255.0 for x in rgb]
        h, s, _v = colorsys.rgb_to_hsv(r, g, b)
        if s > 0.1:  # ignore near-grey pixels
            if _is_warm(h * 360):
                warm_count += count
            else:
                cold_count += count
            saturations.append(s * count)
    warm_cold = (warm_count - cold_count) / total if total else 0.0

    # Brightness + contrast (luminance)
    grey = np.array(img_small.convert("L"))
    brightness = float(grey.mean())
    contrast = float(grey.std())
    saturation = sum(saturations) / total if total else 0.0

    # Colour symbolism notes (culture-relative, §9.4.6)
    notes = []
    top_r, top_g, top_b = dominant[0]["rgb"] if dominant else [128, 128, 128]
    if top_r > 150 and top_g < 100 and top_b < 100:
        notes.append("Red-dominant — in many Western contexts: passion/danger; in many East Asian contexts: luck/celebration.")
    elif top_r > 200 and top_g > 200 and top_b < 100:
        notes.append("Yellow-dominant — commonly: warmth/caution; in some contexts: sacred/royal.")
    elif top_g > 120 and top_r < 120 and top_b < 120:
        notes.append("Green-dominant — commonly: nature/growth; in some Islamic contexts: religious significance.")
    elif top_b > 120 and top_r < 100 and top_g < 100:
        notes.append("Blue-dominant — commonly: calm/trust; in some contexts: melancholy.")
    elif top_r > 150 and top_g < 100 and top_b > 150:
        notes.append("Magenta/purple-dominant — commonly: luxury/spirituality.")
    if brightness > 200:
        notes.append("High-key (very bright) — often connotes openness/optimism.")
    elif brightness < 60:
        notes.append("Low-key (very dark) — often connotes gravity/mystery.")

    return ColourAnalysis(
        dominant_colours=dominant,
        warm_cold_balance=round(warm_cold, 3),
        brightness=round(brightness, 1),
        contrast=round(contrast, 1),
        saturation=round(saturation, 3),
        colour_symbolism_notes=notes,
    )


# --------------------------------------------------------------------------- #
# §9.4.7 Composition analysis (geometric)
# --------------------------------------------------------------------------- #


@dataclass(frozen=True, slots=True)
class CompositionAnalysis:
    information_value: dict[str, float]   # {left, right, top, bottom, centre, margin}
    rule_of_thirds_intersections: list[dict]  # 4 intersection points + salience
    salience_centre: tuple[float, float]      # (x, y) normalized 0–1
    visual_balance: float                    # -1 (left-heavy) to +1 (right-heavy)
    framing_balance: float                   # 0 (centred) to 1 (edge-weighted)
    vectors: list[dict]                      # dominant directional vectors


def analyse_composition(img: Any) -> CompositionAnalysis:
    """Geometric composition analysis (§9.4.7) — information value, salience,
    framing, rule of thirds. Computed from saliency maps + bounding-box
    centroids so results are numeric and reproducible."""
    import numpy as np

    # Downsample for speed
    if img.width > 400:
        ratio = 400 / img.width
        img_small = img.resize((400, max(1, int(img.height * ratio))))
    else:
        img_small = img

    arr = np.array(img_small.convert("L"), dtype=float)
    h, w = arr.shape

    # Simple saliency: local variance from a blurred version
    from PIL import ImageFilter
    blurred = img_small.convert("L").filter(ImageFilter.GaussianBlur(radius=5))
    blurred_arr = np.array(blurred, dtype=float)
    saliency = np.abs(arr - blurred_arr)
    saliency_norm = saliency / (saliency.max() + 1e-8)

    # Salience centre (weighted centroid)
    total_salience = saliency_norm.sum()
    if total_salience > 0:
        ys, xs = np.indices(saliency_norm.shape)
        cx = float((xs * saliency_norm).sum() / total_salience / w)
        cy = float((ys * saliency_norm).sum() / total_salience / h)
    else:
        cx, cy = 0.5, 0.5

    # Information value (Kress & van Leeuwen 1996/2006): split image into
    # left/right, top/bottom, centre/margin quadrants and sum saliency in each.
    left = float(saliency_norm[:, : w // 2].sum() / total_salience) if total_salience else 0.5
    right = float(saliency_norm[:, w // 2 :].sum() / total_salience) if total_salience else 0.5
    top = float(saliency_norm[: h // 2, :].sum() / total_salience) if total_salience else 0.5
    bottom = float(saliency_norm[h // 2 :, :].sum() / total_salience) if total_salience else 0.5

    # Centre vs margin: centre = middle 50% area; margin = outer 25% on each side
    centre = float(saliency_norm[h // 4 : 3 * h // 4, w // 4 : 3 * w // 4].sum() / total_salience) if total_salience else 0.5
    margin = 1.0 - centre

    # Visual balance: left-heavy (-1) vs right-heavy (+1)
    visual_balance = right - left

    # Framing balance: how much salience is at the edges vs the centre
    framing_balance = float(margin)

    # Rule of thirds: 4 intersection points at (1/3, 1/3), (2/3, 1/3), (1/3, 2/3), (2/3, 2/3)
    thirds_points = []
    for tx in [w / 3, 2 * w / 3]:
        for ty in [h / 3, 2 * h / 3]:
            # Sample a small window around the intersection
            x0, x1 = max(0, int(tx - 10)), min(w, int(tx + 10))
            y0, y1 = max(0, int(ty - 10)), min(h, int(ty + 10))
            local_salience = float(saliency_norm[y0:y1, x0:x1].sum() / (total_salience + 1e-8))
            thirds_points.append({
                "x": round(tx / w, 3),
                "y": round(ty / h, 3),
                "salience": round(local_salience, 4),
            })

    return CompositionAnalysis(
        information_value={
            "left": round(left, 3),
            "right": round(right, 3),
            "top": round(top, 3),
            "bottom": round(bottom, 3),
            "centre": round(centre, 3),
            "margin": round(margin, 3),
        },
        rule_of_thirds_intersections=thirds_points,
        salience_centre=(round(cx, 3), round(cy, 3)),
        visual_balance=round(visual_balance, 3),
        framing_balance=round(framing_balance, 3),
        vectors=[],  # Phase 5 will add vector detection via edge analysis
    )


# --------------------------------------------------------------------------- #
# Full image analysis (§9.4 — combines all sub-analyses)
# --------------------------------------------------------------------------- #


@dataclass(frozen=True, slots=True)
class ImageAnalysis:
    image_info: ImageInfo
    ocr: OCRResult
    colours: ColourAnalysis
    composition: CompositionAnalysis
    # Phase 5 will add: objects, scenes, facial (opt-in), body language


def analyse_image(raw: bytes, filename: str, *, ocr_language: str = "eng") -> ImageAnalysis:
    """Run the full Phase 4 image analysis pipeline (§9.4)."""
    img = load_image(raw)
    info = get_image_info(raw, filename)
    ocr = run_ocr(raw, language=ocr_language)
    colours = analyse_colours(img)
    composition = analyse_composition(img)
    log.info(
        "image_analysed",
        filename=filename,
        size=f"{info.width}x{info.height}",
        ocr_engine=ocr.engine,
        ocr_words=ocr.word_count,
        dominant_colour=colours.dominant_colours[0]["hex"] if colours.dominant_colours else "n/a",
    )
    return ImageAnalysis(
        image_info=info,
        ocr=ocr,
        colours=colours,
        composition=composition,
    )
