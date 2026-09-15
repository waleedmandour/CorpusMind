"""Learner-error CANDIDATE detection — rule-based seed finders (v1.2.0 item 5).

**These are seed rules for CANDIDATE detection, not validated errors.** The
module is framed exactly like the metaphor-candidates pipeline
(``discourse.service.compute_metaphor_candidates``): everything it emits is a
*candidate* for human or LLM review, with a stable evidence reference
(``line_ref`` = ``{document_id}:{sentence_idx}:{token_idx}``), a rule label,
and a reason string. ``verified_count`` is always 0 — only the human (or a
human-confirmed LLM triage step) can mark something a verified error.

Lineage: the design follows ERRANT (Bryant & Briscoe 2016; Bryant et al. 2017
— automatic error *type* annotation for learner English), cf. the 2024–25
multilingual GEC extensions of that line of work (Bryant & Ng and follow-ups).
The rules here are deliberately shallow (orthographic / lexical bigram /
curated misspelling lists) and are meant to be replaced by a statistical or
LLM-based checker in a later phase. For Arabic, matching runs on the
*dediacritized* token text (harakat + tatweel stripped, mirroring the
ingestion-time normalization) while the original surface form is reported.

Every rule returns (token_idx, rule_id, reason) triples so candidates can be
reconstructed with their sentence context by the caller.
"""
from __future__ import annotations

import re
from collections import Counter
from dataclasses import dataclass, field

from sqlalchemy import select

from app.logging import get_logger
from stats.service import _latest_version_id
from storage.models import Token

log = get_logger(__name__)

# Dediacritization for Arabic matching: harakat (064B-065F), superscript alef
# (0670) and tatweel (0640). Same set as storage/session.arnorm minus the
# letter-unification steps (we match surface letter forms here, on purpose —
# the rules themselves are about hamza/ta-marbuta/alef-maksura LETTER choice).
_DIACRITICS = re.compile(r"[\u064B-\u065F\u0670\u0640]")


def _dediacritize(text: str) -> str:
    return _DIACRITICS.sub("", text or "")


def _norm(text: str) -> str:
    """Case-folded match key (safe for Arabic — lower() is a no-op there)."""
    return (text or "").lower()


# --------------------------------------------------------------------------- #
# English rules
# --------------------------------------------------------------------------- #

_VOWELS = set("aeiou")

# en_prep: lexical dependency confusions (Granger 1998-style learner-Corpus
# patterns). Wrong bigram → standard usage note.
_EN_PREP_BIGRAMS: dict[tuple[str, str], str] = {
    ("discuss", "about"): "standard usage is 'discuss X' (transitive, no preposition)",
    ("compose", "of"): "standard usage is 'be composed of' / 'compose X'",
    ("married", "with"): "standard usage is 'married to' (or 'married' + no prep)",
    ("depends", "of"): "standard usage is 'depends on'",
    ("good", "in"): "standard usage is 'good at' for skills/activities",
}

_EN_AGREEMENT_BIGRAMS: set[tuple[str, str]] = {
    ("they", "is"), ("they", "was"),
    ("he", "are"), ("she", "are"),
    ("we", "is"), ("we", "was"),
    ("you", "was"),
    ("it", "are"),
    ("those", "is"), ("these", "is"),
}

# en_spelling: curated common misspellings (frequency-ranked in learner
# corpora and ESL error lists). Deliberately a small seed set.
_EN_SPELLING: dict[str, str] = {
    "recieve": "receive",
    "seperate": "separate",
    "occured": "occurred",
    "definately": "definitely",
    "accomodate": "accommodate",
    "untill": "until",
    "wich": "which",
    "teached": "taught",
    "becoz": "because",
    "alot": "a lot",
}


def _detect_en_article(tokens: list[dict]) -> list[tuple[int, str, str]]:
    """'a' + vowel-initial word, or 'an' + consonant-initial word.

    Simple ORTHOGRAPHIC heuristic only — it does not know that 'an hour' is
    right or that 'a university' is right, so it both over- and under-generates
    by design. The reason string says so explicitly.
    """
    out: list[tuple[int, str, str]] = []
    for i in range(len(tokens) - 1):
        cur = _norm(tokens[i].get("text", ""))
        nxt = tokens[i + 1].get("text", "")
        nxt_key = _norm(nxt)
        if not nxt or not nxt_key[:1].isalpha():
            continue
        if cur == "a" and nxt_key[0] in _VOWELS:
            out.append((tokens[i].get("token_idx", 0), "en_article",
                        f"orthographic heuristic: 'a' before vowel-initial '{nxt}' "
                        f"— possible article error (candidate only; silent-h and "
                        f"yu/wo-glide words are exceptions)"))
        elif cur == "an" and nxt_key[0] not in _VOWELS:
            out.append((tokens[i].get("token_idx", 0), "en_article",
                        f"orthographic heuristic: 'an' before consonant-initial '{nxt}' "
                        f"— possible article error (candidate only; silent-h words "
                        f"like 'hour' are exceptions)"))
    return out


def _detect_en_prep(tokens: list[dict]) -> list[tuple[int, str, str]]:
    """Lexical dependency confusions: flag the preposition of the bad bigram."""
    out: list[tuple[int, str, str]] = []
    for i in range(len(tokens) - 1):
        bigram = (_norm(tokens[i].get("text", "")), _norm(tokens[i + 1].get("text", "")))
        note = _EN_PREP_BIGRAMS.get(bigram)
        if note:
            out.append((tokens[i + 1].get("token_idx", 0), "en_prep",
                        f"lexical dependency confusion: '{bigram[0]} {bigram[1]}' — {note}"))
    return out


def _detect_en_agreement(tokens: list[dict]) -> list[tuple[int, str, str]]:
    """Subject–verb agreement bigrams: 'they is', 'he are', …"""
    out: list[tuple[int, str, str]] = []
    for i in range(len(tokens) - 1):
        bigram = (_norm(tokens[i].get("text", "")), _norm(tokens[i + 1].get("text", "")))
        if bigram in _EN_AGREEMENT_BIGRAMS:
            out.append((tokens[i + 1].get("token_idx", 0), "en_agreement",
                        f"subject–verb agreement: '{bigram[0]} {bigram[1]}' — "
                        f"possible agreement error (candidate only)"))
    return out


def _detect_en_spelling(tokens: list[dict]) -> list[tuple[int, str, str]]:
    """Curated misspelling list — flags the token itself."""
    out: list[tuple[int, str, str]] = []
    for tok in tokens:
        key = _norm(tok.get("text", ""))
        if key in _EN_SPELLING:
            out.append((tok.get("token_idx", 0), "en_spelling",
                        f"common misspelling: '{tok.get('text')}' — standard form "
                        f"'{_EN_SPELLING[key]}' (candidate only)"))
    return out


# --------------------------------------------------------------------------- #
# Arabic rules — match on DEDIACRITIZED text, report the original surface form
# --------------------------------------------------------------------------- #

# ar_hamza: common words whose standard orthography needs hamza (أ إ آ ؤ ئ).
# Learners frequently drop the hamza seat. Key = bare-alif form as written.
_AR_HAMZA: dict[str, str] = {
    "اخذ": "أخذ",
    "اكل": "أكل",
    "ان": "أن",
    "اذا": "إذا",
    "انشاء": "إنشاء",
    "اول": "أول",
    "اهم": "أهم",
    "اكثر": "أكثر",
    "اقل": "أقل",
    "ايضا": "أيضا",
}

# ar_ta_marbuta: common words that must end in ة but were written with ه.
_AR_TA_MARBUGA: dict[str, str] = {
    "مدرسه": "مدرسة",
    "فتاه": "فتاة",
    "كليمه": "كلمة",
    "جميله": "جميلة",
    "بديه": "بدية",
    "نافذه": "نافذة",
    "سياره": "سيارة",
    "جامه": "جامعة",
    "لغه": "لغة",
    "دراسه": "دراسة",
    "مشكله": "مشكلة",
    "محافظه": "محافظة",
}

# ar_alef_maksura: words written with ى (alef maksura) where the standard
# orthography requires ي, or vice versa — a frequent Arabic L1/L2 confusion.
_AR_ALEF_MAKSURA: dict[str, str] = {
    "هذى": "هذا",
    "ذلكى": "ذلك",
    "التى": "التي",
    "الذى": "الذي",
    "فى": "في",
}


def _ar_word_map_detector(map_: dict[str, str], rule_id: str, phenomenon: str):
    def detect(tokens: list[dict]) -> list[tuple[int, str, str]]:
        out: list[tuple[int, str, str]] = []
        for tok in tokens:
            surface = tok.get("text", "") or ""
            key = _norm(_dediacritize(surface))
            correct = map_.get(key)
            if correct:
                out.append((tok.get("token_idx", 0), rule_id,
                            f"{phenomenon}: '{surface}' — standard form '{correct}' "
                            f"(candidate only)"))
        return out

    return detect


# --------------------------------------------------------------------------- #
# Rule registry
# --------------------------------------------------------------------------- #

EN_RULES: dict[str, dict] = {
    "en_article": {"label": "Article a/an (orthographic heuristic)",
                   "language": "en", "detect": _detect_en_article},
    "en_prep": {"label": "Preposition / lexical dependency confusion",
                "language": "en", "detect": _detect_en_prep},
    "en_agreement": {"label": "Subject–verb agreement (bigram)",
                     "language": "en", "detect": _detect_en_agreement},
    "en_spelling": {"label": "Common misspellings (curated list)",
                    "language": "en", "detect": _detect_en_spelling},
}

AR_RULES: dict[str, dict] = {
    "ar_hamza": {"label": "Hamza seat (أ/إ/آ) omitted — word list",
                 "language": "ar", "detect": _ar_word_map_detector(_AR_HAMZA, "ar_hamza", "hamza spelling")},
    "ar_ta_marbuta": {"label": "Ta marbuta (ة) written as ه — word list",
                      "language": "ar", "detect": _ar_word_map_detector(_AR_TA_MARBUGA, "ar_ta_marbuta", "ta marbuta spelling")},
    "ar_alef_maksura": {"label": "Alef maksura (ى) vs ya (ي) confusion — word list",
                        "language": "ar", "detect": _ar_word_map_detector(_AR_ALEF_MAKSURA, "ar_alef_maksura", "alef maksura/ya spelling")},
}

ALL_RULES: dict[str, dict] = {**EN_RULES, **AR_RULES}


def _rules_for(language: str, rule_ids: list[str] | None = None) -> dict[str, dict]:
    """Resolve the rule set for a language ('ar*' → Arabic, else English),
    optionally restricted to ``rule_ids`` (unknown ids raise ValueError)."""
    lang = "ar" if language.startswith("ar") else "en"
    pool = {rid: rule for rid, rule in ALL_RULES.items() if rule["language"] == lang}
    if rule_ids is None:
        return pool
    unknown = [rid for rid in rule_ids if rid not in pool]
    if unknown:
        raise ValueError(
            f"Unknown rule id(s) for language '{lang}': {unknown}. "
            f"Valid ids: {sorted(pool)}"
        )
    return {rid: pool[rid] for rid in rule_ids}


# --------------------------------------------------------------------------- #
# Public API
# --------------------------------------------------------------------------- #


def flag_sentence_tokens(tokens: list[dict], language: str) -> bool:
    """True if ANY seed rule fires on this sentence's tokens.

    Used by the CAF battery as the *accuracy proxy* primitive: a sentence
    with no rule firings counts towards the error-free-sentence ratio.
    Pure function — no DB. Tokens are dicts with at least ``text``.
    """
    rules = _rules_for(language)
    for rule in rules.values():
        if rule["detect"](tokens):
            return True
    return False


@dataclass
class ErrorCandidatesResult:
    """Mirror of ``MetaphorCandidatesResult``: candidates for review, never
    confirmed errors. ``verified_count`` is always 0 here."""

    candidates: list[dict]
    counts: dict[str, int]                       # rule_id → candidate count
    total_tokens: int                            # real tokens scanned
    pipeline: str
    verified_count: int = 0
    notes: list[str] = field(default_factory=list)


_PIPELINE = (
    "rule-based seed rules (ERRANT-lineage; cf. Bryant & Ng 2024-25 "
    "multilingual GEC extensions) — candidates only, human/LLM review required"
)


async def detect_error_candidates(
    session,
    corpus_id: str,
    *,
    language: str = "en",
    rule_ids: list[str] | None = None,
    limit: int = 200,
) -> ErrorCandidatesResult:
    """Find error CANDIDATES in the latest annotation version of a corpus.

    Loads real tokens (punctuation/whitespace excluded) ordered by
    (document_id, sentence_idx, token_idx), reconstructs sentences, runs the
    seed rules for ``language`` ('ar*' → Arabic rules, else English), and
    returns up to ``limit`` candidates. Counts are per emitted rule; when the
    limit truncates the list, a note says so.
    """
    rules = _rules_for(language, rule_ids)
    lang = "ar" if language.startswith("ar") else "en"
    notes: list[str] = [
        "Candidates are heuristic, not validated errors — triage with the AI "
        "Assistant and confirm by hand before reporting them as error counts."
    ]

    version_id = await _latest_version_id(session, corpus_id)
    if not version_id:
        notes.append("Corpus has no ingested annotation version — nothing to scan.")
        return ErrorCandidatesResult(
            candidates=[], counts={}, total_tokens=0, pipeline=_PIPELINE,
            verified_count=0, notes=notes,
        )

    stmt = (
        select(
            Token.document_id,
            Token.sentence_idx,
            Token.token_idx,
            Token.text,
            Token.lemma,
            Token.pos,
        )
        .where(
            Token.version_id == version_id,
            Token.is_punct == False,  # noqa: E712
            Token.pos != "SPACE",
        )
        .order_by(Token.document_id, Token.sentence_idx, Token.token_idx)
    )
    rows = (await session.execute(stmt)).all()
    total_tokens = len(rows)

    # Reconstruct sentences in document/sentence order.
    sentences: dict[tuple[str, int], list[dict]] = {}
    for doc_id, sent_idx, tok_idx, text, lemma, pos in rows:
        sentences.setdefault((doc_id, sent_idx), []).append(
            {
                "text": text,
                "lemma": lemma,
                "pos": pos,
                "token_idx": tok_idx,
                "document_id": doc_id,
                "sentence_idx": sent_idx,
            }
        )

    candidates: list[dict] = []
    counts: Counter[str] = Counter()
    truncated = False

    for (doc_id, sent_idx), toks in sorted(sentences.items()):
        if truncated:
            break
        for rid, rule in rules.items():
            for tok_idx, _rid, reason in rule["detect"](toks):
                if len(candidates) >= limit:
                    truncated = True
                    break
                flagged = next(t for t in toks if t["token_idx"] == tok_idx)
                candidates.append(
                    {
                        "rule_id": rid,
                        "language": lang,
                        "rule_label": rule["label"],
                        "word": flagged["text"],
                        "sentence": " ".join(t["text"] for t in toks),
                        "line_ref": f"{doc_id}:{sent_idx}:{tok_idx}",
                        "document_id": doc_id,
                        "sentence_idx": sent_idx,
                        "token_idx": tok_idx,
                        "reason": reason,
                    }
                )
                counts[rid] += 1
            if truncated:
                break

    if truncated:
        notes.append(
            f"Candidate list truncated at limit={limit}; counts reflect the "
            f"emitted candidates only, not the full corpus."
        )
    log.info(
        "learner_error_candidates",
        corpus_id=corpus_id, language=lang, total_tokens=total_tokens,
        candidates=len(candidates),
    )
    return ErrorCandidatesResult(
        candidates=candidates,
        counts=dict(counts),
        total_tokens=total_tokens,
        pipeline=_PIPELINE,
        verified_count=0,
        notes=notes,
    )
