"""
Visual Grammar module (§9.10) — Kress & van Leeuwen's three meaning-metafunctions.

This is the flagship feature of Suite B (per §16: "the most novel and
highest-risk piece"). It produces a structured score/breakdown from the
§9.4 numeric sub-analyses PLUS a natural-language explanation generated
by the AI layer, explicitly citing which sub-analysis drove each claim.

The three metafunctions (Kress & van Leeuwen 2006):

  1. Representational — what the image depicts (narrative vs conceptual
     processes). Phase 4 stubs this; Phase 5 will add object/scene detection.
  2. Interactive / Interactional — the relationship the image constructs
     between viewer and represented (image act, social distance, angle,
     modality). Phase 4 derives these from composition + colour.
  3. Compositional — how the representational + interactive elements are
     integrated (information value, salience, framing). Phase 4 derives
     these from the §9.4.7 composition analysis.

Every interpretive claim is framework-attributed and phrased as a hypothesis
per §4 Principle 5: "Under a Kress & van Leeuwen reading, X may indicate Y."
"""
from __future__ import annotations

from dataclasses import dataclass

from app.logging import get_logger
from vision.pipeline import ColourAnalysis, CompositionAnalysis, ImageInfo, OCRResult

log = get_logger(__name__)


@dataclass(frozen=True, slots=True)
class VisualGrammarClaim:
    """One claim about the image under a Kress & van Leeuwen reading."""
    metafunction: str          # representational | interactive | compositional
    category: str              # e.g. "information_value:given_new"
    claim: str                 # the interpretive claim (framework-lensed)
    evidence: list[str]        # references to §9.4 sub-analyses
    confidence: float          # 0–1


@dataclass(frozen=True, slots=True)
class VisualGrammarAnalysis:
    claims: list[VisualGrammarClaim]
    framework: str             # always "Kress & van Leeuwen (2006)"
    representational_score: dict[str, float]
    interactive_score: dict[str, float]
    compositional_score: dict[str, float]


def analyse_visual_grammar(
    image_info: ImageInfo,
    ocr: OCRResult,
    colours: ColourAnalysis,
    composition: CompositionAnalysis,
) -> VisualGrammarAnalysis:
    """Score an image against Kress & van Leeuwen's three metafunctions.

    Every claim is:
      - framework-attributed ("Under a Kress & van Leeuwen reading…")
      - grounded in a §9.4 sub-analysis (cited in `evidence`)
      - phrased as a hypothesis, not a bare assertion (§4 Principle 5)
    """
    claims: list[VisualGrammarClaim] = []

    # ----------------------------------------------------------------- #
    # Compositional meaning (§9.4.7) — information value, salience, framing
    # ----------------------------------------------------------------- #
    iv = composition.information_value

    # Left/Right = Given/New (Kress & van Leeuwen 1996)
    if iv["left"] > iv["right"] + 0.1:
        claims.append(VisualGrammarClaim(
            metafunction="compositional",
            category="information_value:given_new",
            claim=(
                "Under a Kress & van Leeuwen reading, the left-weighted salience "
                "may construct the left side as the 'Given' (established, accepted "
                "information) and the right as the 'New' (the yet-to-be-accepted point)."
            ),
            evidence=["composition.information_value.left", "composition.information_value.right"],
            confidence=min(1.0, abs(iv["left"] - iv["right"]) * 2),
        ))
    elif iv["right"] > iv["left"] + 0.1:
        claims.append(VisualGrammarClaim(
            metafunction="compositional",
            category="information_value:given_new",
            claim=(
                "Under a Kress & van Leeuwen reading, the right-weighted salience "
                "may emphasize the 'New' — the novel or contested element the viewer "
                "is being asked to accept."
            ),
            evidence=["composition.information_value.left", "composition.information_value.right"],
            confidence=min(1.0, abs(iv["left"] - iv["right"]) * 2),
        ))

    # Top/Bottom = Ideal/Real
    if iv["top"] > iv["bottom"] + 0.1:
        claims.append(VisualGrammarClaim(
            metafunction="compositional",
            category="information_value:ideal_real",
            claim=(
                "Under a Kress & van Leeuwen reading, the top-weighted salience may "
                "construct the upper zone as the 'Ideal' (the promise, the aspirational) "
                "and the lower as the 'Real' (the practical, the factual)."
            ),
            evidence=["composition.information_value.top", "composition.information_value.bottom"],
            confidence=min(1.0, abs(iv["top"] - iv["bottom"]) * 2),
        ))
    elif iv["bottom"] > iv["top"] + 0.1:
        claims.append(VisualGrammarClaim(
            metafunction="compositional",
            category="information_value:ideal_real",
            claim=(
                "Under a Kress & van Leeuwen reading, the bottom-weighted salience may "
                "emphasize the 'Real' — the factual, the evidence, the practical grounding."
            ),
            evidence=["composition.information_value.top", "composition.information_value.bottom"],
            confidence=min(1.0, abs(iv["top"] - iv["bottom"]) * 2),
        ))

    # Centre/Margin
    if iv["centre"] > 0.6:
        claims.append(VisualGrammarClaim(
            metafunction="compositional",
            category="information_value:centre_margin",
            claim=(
                "Under a Kress & van Leeuwen reading, the centrality of the salient "
                "element may construct it as the nucleus of the message, with marginal "
                "elements subordinate to it."
            ),
            evidence=["composition.information_value.centre"],
            confidence=min(1.0, (iv["centre"] - 0.5) * 2),
        ))

    # Salience
    cx, cy = composition.salience_centre
    claims.append(VisualGrammarClaim(
        metafunction="compositional",
        category="salience",
        claim=(
            f"Under a Kress & van Leeuwen reading, the salience centre at "
            f"({cx:.2f}, {cy:.2f}) — normalized coordinates with origin at top-left — "
            f"identifies the visually most prominent element. Higher salience = greater "
            f"attention-grabbing weight."
        ),
        evidence=["composition.salience_centre"],
        confidence=0.9,
    ))

    # Framing
    if composition.framing_balance > 0.6:
        claims.append(VisualGrammarClaim(
            metafunction="compositional",
            category="framing",
            claim=(
                "Under a Kress & van Leeuwen reading, the edge-weighted salience may "
                "indicate weak framing — elements are dispersed rather than contained, "
                "potentially connoting openness or lack of connection."
            ),
            evidence=["composition.framing_balance"],
            confidence=min(1.0, (composition.framing_balance - 0.5) * 2),
        ))
    elif composition.framing_balance < 0.4:
        claims.append(VisualGrammarClaim(
            metafunction="compositional",
            category="framing",
            claim=(
                "Under a Kress & van Leeuwen reading, the centred salience may indicate "
                "strong framing — elements are contained and connected, potentially "
                "connoting coherence or institutional structure."
            ),
            evidence=["composition.framing_balance"],
            confidence=min(1.0, (0.5 - composition.framing_balance) * 2),
        ))

    # ----------------------------------------------------------------- #
    # Interactive / Interactional meaning — modality, contact
    # ----------------------------------------------------------------- #
    # Modality (realism): derived from saturation + brightness
    modality_score = (colours.saturation + (colours.brightness / 255.0)) / 2.0
    if modality_score > 0.6:
        claims.append(VisualGrammarClaim(
            metafunction="interactive",
            category="modality",
            claim=(
                "Under a Kress & van Leeuwen reading, the high saturation + brightness "
                "may indicate high sensory modality — the image presents itself as vivid, "
                "immediate, 'real'. Common in advertising and documentary."
            ),
            evidence=["colours.saturation", "colours.brightness"],
            confidence=min(1.0, (modality_score - 0.5) * 2),
        ))
    elif modality_score < 0.3:
        claims.append(VisualGrammarClaim(
            metafunction="interactive",
            category="modality",
            claim=(
                "Under a Kress & van Leeuwen reading, the low saturation + brightness "
                "may indicate low sensory modality — the image abstracts from reality, "
                "potentially connoting distance, abstraction, or conceptual rather than "
                "sensory meaning."
            ),
            evidence=["colours.saturation", "colours.brightness"],
            confidence=min(1.0, (0.5 - modality_score) * 2),
        ))

    # Colour symbolism (culture-relative, §9.4.6)
    for note in colours.colour_symbolism_notes:
        claims.append(VisualGrammarClaim(
            metafunction="interactive",
            category="colour_symbolism",
            claim=(
                f"Under a Kress & van Leeuwen reading, the colour profile suggests: "
                f"{note} Note: colour symbolism is framework- and culture-relative, "
                f"not universal (§9.4.6)."
            ),
            evidence=["colours.dominant_colours", "colours.colour_symbolism_notes"],
            confidence=0.5,  # lower confidence — symbolism is interpretive
        ))

    # ----------------------------------------------------------------- #
    # Representational meaning (Phase 4 stub — Phase 5 adds object detection)
    # ----------------------------------------------------------------- #
    if ocr.word_count > 0:
        claims.append(VisualGrammarClaim(
            metafunction="representational",
            category="text_in_image",
            claim=(
                f"Under a Kress & van Leeuwen reading, the presence of {ocr.word_count} "
                f"words of text in the image (OCR confidence: {ocr.confidence:.2f}) may "
                f"indicate a conceptual process — the image classifies or defines via "
                f"labeling rather than depicting a narrative action."
            ),
            evidence=["ocr.word_count", "ocr.confidence"],
            confidence=min(1.0, ocr.confidence),
        ))

    # Aggregate scores per metafunction
    comp_claims = [c for c in claims if c.metafunction == "compositional"]
    int_claims = [c for c in claims if c.metafunction == "interactive"]
    rep_claims = [c for c in claims if c.metafunction == "representational"]

    return VisualGrammarAnalysis(
        claims=claims,
        framework="Kress & van Leeuwen (2006)",
        representational_score={
            "claim_count": len(rep_claims),
            "avg_confidence": round(sum(c.confidence for c in rep_claims) / len(rep_claims), 3) if rep_claims else 0.0,
        },
        interactive_score={
            "claim_count": len(int_claims),
            "avg_confidence": round(sum(c.confidence for c in int_claims) / len(int_claims), 3) if int_claims else 0.0,
        },
        compositional_score={
            "claim_count": len(comp_claims),
            "avg_confidence": round(sum(c.confidence for c in comp_claims) / len(comp_claims), 3) if comp_claims else 0.0,
        },
    )
