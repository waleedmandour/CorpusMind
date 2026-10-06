"""Language capability registry (v1.2.11).

The single source of truth for what CorpusMind supports per corpus
language. The engine consumes this registry to:

* answer ``GET /api/v1/languages`` (consumed by the web UI for corpus
  creation, tagset display, and honest per-tool availability messages),
* select the language-appropriate normalizer (see nlp/normalizers.py),
* gate tools whose resources do not exist for a language (sentiment
  lexicons, USAS lexicons, English/A cue lenses, AWL bands, learner error
  rules) behind explicit statuses instead of silent fallbacks.

Design principles honored here (README "Non-Negotiable Design Principles"):

* Tools a language does not support are reported as such — in this registry,
  in the API responses, and in the UI. English and Arabic resources are
  NEVER silently applied to Urdu, Hindi, or Persian.
* Heuristics and lexicon lookups are labeled as such (``support`` values
  carry a reason a researcher can cite).

Support values: ``"supported"`` | ``"partial"`` (labeled with a reason) |
``"unavailable"`` (explicit message; usually with an install hint).
"""
from __future__ import annotations

from dataclasses import dataclass, field

# --------------------------------------------------------------------------- #
# Tool ids — stable strings surfaced through the API and consumed by the UI.
# --------------------------------------------------------------------------- #

TOOL_IDS: tuple[str, ...] = (
    "concordance",
    "frequency",
    "collocation",
    "keyness",
    "dispersion",
    "ngrams",
    "pos",
    "dependency",
    "readability",
    "vector_kwic",
    "learner_caf",
    "learner_errors",
    "sentiment",
    "discourse",
    "vocab_profile",
    "arabic_morphology",
)

# Shorthands so the per-language tool maps stay readable.
_S = "supported"
_P = "partial"
_U = "unavailable"


def _stat(support: str, note_key: str) -> dict[str, str]:
    """One tool-support entry: status + a machine-readable reason key.

    The UI translates the note keys (en/ar); the API also returns the
    human-readable English note so API consumers are never left guessing.
    """
    return {"support": support, "note": note_key}


@dataclass(frozen=True)
class LanguageCapability:
    """Everything the engine knows about one corpus language."""

    code: str                       # BCP-47 short code ("en", "ar", ...)
    name: str                       # English name
    native_name: str
    script: str                     # "Latin" | "Arabic" | "Perso-Arabic" | "Devanagari"
    direction: str                  # "ltr" | "rtl"
    normalizer: str                 # key into nlp.normalizers.NORMALIZERS
    sql_normalizer: str | None      # SQL scalar name (None = case-fold only)
    sentence_splitter: str          # human-readable, pinned in the recipe
    tokenizer: str
    tagger: str                     # "none" when no POS model is available
    lemmatizer: str
    parser: str
    stopword_count: int             # bundled editable list size (0 = none)
    reference_corpora: tuple[str, ...]  # registry names in reference_corpus/registry
    coverage_label: str             # short honest label, e.g. "tokenization + frequency only"
    tools: dict[str, dict[str, str]] = field(default_factory=dict)
    notes: str = ""


def _stats_tools(stanza: bool = False) -> dict[str, dict[str, str]]:
    """Tool matrix shared by Urdu/Hindi/Farsi (statistics run wherever
    tokenization runs; model-dependent layers are labeled honestly)."""
    return {
        "concordance": _stat(_S, "tokenization_supported"),
        "frequency": _stat(_S, "tokenization_supported"),
        "collocation": _stat(_S, "tokenization_supported"),
        "keyness": _stat(_S, "needs_reference_list"),
        "dispersion": _stat(_S, "tokenization_supported"),
        "ngrams": _stat(_S, "tokenization_supported"),
        "pos": _stat(_S if stanza else _P, "stanza_installed" if stanza else "stanza_optional"),
        "dependency": _stat(_S if stanza else _P, "stanza_installed" if stanza else "stanza_optional"),
        "readability": _stat(_P, "lix_rix_only"),
        "vector_kwic": _stat(_S, "bge_m3_multilingual"),
        "learner_caf": _stat(_S, "language_neutral_math"),
        "learner_errors": _stat(_U, "rules_en_ar_only"),
        "sentiment": _stat(_U, "lexicon_missing"),
        "discourse": _stat(_U, "taxonomies_en_ar_only"),
        "vocab_profile": _stat(_U, "bands_en_only"),
        "arabic_morphology": _stat(_U, "arabic_only"),
    }


URDU = LanguageCapability(
    code="ur",
    name="Urdu",
    native_name="اردو",
    script="Perso-Arabic",
    direction="rtl",
    normalizer="ur",
    sql_normalizer="urnorm",
    sentence_splitter="spaCy sentencizer (danda-style terminators incl. ۔ U+06D4) or Stanza when installed",
    tokenizer="spaCy blank tokenizer; Stanza tokenizer when installed (handles unreliable Urdu spacing as far as practical)",
    tagger="Stanza UPOS tagger when installed; none otherwise",
    lemmatizer="Stanza lemmatizer when installed; none otherwise (surface form kept)",
    parser="Stanza dependency parser when installed; none otherwise",
    stopword_count=94,
    reference_corpora=("urdu-freq-top1000",),
    coverage_label="tokenization + statistics; POS/lemma/parse via optional Stanza",
    tools=_stats_tools(),
    notes=(
        "Urdu shares the Arabic script with Persian but has its own "
        "normalizer (ه→ہ folding; ي→ی, ك→ک; ZWNJ modes). Arabic rules "
        "(ة→ه, ى→ي, alef unification) are never applied. Word "
        "segmentation is imperfect because spaces are unreliable in "
        "running Urdu; flagged wherever results depend on it."
    ),
)

HINDI = LanguageCapability(
    code="hi",
    name="Hindi",
    native_name="हिन्दी",
    script="Devanagari",
    direction="ltr",
    normalizer="hi",
    sql_normalizer="hinorm",
    sentence_splitter="spaCy sentencizer (danda । U+0964 and double danda ॥ U+0965) or Stanza when installed",
    tokenizer="spaCy blank tokenizer; Stanza tokenizer when installed",
    tagger="Stanza UPOS tagger when installed; none otherwise",
    lemmatizer="Stanza lemmatizer when installed; none otherwise (surface form kept)",
    parser="Stanza dependency parser when installed; none otherwise",
    stopword_count=103,
    reference_corpora=("hindi-freq-top1000",),
    coverage_label="tokenization + statistics; POS/lemma/parse via optional Stanza",
    tools=_stats_tools(),
    notes=(
        "Hindi is not conflated with Urdu (different script and lexicon) "
        "or with Marathi (the engine's detection heuristics and the "
        "explicit corpus-language field keep them apart). Nukta "
        "(क़/क) and chandrabindu/anusvara variants fold per the "
        "documented normalization; no case folding exists."
    ),
)

FARSI = LanguageCapability(
    code="fa",
    name="Farsi (Persian)",
    native_name="فارسی",
    script="Perso-Arabic",
    direction="rtl",
    normalizer="fa",
    sql_normalizer="fanorm",
    sentence_splitter="spaCy sentencizer (Latin + Arabic interrogative ؟) or Stanza when installed",
    tokenizer="spaCy blank tokenizer (ZWNJ preserved inside words); Stanza tokenizer when installed",
    tagger="Stanza UPOS tagger when installed; none otherwise",
    lemmatizer="Stanza lemmatizer when installed; none otherwise (surface form kept)",
    parser="Stanza dependency parser when installed; none otherwise",
    stopword_count=87,
    reference_corpora=("farsi-freq-top1000",),
    coverage_label="tokenization + statistics; POS/lemma/parse via optional Stanza",
    tools=_stats_tools(),
    notes=(
        "Persian ZWNJ (U+200C) is meaningful inside words (می‌روم) and is "
        "preserved by default; documented keep/space/strip modes exist "
        "for matching. Arabic normalization is never applied to Persian."
    ),
)


def _en_tools() -> dict[str, dict[str, str]]:
    return {t: _stat(_S, "full_support") for t in TOOL_IDS}


def _ar_tools() -> dict[str, dict[str, str]]:
    return {
        "concordance": _stat(_S, "full_support"),
        "frequency": _stat(_S, "full_support"),
        "collocation": _stat(_S, "full_support"),
        "keyness": _stat(_S, "needs_reference_list"),
        "dispersion": _stat(_S, "full_support"),
        "ngrams": _stat(_S, "full_support"),
        "pos": _stat(_S, "camel_tools"),
        "dependency": _stat(_P, "camel_morphology_no_ud_parse"),
        "readability": _stat(_P, "lix_rix_only"),
        "vector_kwic": _stat(_S, "bge_m3_multilingual"),
        "learner_caf": _stat(_S, "language_neutral_math"),
        "learner_errors": _stat(_S, "ar_rules"),
        "sentiment": _stat(_S, "starter_lexicon"),
        "discourse": _stat(_P, "usas_bilingual_other_lenses_en"),
        "vocab_profile": _stat(_U, "bands_en_only"),
        "arabic_morphology": _stat(_S, "camel_tools"),
    }


ENGLISH = LanguageCapability(
    code="en",
    name="English",
    native_name="English",
    script="Latin",
    direction="ltr",
    normalizer="en",
    sql_normalizer=None,
    sentence_splitter="spaCy parser (en_core_web_sm)",
    tokenizer="spaCy en_core_web_sm",
    tagger="spaCy tagger (PTB) + UPOS morphologizer",
    lemmatizer="spaCy rule-based lemmatizer",
    parser="spaCy dependency parser (UD)",
    stopword_count=0,  # replaced below with the real count at import
    reference_corpora=("be06_top1000", "leipzig_news_top100", "bnc_baby", "bawe", "leipzig_english_news_10k", "pd_persuasive_top1000", "ellipse_learner_top1000"),
    coverage_label="full pipeline",
    tools=_en_tools(),
    notes="",
)

ARABIC = LanguageCapability(
    code="ar",
    name="Arabic",
    native_name="العربية",
    script="Arabic",
    direction="rtl",
    normalizer="ar",
    sql_normalizer="arnorm",
    sentence_splitter="ArabicPipeline sentence splitter (MSA terminals; decimal-aware)",
    tokenizer="CAMeL Tools calima-msa-r13 morphology + clitic segmentation",
    tagger="CAMeL Tools morphological tagger (calima POS) mapped to UPOS",
    lemmatizer="CAMeL Tools lemmatizer (diacritic-aware, user-controlled)",
    parser="none (morphology-level; no UD parse for Arabic in the engine)",
    stopword_count=0,  # replaced below with the real count at import
    reference_corpora=("quranic_arabic_freq", "camel_arabic_top1000", "leipzig_arabic_news_10k", "dialectal_tweets_top1000"),
    coverage_label="full pipeline except dependency parse and vocab bands",
    tools=_ar_tools(),
    notes="Arabic behavior is regression-guarded by golden tests (test_language_golden.py).",
)


def _registry() -> dict[str, LanguageCapability]:
    # Resolve stopword counts from the live lists so the registry cannot drift
    # from nlp/stopwords.py (single source of truth stays the list itself).
    from nlp.stopwords import (
        ARABIC_STOPWORDS,
        ENGLISH_STOPWORDS,
        FARSI_STOPWORDS,
        HINDI_STOPWORDS,
        URDU_STOPWORDS,
    )

    def _with_count(cap: LanguageCapability, count: int) -> LanguageCapability:
        return LanguageCapability(
            code=cap.code, name=cap.name, native_name=cap.native_name,
            script=cap.script, direction=cap.direction, normalizer=cap.normalizer,
            sql_normalizer=cap.sql_normalizer, sentence_splitter=cap.sentence_splitter,
            tokenizer=cap.tokenizer, tagger=cap.tagger, lemmatizer=cap.lemmatizer,
            parser=cap.parser, stopword_count=count,
            reference_corpora=cap.reference_corpora,
            coverage_label=cap.coverage_label, tools=cap.tools, notes=cap.notes,
        )

    return {
        "en": _with_count(ENGLISH, len(ENGLISH_STOPWORDS)),
        "ar": _with_count(ARABIC, len(ARABIC_STOPWORDS)),
        "ur": _with_count(URDU, len(URDU_STOPWORDS)),
        "hi": _with_count(HINDI, len(HINDI_STOPWORDS)),
        "fa": _with_count(FARSI, len(FARSI_STOPWORDS)),
    }


LANGUAGES: dict[str, LanguageCapability] = _registry()

#: The order shown in UI selectors.
LANGUAGE_ORDER: tuple[str, ...] = ("en", "ar", "ur", "hi", "fa")


def get_capability(language: str) -> LanguageCapability | None:
    """Return the capability record for ``language`` (None if unknown)."""
    return LANGUAGES.get((language or "").lower())


def is_known_language(language: str) -> bool:
    return (language or "").lower() in LANGUAGES


def tool_support(language: str, tool: str) -> dict[str, str] | None:
    """Return {support, note} for (language, tool), or None if unknown."""
    cap = get_capability(language)
    if cap is None:
        return None
    return cap.tools.get(tool)


def tool_support_label(language: str, tool: str) -> str:
    """Convenience: just the support string ("supported"|"partial"|"unavailable")."""
    entry = tool_support(language, tool)
    return entry["support"] if entry else "unknown"


def serialize() -> dict[str, object]:
    """JSON-safe registry for ``GET /api/v1/languages``.

    Includes per-tool human-readable notes so the UI and API consumers can
    show exactly why a tool is partial/unavailable for a language.
    """
    return {
        "languages": [
            {
                "code": cap.code,
                "name": cap.name,
                "native_name": cap.native_name,
                "script": cap.script,
                "direction": cap.direction,
                "normalizer": cap.normalizer,
                "sql_normalizer": cap.sql_normalizer,
                "sentence_splitter": cap.sentence_splitter,
                "tokenizer": cap.tokenizer,
                "tagger": cap.tagger,
                "lemmatizer": cap.lemmatizer,
                "parser": cap.parser,
                "stopword_count": cap.stopword_count,
                "reference_corpora": list(cap.reference_corpora),
                "coverage_label": cap.coverage_label,
                "notes": cap.notes,
                "tools": {tool: dict(entry) for tool, entry in cap.tools.items()},
            }
            for cap in (LANGUAGES[c] for c in LANGUAGE_ORDER)
        ],
    }
