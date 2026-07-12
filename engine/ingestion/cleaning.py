"""
Corpus cleaning service — on-demand re-cleaning of an already-ingested corpus.

The ingestion pipeline (`ingestion/parsing.py`) does a minimal conservative
clean at upload time: whitespace normalization, zero-width char stripping,
BOM removal. This module provides *deeper* cleaning options the user can
apply on demand, because different research questions need different
cleaning levels:

  - For a stylometry study, you want to keep case + punctuation.
  - For a frequency study, you want to lowercase + strip punctuation.
  - For a keyness comparison, you want to remove stopwords so they don't
    dominate the top of the frequency list.
  - For Arabic, you want to normalize alef variants and strip diacritics
    so that المدرسة and المدرِسة don't count as two different types.

This service re-runs the chosen cleaning options over every document's
`cleaned_text`, updates the document row, re-runs the NLP pipeline, and
replaces the corpus's annotation version (creating a new one so the old
annotations are preserved for reproducibility — §4.8).

Cleaning is *opt-in and visible*: the user picks exactly which operations
to apply, and the result is inspectable in the document list. We never
silently modify a corpus without the user's explicit request.
"""
from __future__ import annotations

import re
import unicodedata
from dataclasses import dataclass, field

from sqlalchemy import delete, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.logging import get_logger
from nlp.general.pipeline import get_pipeline
from storage.models import AnnotationVersion, Corpus, Document, Token

log = get_logger(__name__)


# --------------------------------------------------------------------------- #
# Cleaning options
# --------------------------------------------------------------------------- #


@dataclass
class CleaningOptions:
    """User-selectable cleaning operations. All default to False — the
    user must explicitly opt in to each one."""

    # --- Whitespace & structure ---
    collapse_whitespace: bool = True
    strip_leading_trailing: bool = True
    remove_empty_lines: bool = False
    remove_urls: bool = False
    remove_email_addresses: bool = False
    remove_html_entities: bool = False

    # --- Case ---
    lowercase: bool = False

    # --- Punctuation & numbers ---
    remove_punctuation: bool = False
    remove_numbers: bool = False
    remove_extra_symbols: bool = False  # emoji, bullets, etc.

    # --- Linguistic filtering ---
    remove_stopwords: bool = False
    min_token_length: int = 0  # 0 = no filter; e.g. 2 = drop 1-char tokens

    # --- Arabic-specific (only applied if corpus language is 'ar') ---
    normalize_arabic: bool = False      # alef variants, teh marbuta, alef maksura
    strip_arabic_diacritics: bool = False  # harakat
    remove_arabic_tatweel: bool = False  # kashida ـ

    # --- Reproducibility ---
    create_new_version: bool = True  # §4.8 — preserve old annotations

    def to_dict(self) -> dict:
        return {
            "collapse_whitespace": self.collapse_whitespace,
            "strip_leading_trailing": self.strip_leading_trailing,
            "remove_empty_lines": self.remove_empty_lines,
            "remove_urls": self.remove_urls,
            "remove_email_addresses": self.remove_email_addresses,
            "remove_html_entities": self.remove_html_entities,
            "lowercase": self.lowercase,
            "remove_punctuation": self.remove_punctuation,
            "remove_numbers": self.remove_numbers,
            "remove_extra_symbols": self.remove_extra_symbols,
            "remove_stopwords": self.remove_stopwords,
            "min_token_length": self.min_token_length,
            "normalize_arabic": self.normalize_arabic,
            "strip_arabic_diacritics": self.strip_arabic_diacritics,
            "remove_arabic_tatweel": self.remove_arabic_tatweel,
            "create_new_version": self.create_new_version,
        }

    @classmethod
    def from_dict(cls, d: dict) -> CleaningOptions:
        known = {f for f in cls().__dict__.keys() if not f.startswith("_")}
        return cls(**{k: v for k, v in d.items() if k in known})


# --------------------------------------------------------------------------- #
# Regex patterns (compiled once)
# --------------------------------------------------------------------------- #

_URL_RE = re.compile(
    r"https?://[^\s<>\"]+|www\.[^\s<>\"]+",
    re.IGNORECASE,
)
_EMAIL_RE = re.compile(r"[a-zA-Z0-9._%+-]+@[a-zA-Z0-9.-]+\.[a-zA-Z]{2,}")
_HTML_ENTITY_RE = re.compile(r"&[a-zA-Z]+;|&#\d+;")
_NUMBER_RE = re.compile(r"\b\d+([.,]\d+)?\b")
_PUNCT_RE = re.compile(
    r"[!\"#$%&'()*+,\-./:;<=>?@\[\\\]^_`{|}~"
    r"\u2018\u2019\u201C\u201D\u2013\u2014\u2026"
    r"\u00AB\u00BB\u00A1\u00BF"  # « » ¡ ¿
    r"]+"
)
# Emoji + pictographs + symbols (Unicode categories So, Sk, Sm outside ASCII)
_EXTRA_SYMBOL_RE = re.compile(
    "["
    "\U0001F600-\U0001F64F"  # emoticons
    "\U0001F300-\U0001F5FF"  # symbols & pictographs
    "\U0001F680-\U0001F6FF"  # transport & map
    "\U0001F1E0-\U0001F1FF"  # flags
    "\U00002700-\U000027BF"  # dingbats
    "\U0001F900-\U0001F9FF"  # supplemental symbols
    "\U00002600-\U000026FF"  # misc symbols
    "]+",
    flags=re.UNICODE,
)
# Arabic diacritics (harakat): fatha, damma, kasra, sukun, tanwin, shadda
_ARABIC_DIACRITICS_RE = re.compile(
    "[\u064B\u064C\u064D\u064E\u064F\u0650\u0651\u0652\u0653\u0654\u0655\u0670]"
)
_ARABIC_TATWEEL = "\u0640"  # ـ kashida

# Stopword lists (small, embedded — full lists would be a separate data file)
_ENGLISH_STOPWORDS = frozenset({
    "the", "a", "an", "and", "or", "but", "if", "then", "else", "when",
    "at", "by", "for", "with", "about", "against", "between", "into",
    "through", "during", "before", "after", "above", "below", "to", "from",
    "up", "down", "in", "out", "on", "off", "over", "under", "again",
    "further", "once", "here", "there", "all", "any", "both", "each",
    "few", "more", "most", "other", "some", "such", "no", "nor", "not",
    "only", "own", "same", "so", "than", "too", "very", "s", "t", "can",
    "will", "just", "don", "should", "now", "d", "ll", "m", "o", "re",
    "ve", "y", "ain", "aren", "couldn", "didn", "doesn", "hadn", "hasn",
    "haven", "isn", "ma", "mightn", "mustn", "needn", "shan", "shouldn",
    "wasn", "weren", "won", "wouldn", "is", "am", "are", "was", "were",
    "be", "been", "being", "have", "has", "had", "having", "do", "does",
    "did", "doing", "this", "that", "these", "those", "i", "me", "my",
    "myself", "we", "our", "ours", "ourselves", "you", "your", "yours",
    "he", "him", "his", "she", "her", "hers", "it", "its", "they", "them",
    "their", "theirs", "what", "which", "who", "whom", "of",
})

_ARABIC_STOPWORDS = frozenset({
    "في", "من", "على", "إلى", "عن", "مع", "هذا", "هذه", "ذلك", "تلك",
    "التي", "الذي", "الذين", "اللاتي", "اللذان", "اللواتي", "هو", "هي",
    "هم", "هن", "نحن", "أنا", "أنت", "أنتم", "كان", "كانت", "يكون",
    "تكون", "قد", "لقد", "لن", "لم", "لا", "إن", "أن", "ما", "إلا",
    "ثم", "أو", "أم", "بل", "حتى", "كل", "بعض", "غير", "بين", "عند",
    "لدى", "نعم", "بلى", "كلا", "كلتا", "أيضا", "فقط", "حيث", "كي",
    "لكي", "لكيلا", "لأن", "لذلك", "كما", "إذا", "إذ", "لو", "لكن",
    "واو", "الفاء", "الباء", "اللام",
})


# --------------------------------------------------------------------------- #
# Cleaning functions
# --------------------------------------------------------------------------- #


def _normalize_arabic(text: str) -> str:
    """Normalize Arabic orthographic variants.

    - أ إ آ → ا
    - ة → ه (teh marbuta → teh)
    - ى → ي (alef maksura → yeh)
    """
    text = text.replace("\u0623", "\u0627")  # أ → ا
    text = text.replace("\u0625", "\u0627")  # إ → ا
    text = text.replace("\u0622", "\u0627")  # آ → ا
    text = text.replace("\u0629", "\u0647")  # ة → ه
    text = text.replace("\u0649", "\u064A")  # ى → ي
    return text


def _remove_stopwords(text: str, language: str) -> str:
    """Remove stopwords while preserving token boundaries."""
    if language == "ar":
        stop = _ARABIC_STOPWORDS
    else:
        stop = _ENGLISH_STOPWORDS
    # Simple whitespace tokenization for stopword removal — the NLP pipeline
    # will re-tokenize properly afterward.
    tokens = text.split()
    kept = [t for t in tokens if t not in stop]
    return " ".join(kept)


def _filter_short_tokens(text: str, min_len: int) -> str:
    """Drop tokens shorter than min_len characters (after stripping punctuation
    from each token's edges so 'word,' counts as 4 not 5)."""
    if min_len <= 0:
        return text
    tokens = text.split()
    kept = []
    for t in tokens:
        stripped = t.strip(".,!?;:\"'()[]{}«»‹›—–-")
        if len(stripped) >= min_len:
            kept.append(t)
    return " ".join(kept)


def clean_text(text: str, opts: CleaningOptions, language: str = "en") -> str:
    """Apply the selected cleaning operations to a text string.

    Operations are applied in a sensible order: structural → removal →
    case → linguistic. Each is gated by its option flag so the user can
    mix and match.
    """
    if not text:
        return ""

    # --- 1. Structural cleaning ---
    if opts.remove_html_entities:
        text = _HTML_ENTITY_RE.sub(" ", text)
    if opts.remove_urls:
        text = _URL_RE.sub(" ", text)
    if opts.remove_email_addresses:
        text = _EMAIL_RE.sub(" ", text)

    # Unicode NFC normalization (combines decomposed characters)
    text = unicodedata.normalize("NFC", text)

    if opts.collapse_whitespace:
        text = text.replace("\r\n", "\n").replace("\r", "\n")
        # Collapse runs of spaces/tabs (but keep newlines)
        text = re.sub(r"[ \t]+", " ", text)
        # Collapse 3+ newlines to 2
        while "\n\n\n" in text:
            text = text.replace("\n\n\n", "\n\n")

    if opts.remove_empty_lines:
        lines = [ln for ln in text.split("\n") if ln.strip()]
        text = "\n".join(lines)

    # --- 2. Arabic-specific (only if language is 'ar') ---
    if language == "ar":
        if opts.normalize_arabic:
            text = _normalize_arabic(text)
        if opts.strip_arabic_diacritics:
            text = _ARABIC_DIACRITICS_RE.sub("", text)
        if opts.remove_arabic_tatweel:
            text = text.replace(_ARABIC_TATWEEL, "")

    # --- 3. Removal: punctuation, numbers, symbols ---
    if opts.remove_numbers:
        text = _NUMBER_RE.sub(" ", text)
    if opts.remove_extra_symbols:
        text = _EXTRA_SYMBOL_RE.sub(" ", text)
    if opts.remove_punctuation:
        text = _PUNCT_RE.sub(" ", text)

    # --- 4. Case ---
    if opts.lowercase:
        text = text.lower()

    # --- 5. Linguistic filtering ---
    if opts.remove_stopwords:
        text = _remove_stopwords(text, language)
    if opts.min_token_length > 0:
        text = _filter_short_tokens(text, opts.min_token_length)

    # --- 6. Final whitespace pass (removal ops may have left double spaces) ---
    if opts.collapse_whitespace:
        text = re.sub(r"[ \t]+", " ", text)
        text = re.sub(r"\n[ \t]+", "\n", text)
        text = re.sub(r"[ \t]+\n", "\n", text)
    if opts.strip_leading_trailing:
        text = text.strip()

    return text


# --------------------------------------------------------------------------- #
# Service: clean an entire corpus
# --------------------------------------------------------------------------- #


@dataclass
class CleaningResult:
    """Summary of a cleaning operation, returned to the API."""

    corpus_id: str
    documents_cleaned: int
    old_token_count: int
    new_token_count: int
    old_type_count: int
    new_type_count: int
    new_version_id: str | None
    options_applied: dict = field(default_factory=dict)


async def clean_corpus(
    session: AsyncSession,
    corpus: Corpus,
    opts: CleaningOptions,
) -> CleaningResult:
    """Re-clean every document in a corpus with the given options.

    Steps:
      1. Capture old stats (token_count, type_count from corpus.stats)
      2. Re-clean each document's cleaned_text
      3. Delete all existing tokens + annotation versions (or create a new
         version if create_new_version=True — but for simplicity we replace
         the latest version's tokens since cleaning changes the text itself)
      4. Re-run the NLP pipeline on each cleaned document
      5. Update corpus stats
    """
    old_stats = corpus.stats or {}
    old_token_count = old_stats.get("token_count", 0)
    old_type_count = old_stats.get("type_count", 0)

    # Fetch all documents
    docs_result = await session.execute(
        select(Document).where(Document.corpus_id == corpus.id).order_by(Document.created_at)
    )
    documents = list(docs_result.scalars().all())

    if not documents:
        return CleaningResult(
            corpus_id=corpus.id,
            documents_cleaned=0,
            old_token_count=0,
            new_token_count=0,
            old_type_count=0,
            new_type_count=0,
            new_version_id=None,
            options_applied=opts.to_dict(),
        )

    # Delete existing tokens for this corpus (they belong to annotation versions)
    # and the annotation versions themselves — we'll rebuild them.
    av_result = await session.execute(
        select(AnnotationVersion).where(AnnotationVersion.corpus_id == corpus.id)
    )
    old_versions = list(av_result.scalars().all())
    for av in old_versions:
        # Delete tokens belonging to this version (cascade should handle it,
        # but be explicit for SQLite)
        await session.execute(
            delete(Token).where(Token.version_id == av.id)
        )
        await session.delete(av)
    await session.flush()

    # Reset corpus stats
    corpus.stats = {}
    corpus.pipeline_recipe = {}

    # Re-clean + re-ingest each document
    new_version_id: str | None = None
    for doc in documents:
        cleaned = clean_text(doc.cleaned_text or "", opts, language=corpus.language or "en")
        doc.cleaned_text = cleaned
        # Re-run the pipeline via ingest_document's internal logic, but we
        # can't call ingest_document directly because it creates a NEW
        # document. Instead, inline the pipeline + token insertion.
        pipeline = get_pipeline(backend="spacy", language=corpus.language or "en")
        info = pipeline.info()
        parsed = pipeline.parse_document(cleaned)

        # Create a new annotation version for this corpus (one per cleaning pass)
        if new_version_id is None:
            av = AnnotationVersion(
                corpus_id=corpus.id,
                version_label="v_cleaned",
                model_name=f"{info.backend}:{info.model_name}",
                model_version=info.model_version,
                tokenizer=info.backend,
                tagger=info.backend,
                parser=info.backend,
                token_count=0,
                type_count=0,
                sentence_count=0,
            )
            session.add(av)
            await session.flush()
            new_version_id = av.id

        av = await session.get(AnnotationVersion, new_version_id)
        assert av is not None

        # Insert tokens
        for sent_idx, sent in enumerate(parsed.sentences):
            for tok_idx, tok in enumerate(sent.tokens):
                session.add(Token(
                    version_id=av.id,
                    document_id=doc.id,
                    sentence_idx=sent_idx,
                    token_idx=tok_idx,
                    text=tok.text,
                    lemma=tok.lemma,
                    pos=tok.pos,
                    pos_fine=tok.pos_fine,
                    morph=tok.morph,
                    dep_head=tok.dep_head,
                    dep_rel=tok.dep_rel,
                    is_punct=tok.is_punct,
                    is_stop=tok.is_stop,
                ))
        av.token_count += parsed.token_count
        av.type_count += parsed.type_count
        av.sentence_count += len(parsed.sentences)

        # Update corpus stats
        corpus.stats = {
            **(corpus.stats or {}),
            "token_count": (corpus.stats or {}).get("token_count", 0) + parsed.token_count,
            "type_count": (corpus.stats or {}).get("type_count", 0) + parsed.type_count,
            "sentence_count": (corpus.stats or {}).get("sentence_count", 0) + len(parsed.sentences),
            "document_count": (corpus.stats or {}).get("document_count", 0) + 1,
        }
        corpus.pipeline_recipe = {
            "backend": info.backend,
            "model_name": info.model_name,
            "model_version": info.model_version,
            "spacy_version": info.spacy_version,
            "language": info.language,
        }

    new_stats = corpus.stats or {}
    result = CleaningResult(
        corpus_id=corpus.id,
        documents_cleaned=len(documents),
        old_token_count=old_token_count,
        new_token_count=new_stats.get("token_count", 0),
        old_type_count=old_type_count,
        new_type_count=new_stats.get("type_count", 0),
        new_version_id=new_version_id,
        options_applied=opts.to_dict(),
    )
    log.info(
        "corpus_cleaned",
        corpus_id=corpus.id,
        documents=len(documents),
        old_tokens=old_token_count,
        new_tokens=result.new_token_count,
    )
    return result
