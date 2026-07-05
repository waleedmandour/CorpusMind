"""
Phase 5 multimodal discourse analyses (§9.11–9.18).

Each analysis:
  - Is framework-lensed per §4 Principle 5: interpretive claims are phrased
    as hypotheses ("Under a [Framework] reading, X may indicate Y")
  - Cites the specific visual or linguistic feature that triggered each claim
  - Never states ideology, bias, or power relations as settled fact

Framework lenses implemented:
  - §9.11 Social Semiotic (Kress & van Leeuwen 2006)
  - §9.12 CDA: Fairclough / van Dijk / Wodak / Machin & Mayr (user-selectable)
  - §9.13 Persuasion: Aristotle's Rhetoric + Toulmin's Argumentation Model
  - §9.14 Framing: Entman's 4 framing functions
  - §9.15 Narrative: Labov's 6-stage structure
  - §9.16 Metaphor (visual + cross-modal, MIPVU-inspired)
  - §9.17 Emotion (combined image + text emotion)
  - §9.18 Cultural (culture-specific symbols, always culture-relative)
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Literal

from app.logging import get_logger
from vision.pipeline import ColourAnalysis, CompositionAnalysis, OCRResult

log = get_logger(__name__)


# --------------------------------------------------------------------------- #
# Shared types
# --------------------------------------------------------------------------- #


@dataclass(frozen=True, slots=True)
class DiscourseClaim:
    """One framework-lensed interpretive claim."""
    framework: str
    category: str
    claim: str               # phrased as a hypothesis per §4 Principle 5
    evidence: list[str]      # references to visual/textual features
    confidence: float        # 0–1


@dataclass(frozen=True, slots=True)
class DiscourseAnalysisResult:
    analysis_type: str       # social_semiotic | cda | persuasion | framing | etc.
    framework: str
    claims: list[DiscourseClaim]
    summary: str


# --------------------------------------------------------------------------- #
# §9.11 Social Semiotic Analysis
# --------------------------------------------------------------------------- #


def analyse_social_semiotic(
    colours: ColourAnalysis,
    composition: CompositionAnalysis,
    ocr: OCRResult,
    caption: str = "",
) -> DiscourseAnalysisResult:
    """Social semiotic analysis (§9.11) — actors, processes, participants,
    attributes, symbolic/cultural meaning, power, ideology, identity.

    Grounded in Kress & van Leeuwen's Social Semiotics (2006).
    """
    claims: list[DiscourseClaim] = []

    # Symbolic attributes from colour
    for note in colours.colour_symbolism_notes:
        claims.append(DiscourseClaim(
            framework="Kress & van Leeuwen (Social Semiotics 2006)",
            category="symbolic_attribute",
            claim=(
                f"Under a Social Semiotic reading, the colour profile may function "
                f"as a symbolic attribute: {note} This is a culture-relative reading, "
                f"not a universal meaning."
            ),
            evidence=["colours.dominant_colours", "colours.colour_symbolism_notes"],
            confidence=0.5,
        ))

    # Power relations from composition (centred = authoritative; off-centre = subordinate)
    iv = composition.information_value
    if iv["centre"] > 0.6:
        claims.append(DiscourseClaim(
            framework="Kress & van Leeuwen (Social Semiotics 2006)",
            category="power_relation",
            claim=(
                "Under a Social Semiotic reading, the centrality of the salient "
                "element may construct it as the nucleus of power — the central "
                "actor around whom other participants are arranged. This is a "
                "hypothesis, not a settled fact about the depicted relationship."
            ),
            evidence=["composition.information_value.centre"],
            confidence=min(1.0, (iv["centre"] - 0.5) * 2),
        ))

    # Identity from text content (if caption present)
    if caption:
        # Look for first-person pronouns (self-identity)
        first_person = any(w in caption.lower() for w in [" i ", " we ", " our ", " my ", " us "])
        if first_person:
            claims.append(DiscourseClaim(
                framework="Kress & van Leeuwen (Social Semiotics 2006)",
                category="identity",
                claim=(
                    "Under a Social Semiotic reading, the presence of first-person "
                    "pronouns in the caption may construct a personal identity "
                    "narrative — the image positions its subject as an 'I' or 'we'."
                ),
                evidence=["caption.text"],
                confidence=0.6,
            ))

    return DiscourseAnalysisResult(
        analysis_type="social_semiotic",
        framework="Kress & van Leeuwen (Social Semiotics 2006)",
        claims=claims,
        summary=f"Social semiotic analysis produced {len(claims)} framework-lensed claims.",
    )


# --------------------------------------------------------------------------- #
# §9.12 Critical Discourse Analysis (user-selectable framework)
# --------------------------------------------------------------------------- #


CDA_FRAMEWORKS = {
    "fairclough": "Fairclough (1995) Three-Dimensional CDA",
    "van_dijk": "van Dijk (2008) Socio-Cognitive Approach",
    "wodak": "Wodak (2001) Discourse-Historical Approach",
    "machin_mayr": "Machin & Mayr (2012) Multimodal CDA",
}


def analyse_cda(
    colours: ColourAnalysis,
    composition: CompositionAnalysis,
    ocr: OCRResult,
    caption: str = "",
    *,
    framework: Literal["fairclough", "van_dijk", "wodak", "machin_mayr"] = "fairclough",
) -> DiscourseAnalysisResult:
    """Critical Discourse Analysis (§9.12) — power, ideology, bias,
    representation, marginalization, us-vs-them framing, agency,
    nominalization, passivization, presupposition, evidentiality.

    The framework is user-selectable per §9.24. Each produces a different
    analytic lens but all follow §4 Principle 5: claims are hypotheses.
    """
    fw_name = CDA_FRAMEWORKS.get(framework, CDA_FRAMEWORKS["fairclough"])
    claims: list[DiscourseClaim] = []

    if framework == "fairclough":
        # Fairclough's three dimensions: text, discursive practice, social practice
        if ocr.text or caption:
            claims.append(DiscourseClaim(
                framework=fw_name,
                category="textual_analysis",
                claim=(
                    "Under a Fairclough CDA reading, the textual content may be "
                    "analysed at three levels: (1) text — vocabulary, grammar, "
                    "cohesion; (2) discursive practice — production, distribution, "
                    "consumption; (3) social practice — ideological effects. "
                    "The presence of specific lexical choices may signal "
                    "ideological positioning."
                ),
                evidence=["ocr.text", "caption.text"],
                confidence=0.5,
            ))
        # Visual modality as ideological
        if colours.saturation > 0.5:
            claims.append(DiscourseClaim(
                framework=fw_name,
                category="ideological_naturalization",
                claim=(
                    "Under a Fairclough CDA reading, the high-saturation visual "
                    "modality may naturalize a particular ideological view of "
                    "reality — making the depicted scene appear 'how things are' "
                    "rather than 'how things are represented'. This is a hypothesis."
                ),
                evidence=["colours.saturation", "colours.brightness"],
                confidence=min(1.0, colours.saturation),
            ))

    elif framework == "van_dijk":
        # van Dijk's socio-cognitive: mental models, ideology, context
        if caption:
            # Look for us/them markers
            us_markers = sum(1 for w in ["we", "us", "our"] if w in caption.lower().split())
            them_markers = sum(1 for w in ["they", "them", "their"] if w in caption.lower().split())
            if us_markers > 0 or them_markers > 0:
                claims.append(DiscourseClaim(
                    framework=fw_name,
                    category="us_them_polarization",
                    claim=(
                        f"Under a van Dijk Socio-Cognitive reading, the presence of "
                        f"in-group ({us_markers} 'we/us/our') and out-group "
                        f"({them_markers} 'they/them/their') markers may indicate "
                        f"an ideological polarization — constructing an 'us vs them' "
                        f"mental model. This is a hypothesis about the text's "
                        f"ideological work, not a fact about the author's intent."
                    ),
                    evidence=["caption.text"],
                    confidence=min(1.0, (us_markers + them_markers) / 5.0),
                ))

    elif framework == "wodak":
        # Wodak's discourse-historical: 4 levels (content, linguistic, argumentation, context)
        claims.append(DiscourseClaim(
            framework=fw_name,
            category="historical_context",
            claim=(
                "Under a Wodak Discourse-Historical reading, the image + text "
                "should be analysed at four levels: (1) content; (2) linguistic "
                "realization; (3) argumentation strategies; (4) historical context. "
                "Phase 5 provides the first three; the fourth requires the researcher "
                "to supply the relevant historical context."
            ),
            evidence=["ocr.text", "caption.text", "colours", "composition"],
            confidence=0.4,
        ))

    elif framework == "machin_mayr":
        # Machin & Mayr's multimodal CDA: visual + linguistic together
        if colours.warm_cold_balance > 0.2:
            claims.append(DiscourseClaim(
                framework=fw_name,
                category="visual_evaluative_loading",
                claim=(
                    "Under a Machin & Mayr Multimodal CDA reading, the warm-toned "
                    "colour palette may carry evaluative loading — warm colours are "
                    "often used to connote positivity, intimacy, or tradition. "
                    "This may function ideologically to position the depicted "
                    "subject favourably. This is a hypothesis."
                ),
                evidence=["colours.warm_cold_balance", "colours.dominant_colours"],
                confidence=min(1.0, abs(colours.warm_cold_balance)),
            ))
        elif colours.warm_cold_balance < -0.2:
            claims.append(DiscourseClaim(
                framework=fw_name,
                category="visual_evaluative_loading",
                claim=(
                    "Under a Machin & Mayr Multimodal CDA reading, the cold-toned "
                    "colour palette may carry evaluative loading — cold colours are "
                    "often used to connote distance, objectivity, or modernity. "
                    "This may function ideologically to position the depicted "
                    "subject as neutral or technical. This is a hypothesis."
                ),
                evidence=["colours.warm_cold_balance", "colours.dominant_colours"],
                confidence=min(1.0, abs(colours.warm_cold_balance)),
            ))

    return DiscourseAnalysisResult(
        analysis_type="cda",
        framework=fw_name,
        claims=claims,
        summary=f"CDA ({fw_name}) produced {len(claims)} framework-lensed claims.",
    )


# --------------------------------------------------------------------------- #
# §9.13 Persuasion Analysis (Aristotle + Toulmin)
# --------------------------------------------------------------------------- #


def analyse_persuasion(
    ocr: OCRResult,
    caption: str = "",
) -> DiscourseAnalysisResult:
    """Persuasion analysis (§9.13) — ethos, pathos, logos (Aristotle) +
    claim/data/warrant (Toulmin).

    Per §9.13: "this is legitimate media/propaganda-studies analysis of
    existing texts, not content generation."
    """
    claims: list[DiscourseClaim] = []
    text = (ocr.text + " " + caption).lower()

    # Aristotle's three appeals
    # Ethos: credibility markers
    ethos_markers = ["expert", "authority", "research", "study", "proven",
                     "trusted", "professional", "official", "certified"]
    ethos_count = sum(1 for m in ethos_markers if m in text)
    if ethos_count > 0:
        claims.append(DiscourseClaim(
            framework="Aristotle's Rhetoric",
            category="ethos",
            claim=(
                f"Under an Aristotelian reading, the presence of {ethos_count} "
                f"credibility marker(s) (e.g. 'expert', 'research', 'official') "
                f"may constitute an ethos appeal — persuading via the source's "
                f"credibility. This is an analytical observation about the text's "
                f"rhetorical strategy, not an endorsement."
            ),
            evidence=["ocr.text", "caption.text"],
            confidence=min(1.0, ethos_count / 3.0),
        ))

    # Pathos: emotion markers
    pathos_markers = ["fear", "hope", "love", "hate", "urgent", "crisis",
                      "threat", "opportunity", "dream", "nightmare"]
    pathos_count = sum(1 for m in pathos_markers if m in text)
    if pathos_count > 0:
        claims.append(DiscourseClaim(
            framework="Aristotle's Rhetoric",
            category="pathos",
            claim=(
                f"Under an Aristotelian reading, the presence of {pathos_count} "
                f"emotion marker(s) may constitute a pathos appeal — persuading "
                f"via the audience's emotions. This is an analytical observation."
            ),
            evidence=["ocr.text", "caption.text"],
            confidence=min(1.0, pathos_count / 3.0),
        ))

    # Logos: logical markers
    logos_markers = ["because", "therefore", "thus", "consequently", "result",
                     "evidence", "data", "shows", "demonstrates"]
    logos_count = sum(1 for m in logos_markers if m in text)
    if logos_count > 0:
        claims.append(DiscourseClaim(
            framework="Aristotle's Rhetoric",
            category="logos",
            claim=(
                f"Under an Aristotelian reading, the presence of {logos_count} "
                f"logical connector(s) may constitute a logos appeal — persuading "
                f"via reasoned argument. This is an analytical observation."
            ),
            evidence=["ocr.text", "caption.text"],
            confidence=min(1.0, logos_count / 3.0),
        ))

    # Toulmin's model: claim + data + warrant
    if "because" in text or "since" in text:
        claims.append(DiscourseClaim(
            framework="Toulmin's Argumentation Model",
            category="argument_structure",
            claim=(
                "Under a Toulmin reading, the presence of causal connectors "
                "('because', 'since') may indicate an explicit argument structure: "
                "a claim supported by data. The warrant (the assumption connecting "
                "data to claim) is often implicit and should be examined critically."
            ),
            evidence=["ocr.text", "caption.text"],
            confidence=0.6,
        ))

    return DiscourseAnalysisResult(
        analysis_type="persuasion",
        framework="Aristotle's Rhetoric + Toulmin's Argumentation Model",
        claims=claims,
        summary=f"Persuasion analysis produced {len(claims)} claims across ethos/pathos/logos + Toulmin.",
    )


# --------------------------------------------------------------------------- #
# §9.14 Framing Analysis (Entman)
# --------------------------------------------------------------------------- #


def analyse_framing(
    ocr: OCRResult,
    caption: str = "",
) -> DiscourseAnalysisResult:
    """Framing analysis (§9.14) — Entman's 4 framing functions:
    problem definition, causal interpretation, moral evaluation,
    treatment recommendation.
    """
    claims: list[DiscourseClaim] = []
    text = (ocr.text + " " + caption).lower()

    # Problem definition
    problem_markers = ["problem", "issue", "crisis", "challenge", "threat",
                       "concern", "difficulty"]
    if any(m in text for m in problem_markers):
        claims.append(DiscourseClaim(
            framework="Entman (1993) Framing",
            category="problem_definition",
            claim=(
                "Under an Entman framing reading, the presence of problem-markers "
                "may define an issue as a 'problem' requiring attention. The way "
                "a problem is framed shapes which solutions seem natural. This is "
                "a hypothesis about the text's framing work."
            ),
            evidence=["ocr.text", "caption.text"],
            confidence=0.6,
        ))

    # Causal interpretation
    causal_markers = ["because", "caused", "due to", "result of", "led to"]
    if any(m in text for m in causal_markers):
        claims.append(DiscourseClaim(
            framework="Entman (1993) Framing",
            category="causal_interpretation",
            claim=(
                "Under an Entman framing reading, the presence of causal markers "
                "may attribute the problem to specific causes — which is itself a "
                "framing choice, since competing causes could have been named."
            ),
            evidence=["ocr.text", "caption.text"],
            confidence=0.6,
        ))

    # Moral evaluation
    moral_markers = ["should", "must", "wrong", "right", "unjust", "fair",
                     "unacceptable", "responsible"]
    if any(m in text for m in moral_markers):
        claims.append(DiscourseClaim(
            framework="Entman (1993) Framing",
            category="moral_evaluation",
            claim=(
                "Under an Entman framing reading, the presence of moral-evaluation "
                "markers may judge the actors or actions — framing them as worthy "
                "of praise or blame."
            ),
            evidence=["ocr.text", "caption.text"],
            confidence=0.6,
        ))

    # Treatment recommendation
    treatment_markers = ["must", "should", "need to", "solution", "action",
                         "require", "implement"]
    if any(m in text for m in treatment_markers):
        claims.append(DiscourseClaim(
            framework="Entman (1993) Framing",
            category="treatment_recommendation",
            claim=(
                "Under an Entman framing reading, the presence of treatment-markers "
                "may recommend a remedy — which, combined with the problem definition "
                "and causal interpretation, completes the framing package."
            ),
            evidence=["ocr.text", "caption.text"],
            confidence=0.6,
        ))

    return DiscourseAnalysisResult(
        analysis_type="framing",
        framework="Entman (1993) Framing",
        claims=claims,
        summary=f"Framing analysis identified {len(claims)} of Entman's 4 framing functions.",
    )


# --------------------------------------------------------------------------- #
# §9.15 Narrative Analysis (Labov)
# --------------------------------------------------------------------------- #


def analyse_narrative(
    ocr: OCRResult,
    caption: str = "",
) -> DiscourseAnalysisResult:
    """Narrative analysis (§9.15) — Labov's 6-stage structure:
    abstract, orientation, complicating action, evaluation, resolution, coda.
    """
    claims: list[DiscourseClaim] = []
    text = ocr.text + " " + caption
    text_lower = text.lower()
    sentences = [s.strip() for s in text.split(".") if s.strip()]

    # Abstract: summary at the start
    if sentences and any(w in sentences[0].lower() for w in ["summary", "in short", "briefly"]):
        claims.append(DiscourseClaim(
            framework="Labov (1972) Narrative Structure",
            category="abstract",
            claim="Under a Labov reading, the opening may function as an abstract — summarizing the whole narrative.",
            evidence=["ocr.text[0]"],
            confidence=0.5,
        ))

    # Orientation: who/when/where
    orientation_markers = ["once", "long ago", "in 19", "in 20", "yesterday", "when"]
    if any(m in text_lower for m in orientation_markers):
        claims.append(DiscourseClaim(
            framework="Labov (1972) Narrative Structure",
            category="orientation",
            claim="Under a Labov reading, temporal/setting markers may orient the reader to the narrative's time and place.",
            evidence=["ocr.text", "caption.text"],
            confidence=0.5,
        ))

    # Complicating action: then/but/suddenly
    complicating_markers = ["then", "but", "suddenly", "however", "unexpectedly"]
    if any(m in text_lower for m in complicating_markers):
        claims.append(DiscourseClaim(
            framework="Labov (1972) Narrative Structure",
            category="complicating_action",
            claim="Under a Labov reading,转折 markers (then/but/suddenly) may signal complicating actions — the narrative's turning points.",
            evidence=["ocr.text", "caption.text"],
            confidence=0.5,
        ))

    # Resolution: finally/in the end
    resolution_markers = ["finally", "in the end", "at last", "resolved", "outcome"]
    if any(m in text_lower for m in resolution_markers):
        claims.append(DiscourseClaim(
            framework="Labov (1972) Narrative Structure",
            category="resolution",
            claim="Under a Labov reading, resolution markers may indicate how the complication was resolved.",
            evidence=["ocr.text", "caption.text"],
            confidence=0.5,
        ))

    return DiscourseAnalysisResult(
        analysis_type="narrative",
        framework="Labov (1972) Narrative Structure",
        claims=claims,
        summary=f"Narrative analysis identified {len(claims)} Labov stages.",
    )


# --------------------------------------------------------------------------- #
# §9.16 Visual + Cross-modal Metaphor (MIPVU-inspired)
# --------------------------------------------------------------------------- #


def analyse_visual_metaphor(
    colours: ColourAnalysis,
    composition: CompositionAnalysis,
    ocr: OCRResult,
    caption: str = "",
) -> DiscourseAnalysisResult:
    """Visual + cross-modal metaphor analysis (§9.16).

    Same MIPVU-inspired, human-verified pipeline as §8.17, extended to
    visual/cross-modal candidates. The LLM triages; the human verifies.
    """
    claims: list[DiscourseClaim] = []

    # Visual metaphor: colour as emotional state
    if colours.warm_cold_balance > 0.3 and colours.saturation > 0.4:
        claims.append(DiscourseClaim(
            framework="Conceptual Metaphor Theory (Lakoff & Johnson 1980) + Forceville (2008)",
            category="visual_metaphor_candidate",
            claim=(
                "Under a Visual Metaphor reading, the warm + saturated colour "
                "palette MAY function as a visual metaphor mapping WARMTH IS "
                "EMOTION/INTIMACY. This is a candidate only — the LLM must triage "
                "via MIPVU decision steps, and a human must verify before this "
                "counts as a confirmed metaphor (§9.16, load-bearing)."
            ),
            evidence=["colours.warm_cold_balance", "colours.saturation"],
            confidence=0.4,  # low — candidates only
        ))

    # Cross-modal metaphor: text + image mismatch
    if caption and ocr.text:
        text_lower = (caption + " " + ocr.text).lower()
        # If text mentions cold/neutral words but image is warm → possible irony/metaphor
        cold_words = ["cold", "ice", "frozen", "neutral", "objective", "distant"]
        if any(w in text_lower for w in cold_words) and colours.warm_cold_balance > 0.2:
            claims.append(DiscourseClaim(
                framework="Conceptual Metaphor Theory + Forceville (2008)",
                category="cross_modal_metaphor_candidate",
                claim=(
                    "Under a Cross-modal Metaphor reading, the mismatch between "
                    "cold-related text and warm-coloured image MAY function as an "
                    "ironic or metaphorical cross-modal mapping. This is a candidate "
                    "only — human verification required (§9.16)."
                ),
                evidence=["caption.text", "ocr.text", "colours.warm_cold_balance"],
                confidence=0.3,
            ))

    return DiscourseAnalysisResult(
        analysis_type="visual_metaphor",
        framework="Conceptual Metaphor Theory + Forceville (2008)",
        claims=claims,
        summary=f"Visual/cross-modal metaphor analysis produced {len(claims)} candidates (human verification required).",
    )


# --------------------------------------------------------------------------- #
# §9.17 Emotion Analysis (combined image + text)
# --------------------------------------------------------------------------- #


def analyse_combined_emotion(
    colours: ColourAnalysis,
    ocr: OCRResult,
    caption: str = "",
) -> DiscourseAnalysisResult:
    """Combined emotion analysis (§9.17) — image emotion + text emotion +
    combined emotion + intensity.
    """
    claims: list[DiscourseClaim] = []

    # Image emotion from colour + brightness
    image_emotion = "neutral"
    if colours.warm_cold_balance > 0.2 and colours.brightness > 150:
        image_emotion = "positive/warm"
    elif colours.warm_cold_balance < -0.2 and colours.brightness < 100:
        image_emotion = "negative/cold"
    elif colours.brightness > 200:
        image_emotion = "positive/bright"

    claims.append(DiscourseClaim(
        framework="Combined Emotion Analysis (colour + text lexicon)",
        category="image_emotion",
        claim=(
            f"Under a combined-emotion reading, the image's colour profile "
            f"(warm_cold={colours.warm_cold_balance:.2f}, brightness={colours.brightness:.0f}) "
            f"may suggest a {image_emotion} visual emotional tone. This is a "
            f"hypothesis derived from colour psychology, which is culture-relative."
        ),
        evidence=["colours.warm_cold_balance", "colours.brightness"],
        confidence=0.5,
    ))

    # Text emotion (reuses Phase 2 lexicon logic)
    text = (ocr.text + " " + caption).lower()
    positive_words = {"good", "great", "excellent", "wonderful", "happy", "love",
                      "beautiful", "success", "hope", "joy"}
    negative_words = {"bad", "terrible", "awful", "sad", "hate", "fear",
                      "fail", "crisis", "threat", "danger"}
    pos_count = sum(1 for w in positive_words if w in text)
    neg_count = sum(1 for w in negative_words if w in text)

    if pos_count + neg_count > 0:
        text_emotion = "positive" if pos_count > neg_count else "negative"
        claims.append(DiscourseClaim(
            framework="Combined Emotion Analysis (colour + text lexicon)",
            category="text_emotion",
            claim=(
                f"Under a combined-emotion reading, the text contains {pos_count} "
                f"positive and {neg_count} negative emotion words, suggesting a "
                f"{text_emotion} textual emotional tone."
            ),
            evidence=["ocr.text", "caption.text"],
            confidence=min(1.0, (pos_count + neg_count) / 5.0),
        ))

        # Combined: image vs text congruence
        if image_emotion.startswith("positive") and text_emotion == "negative":
            claims.append(DiscourseClaim(
                framework="Combined Emotion Analysis (colour + text lexicon)",
                category="emotional_mismatch",
                claim=(
                    "Under a combined-emotion reading, the image-positive + "
                    "text-negative mismatch MAY indicate irony, sarcasm, or "
                    "tension between what is shown and what is said. This is a "
                    "hypothesis requiring human verification."
                ),
                evidence=["colours", "ocr.text", "caption.text"],
                confidence=0.4,
            ))

    return DiscourseAnalysisResult(
        analysis_type="emotion",
        framework="Combined Emotion Analysis (colour + text lexicon)",
        claims=claims,
        summary=f"Combined emotion analysis produced {len(claims)} claims.",
    )


# --------------------------------------------------------------------------- #
# §9.18 Cultural Analysis (always culture-relative)
# --------------------------------------------------------------------------- #


def analyse_cultural(
    colours: ColourAnalysis,
    ocr: OCRResult,
    caption: str = "",
) -> DiscourseAnalysisResult:
    """Cultural analysis (§9.18) — culture-specific symbols, religious
    references, national identity, traditional clothing, architecture,
    colour symbolism.

    Per §9.18: "always framework/culture-relative, never presented as
    universal truths."
    """
    claims: list[DiscourseClaim] = []

    # Colour symbolism (already from §9.4.6, but reframed culturally)
    for note in colours.colour_symbolism_notes:
        claims.append(DiscourseClaim(
            framework="Cultural Analysis (Barthes 1957 Mythologies + Kress & van Leeuwen)",
            category="colour_symbolism_cultural",
            claim=(
                f"Under a Cultural reading, {note} Note: cultural symbolism is "
                f"NEVER universal — the same colour may carry different or "
                f"opposite meanings in different cultural contexts (§9.18)."
            ),
            evidence=["colours.dominant_colours"],
            confidence=0.4,  # low — culture-relative
        ))

    # Religious/cultural markers in text
    text_lower = (ocr.text + " " + caption).lower()
    religious_markers = ["god", "allah", "church", "mosque", "temple", "prayer",
                         "faith", "sacred", "holy", "blessed"]
    found_religious = [m for m in religious_markers if m in text_lower]
    if found_religious:
        claims.append(DiscourseClaim(
            framework="Cultural Analysis (Barthes 1957 Mythologies)",
            category="religious_reference",
            claim=(
                f"Under a Cultural reading, the presence of religious marker(s) "
                f"({', '.join(found_religious)}) may invoke a specific cultural-religious "
                f"frame. The meaning of these markers is culture-relative — they "
                f"may function differently for insider vs outsider audiences (§9.18)."
            ),
            evidence=["ocr.text", "caption.text"],
            confidence=0.5,
        ))

    national_markers = ["nation", "country", "flag", "homeland", "patriot",
                        "citizen", "people of"]
    found_national = [m for m in national_markers if m in text_lower]
    if found_national:
        claims.append(DiscourseClaim(
            framework="Cultural Analysis (Anderson 1983 Imagined Communities)",
            category="national_identity",
            claim=(
                f"Under a Cultural reading, the presence of national-identity "
                f"marker(s) ({', '.join(found_national)}) may construct an "
                f"'imagined community' (Anderson 1983) — invoking shared national "
                f"belonging. This is a hypothesis about the text's cultural work."
            ),
            evidence=["ocr.text", "caption.text"],
            confidence=0.5,
        ))

    return DiscourseAnalysisResult(
        analysis_type="cultural",
        framework="Cultural Analysis (Barthes + Anderson)",
        claims=claims,
        summary=f"Cultural analysis produced {len(claims)} culture-relative claims.",
    )
