"""Heuristic script/language detection (v1.2.11).

A small, honest, character-frequency heuristic used ONLY as a fallback when
no corpus language is provided (learner CAF auto-detection). It is labeled
as a heuristic everywhere it surfaces, and it exists to prevent one specific
wrong behavior: Arabic-script text being routed into Arabic-only resources
when the text is actually Persian or Urdu.

Detection order (first match wins):

1. Devanagari characters present -> ``"hi"``. Devanagari is shared by
   Marathi, Nepali, and Sanskrit; CorpusMind supports Hindi, so the
   fallback maps Devanagari to ``hi`` and the corpus-language field (which
   the UI always sets) remains the authoritative signal. The limitation is
   documented here rather than hidden.
2. Urdu-specific letters present (ٹ ڈ ڑ ں ھ ے and the Kashmiri-style
   forms) -> ``"ur"``. These letters do not occur in Persian or MSA.
3. Persian letters (پ چ ژ گ) or ZWNJ (U+200C) present -> ``"fa"``. These
   letters also occur in Urdu, so this check runs AFTER the Urdu check;
   Arabic-script text containing them is at least as likely Persian as
   anything else, and never Arabic.
4. Arabic-specific letters (ة ؤ ئ ٰ) present -> ``"ar"``.
5. Otherwise, if any Arabic-script character is present -> ``"ar"`` (plain
   MSA uses none of the distinctive letters; the fallback matches the
   pre-v1.2.11 behavior for genuinely ambiguous input and is safe because
   every caller treats ``ar`` as "rules that exist").
6. Otherwise -> ``"en"``.

Near-miss handling is pinned by tests (tests/test_script_detect.py): mixed
Arabic/Urdu documents, Persian with Arabic punctuation, Hindi without
danda, and Urdu with Persian loanwords only.
"""
from __future__ import annotations

import re

_DEVANAGARI = re.compile(r"[\u0900-\u097F]")
_ARABIC_SCRIPT = re.compile(r"[\u0600-\u06FF\u0750-\u077F\uFB50-\uFDFF\uFE70-\uFEFF]")

# Urdu-specific letters: ٹ (ṭe) ڈ (ḍāl) ڑ (ṛe) ں (noon ghunna) ھ
# (do-chashmi he) ے (bari ye) ۀ (he with yeh above? no - that is Arabic
# hamza-on-he; excluded). Chars chosen so they NEVER occur in Persian/MSA.
_URDU_SPECIFIC = set("\u0679\u0688\u0691\u06BA\u06BE\u06D2")
# Persian letters shared with Urdu but absent from MSA.
_PERSIAN_LETTERS = set("\u067E\u0686\u0698\u06AF")  # پ چ ژ گ
_ZWNJ = "\u200c"
# Arabic-specific letters absent from Persian/Urdu running text.
_ARABIC_SPECIFIC = set("\u0629\u0624\u0626\u0670")  # ة ؤ ئ ٰ


def detect_language(text: str) -> str:
    """Return the heuristic language code for ``text``.

    Never raises; unknown input returns ``"en"``. See the module docstring
    for the ordered rules and their limitations.
    """
    if not text:
        return "en"
    if _DEVANAGARI.search(text):
        return "hi"
    if not _ARABIC_SCRIPT.search(text):
        return "en"
    if any(ch in _URDU_SPECIFIC for ch in text):
        return "ur"
    if any(ch in _PERSIAN_LETTERS for ch in text) or _ZWNJ in text:
        return "fa"
    # Persian keyboard codepoints: kaf U+06A9 and yeh U+06CC are NEVER used
    # by Arabic (Arabic writes ك U+0643 and ي U+064A). Persian/Urdu text
    # typed on a Persian-style keyboard carries them even when no other
    # distinctive letter appears — the mixed English/Persian near-miss.
    if "\u06A9" in text or "\u06CC" in text:
        return "fa"
    if any(ch in _ARABIC_SPECIFIC for ch in text):
        return "ar"
    return "ar"
