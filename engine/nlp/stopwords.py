"""Shared stopword lists (English + Arabic) — single source of truth.

v1.0.1: previously the Arabic/English stopword lists lived privately in
``ingestion/cleaning.py`` and the Arabic pipeline marked ``is_stop=False``
for every token, which made all stopword filtering inert for Arabic
collocations and n-grams. Both the cleaning step and the Arabic tagger now
import from this module.

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


def is_arabic_stopword(dediacritized: str) -> bool:
    """Check a dediacritized Arabic token against the stopword set."""
    return dediacritized in ARABIC_STOPWORDS
