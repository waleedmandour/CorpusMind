"""Tagset registry + mapping tables (v1.2.0, Issue 4).

The engine tags text with spaCy (English) or CAMeL Tools (Arabic) and
stores TWO grammatical layers per token:

  - ``Token.pos``      — Universal Dependencies UPOS (17 tags)
  - ``Token.pos_fine`` — the language's fine-grained XPOS layer:
      English  → Penn Treebank tag (spaCy ``tag_``)
      Arabic   → the raw CAMeL/Calima morphological tag (v1.2.0)

Analyses historically used UPOS only. This module declares the tagsets a
user can select (in the "Your Corpus" window or the analysis panels) and
knows how to map the stored layers onto each requested tagset:

  Grammatical (en) : ``upos``  (UD, default) | ``ptb`` (Penn Treebank)
                     | ``claws7`` (BNC/Sketch-Engine standard, mapped
                     from PTB — a documented approximation)
  Grammatical (ar) : ``upos``  (UD, default) | ``calima`` (native CAMeL)
  Semantic         : ``usas``  (UCREL Semantic Analysis System,
                     top-level letter categories; lexicon-based and
                     experimental — see reference-data/tagsets/)

Adding a new tagset:
  1. Append a ``TagsetSpec`` to ``TAGSETS``.
  2. If it needs a mapping, add one below and wire it in ``map_tag``.
"""

from __future__ import annotations

import os
from dataclasses import dataclass
from functools import lru_cache
from typing import Literal

TagsetKind = Literal["grammatical", "semantic"]


@dataclass(frozen=True, slots=True)
class TagsetSpec:
    """One selectable tagset (see module docstring)."""

    id: str
    """Stable identifier used in API requests and pipeline_recipe."""

    display_name: str
    """Human-readable label for selectors."""

    kind: TagsetKind
    """``grammatical`` (POS layers) or ``semantic`` (USAS)."""

    languages: tuple[str, ...]
    """BCP-47 short tags this tagset applies to; ``("en", "ar", ...)`` or
    universal tagsets list every supported language."""

    description: str
    """One-paragraph description shown in the UI tooltip / picker."""

    source_note: str = ""
    """Provenance / standard reference, surfaced for citability."""


TAGSETS: list[TagsetSpec] = [
    TagsetSpec(
        id="upos",
        display_name="Universal Dependencies (UPOS)",
        kind="grammatical",
        languages=("en", "ar", "fr", "de", "es", "zh"),
        description=(
            "The 17-tag universal POS inventory of the Universal "
            "Dependencies project. Language-independent, the corpus "
            "linguistics default, and what CorpusMind stores natively."
        ),
        source_note="https://universaldependencies.org/u/pos/",
    ),
    TagsetSpec(
        id="ptb",
        display_name="Penn Treebank",
        kind="grammatical",
        languages=("en",),
        description=(
            "The classic ~36-tag English tagset (NN, VBD, IN, ...) used "
            "by the Penn Treebank and most English treebanks. CorpusMind "
            "stores it natively as the fine POS layer."
        ),
        source_note="Marcus et al. (1993), Building a large annotated corpus of English: the Penn Treebank.",
    ),
    TagsetSpec(
        id="claws7",
        display_name="CLAWS-7",
        kind="grammatical",
        languages=("en",),
        description=(
            "The ~150-tag C7 tagset used by the BNC and Sketch Engine, "
            "the de-facto standard in corpus linguistics. Approximated "
            "here by mapping Penn Treebank tags (documented mapping); "
            "unmappable tags surface as UNC."
        ),
        source_note="http://ucrel.lancs.ac.uk/claws/ (approximation via PTB mapping)",
    ),
    TagsetSpec(
        id="calima",
        display_name="CAMeL / Calima (native Arabic)",
        kind="grammatical",
        languages=("ar",),
        description=(
            "The native morphological tagset of the CAMeL Tools Calima "
            "analyzers (noun, verb, adj, prep, pron, part_neg, ...), "
            "standard for MSA and dialect Arabic morphology."
        ),
        source_note="CAMeL Tools — https://camel.readthedocs.io/",
    ),
    TagsetSpec(
        id="usas",
        display_name="USAS — semantic (top-level)",
        kind="semantic",
        languages=("en", "ar"),
        description=(
            "UCREL Semantic Analysis System: the top-level letter "
            "categories of the USAS semantic tagset (A = general/abstract, "
            "Z = names & grammatical words, ...). Lexicon-based "
            "approximation, experimental."
        ),
        source_note="https://ucrel.lancs.ac.uk/usas/ — lexicon: UCREL Multilingual-USAS (CC BY-NC-SA 4.0)",
    ),
]

_TAGSET_INDEX = {s.id: s for s in TAGSETS}

# Tagsets valid per corpus language (grammatical only — semantic handled
# by the semantic-analysis endpoint).
_GRAMMATICAL_BY_LANG: dict[str, list[str]] = {
    "en": ["upos", "ptb", "claws7"],
    "ar": ["upos", "calima"],
    # Universal default for other languages
    "fr": ["upos"],
    "de": ["upos"],
    "es": ["upos"],
    "zh": ["upos"],
}


def get_tagset(tagset_id: str) -> TagsetSpec | None:
    return _TAGSET_INDEX.get(tagset_id)


def valid_tagsets_for_language(language: str, kind: TagsetKind = "grammatical") -> list[str]:
    """Tagset ids valid for ``language``, first entry = recommended default."""
    lang = (language or "en").lower()
    if kind == "grammatical":
        return _GRAMMATICAL_BY_LANG.get(lang, ["upos"])
    # semantic: USAS ships en + ar lexicons
    return ["usas"] if lang in ("en", "ar") else []


def is_valid_tagset(tagset_id: str, language: str, kind: TagsetKind = "grammatical") -> bool:
    return tagset_id in valid_tagsets_for_language(language, kind)


# --------------------------------------------------------------------------- #
# PTB → CLAWS-7 mapping (documented approximation)
# --------------------------------------------------------------------------- #
# spaCy's English ``tag_`` emits Penn Treebank tags (with a few OTB
# extensions: WP$, EX, ...). The table maps each PTB tag to its most
# common CLAWS-7 counterpart. This is the standard "coarse mapping"
# approach used by web corpus tools; it is NOT a licensed CLAWS tagger —
# tags that genuinely depend on context (e.g. "that" IN/CST/DT) resolve
# to their most frequent class. Tags not in the table surface as "UNC".
# References: Santorini (1990) PTB tagging guidelines; CLAWS C7 tagset
# (http://ucrel.lancs.ac.uk/claws7tags.html).
PTB_TO_CLAWS7: dict[str, str] = {
    # Nouns
    "NN": "NN1",
    "NNS": "NN2",
    "NNP": "NP1",
    "NNPS": "NP2",
    # Verbs
    "VB": "VVI",
    "VBD": "VVD",
    "VBG": "VVG",
    "VBN": "VVN",
    "VBP": "VVB",
    "VBZ": "VVZ",
    # Modals + auxiliaries map to the verb classes they behave like
    "MD": "VM0",
    # Adjectives / adverbs
    "JJ": "JJ",
    "JJR": "JJR",
    "JJS": "JJT",
    "RB": "RR",
    "RBR": "RRR",
    "RBS": "RRT",
    "WRB": "RRQ",
    # Pronouns
    "PRP": "PPH",
    "PRP$": "APPGE",
    "WP": "PNQ",
    "WP$": "APPGE",
    "EX": "EX0",
    # Determiners / quantifiers
    "DT": "AT",
    "PDT": "DB",
    "WDT": "AT",
    "CD": "MC",
    # Conjunctions / prepositions / particles
    "IN": "PR",
    "TO": "TO",
    "CC": "CC",
    "RP": "RP",
    # Interjection / particle / infinitival
    "UH": "UH",
    "POS": "APPGE",
    "SYM": "ZZ",
    "LS": "ZZ",
    ".": ".",
    ",": ",",
    ":": ":",
    "``": "``",
    "''": "''",
    "-LRB-": "(",
    "-RRB-": ")",
    "$": "ZZ",
    "#": "ZZ",
    "HYPH": "-",
    # spaCy-specific fine tags that appear in tag_ for sm models
    "ADD": "ZZ",
    "AFX": "JJ",
    "GW": "NN1",
    "NFP": ".",
    "SP": "AT",
    "-NONE-": "UNC",
}

CLAWS7_UNMAPPED = "UNC"

# UD UPOS → CLAWS-7 fallback for tokens whose fine layer is empty
UPOS_TO_CLAWS7: dict[str, str] = {
    "NOUN": "NN1",
    "PROPN": "NP1",
    "VERB": "VVB",
    "AUX": "VM0",
    "ADJ": "JJ",
    "ADV": "RR",
    "PRON": "PPH",
    "DET": "AT",
    "ADP": "PR",
    "CCONJ": "CC",
    "SCONJ": "CSC",
    "NUM": "MC",
    "PART": "RP",
    "INTJ": "UH",
    "PUNCT": ".",
    "SYM": "ZZ",
    "X": "UNC",
}

# --------------------------------------------------------------------------- #
# USAS top-level categories (24 letter fields of the USAS hierarchy)
# --------------------------------------------------------------------------- #

USAS_TOP_LABELS: dict[str, str] = {
    "A": "General and abstract terms",
    "B": "The body and the individual",
    "C": "Arts and crafts",
    "D": "Emotional actions, states and processes",
    "E": "Food and farming",
    "F": "Furniture and household fittings",
    "G": "Government and the public domain",
    "H": "Architecture, houses and the home",
    "I": "Money and commerce in industry",
    "J": "Leisure, culture and sport",
    "K": "Life and living things",
    "L": "Substances, materials, objects and equipment",
    "M": "Movement, location, travel and transport",
    "N": "Numbers and measurement",
    "O": "Hard to classify",
    "P": "Education",
    "Q": "Linguistic actions, states and processes",
    "R": "Political actions, states and processes",
    "S": "Social actions, states and processes",
    "T": "Time",
    "W": "World and nature",
    "X": "Psychological actions, states and processes",
    "Y": "Science and technology",
    "Z": "Names and grammatical words",
}


def map_tag(
    tagset: str,
    *,
    pos: str,
    pos_fine: str,
    language: str = "en",
) -> str:
    """Map a stored token annotation onto the requested grammatical tagset.

    Falls back through the fine layer → coarse layer → UNC so the
    distribution never loses a token.
    """
    if tagset == "upos":
        return pos or "X"
    if tagset == "ptb":
        if (language or "en") != "en":
            return pos or "X"
        return pos_fine or pos or "X"
    if tagset == "claws7":
        if (language or "en") != "en":
            return pos or "X"
        if pos_fine:
            mapped = PTB_TO_CLAWS7.get(pos_fine)
            if mapped:
                return mapped
        return UPOS_TO_CLAWS7.get(pos, CLAWS7_UNMAPPED)
    if tagset == "calima":
        if (language or "en") != "ar":
            return pos or "X"
        # pos_fine carries the raw CAMeL tag (v1.2.0); older versions
        # stored the stem there — fall back to UPOS.
        return pos_fine or pos or "X"
    # Unknown grammatical tagset → degrade to UPOS rather than fail
    return pos or "X"


# --------------------------------------------------------------------------- #
# USAS semantic lexicon loading
# --------------------------------------------------------------------------- #

ARABIC_DIACRITICS = "ًٌٍَُِّْٰـ"


def strip_diacritics(text: str) -> str:
    return "".join(c for c in text if c not in ARABIC_DIACRITICS)


def _tagsets_data_dir() -> str:
    # Same resolution pattern as api/research.py for reference-data:
    # engine/nlp/../../reference-data/tagsets
    return os.path.join(os.path.dirname(__file__), "..", "..", "reference-data", "tagsets")


@lru_cache(maxsize=4)
def load_semantic_lexicon(language: str) -> dict[str, str]:
    """lemma → USAS top-level letter. Cached per process; empty dict when
    the lexicon file is missing (the API then reports the tagset as
    unavailable instead of failing)."""
    lang = (language or "en").lower()
    path = os.path.join(_tagsets_data_dir(), f"usas-{lang}-top.tsv")
    lexicon: dict[str, str] = {}
    try:
        with open(path, encoding="utf-8") as fh:
            next(fh)  # header
            for line in fh:
                parts = line.rstrip("\n").split("\t")
                if len(parts) >= 2 and parts[0]:
                    lexicon.setdefault(parts[0], parts[1])
    except FileNotFoundError:
        import logging

        logging.getLogger(__name__).warning("semantic_lexicon_missing", extra={"path": path})
    return lexicon


def semantic_lookup(lemma: str, text: str, language: str) -> str | None:
    """USAS top-level tag for a token, or None if the lexicon misses it."""
    lex = load_semantic_lexicon(language)
    if not lex:
        return None
    if (language or "en").lower() == "ar":
        candidates = [
            strip_diacritics(lemma or ""),
            strip_diacritics(text or ""),
        ]
    else:
        candidates = [(lemma or "").lower(), (text or "").lower()]
    for c in candidates:
        if c and c in lex:
            return lex[c]
    return None
