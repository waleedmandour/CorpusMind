"""Readability formulas — v1.0.1 addition.

Classic English formulas (Flesch family) plus two language-neutral indices
(LIX, RIX) that only need word/sentence/long-word counts, so they also work
for Arabic and other non-voweled scripts where syllable counting is invalid.

All functions take raw counts (not text) so callers can compute them from
the tokenized database without re-parsing, and remain unit-testable against
published worked examples.
"""
from __future__ import annotations

import re

# --------------------------------------------------------------------------- #
# English syllable counter (heuristic)
# --------------------------------------------------------------------------- #

_VOWEL_GROUPS = re.compile(r"[aeiouy]+")

# -ed/-es that do NOT add a syllable: after most consonants ('walked',
# 'cakes') they are silent; after t/d ('wanted') and sibilants ('buses',
# 'watches') they do add one. -le after a consonant ('table', 'candle')
# IS syllabic; other silent-final -e ('large', 'name') is not.
_SILENT_ED = re.compile(r"[^aeiouytd]ed$")
_SILENT_ES = re.compile(r"[^aeiouyszx]es$")
_SILENT_E = re.compile(r"[^aeiouy]e$")
_SYLLABIC_LE = re.compile(r"[^aeiouy]le$")


def count_syllables_en(word: str) -> int:
    """Heuristic English syllable count (vowel-group method).

    Rules: count vowel groups; subtract a silent trailing -e (but never the
    syllabic consonant+le ending, e.g. 'table'); subtract silent -ed/-es
    after non-t/d, non-sibilant consonants. Never return fewer than 1.
    Good enough for corpus-level readability screening — the same trade-off
    every desktop corpus tool makes.
    """
    w = word.lower().strip(".,;:!?'\"()[]{}")
    if not w:
        return 0
    n = len(_VOWEL_GROUPS.findall(w))
    if n > 1:
        if _SYLLABIC_LE.search(w):
            pass  # consonant+le counts as its own syllable
        elif _SILENT_E.search(w):
            n -= 1
        elif _SILENT_ED.search(w) or _SILENT_ES.search(w):
            n -= 1
    return max(1, n)


# --------------------------------------------------------------------------- #
# Flesch family (English)
# --------------------------------------------------------------------------- #


def flesch_reading_ease(avg_sentence_length: float, avg_syllables_per_word: float) -> float:
    """FRE = 206.835 − 1.015·ASL − 84.6·ASW  (Flesch 1948). Higher = easier."""
    return 206.835 - 1.015 * avg_sentence_length - 84.6 * avg_syllables_per_word


def flesch_kincaid_grade(avg_sentence_length: float, avg_syllables_per_word: float) -> float:
    """FKGL = 0.39·ASL + 11.8·ASW − 15.59  (Kincaid et al. 1975). U.S. grade level."""
    return 0.39 * avg_sentence_length + 11.8 * avg_syllables_per_word - 15.59


# --------------------------------------------------------------------------- #
# Language-neutral indices
# --------------------------------------------------------------------------- #


def lix(total_words: int, sentences: int, long_words: int) -> float:
    """LIX = (words / sentences) + 100 · (long words / words)  (Björnsson 1968).

    Long word = more than 6 characters. Language-neutral: needs only word,
    sentence and long-word counts — valid for Arabic and other scripts.
    Interpretation: < 30 very easy … > 60 very difficult.
    """
    if total_words <= 0 or sentences <= 0:
        return 0.0
    return (total_words / sentences) + 100.0 * (long_words / total_words)


def rix(long_words: int, sentences: int) -> float:
    """RIX = long words / sentences  (Anderson 1983) — LIX's ratio-only sibling."""
    if sentences <= 0:
        return 0.0
    return long_words / sentences


# --------------------------------------------------------------------------- #
# Convenience
# --------------------------------------------------------------------------- #


def readability_from_counts(
    *,
    words: int,
    sentences: int,
    syllables: int,
    long_words: int,
    language: str = "en",
) -> dict:
    """Assemble the full readability panel from raw counts.

    Flesch formulas are only meaningful for English (syllable counting in
    Arabic script is not valid), so they are returned as ``None`` for other
    languages; LIX/RIX are always returned.
    """
    asl = words / sentences if sentences > 0 else 0.0
    asw = syllables / words if words > 0 else 0.0
    out: dict = {
        "words": words,
        "sentences": sentences,
        "avg_sentence_length": round(asl, 2),
        "long_words": long_words,
        "lix": round(lix(words, sentences, long_words), 2),
        "rix": round(rix(long_words, sentences), 2),
        "flesch_reading_ease": None,
        "flesch_kincaid_grade": None,
    }
    if language == "en" and words > 0 and sentences > 0:
        out["flesch_reading_ease"] = round(flesch_reading_ease(asl, asw), 2)
        out["flesch_kincaid_grade"] = round(flesch_kincaid_grade(asl, asw), 2)
    return out
