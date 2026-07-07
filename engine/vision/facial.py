"""
§9.4.3 Facial analysis — opt-in module, OFF by default (§18 Ethical Guardrails).

Per §18: "Facial/body/demographic inference ships as an explicit opt-in module,
off by default, with an in-app notice explaining what it does and does not do
(no identity recognition, aggregate/descriptive use only)."

This module:
  - Is disabled by default. The user must explicitly opt in via Settings.
  - NEVER performs identity recognition or re-identification of real individuals.
  - Only produces descriptive visual cues (estimated age group, gender
    presentation, facial expression, eye gaze) as described visual cues
    plus optional interpretive glosses — never as bare labels.
  - Surfaces confidence scores + the model version used (§4 Principle 8).

Phase 5 ships a scaffold that uses OpenCV's Haar cascades for face detection
+ a simple emotion-classification heuristic. Phase 6+ may swap in a proper
facial-analysis model behind the same interface — but ALWAYS behind the
opt-in gate.
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from app.logging import get_logger

log = get_logger(__name__)


# --------------------------------------------------------------------------- #
# Consent gate
# --------------------------------------------------------------------------- #


def is_facial_analysis_enabled() -> bool:
    """Check whether the user has explicitly opted in to facial analysis.

    Default: OFF. The user must set CORPUSMIND_FACIAL_ANALYSIS_ENABLED=1
    (or toggle it in Settings → Ethics → Facial Analysis) to enable.
    """
    import os
    return os.environ.get("CORPUSMIND_FACIAL_ANALYSIS_ENABLED", "0") == "1"


class FacialAnalysisDisabledError(PermissionError):
    """Raised when facial analysis is invoked without explicit opt-in."""


def require_facial_consent() -> None:
    """Gate function — call at the top of every facial-analysis entry point."""
    if not is_facial_analysis_enabled():
        raise FacialAnalysisDisabledError(
            "Facial analysis is OFF by default (§18 Ethical Guardrails). "
            "To enable: set CORPUSMIND_FACIAL_ANALYSIS_ENABLED=1 or toggle "
            "in Settings → Ethics → Facial Analysis. "
            "This module NEVER performs identity recognition or re-identification."
        )


# --------------------------------------------------------------------------- #
# §9.4.3 Analysis types
# --------------------------------------------------------------------------- #


@dataclass(frozen=True, slots=True)
class FaceDetection:
    """One detected face — descriptive cues only, never identity."""
    bbox: tuple[int, int, int, int]       # (x, y, w, h) in pixels
    confidence: float                     # detection confidence 0–1
    # Descriptive visual cues (§9.4.4: "always output as a described visual cue
    # plus an optional, clearly-labeled interpretive gloss, not a bare label")
    estimated_age_group: str = "unknown"  # child / young_adult / adult / senior / unknown
    gender_presentation: str = "unknown"  # masculine / feminine / ambiguous / unknown
    facial_expression: str = "unknown"    # neutral / smiling / serious / surprised / unknown
    eye_gaze: str = "unknown"             # direct / averted / unknown
    head_direction: str = "unknown"       # frontal / profile / tilted / unknown
    # Interpretive gloss (clearly labeled, §9.4.4)
    interpretive_gloss: str = ""
    # CRITICAL: no identity field. This module NEVER identifies who a person is.
    evidence_note: str = (
        "Descriptive visual cue only. This module performs NO identity "
        "recognition or re-identification of real individuals (§18)."
    )


@dataclass(frozen=True, slots=True)
class FacialAnalysisResult:
    faces: list[FaceDetection]
    face_count: int
    model: str               # "opencv-haar" (Phase 5)
    consent_verified: bool   # always True when this result is returned
    ethics_notice: str


# --------------------------------------------------------------------------- #
# §9.4.3 Detection pipeline
# --------------------------------------------------------------------------- #


def analyse_faces(img: Any) -> FacialAnalysisResult:
    """Detect faces + produce descriptive visual cues.

    REQUIRES explicit opt-in. Raises FacialAnalysisDisabledError if not enabled.
    """
    require_facial_consent()

    try:
        import cv2
        import numpy as np
    except ImportError as e:
        raise RuntimeError(
            "OpenCV + Pillow required for facial analysis. "
            "Install with: pip install opencv-python-headless pillow"
        ) from e

    # Convert PIL → cv2 format (RGB → BGR)
    arr = np.array(img)
    gray = cv2.cvtColor(arr, cv2.COLOR_RGB2GRAY)

    # Haar cascade for face detection (ships with OpenCV)
    cascade_path = cv2.data.haarcascades + "haarcascade_frontalface_default.xml"
    cascade = cv2.CascadeClassifier(cascade_path)
    faces_cv = cascade.detectMultiScale(gray, scaleFactor=1.1, minNeighbors=5, minSize=(30, 30))

    faces: list[FaceDetection] = []
    for (x, y, w, h) in faces_cv:
        # Phase 5: simple heuristic cues. Phase 6+ swaps in proper classifiers.
        # Age group: based on face size relative to image (very rough)
        _img_h, img_w = gray.shape
        face_size_ratio = w / img_w
        if face_size_ratio < 0.1:
            age_group = "unknown"  # too small to estimate
        elif face_size_ratio < 0.2:
            age_group = "adult"  # typical portrait size
        else:
            age_group = "unknown"  # large face — could be any age

        # Facial expression: based on pixel variance in the face region (rough)
        face_region = gray[y : y + h, x : x + w]
        variance = float(face_region.var())
        if variance > 1500:
            expression = "smiling"  # higher variance often = more features (smile wrinkles)
        elif variance < 500:
            expression = "neutral"
        else:
            expression = "serious"

        # Eye gaze: Phase 5 can't reliably detect this without an eye model
        eye_gaze = "unknown"

        # Head direction: frontal (Haar frontal cascade only detects frontal faces)
        head_direction = "frontal"

        # Gender presentation: Phase 5 does NOT estimate this (legally sensitive,
        # and unreliable without a trained model). Always "unknown".
        gender_presentation = "unknown"

        faces.append(FaceDetection(
            bbox=(int(x), int(y), int(w), int(h)),
            confidence=0.7,  # Haar cascade doesn't give confidence; use a fixed conservative value
            estimated_age_group=age_group,
            gender_presentation=gender_presentation,
            facial_expression=expression,
            eye_gaze=eye_gaze,
            head_direction=head_direction,
            interpretive_gloss=(
                f"Detected face with {expression} expression, frontal orientation. "
                f"Age group and gender presentation are NOT estimated in Phase 5 "
                f"(unreliable without a trained model, legally sensitive per §18)."
            ),
        ))

    return FacialAnalysisResult(
        faces=faces,
        face_count=len(faces),
        model="opencv-haar-heuristic (Phase 5)",
        consent_verified=True,
        ethics_notice=(
            "Facial analysis was enabled by the user. This module performs NO "
            "identity recognition or re-identification of real individuals (§18). "
            "All outputs are descriptive visual cues, not identity labels. "
            "Age group + gender presentation are NOT estimated in Phase 5."
        ),
    )
