"""
Arabic NLP backend abstraction (§8.21, §3.3).

Per the spec: "Build an abstraction layer so the engine can call whichever
backend is best per task/dialect, rather than committing to one."

This module exposes one `ArabicPipeline` interface with concrete backends:
  - CamelBackend (default): CAMeL Tools morphology (calima-msa-r13 + dialects)
  - FarasaBackend: Farasa segmentation/POS/lemmatization (Phase 3+ — install on demand)
  - SinaToolsBackend: SinaTools (Phase 3+ — install on demand)

Phase 3 ships the CAMeL Tools backend fully wired. Farasa and SinaTools are
stubbed but the abstraction is in place so they can be swapped in without
touching the rest of the engine.

Arabic-specific features exposed (§8.21):
  - Root extraction (الجذر)
  - Pattern (وزن) identification
  - Lemma normalization
  - Diacritics handling (removal or retention, user-controlled)
  - Buckwalter transliteration
  - Clitic segmentation
  - Dialect identification (Gulf, Egyptian, Levantine, MSA, Classical)
"""
from __future__ import annotations

import functools
from dataclasses import dataclass
from typing import Any, Protocol

from app.logging import get_logger

log = get_logger(__name__)


# --------------------------------------------------------------------------- #
# Public types
# --------------------------------------------------------------------------- #


@dataclass(frozen=True, slots=True)
class ArabicToken:
    """One Arabic token with morphological annotations."""
    text: str                 # surface form
    lemma: str                # lemma (with diacritics if available)
    root: str                 # triliteral root, e.g. "ك.ت.ب"
    pattern: str              # morphological pattern, e.g. "يُ1ْ2ِ3"
    pos: str                  # POS tag (verb, noun, adj, prep, etc.)
    stem: str                 # stem
    buckwalter: str           # Buckwalter transliteration
    dediacritized: str        # diacritics removed
    dialect: str = "msa"      # detected dialect (msa, egy, glf, lev, classical)


@dataclass(frozen=True, slots=True)
class ArabicAnalysis:
    text: str
    tokens: list[ArabicToken]
    detected_dialect: str
    backend: str


@dataclass(frozen=True, slots=True)
class ArabicBackendInfo:
    name: str
    version: str
    model: str
    dialects_supported: list[str]


class ArabicBackend(Protocol):
    def info(self) -> ArabicBackendInfo: ...
    def analyze(self, text: str, *, dediacritize: bool = False) -> ArabicAnalysis: ...
    def identify_dialect(self, text: str) -> dict[str, float]: ...


# --------------------------------------------------------------------------- #
# CAMeL Tools backend (default)
# --------------------------------------------------------------------------- #


# Map CAMeL dialect DB names to friendly labels
_CAMEL_DIALECT_DBS = {
    "msa": "calima-msa-r13",
    "egy": "calima-egy-r13",
    "glf": "calima-glf-01",
    "lev": "calima-lev-01",
}


class CamelBackend:
    """CAMeL Tools backend — the default for §8.21.

    Uses:
      - camel_tools.tokenizers.word.simple_word_tokenize for tokenization
      - camel_tools.morphology.analyzer.Analyzer for morphology (root, pattern, lemma, pos)
      - camel_tools.utils.dediac.dediac_ar for diacritics removal
      - camel_tools.utils.charmap.CharMapper for Buckwalter transliteration
      - camel_tools.utils.normalize for character normalization
    """

    name = "camel"

    def __init__(self, default_dialect: str = "msa") -> None:
        self._default_dialect = default_dialect
        self._analyzers: dict[str, Any] = {}  # dialect → Analyzer (lazy)
        self._bw_mapper: Any = None
        self._info: ArabicBackendInfo | None = None

    def _load(self) -> None:
        if self._analyzers:
            return
        import camel_tools
        from camel_tools.morphology.analyzer import Analyzer
        from camel_tools.morphology.database import MorphologyDB
        from camel_tools.utils.charmap import CharMapper

        log.info("camel_loading", dialect=self._default_dialect)
        # Load the default dialect's morphology DB
        db_name = _CAMEL_DIALECT_DBS.get(self._default_dialect, "calima-msa-r13")
        db = MorphologyDB.builtin_db(db_name)
        self._analyzers[self._default_dialect] = Analyzer(db)
        self._bw_mapper = CharMapper.builtin_mapper("ar2bw")

        self._info = ArabicBackendInfo(
            name="camel",
            version=camel_tools.__version__ if hasattr(camel_tools, "__version__") else "1.5+",
            model=db_name,
            dialects_supported=list(_CAMEL_DIALECT_DBS.keys()),
        )
        log.info("camel_loaded", model=db_name)

    def info(self) -> ArabicBackendInfo:
        self._load()
        assert self._info is not None
        return self._info

    def analyze(self, text: str, *, dediacritize: bool = False) -> ArabicAnalysis:
        self._load()
        from camel_tools.tokenizers.word import simple_word_tokenize
        from camel_tools.utils.dediac import dediac_ar

        tokens_raw = simple_word_tokenize(text)
        analyzer = self._analyzers[self._default_dialect]

        arabic_tokens: list[ArabicToken] = []
        for tok_text in tokens_raw:
            # Skip whitespace + punct (simple check)
            if not tok_text.strip() or tok_text in {".", ",", "!", "؟", "،", ";", ":"}:
                continue
            # Skip pure-Latin tokens (mixed-language text)
            if all(ord(c) < 128 for c in tok_text):
                continue

            analyses = analyzer.analyze(tok_text)
            if not analyses:
                # Out-of-vocabulary — fall back to surface form as lemma
                arabic_tokens.append(ArabicToken(
                    text=tok_text,
                    lemma=tok_text,
                    root="",
                    pattern="",
                    pos="x",
                    stem=tok_text,
                    buckwalter=self._bw_mapper.map_string(tok_text),
                    dediacritized=dediac_ar(tok_text),
                    dialect=self._default_dialect,
                ))
                continue

            # Take the first analysis (CAMeL returns analyses ranked by frequency)
            a = analyses[0]
            arabic_tokens.append(ArabicToken(
                text=tok_text,
                lemma=a.get("lex", tok_text),
                root=a.get("root", ""),
                pattern=a.get("pattern", ""),
                pos=a.get("pos", "x"),
                stem=a.get("stem", tok_text),
                buckwalter=self._bw_mapper.map_string(tok_text),
                dediacritized=dediac_ar(tok_text),
                dialect=self._default_dialect,
            ))

        return ArabicAnalysis(
            text=text,
            tokens=arabic_tokens,
            detected_dialect=self._default_dialect,
            backend="camel",
        )

    def identify_dialect(self, text: str) -> dict[str, float]:
        """Phase 3 stub — full dialect ID requires the dialectid model
        (274 MB). Returns a trivial {msa: 1.0} until the model is bundled.
        Phase 4 will swap in camel_tools.dialectid.DialectIdentifier."""
        # Heuristic: if any Egyptian markers (بقى, عايز, ليه), flag as egy
        # This is a placeholder — real dialect ID needs the model.
        if any(w in text for w in ("عايز", "ليه", "بقى", "إيه")):
            return {"egy": 0.6, "msa": 0.3, "lev": 0.05, "glf": 0.05}
        if any(w in text for w in ("شلون", "وايد", "كول", "ليش")):
            return {"glf": 0.6, "msa": 0.3, "lev": 0.05, "egy": 0.05}
        if any(w in text for w in ("شو", "هلق", "هيك", "كتير")):
            return {"lev": 0.6, "msa": 0.3, "egy": 0.05, "glf": 0.05}
        return {"msa": 0.85, "egy": 0.05, "glf": 0.05, "lev": 0.05}


# --------------------------------------------------------------------------- #
# Stub backends for Farasa + SinaTools (Phase 3+ — install on demand)
# --------------------------------------------------------------------------- #


class FarasaBackend:
    """Farasa backend (stub). Install with: pip install farasapy.

    Use case: fast segmentation when speed matters more than tagset
    granularity. Smaller tagset than CAMeL but very fast.
    """
    name = "farasa"

    def __init__(self) -> None:
        raise NotImplementedError(
            "Farasa backend not yet wired. Install with `pip install farasapy` "
            "and re-run. The interface is defined here so it can be swapped in "
            "without touching the rest of the engine."
        )

    def info(self) -> ArabicBackendInfo: ...
    def analyze(self, text: str, *, dediacritize: bool = False) -> ArabicAnalysis: ...
    def identify_dialect(self, text: str) -> dict[str, float]: ...


class SinaToolsBackend:
    """SinaTools backend (stub). Install with: pip install sinatools.

    Use case: competitive speed/accuracy across multiple Arabic NLP tasks.
    Per §3.3, SinaTools led on both speed and accuracy in independent
    benchmarking on two tasks.
    """
    name = "sinatools"

    def __init__(self) -> None:
        raise NotImplementedError(
            "SinaTools backend not yet wired. Install with `pip install sinatools` "
            "and re-run. The interface is defined here so it can be swapped in "
            "without touching the rest of the engine."
        )

    def info(self) -> ArabicBackendInfo: ...
    def analyze(self, text: str, *, dediacritize: bool = False) -> ArabicAnalysis: ...
    def identify_dialect(self, text: str) -> dict[str, float]: ...


# --------------------------------------------------------------------------- #
# Registry: maps (backend_name, dialect) → backend instance (cached)
# --------------------------------------------------------------------------- #


@functools.lru_cache(maxsize=4)
def get_arabic_backend(backend: str = "camel", dialect: str = "msa") -> ArabicBackend:
    """Return a cached Arabic backend instance.

    Defaults: CAMeL Tools + MSA. Phase 4+ may branch on dialect to load
    the appropriate CAMeL DB (Egyptian, Gulf, Levantine).
    """
    if backend == "camel":
        return CamelBackend(default_dialect=dialect)
    if backend == "farasa":
        return FarasaBackend()
    if backend == "sinatools":
        return SinaToolsBackend()
    raise ValueError(f"Unknown Arabic backend: {backend}")


# --------------------------------------------------------------------------- #
# Public API used by the API routes + grounded-AI tools
# --------------------------------------------------------------------------- #


def analyze_arabic(text: str, *, backend: str = "camel", dialect: str = "msa",
                   dediacritize: bool = False) -> ArabicAnalysis:
    """Analyze Arabic text — tokenize + morphology (root, pattern, lemma, pos)
    + Buckwalter transliteration + dialect detection."""
    b = get_arabic_backend(backend, dialect)
    return b.analyze(text, dediacritize=dediacritize)


def identify_arabic_dialect(text: str, *, backend: str = "camel") -> dict[str, float]:
    """Identify the Arabic dialect of a text. Returns a distribution over
    {msa, egy, glf, lev, classical}."""
    b = get_arabic_backend(backend)
    return b.identify_dialect(text)


def extract_arabic_roots(text: str) -> list[dict]:
    """Extract roots (الجذر) from Arabic text. Returns one dict per token:
    {token, root, pattern, lemma}."""
    analysis = analyze_arabic(text)
    return [{
        "token": t.text,
        "root": t.root,
        "pattern": t.pattern,
        "lemma": t.lemma,
        "pos": t.pos,
        "buckwalter": t.buckwalter,
    } for t in analysis.tokens if t.root]


def segment_arabic_clitics(text: str) -> list[dict]:
    """Segment Arabic clitics (التصاق الضمائر والات). Uses CAMeL's
    simple_word_tokenize + the morphology analyzer's stem field as a
    first-pass segmentation. Phase 4 will swap in a proper clitic segmenter
    (CAMeL's `MorphologyDB` with `clitic` segmentation enabled)."""
    analysis = analyze_arabic(text)
    return [{
        "surface": t.text,
        "stem": t.stem,
        "pos": t.pos,
    } for t in analysis.tokens]


def transliterate_buckwalter(text: str) -> str:
    """Transliterate Arabic text to Buckwalter encoding (Latin)."""
    from camel_tools.utils.charmap import CharMapper
    bw = CharMapper.builtin_mapper("ar2bw")
    return bw.map_string(text)


def dediacritize_arabic(text: str) -> str:
    """Remove Arabic diacritics (التشكيل) from text."""
    from camel_tools.utils.dediac import dediac_ar
    return dediac_ar(text)


def normalize_arabic(text: str) -> str:
    """Normalize Arabic text (alef variants, teh marbuta, alef maksura)."""
    from camel_tools.utils.normalize import (
        normalize_alef_ar,
        normalize_alef_maksura_ar,
        normalize_teh_marbuta_ar,
    )
    text = normalize_alef_ar(text)
    text = normalize_alef_maksura_ar(text)
    text = normalize_teh_marbuta_ar(text)
    return text


def detect_arabic_register(text: str) -> dict[str, float]:
    """Detect Arabic register: Classical (Quranic/Classical), MSA, or Dialectal.
    Phase 3 heuristic — Phase 4 will use a proper classifier."""
    # Very rough heuristic: presence of Classical markers (إنّ, قال, فعل) vs MSA
    classical_markers = {"إنّ", "قال", "فعل", "كان", "الذي", "التي", "يا أيها"}
    dialect_markers = {"عايز", "شلون", "شو", "هيك", "ليش", "بقى"}
    text_words = set(text.split())
    c_score = sum(1 for m in classical_markers if m in text_words)
    d_score = sum(1 for m in dialect_markers if m in text_words)
    total = c_score + d_score + 1
    return {
        "classical": round(c_score / total, 3),
        "msa": round(1 / total, 3),
        "dialectal": round(d_score / total, 3),
    }
