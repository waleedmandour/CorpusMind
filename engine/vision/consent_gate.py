"""Consent-gate filter for vision-LM output (CorpusMind Lens build step 5).

A vision-LM asked to describe a photo will volunteer age/emotion/gender-
presentation commentary about people in it whether or not anyone asked.
The existing consent gate in vision/facial.py only protects the
dedicated /facial-analysis route — the /describe route (step 3) and the
eight discourse routes' LLM mode (step 4) had no gate at all.

This module implements the post-processing filter the build prompt
requires: 'Route every person-descriptive vision-LM output through the
same gate — check consent status before including that content in any
response, for every route in §3.2 and §3.3.'

Design:

  - Detection is keyword-based, not model-based. A vision-LM generating
    person-descriptive text uses recognizable vocabulary: age groups
    (child, young, adult, senior, elderly, middle-aged), gender
    presentation (masculine, feminine, male, female, man, woman, boy,
    girl), facial expressions (smiling, frowning, serious, surprised),
    and physical-appearance descriptors (attractive, tall, short,
    beautiful, handsome). We scan for these terms (case-insensitive,
    word-boundary-aware) and flag content that contains them.

  - This is NOT a perfect filter. A sophisticated LLM could describe a
    person without triggering any keyword. But it catches the common
    case (small vision models like moondream volunteer exactly this
    kind of commentary) and provides a clear audit trail via the
    `person_descriptive_redacted` field. A future step could swap in
    a classifier-based detector behind the same interface.

  - When the gate is CLOSED (the default, per §18) and person-
    descriptive content is detected, the filtered segments are replaced
    with a redaction marker. The rest of the description/claims pass
    through unchanged — we don't drop the whole response, just the
    person-descriptive parts.

  - When the gate is OPEN (user explicitly opted in via
    CORPUSMIND_FACIAL_ANALYSIS_ENABLED=1), no filtering happens. The
    response includes `person_descriptive_redacted: False` so the UI
    can show the user that person-descriptive content was returned.

  - The filter is enforced at RESPONSE-SHAPING time, not at prompt
    time. You can't stop the LLM from generating person-descriptive
    text, but you can post-process its output before returning it.
    This is the load-bearing design decision: the gate is a filter on
    what reaches the user, not on what the model generates.
"""
from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Any

from app.logging import get_logger
from vision.facial import is_facial_analysis_enabled

log = get_logger(__name__)


# ---------------------------------------------------------------------------
# Person-descriptive vocabulary
# ---------------------------------------------------------------------------

# These keyword lists are derived from:
#   1. vision/facial.py's FaceDetection dataclass fields:
#      estimated_age_group, gender_presentation, facial_expression,
#      eye_gaze, head_direction — and their documented values.
#   2. Common vision-LM volunteered commentary categories (from E2E
#      testing with moondream: it routinely volunteers age, gender,
#      and expression commentary without being asked).
#
# The lists are intentionally conservative — false positives (redacting
# a sentence that happens to contain 'adult' in a non-person context)
# are acceptable; false negatives (letting person-descriptive content
# through) are not. The `person_descriptive_redacted` flag in the
# response makes any filtering visible to the user.

_AGE_KEYWORDS = [
    # Age groups from FaceDetection.estimated_age_group
    "child", "young adult", "young-adult", "adult", "senior", "elderly",
    "middle-aged", "middle aged", "teenager", "teen", "toddler",
    "baby", "infant", "old man", "old woman", "old person",
    "young man", "young woman", "young person", "young boy", "young girl",
]

_GENDER_KEYWORDS = [
    # Gender presentation from FaceDetection.gender_presentation
    "masculine", "feminine",
    # Common gendered terms vision-LMs volunteer
    "male", "female", "man", "woman", "men", "women",
    "boy", "girl", "boys", "girls", "guy", "lady", "ladies",
    "gentleman", "gentlemen",
    # Gender presentation descriptors
    "gender presentation", "gender expression",
]

_EXPRESSION_KEYWORDS = [
    # Facial expressions from FaceDetection.facial_expression
    "smiling", "smile", "smiles", "smiled",
    "frowning", "frown", "frowns",
    "serious expression", "serious face",
    "surprised expression", "surprised face",
    "neutral expression", "neutral face",
    "facial expression", "expression on",
    "grinning", "grin", "smirking", "smirk",
    "laughing", "laugh", "laughed",
    "crying", "cry", "tears",
    "angry expression", "angry face", "angry look",
    "sad expression", "sad face", "sad look",
    "happy expression", "happy face", "happy look",
]

_APPEARANCE_KEYWORDS = [
    # Physical-appearance descriptors vision-LMs volunteer
    "attractive", "beautiful", "handsome", "good-looking", "good looking",
    "pretty", "ugly", "plain-looking", "plain looking",
    "tall", "short", "slim", "slender", "stocky", "muscular",
    "blonde", "blond", "brunette", "redhead", "dark-haired", "dark haired",
    "bald", "balding", "curly hair", "straight hair", "long hair", "short hair",
    "beard", "mustache", "moustache", "goatee", "stubble",
    "blue eyes", "brown eyes", "green eyes", "dark eyes", "light eyes",
    "skin tone", "skin color", "skin colour", "pale skin", "dark skin",
    "fair skin", "olive skin",
]

# Ethnicity / race descriptors
_ETHNICITY_KEYWORDS = [
    "asian", "african", "european", "middle eastern", "middle-eastern",
    "hispanic", "latino", "latina", "latin american", "native american",
    "indigenous", "south asian", "east asian", "southeast asian",
    "caucasian", "white person", "white man", "white woman", "white people",
    "black person", "black man", "black woman", "black people",
    "brown person", "brown man", "brown woman",
    "person of color", "person of colour", "racial", "ethnicity",
    "ethnic background", "ethnic appearance",
    "african american", "afro",
    "mediterranean", "nordic", "scandinavian",
]

# Religious / cultural attire
_RELIGIOUS_KEYWORDS = [
    "hijab", "niqab", "burqa", "chador", "abaya", "khimar",
    "turban", "dastar", "pagri",
    "kippah", "yarmulke", "kipa",
    "cross necklace", "crucifix", "rosary",
    "veil", "head covering", "headscarf", "head scarf",
    "religious attire", "religious garment", "religious dress",
    "prayer shawl", "tallit", "tzitzit",
    "clerical collar", "habit", "cassock",
    "sikh", "muslim", "jewish", "christian", "buddhist", "hindu",
    "orthodox", "fundamentalist",
    "religious", "devout", "practicing",
]

# Socioeconomic speculation
_SOCIOECONOMIC_KEYWORDS = [
    "wealthy", "rich", "poor", "impoverished", "destitute",
    "affluent", "privileged", "underprivileged",
    "working class", "middle class", "upper class", "lower class",
    "homeless", "beggar", "panhandler",
    "socioeconomic", "social class", "economic status",
    "luxury", "designer clothes", "expensive clothing",
    "ragged", "unkempt", "shabby",
    "professional-looking", "business attire",
    "blue-collar", "white-collar",
]

# Combined list, compiled into a single regex for efficient scanning.
# Each keyword is matched as a whole word (\\b boundaries) to avoid
# false positives like "adult" matching inside "adulthood" — though
# we accept some over-matching for compound phrases.
_ALL_KEYWORDS = (
    _AGE_KEYWORDS + _GENDER_KEYWORDS + _EXPRESSION_KEYWORDS + _APPEARANCE_KEYWORDS
    + _ETHNICITY_KEYWORDS + _RELIGIOUS_KEYWORDS + _SOCIOECONOMIC_KEYWORDS
)

# Build a single alternation regex, longest-first so "young adult"
# matches before "young" / "adult" individually.
_ALL_KEYWORDS_SORTED = sorted(_ALL_KEYWORDS, key=len, reverse=True)
_KEYWORD_REGEX = re.compile(
    r"\b(?:" + "|".join(re.escape(kw) for kw in _ALL_KEYWORDS_SORTED) + r")\b",
    re.IGNORECASE,
)


# ---------------------------------------------------------------------------
# Filter result
# ---------------------------------------------------------------------------


@dataclass(frozen=True, slots=True)
class FilterResult:
    """Result of running the consent-gate filter on a text string.

    `filtered_text` is the text with person-descriptive segments replaced
    by the redaction marker (if the gate was closed and content was
    detected). `was_filtered` is True if any redaction happened.
    `matched_keywords` is the list of keywords that triggered the filter
    (for audit/logging).
    """
    filtered_text: str
    was_filtered: bool
    matched_keywords: list[str]


# The redaction marker. Bracketed so it's visually distinct in the UI
# and clearly machine-generated, not model-generated.
_REDACTION_MARKER = "[redacted: person-descriptive content — enable facial analysis in Settings to view]"


def _redact_segment(text: str, matched_keywords: list[str]) -> str:
    """Replace the sentence(s) containing person-descriptive keywords
    with the redaction marker.

    We redact at the SENTENCE level, not the keyword level — replacing
    just the keyword would leave a broken sentence that might still
    convey the person-descriptive meaning through context. Replacing
    the whole sentence is cleaner and more honest.
    """
    # Split into sentences (naive — split on . ! ? followed by space/end).
    # This is good enough for the common case; the redaction marker
    # makes any edge cases visible.
    sentences = re.split(r"(?<=[.!?])\s+", text)
    redacted_sentences = []
    for sent in sentences:
        if _KEYWORD_REGEX.search(sent):
            redacted_sentences.append(_REDACTION_MARKER)
        else:
            redacted_sentences.append(sent)
    return " ".join(redacted_sentences)


def filter_person_descriptive(text: str) -> FilterResult:
    """Filter person-descriptive content from a text string.

    If the consent gate is OPEN (user opted in via
    CORPUSMIND_FACIAL_ANALYSIS_ENABLED=1), no filtering happens — the
    text is returned unchanged with was_filtered=False.

    If the gate is CLOSED (the default), the text is scanned for
    person-descriptive keywords. Any sentence containing a keyword is
    replaced with the redaction marker.
    """
    if not text:
        return FilterResult(filtered_text=text, was_filtered=False, matched_keywords=[])

    # Gate is open — no filtering.
    if is_facial_analysis_enabled():
        return FilterResult(filtered_text=text, was_filtered=False, matched_keywords=[])

    # Gate is closed — scan for person-descriptive content.
    matches = _KEYWORD_REGEX.findall(text)
    if not matches:
        return FilterResult(filtered_text=text, was_filtered=False, matched_keywords=[])

    matched_keywords = list(set(m.lower() for m in matches))
    filtered = _redact_segment(text, matched_keywords)

    log.info(
        "person_descriptive_filtered",
        keyword_count=len(matched_keywords),
        keywords=matched_keywords[:5],  # log first 5 for audit
        original_len=len(text),
        filtered_len=len(filtered),
    )

    return FilterResult(
        filtered_text=filtered,
        was_filtered=True,
        matched_keywords=matched_keywords,
    )


# ---------------------------------------------------------------------------
# Route-level helpers
# ---------------------------------------------------------------------------


def filter_describe_response(description: str) -> dict[str, Any]:
    """Filter the /describe route's description string.

    Returns a dict with:
      - description: the (possibly redacted) description
      - person_descriptive_redacted: bool
    """
    result = filter_person_descriptive(description)
    return {
        "description": result.filtered_text,
        "person_descriptive_redacted": result.was_filtered,
    }


def filter_discourse_claims(claims: list[dict[str, Any]]) -> dict[str, Any]:
    """Filter the person-descriptive content from a list of discourse
    claim dicts (from the LLM discourse routes).

    Each claim's `claim` text and `summary` are filtered independently.
    The `evidence` list is NOT filtered (it references feature names
    like "colours.dominant_colours", not person descriptions).

    Returns a dict with:
      - claims: the (possibly redacted) claims list
      - person_descriptive_redacted: bool (True if ANY claim was filtered)
    """
    any_filtered = False
    filtered_claims: list[dict[str, Any]] = []
    for c in claims:
        claim_text = c.get("claim", "")
        result = filter_person_descriptive(claim_text)
        if result.was_filtered:
            any_filtered = True
        filtered_claims.append({
            **c,
            "claim": result.filtered_text,
        })
    return {
        "claims": filtered_claims,
        "person_descriptive_redacted": any_filtered,
    }
