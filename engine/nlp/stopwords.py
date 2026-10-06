"""Shared stopword lists — single source of truth.

v1.0.1: previously the Arabic/English stopword lists lived privately in
``ingestion/cleaning.py`` and the Arabic pipeline marked ``is_stop=False``
for every token, which made all stopword filtering inert for Arabic
collocations and n-grams. Both the cleaning step and the Arabic tagger now
import from this module.

v1.2.11: added Urdu, Hindi, and Farsi (Persian) lists so corpora in those
languages get working stopword filtering for collocations, n-grams, frequency
lists, and the cleaning step. Each list is a compact closed-class set
(prepositions, pronouns, conjunctions, particles, auxiliaries) — content
words are never stop words here, matching the existing English/Arabic
convention. Surface forms only (no dediacritization); Farsi entries include
both ZWNJ-joined and joined spellings where the variation is common.

The Arabic list is a compact MSA function-word set (dediacritized forms —
match tokens after removing diacritics). It intentionally keeps closed-class
items only; content words are never stop words here.
"""
from __future__ import annotations

ENGLISH_STOPWORDS: frozenset[str] = frozenset({
    "a", "an", "and", "are", "as", "at", "be", "been", "but", "by", "can",
    "could", "did", "do", "does", "for", "from", "had", "has", "have", "he",
    "her", "him", "his", "i", "if", "in", "into", "is", "it", "its", "may",
    "might", "must", "not", "of", "on", "or", "our", "shall", "she", "should",
    "since", "so", "some", "than", "that", "the", "their", "them", "then",
    "there", "these", "they", "this", "those", "to", "was", "we", "were",
    "what", "when", "where", "which", "while", "who", "whom", "will", "with",
    "would", "you", "your",
})

# Dediacritized MSA function words (حروف و ضمائر و أدوات)
ARABIC_STOPWORDS: frozenset[str] = frozenset({
    "من", "الى", "عن", "على", "في", "مع", "بين", "تحت", "فوق",
    "هذا", "هذه", "ذلك", "تلك", "الذي", "التي", "الذين", "هو", "هي", "هم",
    "هن", "انا", "انت", "نحن", "كان", "كانت", "يكون", "تكون", "قد", "لقد",
    "لا", "ما", "لم", "لن", "ان", "أن", "إن", "اذا", "إذا", "كل", "بعض",
    "غير", "او", "أو", "و", "ف", "ب", "ل", "ك", "حتى", "ثم", "ايضا",
    "أيضا", "عند", "عندما", "بينما", "لكن", "بل", "أي", "هناك", "هنا",
    "كما", "منه", "منها", "عليه", "عليها", "به", "بها", "له", "لها",
})

# --------------------------------------------------------------------------- #
# Urdu function words (حروف، ضمائر، حروف ربط، معاون افعال)
# --------------------------------------------------------------------------- #
# Compact MSA-style set covering standard Urdu function words in Nastaliq
# script. Includes common variant spellings (e.g. ی / ئ / ے for yeh).
URDU_STOPWORDS: frozenset[str] = frozenset({
    # pronouns
    "میں", "مجھ", "مجھے", "ہم", "ہمیں", "تو", "تم", "تمہیں", "آپ", "وہ",
    "ان", "انہیں", "یہ", "انہی", "کون", "کسی", "کچھ", "جو", "جس", "جن",
    "اپنا", "اپنے", "اپنی", "اس", "اسے", "اسکا", "اسکی", "اسکے", "انکا",
    "انکی", "انکے", "تمہارا", "تمہاری", "آپکا", "آپکی", "میرا", "میری",
    "ہمارا", "ہماری",
    # postpositions / case markers
    "کا", "کے", "کی", "نے", "کو", "سے", "میں", "پر", "تک", "بھر", "واسطے",
    "لیے", "لئے", "بارے",
    # conjunctions
    "اور", "یا", "مگر", "لیکن", "پر", "کیونکہ", "چونکہ", "اگر", "تو",
    "اسلئے", "اسلیے", "گے",
    # particles / negation
    "نہ", "نہیں", "ہاں", "بھی", "ہی", "تونہ", "تو", "سب", "ہر", "کوئی",
    "اگرچہ", "بلکہ", "ورنہ",
    # auxiliaries / copulas
    "ہے", "ہیں", "تھا", "تھے", "ہوگا", "ہوگی", "ہوں", "ہو", "تھی", "تھیں",
    # misc function words
    "جب", "تب", "یہاں", "وہاں", "کہ", "تو", "پھر", "اب", "پہلے", "بعد",
    "ایک",
})

# --------------------------------------------------------------------------- #
# Hindi function words (कारक, सर्वनाम, संयोजक, क्रिया-सहायक)
# --------------------------------------------------------------------------- #
# Compact set of standard Hindi function words in Devanagari script.
HINDI_STOPWORDS: frozenset[str] = frozenset({
    # pronouns
    "मैं", "मुझ", "मुझे", "मेरा", "मेरी", "मेरे", "हम", "हमें", "हमारा",
    "हमारी", "तू", "तुम", "तुम्हें", "तुम्हारा", "तुम्हारी", "आप", "आपका",
    "आपकी", "वह", "उस", "उसे", "उसका", "उसकी", "वे", "उन", "उन्हें",
    "उनका", "उनकी", "यह", "इस", "इसे", "इसका", "इसकी", "ये", "इन",
    "इन्हें", "कौन", "किसे", "किसी", "कुछ", "जो", "जिस", "जिसे", "जो",
    # postpositions / case markers
    "का", "के", "की", "ने", "को", "से", "में", "पर", "तक", "भर", "लिए",
    "वास्ते", "बारे", "साथ", "द्वारा",
    # conjunctions
    "और", "या", "मगर", "लेकिन", "पर", "क्योंकि", "चूंकि", "अगर", "तो",
    "इसलिए", "अत", "अतः",
    # particles / negation
    "नहीं", "न", "हां", "भी", "ही", "सब", "हर", "कोई", "अगरच", "बल्कि",
    "वरना",
    # auxiliaries / copulas
    "है", "हैं", "था", "थे", "थी", "थीं", "होगा", "होगी", "हूँ", "हों",
    "हो",
    # misc function words
    "जब", "तब", "यहाँ", "वहाँ", "कि", "फिर", "अब", "पहले", "बाद", "एक",
    "कुछ", "सा", "से", "मात्र",
})

# --------------------------------------------------------------------------- #
# Farsi / Persian function words (حروف، ضمائر، حروف ربط، افعال کمکی)
# --------------------------------------------------------------------------- #
# Compact set of standard Persian function words in Arabic script.
# ZWNJ (U+200C) variants are included for the most common splits, e.g.
# ``آن‌ها`` (with ZWNJ) and ``آنها`` (without) are both in the set so the
# match works regardless of which form the source text uses.
FARSI_STOPWORDS: frozenset[str] = frozenset({
    # pronouns — both ZWNJ and joined spellings
    "من", "تو", "او", "ما", "شما", "آن‌ها", "آنها", "این‌ها", "اینها",
    "آن", "این", "آن‌که", "آنکه", "چه", "کسی", "ککه", "که", "همه", "هیچ",
    "هر", "چند", "خود", "خویش", "یک", "چیزی", "چیز",
    # prepositions
    "در", "به", "از", "با", "برای", "تا", "روی", "زیر", "پشت", "کنار",
    "بی", "بدون", "جز", "مثل", "مانند", "طی", "طریق",
    # conjunctions
    "و", "یا", "اما", "ولی", "چون", "اگر", "که", "بنابراین", "پس", "زیرا",
    "لیکن",
    # particles / negation / emphasis
    "نه", "نیز", "هم", "فقط", "حتی", "البته", "گرچه", "بلکه", "وگرنه",
    "بله",
    # auxiliaries / copulas
    "است", "هست", "هستند", "بود", "بودند", "شد", "شدند", "می‌شود",
    "میشود", "شده", "باشد", "باشند", "می‌باشد", "میباشد",
    # misc function words
    "وقتی", "کجا", "چرا", "چگونه", "اینکه", "آنکه", "ها", "های", "تر",
    "تری", "ترین",
})


# --------------------------------------------------------------------------- #
# Registry — maps a BCP-47 short code to its stopword frozenset.
# Used by ingestion/cleaning.py and any other module that needs to look up
# the right list by corpus language. Returns frozenset() for languages with
# no bundled list (callers should treat empty-set as "no filtering").
# --------------------------------------------------------------------------- #

_STOPWORDS_BY_LANG: dict[str, frozenset[str]] = {
    "en": ENGLISH_STOPWORDS,
    "ar": ARABIC_STOPWORDS,
    "ur": URDU_STOPWORDS,
    "hi": HINDI_STOPWORDS,
    "fa": FARSI_STOPWORDS,
}


def get_stopwords(language: str) -> frozenset[str]:
    """Return the stopword frozenset for ``language`` (BCP-47 short code).

    Returns an empty frozenset for languages with no bundled list, so callers
    can treat the result as "filter nothing" without special-casing. The
    matching is case-insensitive for the language code but case-sensitive for
    the tokens themselves (matching the existing English/Arabic convention;
    callers that need case-insensitive token matching should lowercase first).
    """
    return _STOPWORDS_BY_LANG.get((language or "").lower(), frozenset())


def is_stopword(token: str, language: str) -> bool:
    """Check a token against the stopword set for ``language``.

    Returns False for languages with no bundled list. For Arabic, callers
    that already have a dediacritized token should prefer
    :func:`is_arabic_stopword` which documents that expectation; this
    function does NOT dediacritize — it matches the surface form.
    """
    return token in get_stopwords(language)


def is_arabic_stopword(dediacritized: str) -> bool:
    """Check a dediacritized Arabic token against the stopword set.

    Kept for backward compatibility with the Arabic pipeline, which
    dediacritizes before checking. For non-Arabic languages or for callers
    that want surface-form matching, use :func:`is_stopword` instead.
    """
    return dediacritized in ARABIC_STOPWORDS
