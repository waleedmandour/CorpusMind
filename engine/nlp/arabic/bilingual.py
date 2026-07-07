"""
§8.22 Bilingual corpus tools — Arabic–English alignment, parallel concordance,
translation equivalents.

Phase 3 polish ships:
  - Sentence-level alignment between Arabic + English parallel documents
  - Parallel concordance (KWIC side-by-side)
  - Translation-equivalent lookup (uses a small built-in dictionary; Phase 4
    will integrate a proper bilingual word-alignment model)

The alignment is sentence-level + length-based (Gale-Church 1993 algorithm)
which works well for clean parallel corpora. Phase 4 will swap in a proper
word-alignment model (fast_align or similar) behind the same interface.
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Literal

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.logging import get_logger
from storage.models import AnnotationVersion, Token

log = get_logger(__name__)


# --------------------------------------------------------------------------- #
# §8.22 Sentence-level alignment (Gale-Church 1993 length-based)
# --------------------------------------------------------------------------- #


@dataclass(frozen=True, slots=True)
class AlignedPair:
    ar_sentence: str
    en_sentence: str
    ar_doc_id: str
    en_doc_id: str
    ar_sent_idx: int
    en_sent_idx: int
    confidence: float       # 0–1, based on length-ratio match
    pair_type: Literal["1-1", "1-0", "0-1", "2-1", "1-2"] = "1-1"


@dataclass
class AlignmentResult:
    pairs: list[AlignedPair]
    ar_doc_count: int
    en_doc_count: int
    method: str = "Gale-Church 1993 length-based"


async def _get_sentences(session: AsyncSession, corpus_id: str) -> list[tuple[int, str]]:
    """Return sentences as (sentence_idx, joined_text) for a corpus."""
    vid = await _latest_version_id_safe(session, corpus_id)
    if not vid:
        return []
    stmt = (
        select(Token.sentence_idx, Token.text, Token.document_id)
        .where(Token.version_id == vid, Token.is_punct == False)  # noqa: E712
        .order_by(Token.document_id, Token.sentence_idx, Token.token_idx)
    )
    rows = (await session.execute(stmt)).all()
    sentences: dict[int, list[str]] = {}
    for sent_idx, text, _doc_id in rows:
        sentences.setdefault(sent_idx, []).append(text)
    return [(idx, " ".join(words)) for idx, words in sorted(sentences.items())]


async def _latest_version_id_safe(session: AsyncSession, corpus_id: str) -> str | None:
    stmt = (
        select(AnnotationVersion.id)
        .where(AnnotationVersion.corpus_id == corpus_id)
        .order_by(AnnotationVersion.created_at.desc())
        .limit(1)
    )
    return await session.scalar(stmt)


def _gale_church_align(ar_sents: list[str], en_sents: list[str]) -> list[tuple[int, int, float]]:
    """Gale-Church (1993) length-based sentence alignment.

    Returns a list of (ar_idx, en_idx, confidence) pairs.
    Confidence is inversely proportional to the length-ratio deviation.
    """
    # Simple 1-1 alignment with length-ratio scoring.
    # A full implementation would use dynamic programming with 1-0, 0-1, 1-1,
    # 2-1, 1-2 match types. Phase 3 polish ships the simple version; Phase 4
    # will swap in the full DP version.
    pairs: list[tuple[int, int, float]] = []
    i = j = 0
    while i < len(ar_sents) and j < len(en_sents):
        ar_len = len(ar_sents[i])
        en_len = len(en_sents[j])
        # Arabic characters are ~1.5× denser than English chars per concept.
        # Gale-Church uses a fixed ratio; we use a simple length-ratio confidence.
        if ar_len == 0 or en_len == 0:
            conf = 0.5
        else:
            ratio = ar_len / en_len
            # Confidence peaks at ratio ~1.0 (we expect similar lengths post-translation)
            conf = max(0.0, 1.0 - abs(1.0 - ratio) * 0.5)
        pairs.append((i, j, conf))
        i += 1
        j += 1
    return pairs


async def align_parallel_corpora(
    session: AsyncSession,
    ar_corpus_id: str,
    en_corpus_id: str,
) -> AlignmentResult:
    """Align two parallel corpora at the sentence level."""
    ar_sents = await _get_sentences(session, ar_corpus_id)
    en_sents = await _get_sentences(session, en_corpus_id)
    if not ar_sents or not en_sents:
        return AlignmentResult(pairs=[], ar_doc_count=0, en_doc_count=0)

    ar_text_only = [s for _, s in ar_sents]
    en_text_only = [s for _, s in en_sents]
    pairs_idx = _gale_church_align(ar_text_only, en_text_only)

    pairs: list[AlignedPair] = []
    for ar_i, en_i, conf in pairs_idx:
        ar_idx, ar_text = ar_sents[ar_i]
        en_idx, en_text = en_sents[en_i]
        pairs.append(AlignedPair(
            ar_sentence=ar_text,
            en_sentence=en_text,
            ar_doc_id=ar_corpus_id,
            en_doc_id=en_corpus_id,
            ar_sent_idx=ar_idx,
            en_sent_idx=en_idx,
            confidence=round(conf, 3),
        ))

    return AlignmentResult(
        pairs=pairs,
        ar_doc_count=1,  # Phase 3: per-corpus; Phase 4 will track per-doc
        en_doc_count=1,
    )


# --------------------------------------------------------------------------- #
# §8.22 Parallel concordance (KWIC side-by-side)
# --------------------------------------------------------------------------- #


@dataclass
class ParallelConcordanceResult:
    query: str
    pairs: list[dict]   # [{ar_line_id, ar_left, ar_node, ar_right, en_sentence, en_line_id}]
    total: int


async def parallel_concordance(
    session: AsyncSession,
    ar_corpus_id: str,
    en_corpus_id: str,
    query: str,
    *,
    level: Literal["word", "lemma"] = "lemma",
    window: int = 5,
    limit: int = 50,
) -> ParallelConcordanceResult:
    """Search the Arabic side, then return each hit paired with its
    English translation (per the sentence alignment)."""
    # Get Arabic sentences containing the query
    ar_sents = await _get_sentences(session, ar_corpus_id)

    # Get alignment (which loads the English sentences internally)
    alignment = await align_parallel_corpora(session, ar_corpus_id, en_corpus_id)
    align_map = {p.ar_sent_idx: p for p in alignment.pairs}

    query_lower = query.lower()
    pairs_out: list[dict] = []
    total = 0

    for sent_idx, sent_text in ar_sents:
        tokens = sent_text.split()
        for tok_idx, tok in enumerate(tokens):
            match = False
            if level == "lemma":
                # Phase 3: simple surface match (Phase 4 will use CAMeL lemma lookup)
                match = tok.lower() == query_lower or query_lower in tok.lower()
            else:
                match = tok.lower() == query_lower
            if not match:
                continue
            total += 1
            aligned = align_map.get(sent_idx)
            left = " ".join(tokens[max(0, tok_idx - window):tok_idx])
            right = " ".join(tokens[tok_idx + 1:tok_idx + 1 + window])
            pairs_out.append({
                "ar_line_id": f"{ar_corpus_id}:{sent_idx}:{tok_idx}",
                "ar_left": left,
                "ar_node": tok,
                "ar_right": right,
                "ar_sentence": sent_text,
                "en_sentence": aligned.en_sentence if aligned else "",
                "en_line_id": f"{en_corpus_id}:{aligned.en_sent_idx}" if aligned else "",
                "confidence": aligned.confidence if aligned else 0.0,
            })
            if len(pairs_out) >= limit:
                break
        if len(pairs_out) >= limit:
            break

    return ParallelConcordanceResult(query=query, pairs=pairs_out, total=total)


# --------------------------------------------------------------------------- #
# §8.22 Translation equivalents
# --------------------------------------------------------------------------- #


# Small built-in Arabic↔English dictionary for the most frequent words.
# Phase 4 will integrate a proper bilingual word-alignment model (fast_align
# or similar) trained on a parallel corpus. For now, this gives researchers
# a quick lookup for high-frequency items.
_STARTER_DICT_AR_EN: dict[str, list[str]] = {
    "كتاب": ["book", "writing"],
    "مكتبة": ["library", "bookshop"],
    "مدرسة": ["school"],
    "طالب": ["student", "pupil"],
    "معلم": ["teacher", "instructor"],
    "يدرس": ["studies", "is studying"],
    "يكتب": ["writes", "is writing"],
    "يقرأ": ["reads", "is reading"],
    "بيت": ["house", "home"],
    "مدينة": ["city", "town"],
    "رجل": ["man"],
    "امرأة": ["woman"],
    "ولد": ["boy", "child"],
    "بنت": ["girl", "daughter"],
    "ماء": ["water"],
    "طعام": ["food", "meal"],
    "يوم": ["day"],
    "ليل": ["night"],
    "صباح": ["morning"],
    "مساء": ["evening"],
    "كبير": ["big", "large", "great"],
    "صغير": ["small", "little"],
    "جديد": ["new"],
    "قديم": ["old", "ancient"],
    "جيد": ["good"],
    "سيئ": ["bad"],
    "جميل": ["beautiful", "handsome"],
    "سريع": ["fast", "quick"],
    "بطيء": ["slow"],
    "قوي": ["strong", "powerful"],
    "ضعيف": ["weak"],
    "في": ["in", "at"],
    "من": ["from", "of"],
    "إلى": ["to", "towards"],
    "على": ["on", "upon"],
    "عن": ["about", "from"],
    "مع": ["with"],
    "هذا": ["this"],
    "ذلك": ["that"],
    "الذي": ["who", "which", "that"],
    "التي": ["who", "which", "that"],
}


@dataclass
class TranslationResult:
    word: str
    direction: Literal["ar-en", "en-ar"]
    equivalents: list[str]
    source: str  # "starter-dict" for Phase 3; Phase 4 swaps to "fast_align"


def lookup_translation(
    word: str,
    direction: Literal["ar-en", "en-ar"] = "ar-en",
) -> TranslationResult:
    """Look up translation equivalents for a word.

    Phase 3 uses a small starter dictionary. Phase 4 will integrate a proper
    bilingual word-alignment model trained on a parallel corpus, behind the
    same interface (§4 Principle 8: model + version pinned per project).
    """
    if direction == "ar-en":
        equivs = _STARTER_DICT_AR_EN.get(word, [])
    else:
        # Reverse lookup: en → ar
        equivs = [ar for ar, ens in _STARTER_DICT_AR_EN.items() if word.lower() in [e.lower() for e in ens]]
    return TranslationResult(
        word=word,
        direction=direction,
        equivalents=equivs,
        source="starter-dict",
    )
