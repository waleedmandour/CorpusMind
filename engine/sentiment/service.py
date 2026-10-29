"""Layered, Appraisal-grounded sentiment analysis (v1.2.8, review #8).

Replaces the v1.0 starter scorer (a ~100-word surface-form lexicon with no
negation handling) with a three-layer model:

  Layer A - Appraisal (Martin & White 2005): Attitude (Affect, Judgment,
            Appreciation), Engagement and Graduation cue profiles over the
            corpus and per sentence. English cue sets (bundled).
  Layer B - Valence + emotion: lemma-level lookup in the bundled starter
            valence lexicon (EN + AR), upgraded to the full NRC EmoLex
            8-emotion taxonomy when the user configures it (NRC's Terms of
            Use forbid redistribution, so the data is never shipped).
  Grammar - the stored dependency parses drive negation scope (a `neg`
            dependent flips the polarity of its head) and booster
            intensification (graduation.force cues scale their head's
            contribution x1.5). This is what makes the analysis *nuanced*
            rather than bag-of-words: "not good" scores negative,
            "very good" scores stronger than "good".

Backward compatibility: the top-level fields the UI and exports relied on
(total_sentences, positive, negative, neutral, avg_score, timeline) keep
their meaning; everything else is additive.
"""

from __future__ import annotations

from collections import Counter, defaultdict
from dataclasses import dataclass, field

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

# The same diacritic handling as the USAS lens so Arabic corpora behave
# identically across the semantic and sentiment surfaces.
from nlp.tagsets import ARABIC_DIACRITICS
from sentiment.lexicons import (
    APPRAISAL_CUES,
    ATTITUDE_CATEGORIES,
    BOOSTERS,
    EMOTIONS,
    NEGATION_WORDS,
    SENTIMENT_FRAMEWORK_CITATION,
    SENTIMENT_METHOD,
    STARTER_COVERAGE_NOTE,
    STARTER_VALENCE_AR,
    STARTER_VALENCE_EN,
    ValenceEntry,
    emolex_status,
    load_emolex,
)
from stats.service import _latest_version_id
from storage.models import Token


def strip_diacritics(text: str) -> str:
    return "".join(c for c in text if c not in ARABIC_DIACRITICS)


BOOST_MULTIPLIER = 1.5
NEGATION_RELATIONS = ("neg", "advmod")  # UD "neg"; spaCy sm emits advmod/neg

# Negation scope propagation: spaCy typically attaches "not" to the copula
# ("is not good" -> neg(is)), not to the valenced adjective, so the flip
# must travel through the dependency chain that carries the predicate's
# scope. These relations pass negation from head to dependent.
NEGATION_SCOPE_RELATIONS = frozenset({
    "aux", "aux:pass", "auxpass", "cop", "acomp", "xcomp",
})

# Attitude categories reported per sentence in the timeline (compact).
_TIMELINE_ATTITUDE = ATTITUDE_CATEGORIES


@dataclass
class SentimentResult:
    total_sentences: int
    positive: int
    negative: int
    neutral: int
    avg_score: float
    timeline: list[dict]
    # v1.2.8 (review #8) additive fields -------------------------------------
    language: str = "en"
    method: str = SENTIMENT_METHOD
    framework_citation: str = SENTIMENT_FRAMEWORK_CITATION
    # Per-layer availability and coverage (honest, never silent zeros).
    lexicons: dict = field(default_factory=dict)
    # Appraisal profile: {category: {count, sentence_coverage, group}}.
    appraisal: dict = field(default_factory=dict)
    # Sentence-dominant emotion distribution over the 8 EmoLex categories.
    emotions: dict = field(default_factory=dict)
    # Token-level emotion mention totals (weighted).
    emotion_mentions: dict = field(default_factory=dict)
    # Most frequent valenced lemmas: [{lemma, freq, polarity, emotions}]
    top_emotional: list[dict] = field(default_factory=list)


async def _load_parses(session: AsyncSession, version_id: str) -> list[list[dict]]:
    """Load tokens with their dep head/rel, grouped by sentence.

    Mirrors discourse.service._load_parses (same ordering, same keys) so
    the sentiment lens and the discourse lenses always see identical data.
    """
    stmt = (
        select(
            Token.document_id,
            Token.sentence_idx,
            Token.token_idx,
            Token.text,
            Token.lemma,
            Token.pos,
            Token.dep_head,
            Token.dep_rel,
        )
        .where(Token.version_id == version_id)
        .order_by(Token.document_id, Token.sentence_idx, Token.token_idx)
    )
    rows = (await session.execute(stmt)).all()
    sentences: dict[tuple[str, int], list[dict]] = defaultdict(list)
    for doc_id, sent_idx, tok_idx, text, lemma, pos, dep_head, dep_rel in rows:
        sentences[(doc_id, sent_idx)].append(
            {
                "idx": tok_idx,
                "text": text,
                "lemma": lemma,
                "pos": pos,
                "head": dep_head,
                "rel": dep_rel,
                "doc": doc_id,
                "sent": sent_idx,
            }
        )
    return list(sentences.values())


def _lookup(
    tok: dict, language: str, starter: dict, emolex: dict | None
) -> ValenceEntry | None:
    """Lemma-first (then surface-form) lookup; EmoLex wins when configured."""
    lemma = (tok.get("lemma") or "").lower()
    text = (tok.get("text") or "").lower()
    if language == "ar":
        lemma = strip_diacritics(lemma)
        text = strip_diacritics(text)
    if emolex:
        for key in (lemma, text):
            if key and key in emolex:
                return emolex[key]
    for key in (lemma, text):
        if key and key in starter:
            polarity, emotions = starter[key]
            return ValenceEntry(polarity, emotions)
    return None


def _is_negation(tok: dict) -> bool:
    """A negation DEPENDENT: UD `neg`, or a negation lemma attached as an
    adverbial modifier ("not" in spaCy sm parses)."""
    if tok.get("rel") == "neg":
        return True
    return (
        tok.get("rel") in NEGATION_RELATIONS
        and (tok.get("lemma") or "").lower() in NEGATION_WORDS
    )


def _is_booster(tok: dict) -> bool:
    return (tok.get("lemma") or "").lower() in BOOSTERS


def _appraisal_hits(sent: list[dict]) -> Counter:
    """Appraisal cue hits for one sentence (same matching semantics as the
    discourse lens: single-word cues match token surface forms, multi-word
    cues substring-match the joined sentence text)."""
    sent_lower = " ".join(t["text"].lower() for t in sent)
    hits: Counter = Counter()
    for cat, cues in APPRAISAL_CUES.items():
        for cue in cues:
            if " " in cue:
                if cue in sent_lower:
                    hits[cat] += 1
            else:
                for tok in sent:
                    if tok["text"].lower() == cue:
                        hits[cat] += 1
    return hits


def _negated_heads(sent: list[dict]) -> set[int]:
    """Token indices whose polarity is under negation scope.

    Two passes: (1) a negation dependent flips its head; (2) the flip
    propagates through copular/auxiliary chains ("is not good" attaches
    neg to "is", so "good" inherits the flip via acomp)."""
    negated: set[int] = {
        (tok.get("head") or 0) - 1 for tok in sent if _is_negation(tok)
    }
    changed = True
    while changed:
        changed = False
        for tok in sent:
            if tok["idx"] in negated:
                continue
            head_idx = (tok.get("head") or 0) - 1
            if head_idx in negated and tok.get("rel") in NEGATION_SCOPE_RELATIONS:
                negated.add(tok["idx"])
                changed = True
    return negated


def _score_sentence(
    sent: list[dict], language: str, starter: dict, emolex: dict | None
) -> dict:
    """One sentence: valence, dominant emotion, appraisal hits."""
    negated_heads = _negated_heads(sent)
    booster_heads: set[int] = set()
    for tok in sent:
        if _is_booster(tok) and tok.get("pos") == "ADV":
            booster_heads.add((tok.get("head") or 0) - 1)

    pos_w = neg_w = 0.0
    emotion_weights: Counter = Counter()
    lemma_counts: Counter = Counter()

    for tok in sent:
        if tok.get("pos") in ("SPACE", "PUNCT"):
            continue
        entry = _lookup(tok, language, starter, emolex)
        if entry is None or entry.polarity == 0:
            continue
        sign = entry.polarity
        if tok["idx"] in negated_heads:
            sign = -sign
        weight = BOOST_MULTIPLIER if tok["idx"] in booster_heads else 1.0
        if sign > 0:
            pos_w += weight
        else:
            neg_w += weight
        for e in entry.emotions:
            emotion_weights[e] += weight
        lemma_counts[(tok.get("lemma") or tok["text"]).lower()] += 1

    denom = pos_w + neg_w + 1.0  # same smoothing as the previous scorer
    score = (pos_w - neg_w) / denom
    dominant = None
    if emotion_weights:
        dominant = max(emotion_weights.items(), key=lambda kv: (kv[1], kv[0]))[0]
    return {
        "score": score,
        "pos_w": pos_w,
        "neg_w": neg_w,
        "dominant_emotion": dominant,
        "emotion_weights": emotion_weights,
        "lemma_counts": lemma_counts,
        "appraisal": _appraisal_hits(sent),
    }


def _lexicon_report(lang: str, appraisal_available: bool) -> dict:
    return {
        "emolex": emolex_status(lang),
        "appraisal_cues": {
            "available": appraisal_available,
            "categories": sorted(APPRAISAL_CUES),
            "note": (
                "Appraisal cue sets are English-only; Arabic corpora are "
                "scored on the valence + emotion layers."
                if not appraisal_available
                else STARTER_COVERAGE_NOTE
            ),
        },
    }


async def compute_sentiment(
    session: AsyncSession,
    corpus_id: str,
    *,
    language: str | None = None,
) -> SentimentResult:
    """Layered sentiment per sentence (§8.18, v1.2.8 review #8).

    Method + lexicon configuration are reported with every result so
    cross-corpus comparisons stay interpretable (Principle 8: the model is
    pinned per project; here the pinned inputs are the Appraisal cue
    version, the starter lexicon, and the optional EmoLex files).
    """
    from storage.models import Corpus as CorpusModel

    corpus_row = await session.get(CorpusModel, corpus_id)
    lang = (language or (corpus_row.language if corpus_row else None) or "en").lower()

    # v1.2.11: honest gating. Bundled valence lexicons exist for en and ar
    # only. Urdu/Hindi/Farsi previously fell through to the ENGLISH starter
    # lexicon, which silently scored Urdu text against English words and
    # returned meaningless zeros. Missing resources must return an explicit
    # status with a hint (503 pattern), never a silent fallback.
    if lang not in ("en", "ar"):
        raise ValueError(f"sentiment_lexicon_missing:{lang}")

    starter = STARTER_VALENCE_AR if lang == "ar" else STARTER_VALENCE_EN
    emolex = load_emolex(lang)

    # English appraisal cues; Arabic corpora still get the valence + emotion
    # layers, with the Appraisal layer reported unavailable instead of zeroed.
    appraisal_available = lang != "ar"

    version_id = await _latest_version_id(session, corpus_id)
    if not version_id:
        return SentimentResult(
            total_sentences=0,
            positive=0,
            negative=0,
            neutral=0,
            avg_score=0.0,
            timeline=[],
            language=lang,
            lexicons=_lexicon_report(lang, appraisal_available),
            emotions={e: 0 for e in EMOTIONS},
            emotion_mentions={e: 0 for e in EMOTIONS},
        )

    sentences = await _load_parses(session, version_id)

    pos_count = neg_count = neu_count = 0
    total_score = 0.0
    timeline: list[dict] = []

    attitude_counts: Counter = Counter()
    attitude_sentences: Counter = Counter()
    emotion_sentence_counts: Counter = Counter()
    emotion_mention_counts: Counter = Counter()
    lemma_totals: Counter = Counter()

    for sent in sentences:
        s = _score_sentence(sent, lang, starter, emolex)
        score = s["score"]
        total_score += score
        if score > 0.05:
            pos_count += 1
        elif score < -0.05:
            neg_count += 1
        else:
            neu_count += 1

        if appraisal_available:
            for cat, n in s["appraisal"].items():
                attitude_counts[cat] += n
                attitude_sentences[cat] += 1

        if s["dominant_emotion"]:
            emotion_sentence_counts[s["dominant_emotion"]] += 1
        for e, w in s["emotion_weights"].items():
            emotion_mention_counts[e] += w
        for lemma, n in s["lemma_counts"].items():
            lemma_totals[lemma] += n

        timeline.append(
            {
                "doc": sent[0]["doc"] if sent else "",
                "sent": sent[0]["sent"] if sent else 0,
                "score": round(score, 3),
                "pos_hits": round(s["pos_w"], 2),
                "neg_hits": round(s["neg_w"], 2),
                "dominant_emotion": s["dominant_emotion"],
                "attitude": [
                    cat for cat in _TIMELINE_ATTITUDE if s["appraisal"].get(cat)
                ],
            }
        )

    total = len(sentences)
    avg = total_score / total if total else 0.0

    # Top emotional vocabulary (lemma-level, most frequent first).
    top: list[dict] = []
    for lemma, freq in lemma_totals.most_common(20):
        entry = _lookup({"lemma": lemma, "text": lemma}, lang, starter, emolex)
        if entry is None:
            continue
        top.append(
            {
                "lemma": lemma,
                "freq": freq,
                "polarity": entry.polarity,
                "emotions": list(entry.emotions),
            }
        )

    appraisal_profile = {
        "available": appraisal_available,
        "categories": {
            cat: {
                "count": attitude_counts.get(cat, 0),
                "sentence_coverage": attitude_sentences.get(cat, 0),
                "group": (
                    "attitude" if cat.startswith("attitude.") else cat.split(".")[0]
                ),
            }
            for cat in APPRAISAL_CUES
        },
    }

    return SentimentResult(
        total_sentences=total,
        positive=pos_count,
        negative=neg_count,
        neutral=neu_count,
        avg_score=round(avg, 3),
        timeline=timeline,
        language=lang,
        lexicons=_lexicon_report(lang, appraisal_available),
        appraisal=appraisal_profile,
        emotions={e: emotion_sentence_counts.get(e, 0) for e in EMOTIONS},
        emotion_mentions={
            e: round(emotion_mention_counts.get(e, 0.0), 2) for e in EMOTIONS
        },
        top_emotional=top,
    )


__all__ = ["SentimentResult", "compute_sentiment"]
