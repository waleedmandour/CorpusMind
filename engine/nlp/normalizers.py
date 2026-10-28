"""Per-language text normalizers (v1.2.11).

This module is the single source of truth for cross-script orthographic
normalization used by matching/aggregation (concordance, frequency,
collocation, keyness) and by the Vector KWIC embedding pre-processing.

Design rules (docs/METHODOLOGY.md §Normalization):

1. Arabic keeps its existing normalizer exactly (``ar_norm`` — the Python
   mirror of the SQL ``arnorm()`` scalar registered in storage.session).
   It is deliberately NOT applied to Persian/Urdu: those languages share the
   Arabic script but not Arabic orthographic rules (no teh-marbuta → he, no
   alef-maksura folding, no Arabic alef unification).
2. Persian/Urdu: unify Arabic-script lookalikes toward each language's own
   conventions — ي (U+064A) → ی (U+06CC) and ك (U+0643) → ک (U+06A9) for
   both; Urdu additionally folds bare Arabic he ه (U+0647) → gol he ہ
   (U+06C1) while keeping do-chashmi he ھ (U+06BE) distinct. Bari ye ے
   (U+06D2) is never folded into ی (they are distinct phonemes).
3. ZWNJ (U+200C) is meaningful inside Persian/Urdu words (e.g. می‌روم).
   The default keeps it. Two documented optional modes exist for matching
   spelled-variant aggregation: ``"space"`` (ZWNJ → space, so می‌روم and
   می روم match) and ``"strip"`` (ZWNJ removed, so می‌روم and میروم match).
   The SQL scalars ``fanorm``/``urnorm`` accept the mode as a second
   argument; the 1-argument form is keep-mode.
4. Hindi (Devanagari): NFC composition (so precomposed क़ and decomposed
   क + nukta become the same string), nukta folding (क़ → क), chandrabindu
   → anusvara folding (हैँ → हैं), NO case operations (Devanagari has no
   case). Danda । (U+0964) and double danda ॥ (U+0965) are preserved.
5. Digits are preserved verbatim by every normalizer here (Latin 0-9,
   Arabic-Indic ٠-٩, Extended Arabic-Indic ۰-۹, Devanagari ०-९). Cleaning
   (ingestion.cleaning) offers an optional remove-numbers step, but the
   normalizers never alter digit forms.
"""
from __future__ import annotations

import re
import unicodedata

# --------------------------------------------------------------------------- #
# ZWNJ
# --------------------------------------------------------------------------- #

ZWNJ = "\u200c"
_ZWNJ_RE = re.compile(ZWNJ)


def apply_zwnj_mode(text: str, mode: str) -> str:
    """Apply one of the documented ZWNJ modes to Persian/Urdu text.

    - ``"keep"``  (default): ZWNJ preserved (it is meaningful inside words).
    - ``"space"``: each ZWNJ becomes a single space (splits ZWNJ-joined
      compounds into their parts so می‌روم matches می روم).
    - ``"strip"``: each ZWNJ is removed (so می‌روم matches میروم).
    Unknown modes raise ValueError — silence here would corrupt matching.
    """
    if mode == "keep":
        return text
    if mode == "space":
        return _ZWNJ_RE.sub(" ", text)
    if mode == "strip":
        return _ZWNJ_RE.sub("", text)
    raise ValueError(f"unknown zwnj mode: {mode!r} (expected keep|space|strip)")


# --------------------------------------------------------------------------- #
# Persian (fa)
# --------------------------------------------------------------------------- #

# Arabic yeh → Persian yeh; Arabic kaf → Persian keheh.
_FA_CHAR_MAP = str.maketrans({
    "\u064A": "\u06CC",  # ي → ی
    "\u0643": "\u06A9",  # ك → ک
})


def fa_norm(text: str, zwnj: str = "keep") -> str:
    """Persian normalization — Python mirror of the SQL ``fanorm()`` scalar.

    - NFC compose (so combining-mark order does not split one spelling in two)
    - ي → ی and ك → ک (Arabic keyboard lookalikes fold onto Persian forms)
    - Arabic-script rules NOT applied: ة stays ة, ى stays ى, أ إ آ stay put
    - ZWNJ handled per the documented modes (default: preserved)
    - digits preserved (Latin, Arabic-Indic ٠-٩, Extended Arabic-Indic ۰-۹)
    """
    s = unicodedata.normalize("NFC", text)
    s = s.translate(_FA_CHAR_MAP)
    return apply_zwnj_mode(s, zwnj)


# --------------------------------------------------------------------------- #
# Urdu (ur)
# --------------------------------------------------------------------------- #

# Everything Persian folds, plus bare Arabic he → gol he. Do-chashmi he ھ
# (U+06BE) and bari ye ے (U+06D2) stay distinct on purpose.
_UR_CHAR_MAP = str.maketrans({
    "\u064A": "\u06CC",  # ي → ی
    "\u0643": "\u06A9",  # ك → ک
    "\u0647": "\u06C1",  # ه → ہ (bare Arabic he → gol he)
})


def ur_norm(text: str, zwnj: str = "keep") -> str:
    """Urdu normalization — Python mirror of the SQL ``urnorm()`` scalar.

    Same rules as Persian plus ه → ہ folding. ھ (do-chashmi he, the
    aspirate digraph second half) and ے (bari ye) are NOT folded — they are
    phonemically distinct in Urdu. Note: Urdu word segmentation from raw
    text is imperfect (spaces are unreliable in running Urdu text); the
    tokenizer handles common cases and the limitation is documented in
    docs/METHODOLOGY.md — this normalizer never inserts or deletes spaces
    (the optional "space" ZWNJ mode being the documented exception, since
    ZWNJ was typed deliberately).
    """
    s = unicodedata.normalize("NFC", text)
    s = s.translate(_UR_CHAR_MAP)
    return apply_zwnj_mode(s, zwnj)


# --------------------------------------------------------------------------- #
# Hindi (hi)
# --------------------------------------------------------------------------- #

_CHANDRABINDU = "\u0901"  # ँ
_ANUSVARA = "\u0902"      # ं
_NUKTA = "\u093C"         # combining nukta


def hi_norm(text: str) -> str:
    """Hindi (Devanagari) normalization — Python mirror of SQL ``hinorm()``.

    - NFC compose (precomposed क़ U+0958 and क + nukta become one form)
    - nukta removed after composition (क़ → क, ख़ → ख, ग़ → ग, ज़ → ज,
      फ़ → फ, य़ → य) — the loanword distinction is orthographic noise for
      matching/aggregation
    - chandrabindu → anusvara (हैँ → हैं) — the two nasalization marks are
      used interchangeably in running text
    - NO case operations (Devanagari has none)
    - danda । and double danda ॥ preserved; digits (Latin + Devanagari
      ०-९) preserved
    """
    s = unicodedata.normalize("NFC", text)
    s = s.replace(_CHANDRABINDU, _ANUSVARA)
    s = s.replace(_NUKTA, "")
    return s


# --------------------------------------------------------------------------- #
# English (en) — case folding only (existing _fold behavior in stats, kept
# here for the registry dispatch; the stats module keeps its own NFD-aware
# implementation for backward compatibility).
# --------------------------------------------------------------------------- #

def en_norm(text: str) -> str:
    """English normalization: plain lowercase (used by the registry dispatch
    for language-appropriate matching; the stats module's ``_fold`` adds NFD
    diacritic stripping for loanwords and stays the canonical en folder)."""
    return text.lower()


# --------------------------------------------------------------------------- #
# Dispatch helpers
# --------------------------------------------------------------------------- #

#: Maps a corpus language to its (python normalizer, sql scalar name) pair.
#: ``sql_arity2`` marks the scalars that accept the ZWNJ mode argument.
NORMALIZERS: dict[str, dict[str, object]] = {
    "en": {"kind": "en", "sql": None},
    "ar": {"kind": "ar", "sql": "arnorm"},
    "ur": {"kind": "ur", "sql": "urnorm"},
    "fa": {"kind": "fa", "sql": "fanorm"},
    "hi": {"kind": "hi", "sql": "hinorm"},
}


def normalize_for_language(text: str, language: str, zwnj: str = "keep") -> str:
    """Dispatch to the language-appropriate normalizer.

    Unknown languages fall back to plain lowercase — never to Arabic
    rules (an Urdu corpus must never be Arabic-folded just because the
    script overlaps).
    """
    lang = (language or "en").lower()
    if lang == "ur":
        return ur_norm(text, zwnj)
    if lang == "fa":
        return fa_norm(text, zwnj)
    if lang == "hi":
        return hi_norm(text)
    if lang == "ar":
        # Delegates to the canonical Arabic normalizer to keep one source of
        # truth; imported lazily to avoid a circular import with stats.
        from stats.service import ar_norm as _ar_norm
        return _ar_norm(text)
    return en_norm(text)
