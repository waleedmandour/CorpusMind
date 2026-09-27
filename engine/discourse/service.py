"""
Phase 2 corpus-analysis services: n-grams, POS patterns, grammar queries,
dependency queries, discourse (multi-taxonomy: Hyland's metadiscourse,
Halliday & Hasan cohesion, Martin & White Appraisal, CLAWS/USAS semantics),
vocabulary profiling, sentiment.

All functions take an async SQLAlchemy session and return plain Python data
structures. Every result includes reproducibility info (parameters used).
"""

from __future__ import annotations

from collections import Counter, defaultdict
from dataclasses import dataclass
from functools import lru_cache
from typing import Any, cast

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.logging import get_logger
from nlp.ud_relations import base_relation
from stats.measures import (
    chi2_min_expected,
    gries_dp,
    keyness_ll,
    log_ratio,
    pct_diff,
    simple_maths,
)
from stats.service import _corpus_size, _is_real_token, _latest_version_id
from storage.models import Token

log = get_logger(__name__)


# --------------------------------------------------------------------------- #
# §8.8 N-grams + lexical bundles
# --------------------------------------------------------------------------- #


@dataclass
class NGramResult:
    n: int
    total_tokens: int
    rows: list[dict]  # [{ngram, freq, per_million, range (distinct docs), range_percent}]
    min_freq: int
    min_range: int  # minimum distinct documents required (§8.8 lexical bundles)


async def compute_ngrams(
    session: AsyncSession,
    corpus_id: str,
    *,
    n: int = 2,
    min_freq: int = 5,
    min_range: int = 1,  # §8.8: lexical bundles require min distinct docs
    limit: int = 200,
    skip_punct: bool = True,
    skip_stop: bool = False,
) -> NGramResult:
    """Compute n-grams with the standard frequency-and-range criterion (§8.8).

    Per Biber et al., lexical bundles require BOTH a minimum frequency per
    million words AND a minimum number of distinct texts/speakers — raw
    frequency alone is not enough to distinguish genuine bundles from
    single-text artifacts.
    """
    if n < 2 or n > 10:
        raise ValueError(f"n must be in [2, 10], got {n}")

    version_id = await _latest_version_id(session, corpus_id)
    if not version_id:
        return NGramResult(n=n, total_tokens=0, rows=[], min_freq=min_freq, min_range=min_range)

    # Load ordered tokens per document
    stmt = (
        select(
            Token.document_id,
            Token.sentence_idx,
            Token.token_idx,
            Token.text,
            Token.is_punct,
            Token.is_stop,
            Token.pos,
        )
        .where(Token.version_id == version_id)
        .order_by(Token.document_id, Token.sentence_idx, Token.token_idx)
    )
    rows_raw = (await session.execute(stmt)).all()

    # Group by document, filtering tokens as configured
    doc_tokens: dict[str, list[str]] = defaultdict(list)
    for doc_id, _, _, text, is_punct, is_stop, pos in rows_raw:
        if skip_punct and (is_punct or pos == "SPACE"):
            continue
        if skip_stop and is_stop:
            continue
        doc_tokens[doc_id].append(text)

    total_tokens = sum(len(toks) for toks in doc_tokens.values())

    # Count n-grams across documents, tracking range (distinct docs).
    # n-grams don't cross sentence boundaries — group by sentence first.
    ngram_freq: Counter = Counter()
    ngram_docs: dict[str, set[str]] = defaultdict(set)
    sentences_per_doc: dict[str, list[list[str]]] = defaultdict(list)
    current_doc = None
    current_sent = None
    current_tokens: list[str] = []
    for doc_id, sent_idx, _, text, is_punct, is_stop, pos in rows_raw:
        if doc_id != current_doc or sent_idx != current_sent:
            if current_tokens:
                sentences_per_doc[current_doc].append(current_tokens)
            current_doc = doc_id
            current_sent = sent_idx
            current_tokens = []
        if skip_punct and (is_punct or pos == "SPACE"):
            continue
        if skip_stop and is_stop:
            continue
        current_tokens.append(text)
    if current_tokens:
        sentences_per_doc[current_doc].append(current_tokens)

    for doc_id, sents in sentences_per_doc.items():
        for sent_tokens in sents:
            for i in range(len(sent_tokens) - n + 1):
                ngram = " ".join(sent_tokens[i : i + n])
                ngram_freq[ngram] += 1
                ngram_docs[ngram].add(doc_id)

    total_docs = len(sentences_per_doc)
    rows = []
    for ngram, freq in ngram_freq.most_common():
        if freq < min_freq:
            continue
        range_count = len(ngram_docs[ngram])
        if range_count < min_range:
            continue
        per_million = (freq / total_tokens * 1_000_000) if total_tokens else 0.0
        rows.append(
            {
                "ngram": ngram,
                "freq": freq,
                "per_million": round(per_million, 2),
                "range": range_count,
                "range_percent": round((range_count / total_docs * 100) if total_docs else 0.0, 2),
            }
        )
        if len(rows) >= limit:
            break

    return NGramResult(
        n=n,
        total_tokens=total_tokens,
        rows=rows,
        min_freq=min_freq,
        min_range=min_range,
    )


# --------------------------------------------------------------------------- #
# §8.11 POS analysis
# --------------------------------------------------------------------------- #


@dataclass
class POSResult:
    total_tokens: int
    distribution: list[dict]  # [{pos, freq, percent}]
    pos_ngrams: list[dict]  # [{pattern, freq}] — top POS n-grams
    n: int
    tagset: str = "upos"  # v1.2.0: which tagset the tags belong to


async def compute_pos_analysis(
    session: AsyncSession,
    corpus_id: str,
    *,
    n: int = 2,  # POS n-gram size (1=distribution, 2=bigrams, etc.)
    min_freq: int = 2,
    limit: int = 100,
    tagset: str = "upos",  # v1.2.0: upos | ptb | claws7 | calima
) -> POSResult:
    version_id = await _latest_version_id(session, corpus_id)
    if not version_id:
        return POSResult(total_tokens=0, distribution=[], pos_ngrams=[], n=n, tagset=tagset)

    # v1.2.0: resolve the corpus language once for language-aware mapping.
    from storage.models import Corpus as CorpusModel

    language = "en"
    corpus_row = await session.get(CorpusModel, corpus_id)
    if corpus_row and corpus_row.language:
        language = corpus_row.language

    # Import here to keep the module import graph lean.
    from nlp.tagsets import map_tag

    def _tag(pos: str, pos_fine: str) -> str:
        return map_tag(tagset, pos=pos, pos_fine=pos_fine, language=language)

    # Distribution — grouped over the layers the tagset needs, then mapped
    # in Python (mapping is pure string logic, so grouping on the raw
    # layers first keeps the SQL identical for every tagset).
    dist_stmt = (
        select(Token.pos, Token.pos_fine, func.count(Token.id))
        .where(Token.version_id == version_id, _is_real_token())
        .group_by(Token.pos, Token.pos_fine)
        .order_by(func.count(Token.id).desc())
    )
    dist_rows = (await session.execute(dist_stmt)).all()
    tag_counter: Counter = Counter()
    for pos, pos_fine, cnt in dist_rows:
        tag_counter[_tag(pos or "", pos_fine or "")] += cnt
    total = sum(tag_counter.values())
    distribution = [
        {"pos": p, "freq": c, "percent": round(c / total * 100, 3) if total else 0}
        for p, c in tag_counter.most_common()
    ]

    # POS n-grams
    stmt = (
        select(
            Token.document_id,
            Token.sentence_idx,
            Token.token_idx,
            Token.pos,
            Token.pos_fine,
            Token.is_punct,
        )
        .where(Token.version_id == version_id)
        .order_by(Token.document_id, Token.sentence_idx, Token.token_idx)
    )
    rows_raw = (await session.execute(stmt)).all()

    # Build per-sentence POS sequences (mapped to the requested tagset)
    sentences: dict[tuple[str, int], list[str]] = defaultdict(list)
    for doc_id, sent_idx, _, pos, pos_fine, is_punct in rows_raw:
        if is_punct or pos == "SPACE":
            continue
        sentences[(doc_id, sent_idx)].append(_tag(pos or "", pos_fine or ""))

    pos_ngram_counter: Counter = Counter()
    for sent_pos in sentences.values():
        for i in range(len(sent_pos) - n + 1):
            pattern = " ".join(sent_pos[i : i + n])
            pos_ngram_counter[pattern] += 1

    pos_ngrams = [
        {"pattern": p, "freq": c} for p, c in pos_ngram_counter.most_common(limit) if c >= min_freq
    ]

    return POSResult(
        total_tokens=total, distribution=distribution, pos_ngrams=pos_ngrams, n=n, tagset=tagset
    )


# --------------------------------------------------------------------------- #
# §8.11b Semantic analysis — USAS top-level (v1.2.0, Issue 4)
# --------------------------------------------------------------------------- #


@dataclass
class SemanticResult:
    total_tokens: int
    matched_tokens: int
    distribution: list[dict]  # [{tag, label, freq, percent}]
    unmatched_percent: float
    tagset: str = "usas"


async def compute_semantic_analysis(
    session: AsyncSession,
    corpus_id: str,
    *,
    limit: int = 100,
) -> SemanticResult:
    """USAS top-level semantic distribution (lexicon-based, experimental).

    Each content token's lemma is looked up in the bundled USAS top-level
    lexicon (reference-data/tagsets/); matched tokens are grouped by the
    24 letter categories. Lexicon misses are reported honestly as
    ``unmatched_percent`` — this is NOT the licensed CLAWS/USAS tagger.
    """
    from nlp.tagsets import USAS_TOP_LABELS, semantic_lookup
    from storage.models import Corpus as CorpusModel

    version_id = await _latest_version_id(session, corpus_id)
    if not version_id:
        return SemanticResult(
            total_tokens=0, matched_tokens=0, distribution=[], unmatched_percent=100.0
        )

    corpus_row = await session.get(CorpusModel, corpus_id)
    language = corpus_row.language if corpus_row and corpus_row.language else "en"

    stmt = (
        select(Token.lemma, Token.text, Token.is_punct, Token.pos)
        .where(Token.version_id == version_id)
        .order_by(Token.document_id, Token.sentence_idx, Token.token_idx)
    )
    rows_raw = (await session.execute(stmt)).all()

    tag_counter: Counter = Counter()
    total = 0
    matched = 0
    for lemma, text, is_punct, pos in rows_raw:
        if is_punct or (pos or "") == "SPACE":
            continue
        total += 1
        tag = semantic_lookup(lemma or "", text or "", language)
        if tag:
            matched += 1
            tag_counter[tag] += 1

    distribution = [
        {
            "tag": t,
            "label": USAS_TOP_LABELS.get(t, "Unknown"),
            "freq": c,
            "percent": round(c / matched * 100, 3) if matched else 0,
        }
        for t, c in tag_counter.most_common(limit)
    ]
    unmatched_percent = round((total - matched) / total * 100, 2) if total else 0.0
    return SemanticResult(
        total_tokens=total,
        matched_tokens=matched,
        distribution=distribution,
        unmatched_percent=unmatched_percent,
    )


# --------------------------------------------------------------------------- #
# §8.12 Grammar analysis (dependency-driven pattern detectors)
# --------------------------------------------------------------------------- #


@dataclass
class GrammarResult:
    patterns: dict[str, list[dict]]  # {pattern_name: [{doc, sent, text, ...}]}
    counts: dict[str, int]


# Grammar detectors — each inspects the dependency parse and returns matches.
# These are pattern detectors over UD parses, not regex over surface text (§8.12).


async def _load_parses(
    session: AsyncSession, version_id: str
) -> list[list[dict[str, Any]]]:
    """Load tokens with their dep head/rel, grouped by sentence.

    v1.2.10: memoized through ``app.version_cache`` — annotation versions
    are append-only, so the same version id always deserializes to the same
    stream until a document deletion mutates it (which calls
    ``invalidate_all``). Classroom bursts (up to 20 students, same corpus,
    same queries) used to pay this full-table load per request.
    """
    from app.version_cache import get_or_load

    async def _load() -> list[list[dict[str, Any]]]:
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
                Token.morph,
            )
            .where(Token.version_id == version_id)
            .order_by(Token.document_id, Token.sentence_idx, Token.token_idx)
        )
        rows = (await session.execute(stmt)).all()
        sentences: dict[tuple[str, int], list[dict[str, Any]]] = defaultdict(list)
        for doc_id, sent_idx, tok_idx, text, lemma, pos, dep_head, dep_rel, morph in rows:
            sentences[(doc_id, sent_idx)].append(
                {
                    "idx": tok_idx,
                    "text": text,
                    "lemma": lemma,
                    "pos": pos,
                    "head": dep_head,
                    "rel": dep_rel,
                    "morph": morph,
                    "doc": doc_id,
                    "sent": sent_idx,
                }
            )
        return list(sentences.values())

    # get_or_load is typed -> Any (heterogeneous cache); pin the contract here.
    return cast("list[list[dict[str, Any]]]", await get_or_load(version_id, _load))


def _detect_passives(sentence: list[dict]) -> list[dict]:
    """Detect passive voice: AUX 'be'/'get' + VERB with aux:pass dependency.

    Handles both UD v2 labels (aux:pass, nsubj:pass) and the older spaCy
    English labels (auxpass, nsubjpass) — en_core_web_sm still uses the latter.
    """
    matches = []
    for tok in sentence:
        if tok["rel"] in ("aux:pass", "auxpass"):
            head_idx = tok["head"] - 1  # convert 1-indexed to 0-indexed
            if 0 <= head_idx < len(sentence):
                head = sentence[head_idx]
                matches.append(
                    {
                        "pattern": "passive_voice",
                        "doc": tok["doc"],
                        "sent": tok["sent"],
                        "verb": head["text"],
                        "verb_lemma": head["lemma"],
                        "aux": tok["text"],
                        "evidence_id": f"{tok['doc']}:{tok['sent']}:{tok['idx']}",
                    }
                )
    return matches


def _detect_modals(sentence: list[dict]) -> list[dict]:
    """Detect modal verbs (aux dependency with a modal lemma)."""
    MODALS = {"can", "could", "may", "might", "must", "shall", "should", "will", "would"}
    matches = []
    for tok in sentence:
        if tok["rel"] == "aux" and tok["lemma"].lower() in MODALS:
            head_idx = tok["head"] - 1
            if 0 <= head_idx < len(sentence):
                head = sentence[head_idx]
                matches.append(
                    {
                        "pattern": "modal",
                        "doc": tok["doc"],
                        "sent": tok["sent"],
                        "modal": tok["text"],
                        "verb": head["text"],
                        "verb_lemma": head["lemma"],
                        "evidence_id": f"{tok['doc']}:{tok['sent']}:{tok['idx']}",
                    }
                )
    return matches


def _detect_negation(sentence: list[dict]) -> list[dict]:
    """Detect negation: 'not' / 'n't' as 'advmod' or 'neg' dependency."""
    matches = []
    for tok in sentence:
        if tok["rel"] == "neg" or (tok["pos"] == "PART" and "Neg" in (tok["morph"] or "")):
            matches.append(
                {
                    "pattern": "negation",
                    "doc": tok["doc"],
                    "sent": tok["sent"],
                    "negator": tok["text"],
                    "evidence_id": f"{tok['doc']}:{tok['sent']}:{tok['idx']}",
                }
            )
    return matches


def _detect_relative_clauses(sentence: list[dict]) -> list[dict]:
    """Detect relative clauses: acl:relc (UD v2) or relcl (spaCy legacy) dependency."""
    matches = []
    for tok in sentence:
        if tok["rel"] in ("acl:relc", "relcl"):
            matches.append(
                {
                    "pattern": "relative_clause",
                    "doc": tok["doc"],
                    "sent": tok["sent"],
                    "marker": tok["text"],
                    "evidence_id": f"{tok['doc']}:{tok['sent']}:{tok['idx']}",
                }
            )
    return matches


def _detect_complex_np(sentence: list[dict]) -> list[dict]:
    """Detect complex noun phrases: NOUN with >1 modifier (amod, nmod, compound)."""
    matches = []
    np_heads: dict[int, list[dict]] = defaultdict(list)
    for tok in sentence:
        if tok["rel"] in ("amod", "nmod", "compound", "nummod", "appos"):
            head_idx = tok["head"] - 1
            if 0 <= head_idx < len(sentence) and sentence[head_idx]["pos"] == "NOUN":
                np_heads[head_idx].append(tok)
    for head_idx, mods in np_heads.items():
        if len(mods) >= 2:
            head = sentence[head_idx]
            matches.append(
                {
                    "pattern": "complex_np",
                    "doc": head["doc"],
                    "sent": head["sent"],
                    "head": head["text"],
                    "modifiers": [m["text"] for m in mods],
                    "evidence_id": f"{head['doc']}:{head['sent']}:{head['idx']}",
                }
            )
    return matches


def _detect_tense(sentence: list[dict]) -> list[dict]:
    """Detect verb tense from morphological features."""
    matches = []
    for tok in sentence:
        if tok["pos"] not in ("VERB", "AUX"):
            continue
        morph = tok["morph"] or ""
        tense = None
        if "Tense=Past" in morph:
            tense = "past"
        elif "Tense=Pres" in morph:
            tense = "present"
        elif "Tense=Fut" in morph:
            tense = "future"
        if tense:
            matches.append(
                {
                    "pattern": f"tense_{tense}",
                    "doc": tok["doc"],
                    "sent": tok["sent"],
                    "verb": tok["text"],
                    "lemma": tok["lemma"],
                    "evidence_id": f"{tok['doc']}:{tok['sent']}:{tok['idx']}",
                }
            )
    return matches


GRAMMAR_DETECTORS = {
    "passive_voice": _detect_passives,
    "modal": _detect_modals,
    "negation": _detect_negation,
    "relative_clause": _detect_relative_clauses,
    "complex_np": _detect_complex_np,
    "tense": _detect_tense,
}


async def compute_grammar_analysis(
    session: AsyncSession,
    corpus_id: str,
    *,
    patterns: list[str] | None = None,
    limit: int = 50,
) -> GrammarResult:
    """Run dependency-driven grammar pattern detectors over the corpus."""
    version_id = await _latest_version_id(session, corpus_id)
    if not version_id:
        return GrammarResult(patterns={}, counts={})

    if patterns is None:
        patterns = list(GRAMMAR_DETECTORS.keys())

    sentences = await _load_parses(session, version_id)
    results: dict[str, list[dict]] = {p: [] for p in patterns}
    counts: dict[str, int] = {p: 0 for p in patterns}

    for sent in sentences:
        for pattern_name in patterns:
            detector = GRAMMAR_DETECTORS.get(pattern_name)
            if not detector:
                continue
            matches = detector(sent)
            for m in matches:
                if len(results[pattern_name]) < limit:
                    results[pattern_name].append(m)
                counts[pattern_name] += 1

    return GrammarResult(patterns=results, counts=counts)


# --------------------------------------------------------------------------- #
# §8.13 Dependency analysis (subject-object queries, verb patterns)
# --------------------------------------------------------------------------- #


@dataclass
class DependencyResult:
    relation: str  # nsubj / obj / iobj / etc.
    rows: list[dict]  # [{governor, dependent, relation, freq, examples}]


async def compute_dependency_analysis(
    session: AsyncSession,
    corpus_id: str,
    *,
    relation: str = "nsubj",  # nsubj, obj, iobj, obl, etc.
    limit: int = 100,
) -> DependencyResult:
    """Aggregate dependency relations — find the most common governors/dependents
    for a given relation type."""
    version_id = await _latest_version_id(session, corpus_id)
    if not version_id:
        return DependencyResult(relation=relation, rows=[])

    sentences = await _load_parses(session, version_id)

    pair_counter: Counter = Counter()
    examples: dict[tuple[str, str], list[str]] = defaultdict(list)
    for sent in sentences:
        for tok in sent:
            if tok["rel"] != relation:
                continue
            head_idx = tok["head"] - 1
            if 0 <= head_idx < len(sent):
                head = sent[head_idx]
                pair = (head["lemma"], tok["lemma"])
                pair_counter[pair] += 1
                if len(examples[pair]) < 3:
                    examples[pair].append(f"{tok['doc']}:{tok['sent']}:{tok['idx']}")

    rows = [
        {
            "governor": gov,
            "dependent": dep,
            "relation": relation,
            "freq": freq,
            "examples": ex,
        }
        for (gov, dep), freq in pair_counter.most_common(limit)
        for ex in [examples[(gov, dep)]]
    ]

    return DependencyResult(relation=relation, rows=rows)


# --------------------------------------------------------------------------- #
# §8.15 Discourse analysis — multi-taxonomy (v1.2.6)
#
# Four citable lenses over the same corpus:
#   hyland2005          — Hyland's interactive/interactional metadiscourse
#   hallidayhasan1976   — Halliday & Hasan cohesion (reference, conjunction,
#                         lexical repetition across adjacent sentences)
#   martinwhite2005     — Martin & White Appraisal (engagement, graduation,
#                         attitude starter set)
#   usas                — CLAWS-family USAS top-level semantic tagset
#                         (lexicon-based; reuses reference-data/tagsets)
#
# Each lens is a named, citable taxonomy pinned to its source so results
# stay comparable across studies. Cue lists are open-class starter sets —
# Phase 3+ may swap in learned classifiers.
# --------------------------------------------------------------------------- #


# Hyland's interactive + interactional metadiscourse markers (§8.15 +ADD).
# These are open-class lexical cue lists — Phase 2 ships a starter set;
# Phase 3+ may swap in a learned classifier. Each category is citable
# because it's pinned to a named taxonomy.

HYLAND_INTERACTIVE = {
    "transitions": {  # logical relations between propositions
        "moreover",
        "however",
        "therefore",
        "thus",
        "furthermore",
        "in addition",
        "consequently",
        "nevertheless",
        "nonetheless",
        "instead",
        "rather",
        "in contrast",
        "similarly",
        "likewise",
        "accordingly",
        "hence",
    },
    "frame_markers": {  # sequence, topic, discourse-stage
        "first",
        "second",
        "third",
        "finally",
        "to begin",
        "in conclusion",
        "to summarize",
        "in short",
        "turning to",
        "with regard to",
    },
    "endophoric_markers": {  # reference to other parts of the text
        "see figure",
        "see table",
        "as noted above",
        "as discussed below",
        "as mentioned earlier",
        "as shown in",
    },
    "evidentials": {  # attribution to other sources
        "according to",
        "cited in",
        "quoted in",
        "as X argues",
        "as X claims",
        "X suggests",
        "X states",
        "X found that",
    },
    "code_glosses": {  # reformulation / explanation
        "namely",
        "in other words",
        "that is",
        "for example",
        "for instance",
        "such as",
        "e.g.",
        "i.e.",
        "to put it differently",
    },
}

HYLAND_INTERACTIONAL = {
    "hedges": {  # withhold full commitment to a proposition
        "perhaps",
        "possibly",
        "probably",
        "likely",
        "may",
        "might",
        "could",
        "would",
        "appear to",
        "seem to",
        "tend to",
        "suggest",
        "indicate",
        "in general",
        "in most cases",
        "to some extent",
    },
    "boosters": {  # emphasize certainty
        "clearly",
        "obviously",
        "evidently",
        "demonstrably",
        "of course",
        "undoubtedly",
        "certainly",
        "definitely",
        "indeed",
        "in fact",
        "necessarily",
        "undeniably",
    },
    "attitude_markers": {  # express writer's attitude
        "surprisingly",
        "interestingly",
        "importantly",
        "remarkably",
        "unfortunately",
        "fortunately",
        "strikingly",
        "notably",
        "significantly",
        "I believe",
        "I argue",
        "I contend",
    },
    "self_mentions": {  # first-person pronouns referring to the writer
        "I",
        "me",
        "my",
        "mine",
        "we",
        "us",
        "our",
        "ours",
    },
    "engagement_markers": {  # explicitly address the reader
        "you",
        "your",
        "yours",
        "consider",
        "note that",
        "recall that",
        "imagine",
        "let us",
        "as you can see",
    },
}


# --- Halliday & Hasan (1976) cohesion — reference, conjunction, lexical --- #
# Halliday, M.A.K., & Hasan, R. (1976). Cohesion in English. Longman.
# Substitution and ellipsis need parse-level analysis and are intentionally
# NOT covered by this starter set; the remaining categories are.

HALLIDAY_HASAN_1976 = {
    "reference.pronouns": {  # anaphoric reference via pronouns/demonstratives
        "he", "she", "it", "they", "him", "her", "them",
        "his", "hers", "its", "their", "theirs",
        "this", "that", "these", "those",
    },
    "conjunction.additive": {
        "and", "also", "furthermore", "in addition", "besides",
        "similarly", "likewise", "by contrast", "or", "nor",
        "in other respects",
    },
    "conjunction.adversative": {
        "but", "yet", "however", "nevertheless", "nonetheless",
        "on the other hand", "though", "although", "whereas",
        "in spite of", "despite this", "conversely",
    },
    "conjunction.causal": {
        "so", "therefore", "thus", "hence", "consequently",
        "because", "since", "accordingly", "for this reason", "as a result",
    },
    "conjunction.temporal": {
        "then", "next", "finally", "afterwards", "meanwhile",
        "subsequently", "first", "at last", "previously", "before that",
        "earlier", "later",
    },
    # "lexical.repetition" is computed (same content lemma across adjacent
    # sentences) — see _detect_lexical_cohesion below; it is NOT a cue list.
}


# --- Martin & White (2005) Appraisal — engagement, graduation, attitude --- #
# Martin, J.R., & White, P.R.R. (2005). The Language of Evaluation:
# Appraisal in English. Palgrave Macmillan.
# Lexical starter set: INVOKED attitude (ideational appraisal) and
# graduated normativity are beyond cue lists; the categories below cover
# the inscribed, lexically-realised core.

MARTIN_WHITE_2005 = {
    "engagement.entertain": {  # open the dialogic space
        "perhaps", "possibly", "probably", "may", "might", "could",
        "seem", "appear", "likely", "presumably", "apparently",
        "it seems", "arguably",
    },
    "engagement.attribute": {  # external voices
        "according to", "cited in", "reported", "claimed", "as x argues",
        "as x claims", "as x states", "x suggests", "x found that",
    },
    "engagement.deny": {  # disclaim: reject
        "not", "no", "never", "none", "nor", "without",
    },
    "engagement.counter": {  # disclaim: counter-expectation
        "but", "although", "while", "despite", "however", "yet",
        "nevertheless", "ironically", "even so", "still",
    },
    "engagement.proclaim": {  # contract the space: concur/endorse/pronounce
        "clearly", "obviously", "of course", "undoubtedly", "certainly",
        "indeed", "necessarily", "naturally", "not surprisingly", "as is well known",
    },
    "graduation.force": {  # intensifiers and maximisers
        "very", "extremely", "highly", "deeply", "strongly", "utterly",
        "completely", "entirely", "totally", "so", "such", "too",
        "remarkably", "strikingly", "considerably", "substantially",
    },
    "attitude.affect": {  # inscribed affect (honest starter subset)
        "surprisingly", "unfortunately", "fortunately", "happily",
        "sadly", "regrettably", "interestingly", "importantly", "notably",
        "worryingly", "encouragingly",
    },
}


# Cialdini's six principles (Influence, Revised Edition 2007, ch. 2-7) as
# lexical cue sets (v1.2.10). House "starter subset" convention, same as
# the Appraisal lens above: these are the most frequent surface markers of
# persuasive text, not a closed inventory — chapter concepts like
# engineered reciprocation or structured commitment sequences are
# discourse-level and not recoverable from token cues. The 2021 seventh
# principle (Unity) is deliberately EXCLUDED: it belongs to a different
# edition and was not part of the approved v1.2.10 scope.
CIALDINI_2007: dict[str, set[str]] = {
    "reciprocation": {  # ch.2 — free gift / concession first, then the ask
        "free", "gift", "complimentary", "bonus", "trial", "favor",
        "favour", "concession", "reciprocal", "owe", "obligation",
        "no obligation", "with our compliments", "try before you buy",
    },
    "commitment_consistency": {  # ch.3 — small commitments bind later ones
        "commitment", "committed", "consistent", "consistency", "promise",
        "pledge", "vow", "start small", "take a stand", "foot in the door",
        "write it down", "sign below", "make it official",
    },
    "social_proof": {  # ch.4 — many others already act this way
        "everyone", "most people", "many others", "thousands", "millions",
        "best-selling", "bestselling", "popular", "trending", "join the",
        "out of 10", "as seen", "others like you", "people are saying",
    },
    "liking": {  # ch.5 — similarity + compliments before the request
        "like you", "just like you", "similar to you", "your friend",
        "friends like you", "fellow", "great taste", "compliment",
        "someone like you", "we are alike",
    },
    "authority": {  # ch.6 — expertise and credentials as evidence
        "expert", "experts", "study shows", "studies show", "research shows",
        "doctors recommend", "scientists", "professor", "certified",
        "official", "leading", "award-winning", "according to", "proven",
        "recommended by",
    },
    "scarcity": {  # ch.7 — limited availability raises perceived value
        "limited", "limited time", "only a few", "while supplies last",
        "act now", "expires", "last chance", "deadline", "running out",
        "exclusive", "once they're gone", "hurry", "offer ends",
        "before it's gone",
    },
}


# --- Taxonomy registry ---------------------------------------------------- #

DISCOURSE_TAXONOMIES: dict[str, dict] = {
    "hyland2005": {
        "name": "Hyland 2005",
        "citation": (
            "Hyland, K. (2005). Metadiscourse: Exploring Interaction in "
            "Writing. London: Continuum."
        ),
        "categories": {
            **{f"interactive.{k}": v for k, v in HYLAND_INTERACTIVE.items()},
            **{f"interactional.{k}": v for k, v in HYLAND_INTERACTIONAL.items()},
        },
    },
    "hallidayhasan1976": {
        "name": "Halliday & Hasan 1976",
        "citation": (
            "Halliday, M.A.K., & Hasan, R. (1976). Cohesion in English. "
            "London: Longman. (Substitution and ellipsis not covered.)"
        ),
        "categories": dict(HALLIDAY_HASAN_1976),
    },
    "martinwhite2005": {
        "name": "Martin & White 2005",
        "citation": (
            "Martin, J.R., & White, P.R.R. (2005). The Language of "
            "Evaluation: Appraisal in English. Basingstoke: Palgrave "
            "Macmillan. (Lexical starter set; invoked attitude not covered.)"
        ),
        "categories": dict(MARTIN_WHITE_2005),
    },
    "cialdini2007": {
        "name": "Cialdini 2007",
        "citation": (
            "Cialdini, R.B. (2007). Influence: The Psychology of Persuasion "
            "(Revised Edition). New York: HarperBusiness. (Chapters 2-7: "
            "reciprocation, commitment & consistency, social proof, liking, "
            "authority, scarcity. Lexical starter set; the 2021 'Unity' "
            "principle is not covered.)"
        ),
        "categories": dict(CIALDINI_2007),
    },
}

# CLAWS-family semantic lens: the bundled USAS top-level lexicon
# (reference-data/tagsets/usas-<lang>-top.tsv, CC BY-NC-SA 4.0) re-read as
# discourse-functional groupings rather than a plain frequency list.
USAS_TAXONOMY_KEY = "usas"

USAS_CITATION = (
    "Rayson, P., Archer, D., Piao, S., & McEnery, T. (2004). "
    "The UCREL Semantic Analysis System. Lancaster: UCREL "
    "(CLAWS-family semantic tagset). Bundled top-level lexicon: "
    "CC BY-NC-SA 4.0 - lexicon-based lookup, not the licensed "
    "CLAWS/USAS tagger."
)

USAS_DISCOURSE_GROUPS: dict[str, str] = {
    "Q": "Communication and speech reporting",
    "S": "Social interaction and relations",
    "X": "Cognition and mental states",
    "D": "Emotion and affect",
    "R": "Politics and ideology",
    "G": "Institutional power and governance",
    "T": "Temporality and sequence",
    "N": "Quantity, measurement and evidence",
    "Z": "Grammatical / function words",
    "W": "The physical world and environment",
    "K": "Life and living things",
    "B": "The body and health",
    "A": "General and abstract terms",
    "M": "Movement, location and travel",
    "L": "Substances, materials and equipment",
    "I": "Money and commerce",
    "P": "Education and knowledge transmission",
    "Y": "Science and technology",
    "C": "Arts, crafts and culture",
    "J": "Leisure, sport and entertainment",
    "H": "Architecture, housing and home",
    "E": "Food and farming",
    "F": "Furniture and household fittings",
    "O": "Hard to classify",
}


@dataclass
class DiscourseResult:
    categories: dict[str, dict]  # {category: {freq, per_million, examples, ...}}
    total_tokens: int
    taxonomy: str  # display name, e.g. "Hyland 2005"
    taxonomy_key: str = "hyland2005"
    citation: str = ""
    unmatched_percent: float | None = None  # USAS lens only (lexicon misses)
    # v1.2.7 (§3): dispersion + optional keyness comparison.
    # Every category dict gains `dp` (Gries' DP across documents, size-
    # weighted). When compare_corpus_id is set, category dicts also gain
    # `log_likelihood`, `log_ratio`, `pct_diff`, `simple_maths` and
    # `cochran_warning` — computed against the same taxonomy run over the
    # comparison corpus. log_ratio/pct_diff are None (JSON null) when the
    # category is absent from either side: the raw formulas return ±inf
    # there and JSON cannot carry infinities — the UI shows an em dash.
    # v1.2.9: category dicts additionally gain `ref_freq` and
    # `ref_per_million` (the reference side's raw count and normalized
    # rate), so the UI can draw a true target-vs-reference grouped bar
    # chart (green vs purple) alongside the green/red log-ratio
    # divergence view.
    compare_corpus_id: str | None = None
    compare_total_tokens: int | None = None
    # v1.2.7 (§4): persuasion lens — how many documents were actually scored
    scored_documents: int | None = None


def discourse_taxonomy_list() -> list[dict]:
    """Registry for the API/frontend: keys, display names, citations."""
    items = [
        {
            "key": key,
            "name": spec["name"],
            "citation": spec["citation"],
            "categories": sorted(spec["categories"].keys()),
        }
        for key, spec in DISCOURSE_TAXONOMIES.items()
    ]
    items.append(
        {
            "key": USAS_TAXONOMY_KEY,
            "name": "CLAWS/USAS semantic tagset (top-level)",
            "citation": USAS_CITATION,
            "categories": sorted(USAS_DISCOURSE_GROUPS.keys()),
        }
    )
    # v1.2.7 (§2): SFG transitivity & modality lens (parse-driven).
    items.append(
        {
            "key": SFG_TAXONOMY_KEY,
            "name": "SFG Transitivity & Modality (Halliday & Matthiessen 2014)",
            "citation": SFG_CITATION,
            "categories": sorted(
                [
                    "transitivity.material", "transitivity.mental",
                    "transitivity.relational", "transitivity.behavioural",
                    "transitivity.verbal", "transitivity.existential",
                    "modality.probability", "modality.usuality",
                    "modality.obligation", "modality.inclination",
                ]
            ),
        }
    )
    # v1.2.7 (§4): persuasion index lens (optional dependency).
    items.append(
        {
            "key": PERSUASION_TAXONOMY_KEY,
            "name": "Persuasion Index (Wang & Gong 2026) - 15 dimensions",
            "citation": PERSUASION_CITATION,
            "categories": sorted(
                f"pi.{family}.{dim}" for dim, family in PI_DIMENSION_FAMILIES.items()
            ),
        }
    )
    return items


def _detect_lexical_cohesion(
    sentences: list[list[dict]],
    *,
    limit_examples: int,
    category_counts: Counter,
    category_examples: dict[str, list[dict]],
    category_doc_counts: dict[str, Counter] | None = None,  # v1.2.7 (§3) DP support
) -> None:
    """Halliday & Hasan lexical cohesion: the same content lemma recurring
    across ADJACENT sentences (repetition chains). Each shared lemma in a
    sentence pair counts once. Substitution/ellipsis are not detected."""
    content_pos = {"NOUN", "VERB", "ADJ", "ADV"}
    for i in range(len(sentences) - 1):
        a, b = sentences[i], sentences[i + 1]
        a_lemmas = {
            t["lemma"].lower()
            for t in a
            if t.get("pos") in content_pos and len(t.get("lemma", "")) > 2
        }
        if not a_lemmas:
            continue
        seen: set[str] = set()
        for t in b:
            lemma = t["lemma"].lower()
            if t.get("pos") in content_pos and len(lemma) > 2 and lemma in a_lemmas and lemma not in seen:
                seen.add(lemma)
                if len(category_examples["lexical.repetition"]) < limit_examples:
                    category_examples["lexical.repetition"].append(
                        {
                            "cue": lemma,
                            "evidence_id": f"{t['doc']}:{t['sent']}:{t['idx']}",
                            "sentence_preview": " ".join(
                                x["text"].lower() for x in b
                            )[:120],
                        }
                    )
                category_counts["lexical.repetition"] += 1
                if category_doc_counts is not None:
                    # attributed to the document of the repeating sentence
                    category_doc_counts["lexical.repetition"][t["doc"]] += 1


def _count_cue_categories(
    sentences: list[list[dict]],
    categories: dict[str, set[str] | list[str]],
    *,
    limit_examples: int,
    include_lexical_cohesion: bool = False,
) -> tuple[Counter, dict[str, list[dict]], dict[str, Counter], Counter]:
    """Count cue matches per category over parsed sentences.

    v1.2.7 (§3): factored out of :func:`compute_discourse_analysis` so the
    SAME counting runs on the target corpus and on a comparison corpus —
    the per-category keyness battery is only meaningful when both sides use
    identical detection semantics. Also tracks per-document counts (for
    Gries' DP) and per-document token sizes (the DP expected proportions).

    Returns (category_counts, category_examples, category_doc_counts,
    doc_sizes). Doc sizes exclude SPACE/PUNCT tokens so the DP parts match
    the same token convention as ``_corpus_size`` (punctuation excluded).
    """
    category_counts: Counter = Counter()
    category_examples: dict[str, list[dict]] = defaultdict(list)
    category_doc_counts: dict[str, Counter] = defaultdict(Counter)
    doc_sizes: Counter = Counter()

    for sent in sentences:
        sent_text_tokens = [t["text"].lower() for t in sent]
        sent_lower = " ".join(sent_text_tokens)
        for tok in sent:
            if tok.get("pos") not in ("SPACE", "PUNCT"):
                doc_sizes[tok["doc"]] += 1
        for cat_name, cue_set in categories.items():
            if cat_name == "lexical.repetition":
                continue  # computed separately across sentence pairs
            for cue in cue_set:
                # Multi-word cues: check if it appears as a substring of the sentence
                if " " in cue:
                    if cue in sent_lower:
                        if len(category_examples[cat_name]) < limit_examples:
                            category_examples[cat_name].append(
                                {
                                    "cue": cue,
                                    "evidence_id": f"{sent[0]['doc']}:{sent[0]['sent']}:0",
                                    "sentence_preview": sent_lower[:120],
                                }
                            )
                        category_counts[cat_name] += 1
                        category_doc_counts[cat_name][sent[0]["doc"]] += 1
                else:
                    # Single-word: match against individual tokens
                    for tok in sent:
                        if tok["text"].lower() == cue:
                            if len(category_examples[cat_name]) < limit_examples:
                                category_examples[cat_name].append(
                                    {
                                        "cue": cue,
                                        "evidence_id": f"{tok['doc']}:{tok['sent']}:{tok['idx']}",
                                        "sentence_preview": sent_lower[:120],
                                    }
                                )
                            category_counts[cat_name] += 1
                            category_doc_counts[cat_name][tok["doc"]] += 1

    if include_lexical_cohesion:
        _detect_lexical_cohesion(
            sentences,
            limit_examples=limit_examples,
            category_counts=category_counts,
            category_examples=category_examples,
            category_doc_counts=category_doc_counts,
        )

    return category_counts, category_examples, category_doc_counts, doc_sizes


def _per_category_dp(
    category_counts: Counter,
    category_doc_counts: dict[str, Counter],
    doc_sizes: Counter,
) -> dict[str, float]:
    """Gries' DP for every category, size-weighted over the document parts.

    Documents are iterated in sorted-id order so the result is deterministic
    regardless of dict insertion order. A category absent from every
    document (cannot happen for rows we emit) would get DP 0.
    """
    docs = sorted(doc_sizes)
    sizes = [doc_sizes[d] for d in docs]
    dp_by_cat: dict[str, float] = {}
    for cat, count in category_counts.items():
        if count <= 0 or not docs:
            dp_by_cat[cat] = 0.0
            continue
        observed = [category_doc_counts.get(cat, Counter()).get(d, 0) for d in docs]
        dp_by_cat[cat] = round(gries_dp(observed, sizes), 3)
    return dp_by_cat


def _keyness_fields(f1: int, N1: int, f2: int, N2: int) -> dict:
    """v1.2.7 (§3): the per-category keyness battery against a comparison
    corpus, wired onto the existing measures library (§12 formulas).

    LL (Dunning 1993) and simple_maths are defined for zero cells;
    Log Ratio (Hardie 2014) and %DIFF are NOT — they return None (JSON
    null) when the category is absent from either side, and the UI shows
    an em dash. `cochran_warning` flags 2x2 tables whose smallest expected
    cell is < 5 (Cochran's validity rule) — the chi-square/LL p-value
    approximation behind the significance claim is unreliable there.
    """
    return {
        "log_likelihood": round(keyness_ll(f1, f2, N1, N2), 2),
        "log_ratio": round(log_ratio(f1, f2, N1, N2), 3) if (f1 > 0 and f2 > 0) else None,
        "pct_diff": round(pct_diff(f1, f2, N1, N2), 1) if (f1 > 0 and f2 > 0) else None,
        "simple_maths": round(simple_maths(f1, f2, N1, N2), 3),
        "cochran_warning": chi2_min_expected(f1, N1 - f1, f2, N2 - f2) < 5,
    }


async def compute_discourse_analysis(
    session: AsyncSession,
    corpus_id: str,
    *,
    taxonomy: str = "hyland2005",
    limit_examples: int = 5,
    compare_corpus_id: str | None = None,
) -> DiscourseResult:
    """Detect discourse markers across the corpus under a named taxonomy.

    taxonomy: hyland2005 (default) | hallidayhasan1976 | martinwhite2005
    | usas. Raises ValueError for unknown keys — the API layer maps that
    to a 400 listing the supported values.

    v1.2.7 (§3): every category row carries `dp` (dispersion across
    documents). When ``compare_corpus_id`` is set, the same taxonomy is
    run over the comparison corpus and each row additionally carries the
    keyness battery (log_likelihood, log_ratio, pct_diff, simple_maths,
    cochran_warning) — effect size + significance + a Cochran low-power
    warning, all from the shared measures library.
    """
    key = (taxonomy or "hyland2005").strip().lower()
    if key == USAS_TAXONOMY_KEY:
        return await compute_usas_discourse_analysis(
            session, corpus_id, limit_examples=limit_examples,
            compare_corpus_id=compare_corpus_id,
        )
    if key == SFG_TAXONOMY_KEY:
        return await compute_sfg_discourse_analysis(
            session, corpus_id, limit_examples=limit_examples,
            compare_corpus_id=compare_corpus_id,
        )
    if key == PERSUASION_TAXONOMY_KEY:
        if compare_corpus_id:
            raise ValueError(
                "compare_corpus_id is not supported for the persuasion lens "
                "(document-level scores, not token frequencies)"
            )
        return await compute_persuasion_discourse_analysis(
            session, corpus_id, limit_examples=limit_examples,
        )
    spec = DISCOURSE_TAXONOMIES.get(key)
    if spec is None:
        raise ValueError(
            f"Unknown discourse taxonomy: {taxonomy}. Supported: "
            f"{[*DISCOURSE_TAXONOMIES.keys(), USAS_TAXONOMY_KEY, SFG_TAXONOMY_KEY, PERSUASION_TAXONOMY_KEY]}"
        )

    version_id = await _latest_version_id(session, corpus_id)
    if not version_id:
        return DiscourseResult(
            categories={}, total_tokens=0, taxonomy=spec["name"],
            taxonomy_key=key, citation=spec["citation"],
        )

    total_tokens = await _corpus_size(session, version_id)
    sentences = await _load_parses(session, version_id)

    all_categories = spec["categories"]
    counts, examples, per_doc, doc_sizes = _count_cue_categories(
        sentences,
        all_categories,
        limit_examples=limit_examples,
        include_lexical_cohesion=(key == "hallidayhasan1976"),
    )
    dp_by_cat = _per_category_dp(counts, per_doc, doc_sizes)

    categories: dict[str, dict] = {}
    for cat, count in counts.most_common():
        per_million = (count / total_tokens * 1_000_000) if total_tokens else 0.0
        categories[cat] = {
            "freq": count,
            "per_million": round(per_million, 2),
            "examples": examples[cat],
            "dp": dp_by_cat.get(cat, 0.0),
        }

    # v1.2.7 (§3): optional keyness comparison against a second corpus run
    # under the SAME taxonomy. Rows are the union of categories seen on
    # either side (freq 0 rows make the "absent here, common there"
    # contrast visible, which is exactly what keyness is for).
    compare_total: int | None = None
    if compare_corpus_id:
        compare_version_id = await _latest_version_id(session, compare_corpus_id)
        if compare_version_id:
            compare_total = await _corpus_size(session, compare_version_id)
            compare_sentences = await _load_parses(session, compare_version_id)
            c_counts, _c_examples, _c_per_doc, _c_sizes = _count_cue_categories(
                compare_sentences,
                all_categories,
                limit_examples=0,
                include_lexical_cohesion=(key == "hallidayhasan1976"),
            )
            for cat in sorted(set(categories) | set(c_counts)):
                row = categories.setdefault(
                    cat,
                    {
                        "freq": 0,
                        "per_million": 0.0,
                        "examples": [],
                        "dp": 0.0,
                    },
                )
                # v1.2.9: expose the reference side's rate so the UI can
                # draw grouped target-vs-reference bars (green/purple).
                c_freq = c_counts.get(cat, 0)
                row["ref_freq"] = c_freq
                row["ref_per_million"] = (
                    round(c_freq / compare_total * 1_000_000, 2) if compare_total else 0.0
                )
                row.update(
                    _keyness_fields(
                        row["freq"], total_tokens,
                        c_freq, compare_total,
                    )
                )

    return DiscourseResult(
        categories=categories,
        total_tokens=total_tokens,
        taxonomy=spec["name"],
        taxonomy_key=key,
        citation=spec["citation"],
        compare_corpus_id=compare_corpus_id if compare_total is not None else None,
        compare_total_tokens=compare_total,
    )


async def _count_usas_tags(
    session: AsyncSession,
    version_id: str,
    language: str,
    *,
    limit_examples: int,
) -> tuple[Counter, dict[str, list[dict]], dict[str, Counter], Counter, int, int]:
    """v1.2.7 (§3): USAS top-level scan, factored out so the target and
    the comparison corpus run IDENTICAL detection semantics (the compare-
    side keyness is only valid if both sides count the same way).

    Returns (tag_counts, tag_examples, tag_doc_counts, doc_sizes, matched,
    total_tokens). Doc sizes exclude punct/space, matching the DP
    convention of the cue-based lens.
    """
    from nlp.tagsets import semantic_lookup

    total_tokens = await _corpus_size(session, version_id)
    stmt = (
        select(Token.lemma, Token.text, Token.document_id, Token.sentence_idx,
               Token.token_idx, Token.is_punct, Token.pos)
        .where(Token.version_id == version_id)
        .order_by(Token.document_id, Token.sentence_idx, Token.token_idx)
    )
    rows_raw = (await session.execute(stmt)).all()

    tag_counts: Counter = Counter()
    tag_examples: dict[str, list[dict]] = defaultdict(list)
    tag_doc_counts: dict[str, Counter] = defaultdict(Counter)
    doc_sizes: Counter = Counter()
    matched = 0
    for lemma, text, doc_id, sent_idx, tok_idx, is_punct, pos in rows_raw:
        if is_punct or (pos or "") == "SPACE":
            continue
        doc_sizes[doc_id] += 1
        tag = semantic_lookup(lemma or "", text or "", language)
        if not tag:
            continue
        matched += 1
        tag_counts[tag] += 1
        tag_doc_counts[tag][doc_id] += 1
        if len(tag_examples[tag]) < limit_examples:
            tag_examples[tag].append(
                {
                    "cue": (lemma or text or "").lower(),
                    "evidence_id": f"{doc_id}:{sent_idx}:{tok_idx}",
                    "sentence_preview": "",
                }
            )
    return tag_counts, tag_examples, tag_doc_counts, doc_sizes, matched, total_tokens


async def compute_usas_discourse_analysis(
    session: AsyncSession,
    corpus_id: str,
    *,
    limit_examples: int = 5,
    compare_corpus_id: str | None = None,
) -> DiscourseResult:
    """CLAWS/USAS top-level semantic distribution re-read as discourse-
    relevant features (v1.2.6).

    Uses the SAME lexicon-based lookup as the semantic-analysis tool
    (reference-data/tagsets/usas-<lang>-top.tsv) — honest label: this is
    NOT the licensed CLAWS/USAS tagger. Each matched token contributes to
    its top-level letter category; categories are additionally grouped
    into discourse-functional readings (communication, cognition, emotion,
    ideology...) via USAS_DISCOURSE_GROUPS so the Discourse page can show
    what the semantic profile MEANS for discourse analysis.

    v1.2.7 (§3): per-category `dp` + optional keyness comparison against
    another corpus (each side uses its own language's bundled lexicon).
    """
    from nlp.tagsets import USAS_TOP_LABELS, load_semantic_lexicon
    from storage.models import Corpus as CorpusModel

    version_id = await _latest_version_id(session, corpus_id)
    if not version_id:
        return DiscourseResult(
            categories={}, total_tokens=0,
            taxonomy="CLAWS/USAS semantic tagset (top-level)",
            taxonomy_key=USAS_TAXONOMY_KEY,
            citation=USAS_CITATION,
            unmatched_percent=100.0,
        )

    corpus_row = await session.get(CorpusModel, corpus_id)
    language = corpus_row.language if corpus_row and corpus_row.language else "en"
    if not load_semantic_lexicon(language):
        raise ValueError(f"usas_lexicon_missing:{language}")

    total_tokens = await _corpus_size(session, version_id)
    tag_counts, tag_examples, tag_doc_counts, doc_sizes, matched, _ = (
        await _count_usas_tags(session, version_id, language, limit_examples=limit_examples)
    )

    dp_by_cat = _per_category_dp(tag_counts, tag_doc_counts, doc_sizes)

    categories: dict[str, dict] = {}
    for tag, count in tag_counts.most_common():
        per_million = (count / total_tokens * 1_000_000) if total_tokens else 0.0
        categories[tag] = {
            "freq": count,
            "per_million": round(per_million, 2),
            "examples": tag_examples[tag],
            "label": USAS_TOP_LABELS.get(tag, "Unknown"),
            "group": USAS_DISCOURSE_GROUPS.get(tag, "Other"),
            "dp": dp_by_cat.get(tag, 0.0),
        }

    # v1.2.7 (§3): optional keyness comparison. The comparison corpus uses
    # ITS OWN language lexicon; comparing across languages is technically
    # possible but semantically dubious, so the UI labels the comparison.
    compare_total: int | None = None
    if compare_corpus_id:
        compare_version_id = await _latest_version_id(session, compare_corpus_id)
        if compare_version_id:
            compare_row = await session.get(CorpusModel, compare_corpus_id)
            compare_lang = compare_row.language if compare_row and compare_row.language else "en"
            if not load_semantic_lexicon(compare_lang):
                raise ValueError(f"usas_lexicon_missing:{compare_lang}")
            compare_total = await _corpus_size(session, compare_version_id)
            c_counts, _c_ex, _c_dc, _c_sz, _c_matched, _c_total = (
                await _count_usas_tags(
                    session, compare_version_id, compare_lang, limit_examples=0
                )
            )
            for tag in sorted(set(categories) | set(c_counts)):
                row = categories.setdefault(
                    tag,
                    {
                        "freq": 0,
                        "per_million": 0.0,
                        "examples": [],
                        "label": USAS_TOP_LABELS.get(tag, "Unknown"),
                        "group": USAS_DISCOURSE_GROUPS.get(tag, "Other"),
                        "dp": 0.0,
                    },
                )
                # v1.2.9: expose the reference side's rate (grouped bars).
                c_freq = c_counts.get(tag, 0)
                row["ref_freq"] = c_freq
                row["ref_per_million"] = (
                    round(c_freq / compare_total * 1_000_000, 2) if compare_total else 0.0
                )
                row.update(
                    _keyness_fields(
                        row["freq"], total_tokens,
                        c_freq, compare_total,
                    )
                )

    unmatched = round((total_tokens - matched) / total_tokens * 100, 2) if total_tokens else 0.0
    return DiscourseResult(
        categories=categories,
        total_tokens=total_tokens,
        taxonomy="CLAWS/USAS semantic tagset (top-level)",
        taxonomy_key=USAS_TAXONOMY_KEY,
        citation=USAS_CITATION,
        unmatched_percent=unmatched,
        compare_corpus_id=compare_corpus_id if compare_total is not None else None,
        compare_total_tokens=compare_total,
    )


# --------------------------------------------------------------------------- #
# §8.13b UD v2 syntax upgrade (v1.2.7, §2)
#
# Three additions over the basic dependency queries above, all computed
# from the SAME parses (no new pipeline):
#   1. ud_profile      — the 37 universal relations profiled by functional
#                        group (nlp/ud_relations.py inventory)
#   2. valency_frames  — argument-frame profiles for one verb lemma
#   3. sentence_tree   — raw head/rel tokens for one sentence, rendered
#                        as a displaCy-style arc diagram in the UI
# --------------------------------------------------------------------------- #


@dataclass
class UDProfileResult:
    total_relations: int
    relations: list[dict]  # [{relation, group, group_label, description, freq, per_million}]
    groups: list[dict]     # [{group, label, freq, percent}]
    citation: str = (
        "Nivre, J., de Marneffe, M.-C., Ginter, F., Hajič, J., Manning, C.D., "
        "Pyysalo, S., Schuster, S., Tyers, F., & Zeman, D. (2020). Universal "
        "Dependencies v2: An evolving multilingual treebank collection. "
        "LREC 2020. https://universaldependencies.org"
    )


async def compute_ud_profile(session: AsyncSession, corpus_id: str) -> UDProfileResult:
    """Profile the corpus over the 37 UD v2 universal relations, grouped by
    grammatical function. Subtypes collapse onto their base relation
    (``nsubj:pass`` → ``nsubj``) — the universal inventory's own rule."""
    from nlp.ud_relations import UD_RELATION_GROUPS, UD_RELATION_INFO, base_relation

    version_id = await _latest_version_id(session, corpus_id)
    if not version_id:
        return UDProfileResult(total_relations=0, relations=[], groups=[])

    sentences = await _load_parses(session, version_id)
    rel_counts: Counter = Counter()
    for sent in sentences:
        for tok in sent:
            if (tok.get("pos") or "") == "SPACE":
                continue
            base = base_relation(tok.get("rel"))
            if base:
                rel_counts[base] += 1

    total = sum(rel_counts.values())
    relations = [
        {
            "relation": rel,
            "group": info[0],
            "group_label": UD_RELATION_GROUPS.get(info[0], info[0]),
            "description": info[1],
            "freq": freq,
            "per_million": round(freq / total * 1_000_000, 2) if total else 0.0,
        }
        for rel, freq in rel_counts.most_common()
        if (info := UD_RELATION_INFO.get(rel))
    ]

    group_counts: Counter = Counter()
    for rel, freq in rel_counts.items():
        info = UD_RELATION_INFO.get(rel)
        if info:
            group_counts[info[0]] += freq
    groups = [
        {
            "group": g,
            "label": UD_RELATION_GROUPS.get(g, g),
            "freq": freq,
            "percent": round(freq / total * 100, 2) if total else 0.0,
        }
        for g, freq in group_counts.most_common()
    ]
    return UDProfileResult(total_relations=total, relations=relations, groups=groups)


# Relations treated as arguments/complements when building valency frames.
_VALENCY_SLOT_RELS = {"nsubj", "csubj", "obj", "iobj", "ccomp", "xcomp", "obl"}


@dataclass
class ValencyResult:
    lemma: str
    total_occurrences: int  # times the lemma is the HEAD of a dependency
    frames: list[dict]      # [{frame, freq, percent, examples}]
    obliques: list[dict]    # [{prep, freq}] — case-markers of its obl children
    citation: str = (
        "Frames are observed argument combinations (nsubj/obj/iobj/xcomp/"
        "ccomp/obl) of the lemma as dependency head. Cf. the UD v2 valency "
        "pattern work: Nivre et al. (2020), https://universaldependencies.org"
    )


async def compute_valency_frames(
    session: AsyncSession,
    corpus_id: str,
    *,
    lemma: str,
    limit: int = 20,
) -> ValencyResult:
    """Observed argument frames for one verb lemma (§2 valency).

    A frame is the sorted set of argument/complement relations realized by
    the lemma's children in a single occurrence (e.g. ``nsubj+obj``). The
    oblique's case-marker (preposition) is tracked separately rather than
    inside the frame string, so ``obl`` frames stay comparable.
    """
    target = (lemma or "").strip().lower()
    if not target:
        raise ValueError("lemma is required")

    version_id = await _latest_version_id(session, corpus_id)
    if not version_id:
        return ValencyResult(lemma=target, total_occurrences=0, frames=[], obliques=[])

    sentences = await _load_parses(session, version_id)
    frame_counts: Counter = Counter()
    frame_examples: dict[str, list[str]] = defaultdict(list)
    obl_preps: Counter = Counter()
    total_heads = 0

    for sent in sentences:
        for tok in sent:
            if (tok.get("lemma") or "").lower() != target:
                continue
            rel_base = base_relation(tok["rel"]) if tok.get("rel") else ""
            # dep_head is 1-based within the sentence; token_idx is 0-based
            # (ingestion stores enumerate() positions). A self-head is an
            # alternative root encoding seen in some parse paths.
            is_root = rel_base == "root" or tok.get("head") == tok["idx"] + 1
            if tok.get("rel") and rel_base not in ("", "root") and not is_root:
                continue
            head_idx = tok["idx"]
            # children point at the head's 1-based position == idx + 1
            children = [t for t in sent if t.get("head") == head_idx + 1 and t is not tok]
            if not children:
                continue
            total_heads += 1
            slots: list[str] = []
            prep = ""
            for child in children:
                base = base_relation(child.get("rel"))
                if base == "case":
                    # ClearNLP parses hang the preposition directly off the
                    # verb (prep) with the oblique noun as ITS child (pobj).
                    prep = (child.get("text") or "").lower()
                    slots.append("obl")
                elif base == "obl":
                    # UD-style parse: obl child; case marker is ITS child.
                    prep = _obl_case_marker(sent, child)
                    slots.append("obl")
                elif base in _VALENCY_SLOT_RELS:
                    slots.append(base)
            slots = [s for s in slots if s != "obl" or "obl" not in slots[: slots.index(s)]]
            if not slots:
                continue
            frame = "+".join(sorted(set(slots)))
            frame_counts[frame] += 1
            if len(frame_examples[frame]) < 3:
                frame_examples[frame].append(f"{tok['doc']}:{tok['sent']}")
            if prep:
                obl_preps[prep] += 1

    frames = [
        {
            "frame": frame,
            "freq": freq,
            "percent": round(freq / total_heads * 100, 2) if total_heads else 0.0,
            "examples": frame_examples[frame],
        }
        for frame, freq in frame_counts.most_common(limit)
    ]
    obliques = [
        {"prep": prep, "freq": freq}
        for prep, freq in obl_preps.most_common(10)
    ]
    return ValencyResult(lemma=target, total_occurrences=total_heads, frames=frames, obliques=obliques)


def _obl_case_marker(sent: list[dict], obl_tok: dict) -> str:
    """Lowercase surface form of an oblique's ``case`` child (preposition),
    or '' when the obl is case-marked morphologically (no case child)."""
    for child in sent:
        if child.get("head") == obl_tok["idx"] + 1 and base_relation(child.get("rel")) == "case":
            return (child.get("text") or "").lower()
    return ""


@dataclass
class SentenceListResult:
    total_sentences: int
    items: list[dict]  # [{doc, sent, token_count, preview}]


async def list_corpus_sentences(
    session: AsyncSession,
    corpus_id: str,
    *,
    limit: int = 30,
    offset: int = 0,
) -> SentenceListResult:
    """Paginated sentence index for the syntax-tree picker."""
    version_id = await _latest_version_id(session, corpus_id)
    if not version_id:
        return SentenceListResult(total_sentences=0, items=[])

    sentences = await _load_parses(session, version_id)
    # Deterministic order: (doc, sent)
    sentences.sort(key=lambda s: (s[0]["doc"], s[0]["sent"]))
    total = len(sentences)
    items = []
    for sent in sentences[offset : offset + limit]:
        toks = [t for t in sent if (t.get("pos") or "") != "SPACE"]
        items.append(
            {
                "doc": toks[0]["doc"] if toks else "",
                "sent": toks[0]["sent"] if toks else 0,
                "token_count": len(toks),
                "preview": " ".join(t["text"] for t in toks)[:160],
            }
        )
    return SentenceListResult(total_sentences=total, items=items)


@dataclass
class SentenceTreeResult:
    doc: str
    sent: int
    tokens: list[dict]  # [{id (1-based), text, lemma, pos, head (0=root), rel, rel_base}]
    citation: str = (
        "Rendered from the corpus dependency parses (UD v2). See Nivre et "
        "al. (2020), https://universaldependencies.org"
    )


async def compute_sentence_tree(
    session: AsyncSession,
    corpus_id: str,
    *,
    doc: str,
    sent: int,
) -> SentenceTreeResult:
    """Head/rel token list for one sentence — the UI draws it as a
    displaCy-style arc diagram (§2)."""
    from nlp.ud_relations import base_relation

    version_id = await _latest_version_id(session, corpus_id)
    if not version_id:
        return SentenceTreeResult(doc=doc, sent=sent, tokens=[])

    sentences = await _load_parses(session, version_id)
    for sent_tokens in sentences:
        if not sent_tokens:
            continue
        if sent_tokens[0]["doc"] == doc and sent_tokens[0]["sent"] == sent:
            toks = [t for t in sent_tokens if (t.get("pos") or "") != "SPACE"]
            # dep_head is 1-based within the ORIGINAL sentence sequence;
            # map original positions → sequential ids so the UI can draw
            # arcs directly. A self-head (dep_head == own 1-based position)
            # is treated as root (0) — some parse paths encode root that way.
            idx_to_id = {t["idx"]: i + 1 for i, t in enumerate(toks)}
            out = []
            for i, t in enumerate(toks):
                raw_head = t.get("head") or 0
                if raw_head == t["idx"] + 1:
                    normalized_head = 0  # self-head = root
                elif raw_head == 0:
                    normalized_head = 0
                else:
                    normalized_head = idx_to_id.get(raw_head - 1, 0)
                out.append(
                    {
                        "id": i + 1,
                        "text": t.get("text") or "",
                        "lemma": t.get("lemma") or "",
                        "pos": t.get("pos") or "",
                        "head": normalized_head,
                        "rel": t.get("rel") or "",
                        "rel_base": base_relation(t.get("rel")),
                    }
                )
            return SentenceTreeResult(doc=doc, sent=sent, tokens=out)
    raise ValueError(f"sentence_not_found:{doc}:{sent}")


# --------------------------------------------------------------------------- #
# §8.15a Dependency concordance (v1.2.8, review #2)
#
# One row per dependency hit: left context | node | right context | head |
# relation | source. This is the KWIC-style layout familiar from Sketch
# Engine / AntConc, applied to dependency hits, so the syntax panel no
# longer depends on a per-instance sentence dropdown.
# --------------------------------------------------------------------------- #

DEP_CONCORDANCE_WINDOW = 6

DEP_CONCORDANCE_CITATION = (
    "Rows come from the corpus dependency parses (UD v2; Nivre et al. 2020, "
    "https://universaldependencies.org). The node is colour-coded by "
    "part of speech following the displaCy convention; Relation is the "
    "node's base UD relation, with the raw subtype in parentheses when the "
    "parse carries one."
)


@dataclass
class DepConcordanceResult:
    rows: list[dict]  # one row per hit (see compute_dep_concordance)
    total: int
    node_query: str
    relation: str | None
    pos: str | None
    citation: str = DEP_CONCORDANCE_CITATION


def _dep_matcher(
    node_query: str, *, level: str, regex: bool, case_sensitive: bool
):
    """Build a token predicate with concordancer semantics: whole-token
    match (word/lemma), ``*``/``?`` wildcards, or Python regex."""
    import fnmatch
    import re

    if not node_query:
        return None
    if regex:
        pattern = re.compile(node_query, 0 if case_sensitive else re.IGNORECASE)

        def matches_regex(tok: dict[str, Any]) -> bool:
            hay = tok.get("text") if level == "word" else (tok.get("lemma") or "")
            return bool(hay) and bool(pattern.search(hay))

        return matches_regex

    needle = node_query if case_sensitive else node_query.lower()
    if "*" in needle or "?" in needle:
        rx = re.compile(fnmatch.translate(needle), 0 if case_sensitive else re.IGNORECASE)

        def matches_wildcard(tok: dict[str, Any]) -> bool:
            hay = tok.get("text") if level == "word" else (tok.get("lemma") or "")
            return bool(hay) and bool(rx.fullmatch(hay))

        return matches_wildcard

    def matches_plain(tok: dict[str, Any]) -> bool:
        hay = tok.get("text") if level == "word" else (tok.get("lemma") or "")
        if not hay:
            return False
        return hay if case_sensitive else hay.lower() == needle

    return matches_plain


async def compute_dep_concordance(
    session: AsyncSession,
    corpus_id: str,
    *,
    node_query: str = "",
    level: str = "word",
    regex: bool = False,
    case_sensitive: bool = False,
    relation: str | None = None,
    pos: str | None = None,
    window: int = DEP_CONCORDANCE_WINDOW,
    limit: int = 100,
) -> DepConcordanceResult:
    """Concordance over dependency hits (v1.2.8, review #2).

    Every token whose base UD relation and/or surface form matches the
    filters becomes one row: left context | node | right context | head
    token | relation label | source reference. Row order is deterministic
    (document, sentence, token). ``relation`` matches the node's base UD
    relation OR its raw subtype (so ``nsubj`` also catches ``nsubj:pass``).
    """
    from nlp.ud_relations import base_relation
    from storage.models import Document as DocumentModel

    version_id = await _latest_version_id(session, corpus_id)
    if not version_id:
        return DepConcordanceResult(
            rows=[], total=0, node_query=node_query, relation=relation, pos=pos
        )

    matcher = _dep_matcher(
        node_query.strip(), level=level, regex=regex, case_sensitive=case_sensitive
    )
    if matcher is None and not (relation and relation.strip()) and not (pos and pos.strip()):
        raise ValueError("dep_concordance_empty_query: give a node query, a relation, or a POS")

    sentences = await _load_parses(session, version_id)
    sentences.sort(key=lambda s: (s[0]["doc"], s[0]["sent"]) if s else ("", 0))

    rel_filter = relation.strip() if relation and relation.strip() else None
    pos_filter = pos.strip().upper() if pos and pos.strip() else None

    rows: list[dict] = []
    total = 0
    for sent_tokens in sentences:
        if not sent_tokens:
            continue
        surface = [t for t in sent_tokens if (t.get("pos") or "") != "SPACE"]
        if not surface:
            continue
        for i, tok in enumerate(surface):
            tok_rel_base = base_relation(tok.get("rel"))
            if rel_filter and rel_filter not in (tok_rel_base, tok.get("rel") or ""):
                continue
            if pos_filter and (tok.get("pos") or "").upper() != pos_filter:
                continue
            if matcher is not None and not matcher(tok):
                continue
            total += 1
            if len(rows) >= limit:
                continue  # keep counting, stop storing

            left = " ".join(t["text"] for t in surface[max(0, i - window) : i])
            right = " ".join(t["text"] for t in surface[i + 1 : i + 1 + window])

            raw_head = tok.get("head") or 0
            head_text, head_pos = "ROOT", ""
            if raw_head > 0 and raw_head != tok["idx"] + 1:
                head = next((t for t in sent_tokens if t["idx"] == raw_head - 1), None)
                if head is not None and (head.get("pos") or "") != "SPACE":
                    head_text = head.get("text") or ""
                    head_pos = head.get("pos") or ""

            rel_full = tok.get("rel") or ""
            rel_label = tok_rel_base
            if rel_full and rel_full != tok_rel_base:
                rel_label = f"{tok_rel_base} ({rel_full})"

            rows.append(
                {
                    "evidence_id": f"{tok['doc']}:{tok['sent']}:{tok['idx']}",
                    "document_filename": "",
                    "doc": tok["doc"],
                    "sentence_idx": tok["sent"],
                    "token_idx": tok["idx"],
                    "left": left,
                    "node": tok.get("text") or "",
                    "node_pos": tok.get("pos") or "",
                    "node_lemma": tok.get("lemma") or "",
                    "relation": rel_label,
                    "head": head_text,
                    "head_pos": head_pos,
                    "right": right,
                }
            )

    # Filenames in one extra query (keeps the row builder a pure function).
    if rows:
        doc_ids = {r["doc"] for r in rows}
        name_rows = (
            await session.execute(
                select(DocumentModel.id, DocumentModel.filename).where(
                    DocumentModel.id.in_(doc_ids)
                )
            )
        ).all()
        names = {d_id: fname for d_id, fname in name_rows}
        for r in rows:
            r["document_filename"] = names.get(r["doc"], r["doc"])

    return DepConcordanceResult(
        rows=rows, total=total, node_query=node_query, relation=relation, pos=pos
    )


# --------------------------------------------------------------------------- #
# §8.15b SFG Transitivity & Modality lens (v1.2.7, §2)
#
# Halliday & Matthiessen (2014) transitivity process types and the
# modality system, implemented as an HONEST lexicon+structural heuristic
# over the dependency parses (USAS-style): process types are assigned only
# when a lexical cue or a structural cue (copula, existential) fires, and
# `unmatched_percent` reports the share of clauses left unassigned. This
# is a starter heuristic, NOT the full IFG system — the citation says so.
# --------------------------------------------------------------------------- #

SFG_TAXONOMY_KEY = "sfg_hm2014"

SFG_CITATION = (
    "Halliday, M.A.K., & Matthiessen, C.M.I.M. (2014). Halliday's "
    "Introduction to Functional Grammar (4th ed.). London: Routledge. "
    "Process types and modality detected via a structural+lexicon starter "
    "heuristic over dependency parses - an approximation, not the full "
    "IFG system; unmatched clauses are reported, not force-bucketed."
)

# Verbalization processes (verbal: 'X said that ...')
SFG_VERBAL_LEXICON = {
    "say", "tell", "report", "state", "claim", "ask", "answer", "reply",
    "explain", "describe", "announce", "declare", "argue", "promise",
    "warn", "suggest", "mention", "add", "note", "demand", "request",
}
# Perception/cognition/affectation (mental)
SFG_MENTAL_LEXICON = {
    "see", "hear", "feel", "sense", "notice", "perceive", "watch", "listen",
    "think", "know", "believe", "understand", "realise", "realize",
    "imagine", "suppose", "guess", "doubt", "forget", "remember",
    "want", "wish", "hope", "fear", "like", "love", "hate", "enjoy",
    "prefer", "mind", "wonder", "expect",
}
# Behavioural: physiological/behavioural consciousness (between material & mental)
SFG_BEHAVIOURAL_LEXICON = {
    "laugh", "cry", "smile", "grin", "frown", "sigh", "breathe", "cough",
    "sneeze", "yawn", "sleep", "wake", "stare", "glare", "gaze", "look",
    "tremble", "shiver", "nod", "shrug", "dream", "chat", "gossip", "grumble",
}
# Doing & happening (material) — largest honest starter set
SFG_MATERIAL_LEXICON = {
    "do", "make", "take", "give", "get", "go", "come", "run", "walk", "move",
    "carry", "bring", "put", "break", "hit", "cut", "build", "create",
    "destroy", "send", "receive", "buy", "sell", "open", "close", "eat",
    "drink", "cook", "write", "read", "draw", "throw", "catch", "kick",
    "fall", "rise", "grow", "change", "increase", "decrease", "arrive",
    "leave", "enter", "exit", "start", "stop", "continue", "finish",
    "work", "play", "help", "kill", "die", "live", "sit", "stand", "drive",
    "travel", "wash", "clean", "fix", "repair", "pay", "spend", "cost",
    "lose", "find", "keep", "hold", "lift", "drop", "fill", "remove",
}
# Relational: attributive/identifying cues beyond the structural copula
SFG_RELATIONAL_LEXICON = {
    "be", "seem", "appear", "become", "remain", "stay", "look", "sound",
    "smell", "taste", "belong", "contain", "include", "consist", "involve",
    "represent", "constitute", "equal", "mean", "lack", "resemble", "matter",
}
# Modality — MODALIZATION (probability / usuality) and MODULATION
# (obligation / inclination), per IFG ch. 4 (Halliday & Matthiessen 2014).
SFG_MODALITY_AUX = {
    "modality.probability": {"may", "might", "could", "will", "shall", "must"},
    "modality.obligation": {"must", "should", "ought", "need"},
    "modality.inclination": {},
}
SFG_MODALITY_ADVERB = {
    "modality.probability": {"perhaps", "possibly", "probably", "likely", "certainly", "definitely"},
    "modality.usuality": {"usually", "often", "always", "sometimes", "never", "seldom", "rarely", "generally", "normally"},
}
# Catenative inclination: verb + xcomp open clausal complement
SFG_INCLINATION_LEXICON = {
    "want", "wish", "intend", "decide", "agree", "refuse", "offer",
    "promise", "manage", "fail", "try", "plan", "hope", "attempt",
}


@dataclass
class SFGResult:
    categories: dict[str, dict]  # {category: {freq, per_million, examples}}
    total_clauses: int
    unmatched_percent: float  # clauses with no determinate process type
    citation: str = SFG_CITATION


def _clause_verb_units(sent: list[dict]) -> list[dict]:
    """Clause 'units' = the verb heading each clause: root tokens plus
    dependents heading subordinate/coordinated clauses (conj, advcl,
    ccomp, xcomp, acl, parataxis). Deterministic, parse-driven."""
    clause_rels = {"conj", "advcl", "ccomp", "xcomp", "acl", "parataxis"}
    units = []
    for tok in sent:
        base = base_relation(tok.get("rel")) if tok.get("rel") else ""
        pos = tok.get("pos") or ""
        if base == "root" or (base in clause_rels and pos in ("VERB", "AUX")):
            units.append(tok)
    return units


def _children_of(sent: list[dict], tok: dict) -> list[dict]:
    # dep_head (1-based) == token_idx (0-based) + 1
    return [t for t in sent if t.get("head") == tok["idx"] + 1 and t is not tok]


def _classify_process_type(sent: list[dict], verb: dict) -> str:
    """One process-type reading per clause, structural cues first, then
    lexicon. '' = no determinate reading (honest unmatched)."""
    lemma = (verb.get("lemma") or "").lower()
    children = _children_of(sent, verb)
    child_rels = {base_relation(c.get("rel")) for c in children}
    child_lemmas = {(c.get("lemma") or "").lower() for c in children}

    # 1. existential: "there be" (expl child or 'there' subject of be)
    if lemma == "be" and ("expl" in child_rels or "there" in child_lemmas):
        return "transitivity.existential"
    # 2. relational via copula (structural, strongest cue)
    if "cop" in child_rels:
        return "transitivity.relational"
    # 3. lexical starter sets (verbal > mental > behavioural > material >
    #    relational; behavioural overlaps material/mental — first match wins)
    if lemma in SFG_VERBAL_LEXICON:
        return "transitivity.verbal"
    if lemma in SFG_MENTAL_LEXICON:
        return "transitivity.mental"
    if lemma in SFG_BEHAVIOURAL_LEXICON:
        return "transitivity.behavioural"
    if lemma in SFG_MATERIAL_LEXICON:
        return "transitivity.material"
    if lemma in SFG_RELATIONAL_LEXICON:
        return "transitivity.relational"
    # 4. behavioral fallback: 'there'-existential via bare be + locative obl
    if lemma == "be" and "obl" in child_rels:
        return "transitivity.existential"
    return ""


def _clause_modality_categories(sent: list[dict], verb: dict) -> list[str]:
    """Modality readings realized inside this clause (0..n categories)."""
    found: list[str] = []
    children = _children_of(sent, verb)
    lemma = (verb.get("lemma") or "").lower()
    for child in children:
        base = base_relation(child.get("rel"))
        cl = (child.get("lemma") or "").lower()
        if base == "aux" and cl:
            for cat, lemmas in SFG_MODALITY_AUX.items():
                if cl in lemmas and cat not in found:
                    found.append(cat)
        if base == "advmod" and cl:
            for cat, lemmas in SFG_MODALITY_ADVERB.items():
                if cl in lemmas and cat not in found:
                    found.append(cat)
    # inclination: catenative verb + open complement
    if lemma in SFG_INCLINATION_LEXICON and any(
        base_relation(c.get("rel")) == "xcomp" for c in children
    ):
        if "modality.inclination" not in found:
            found.append("modality.inclination")
    return found


def _count_sfg_categories(
    sentences: list[list[dict]],
    *,
    limit_examples: int,
) -> tuple[Counter, dict[str, list[dict]], int, int]:
    """SFG scan over parsed sentences (factored so the target and the
    comparison corpus run identical detection semantics, §3-compat).

    Returns (counts, examples, total_clauses, matched_clauses)."""
    counts: Counter = Counter()
    examples: dict[str, list[dict]] = defaultdict(list)
    total_clauses = 0
    matched_clauses = 0

    for sent in sentences:
        sent_lower = " ".join(t["text"].lower() for t in sent)
        for verb in _clause_verb_units(sent):
            total_clauses += 1
            evidence_id = f"{verb['doc']}:{verb['sent']}:{verb['idx']}"
            process = _classify_process_type(sent, verb)
            if process:
                matched_clauses += 1
                counts[process] += 1
                if len(examples[process]) < limit_examples:
                    examples[process].append(
                        {"cue": (verb.get("lemma") or "").lower(),
                         "evidence_id": evidence_id,
                         "sentence_preview": sent_lower[:120]}
                    )
            for cat in _clause_modality_categories(sent, verb):
                counts[cat] += 1
                if len(examples[cat]) < limit_examples:
                    examples[cat].append(
                        {"cue": (verb.get("lemma") or "").lower(),
                         "evidence_id": evidence_id,
                         "sentence_preview": sent_lower[:120]}
                    )
    return counts, examples, total_clauses, matched_clauses


async def compute_sfg_discourse_analysis(
    session: AsyncSession,
    corpus_id: str,
    *,
    limit_examples: int = 5,
    compare_corpus_id: str | None = None,
) -> DiscourseResult:
    """SFG Transitivity & Modality over dependency parses (v1.2.7 §2).

    Clause units are the verbs heading root/subordinate/coordinated
    clauses. Each clause contributes at most ONE process type (structural
    existential/copula cues first, then lexicon); clauses with no firing
    cue are counted in `unmatched_percent` instead of being force-bucketed.
    Modality categories (probability/usuality/obligation/inclination) are
    detected per clause and may co-occur with any process type.

    Supports the same optional compare_corpus_id keyness battery as the
    other lenses (§3).
    """
    version_id = await _latest_version_id(session, corpus_id)
    if not version_id:
        return DiscourseResult(
            categories={}, total_tokens=0,
            taxonomy="SFG Transitivity & Modality (Halliday & Matthiessen 2014)",
            taxonomy_key=SFG_TAXONOMY_KEY, citation=SFG_CITATION,
            unmatched_percent=100.0,
        )

    total_tokens = await _corpus_size(session, version_id)
    sentences = await _load_parses(session, version_id)
    counts, examples, total_clauses, matched_clauses = _count_sfg_categories(
        sentences, limit_examples=limit_examples
    )

    categories: dict[str, dict] = {}
    for cat, count in counts.most_common():
        per_million = (count / total_tokens * 1_000_000) if total_tokens else 0.0
        categories[cat] = {
            "freq": count,
            "per_million": round(per_million, 2),
            "examples": examples[cat],
        }

    compare_total: int | None = None
    if compare_corpus_id:
        compare_version_id = await _latest_version_id(session, compare_corpus_id)
        if compare_version_id:
            compare_total = await _corpus_size(session, compare_version_id)
            compare_sentences = await _load_parses(session, compare_version_id)
            c_counts, _c_ex, _c_total, _c_matched = _count_sfg_categories(
                compare_sentences, limit_examples=0
            )
            for cat in sorted(set(categories) | set(c_counts)):
                row = categories.setdefault(cat, {"freq": 0, "per_million": 0.0, "examples": []})
                # v1.2.9: expose the reference side's rate (grouped bars).
                c_freq = c_counts.get(cat, 0)
                row["ref_freq"] = c_freq
                row["ref_per_million"] = (
                    round(c_freq / compare_total * 1_000_000, 2) if compare_total else 0.0
                )
                row.update(
                    _keyness_fields(
                        row["freq"], total_tokens, c_freq, compare_total
                    )
                )

    unmatched = round((total_clauses - matched_clauses) / total_clauses * 100, 2) if total_clauses else 0.0
    return DiscourseResult(
        categories=categories,
        total_tokens=total_tokens,
        taxonomy="SFG Transitivity & Modality (Halliday & Matthiessen 2014)",
        taxonomy_key=SFG_TAXONOMY_KEY,
        citation=SFG_CITATION,
        unmatched_percent=unmatched,
        compare_corpus_id=compare_corpus_id if compare_total is not None else None,
        compare_total_tokens=compare_total,
    )


# --------------------------------------------------------------------------- #
# §8.15c Persuasion Index lens (v1.2.7, §4)
#
# Integrates the persuasion-index package (Wang & Gong 2026, EMNLP;
# Apache-2.0) as a citable lens: 15 interpretable dimensions scored per
# document, aggregated to corpus-level 0–100 indices. The optional LIWC /
# concreteness / NRC-VAD resources are NOT required — the package's own
# bundled lexicons carry the core scoring and it degrades honestly.
#
# The package is an OPTIONAL dependency (lazy import): production installs
# without it get an explicit 503 with an install hint, not a crash.
# --------------------------------------------------------------------------- #

PERSUASION_TAXONOMY_KEY = "persuasion_gong2026"

PERSUASION_CITATION = (
    "Wang, Z., & Gong, L. (2026). persuasion-index: Theory-guided, "
    "interpretable analysis of persuasive language (v0.3.0). EMNLP 2026. "
    "Apache-2.0. https://github.com/krystalgong/Persuasion_Index_Code "
    "(arXiv:2606.14580). Scores are aggregated over documents; optional "
    "LIWC/concreteness/VAD resources are not bundled, and the package "
    "degrades those subfeatures to neutral baselines."
)

# Grouping of the 15 PI dimensions onto the classical rhetorical triad,
# grounded against the package's own dimension inventory (persuasion-index
# 0.3.0, verified against PyPI/GitHub): Logos 5, Ethos 4, Pathos 6. This is
# an analysis-facing interpretation, not a claim about the PI paper's own
# taxonomy — but the membership counts below ARE the package's, so the UI
# can never silently drop or misfile a dimension.
PI_DIMENSION_FAMILIES: dict[str, str] = {
    # Logos (5)
    "Evidence": "logos",
    "Logic/Cohesion": "logos",
    "Argumentation": "logos",
    "Specificity": "logos",
    "Opponent’s View": "logos",
    # Ethos (4)
    "Authority/Credibility": "ethos",
    "Politeness": "ethos",
    "Commitment": "ethos",
    "Style": "ethos",
    # Pathos (6)
    "Sentiment": "pathos",
    "Impact": "pathos",
    "Engagement": "pathos",
    "Reciprocity": "pathos",
    "Scarcity/Urgency": "pathos",
    "Propaganda": "pathos",
}

# Canonical 15-dimension inventory. Every lens run emits ALL of these —
# a dimension the scorer returns no mean for shows as a 0 baseline instead
# of being silently dropped from the table/radar.
PI_DIMENSIONS: tuple[str, ...] = tuple(PI_DIMENSION_FAMILIES)

PI_DISCLAIMER = (
    "The Persuasion Index measures rhetorical STRATEGIES (how a text "
    "persuades), not whether its arguments are TRUE. A high score is not "
    "a quality verdict and a low score is not a refutation."
)


def _log_pi_resource_status() -> None:
    """Log the persuasion-index `doctor` resource status (v1.2.8).

    The lens deliberately ships on the package's bundled lexicons: optional
    resources (spaCy NER, concreteness ratings, LIWC, NRC-VAD) only refine
    specific subfeatures and degrade to neutral baselines when absent. Each
    run logs which ones are missing so the choice is visible in the engine
    log, and `GET /discourse/persuasion/health` reports the same payload to
    the UI.
    """
    try:
        from persuasion_index import check_resources

        resources = check_resources()
        missing = sorted(k for k, v in resources.items() if not v.get("available"))
        if missing:
            log.info(
                "persuasion_optional_resources_missing",
                missing=missing,
                policy="shipping on bundled lexicons; affected subfeatures use neutral baselines",
            )
        else:
            log.info("persuasion_optional_resources_complete")
    except Exception as e:  # pragma: no cover — diagnostics must never kill the lens
        log.warning("persuasion_resource_check_failed", error=str(e))


async def _pi_dimension_means(docs: list[tuple[str, str, str]]) -> list[dict[str, float]]:
    """Return per-document {dimension: mean} maps using persuasion-index.

    Multi-document corpora go through ``score_batch`` (index-preserving, one
    pass over the package's vectorised pipeline); single documents use
    ``score``. If the batch path fails for any reason the loop degrades to
    per-document ``score`` calls so one bad document never kills the lens.
    """
    from persuasion_index import score as pi_score

    doc_ids = [d[0] for d in docs]
    texts = [d[2] for d in docs]
    out: list[dict[str, float]] = [{} for _ in docs]

    if len(texts) > 1:
        try:
            from persuasion_index import score_batch as pi_score_batch

            _subfeatures, meta = pi_score_batch(texts)
            # meta is index-aligned; columns are '<dimension>.mean' floats.
            for i in range(len(doc_ids)):
                row = meta.iloc[i]
                for dim in PI_DIMENSIONS:
                    col = f"{dim}.mean"
                    if col in row.index:
                        val = row[col]
                        if val is not None and val == val:  # NaN-safe
                            out[i][dim] = float(val)
            return out
        except Exception as e:
            log.warning(
                "persuasion_score_batch_failed_falling_back", docs=len(texts), error=str(e)
            )

    for i, text in enumerate(texts):
        try:
            result = pi_score(text)
        except Exception as e:  # per-doc resilience
            log.warning("persuasion_score_failed", doc=doc_ids[i], error=str(e))
            continue
        for dim, sub in result.items():
            mean = sub.get("mean") if isinstance(sub, dict) else None
            if mean is not None:
                out[i][dim] = float(mean)
    return out


async def compute_persuasion_discourse_analysis(
    session: AsyncSession,
    corpus_id: str,
    *,
    limit_examples: int = 5,
    max_docs: int = 50,
) -> DiscourseResult:
    """Score every document with persuasion-index and aggregate the 15
    dimensions to corpus-level 0–100 indices (v1.2.7 §4).

    Documents are iterated in id order (deterministic); up to ``max_docs``
    documents are scored and the count is reported so aggregation scope is
    never hidden. Examples cite the highest-scoring document per dimension.
    All 15 canonical dimensions are always present in the output — a
    dimension with no score shows its 0 baseline instead of being dropped.
    """
    from storage.models import Document as DocumentModel

    try:
        from persuasion_index import score as pi_score  # noqa: F401 — presence check
    except ImportError as e:  # optional dependency — honest 503 upstream
        raise ValueError(
            "persuasion_index_missing: install the optional dependency with "
            "`pip install persuasion-index` (or `pip install -e \".[persuasion]\"`)"
        ) from e

    _log_pi_resource_status()

    version_id = await _latest_version_id(session, corpus_id)
    total_tokens = await _corpus_size(session, version_id) if version_id else 0

    stmt = (
        select(DocumentModel.id, DocumentModel.filename, DocumentModel.cleaned_text)
        .where(DocumentModel.corpus_id == corpus_id)
        .order_by(DocumentModel.id)
        .limit(max_docs)
    )
    docs = (await session.execute(stmt)).all()
    docs = [(d_id, name, text) for d_id, name, text in docs if (text or "").strip()]

    dim_scores: dict[str, list[float]] = {dim: [] for dim in PI_DIMENSIONS}
    top_docs: dict[str, tuple[float, str, str]] = {}  # dim -> (score, doc_id, filename)
    scored_docs = 0

    per_doc_means = await _pi_dimension_means(docs)
    for (d_id, name, _text), means in zip(docs, per_doc_means, strict=False):
        if not means:
            continue  # every scoring path failed for this document
        scored_docs += 1
        for dim in PI_DIMENSIONS:
            if dim not in means:
                continue
            mean = means[dim]
            dim_scores[dim].append(mean)
            top = top_docs.get(dim)
            if top is None or mean > top[0]:
                top_docs[dim] = (mean, d_id, name)

    categories: dict[str, dict] = {}
    for dim in PI_DIMENSIONS:
        scores = dim_scores[dim]
        index = round(sum(scores) / len(scores) * 100, 1) if scores else 0.0
        family = PI_DIMENSION_FAMILIES[dim]
        top = top_docs.get(dim)
        categories[f"pi.{family}.{dim}"] = {
            "freq": index,  # 0–100 index, not a token count — see the UI note
            "per_million": None,  # not a frequency measure; UI shows an em dash
            "examples": [
                {
                    "cue": f"{top[0]:.2f}",
                    "evidence_id": top[1],
                    "sentence_preview": top[2],
                }
            ][:limit_examples] if top else [],
            "label": dim,
            "group": family,
            "dp": None,  # document-level scores, not token counts
        }

    return DiscourseResult(
        categories=categories,
        total_tokens=total_tokens,
        taxonomy="Persuasion Index (Wang & Gong 2026) - 15 dimensions",
        taxonomy_key=PERSUASION_TAXONOMY_KEY,
        citation=PERSUASION_CITATION,
        compare_corpus_id=None,
        compare_total_tokens=None,
        scored_documents=scored_docs,
    )


# --------------------------------------------------------------------------- #
# §8.10 Vocabulary profiling
# --------------------------------------------------------------------------- #


@dataclass
class VocabProfileResult:
    total_tokens: int
    total_types: int
    bands: list[dict]  # [{band, freq, percent, examples}]
    rare_words: list[dict]  # off the open frequency list
    academic_words: list[dict]  # in the academic word list


# v1.0.1: the full Coxhead (2000) Academic Word List is loaded from
# reference-data/wordlists/awl-sublists.tsv (570 families, 10 sublists).
# STARTER_AWL remains as a fallback when the data file is unavailable.
@lru_cache(maxsize=1)
def _load_awl() -> frozenset[str]:
    """All AWL forms (headwords + family members), lowercased."""
    forms: set[str] = set()
    # v1.2.8 (review #1): bundle-safe resolution via app.resource_paths —
    # the old three-parent walk missed reference-data inside the packaged
    # engine and silently degraded every vocab profile to STARTER_AWL.
    try:
        from app.resource_paths import resource_path

        path = resource_path("wordlists", "awl-sublists.tsv")
    except FileNotFoundError:
        return frozenset(forms)
    if path.exists():
        for line in path.read_text(encoding="utf-8").splitlines():
            if not line or line.startswith("#"):
                continue
            parts = line.split("\t")
            if not parts or not parts[0]:
                continue
            forms.add(parts[0].strip().lower())
            if len(parts) > 2:
                for member in parts[2].split():
                    forms.add(member.strip().lower())
    return frozenset(forms)


# A small starter Academic Word List (AWL) — fallback only; the full list
# (Coxhead 2000, 570 families) loads from reference-data when present.
STARTER_AWL = {
    "analyze",
    "approach",
    "area",
    "assess",
    "assume",
    "authority",
    "available",
    "benefit",
    "concept",
    "consistent",
    "constitute",
    "context",
    "contract",
    "create",
    "data",
    "define",
    "derive",
    "distribute",
    "economy",
    "environment",
    "establish",
    "estimate",
    "evident",
    "export",
    "factor",
    "finance",
    "formula",
    "function",
    "identify",
    "income",
    "indicate",
    "individual",
    "interpret",
    "involve",
    "issue",
    "labour",
    "legal",
    "legislate",
    "major",
    "method",
    "occur",
    "percent",
    "period",
    "policy",
    "principle",
    "proceed",
    "process",
    "require",
    "research",
    "respond",
    "section",
    "sector",
    "significant",
    "similar",
    "source",
    "specific",
    "structure",
    "theory",
    "vary",
}


async def compute_vocab_profile(
    session: AsyncSession,
    corpus_id: str,
    *,
    rare_threshold: int = 1,  # appears <= this many times in the corpus
    limit: int = 100,
) -> VocabProfileResult:
    """Profile vocabulary into frequency bands (K1, K2, K3-9, AWL, off-list).

    Uses the bundled open English top-200 wordlist as K1 approximation.
    Phase 3 will swap in a proper open frequency corpus.
    """
    version_id = await _latest_version_id(session, corpus_id)
    if not version_id:
        return VocabProfileResult(
            total_tokens=0, total_types=0, bands=[], rare_words=[], academic_words=[]
        )

    # Load bundled K1 wordlist (bundle-safe resolution, review #1)
    k1_set: set[str] = set()
    try:
        from app.resource_paths import resource_path

        k1_path = resource_path("wordlists", "en", "top200.tsv")
    except FileNotFoundError:
        k1_path = None
    if k1_path is not None and k1_path.exists():
        for line in k1_path.read_text().splitlines():
            if line and not line.startswith("#"):
                parts = line.split("\t")
                if parts:
                    k1_set.add(parts[0].lower())

    # Frequency distribution by lemma
    stmt = (
        select(Token.lemma, Token.text, func.count(Token.id))
        .where(Token.version_id == version_id, _is_real_token())
        .group_by(Token.lemma, Token.text)
    )
    rows = (await session.execute(stmt)).all()

    total_tokens = sum(c for _, _, c in rows)
    total_types = len(rows)

    awl_set = _load_awl() or frozenset(STARTER_AWL)

    bands = {"K1": 0, "K2_K9": 0, "AWL": 0, "Off-list": 0}
    rare_words = []
    academic_words = []

    for lemma, text, freq in rows:
        lemma_lower = (lemma or text).lower()
        if lemma_lower in k1_set:
            bands["K1"] += freq
        elif lemma_lower in awl_set:
            bands["AWL"] += freq
            if len(academic_words) < limit:
                academic_words.append({"word": lemma_lower, "freq": freq})
        else:
            bands["Off-list"] += freq
            if freq <= rare_threshold and len(rare_words) < limit:
                rare_words.append({"word": lemma_lower, "freq": freq})

    band_rows = [
        {
            "band": name,
            "freq": freq,
            "percent": round(freq / total_tokens * 100, 2) if total_tokens else 0,
        }
        for name, freq in bands.items()
    ]

    return VocabProfileResult(
        total_tokens=total_tokens,
        total_types=total_types,
        bands=band_rows,
        rare_words=rare_words,
        academic_words=academic_words,
    )


# --------------------------------------------------------------------------- #
# §8.18 Sentiment analysis (v1.2.8, review #8)
# --------------------------------------------------------------------------- #
# The layered, Appraisal-grounded implementation now lives in
# engine/sentiment/. The re-export below keeps every existing importer
# (`from discourse.service import compute_sentiment, SentimentResult`)
# working unchanged; new code should import from sentiment.service.

from sentiment.service import SentimentResult, compute_sentiment  # noqa: E402,F401

# --------------------------------------------------------------------------- #
# §8.17 Metaphor detection — LLM-assisted MIPVU pipeline scaffold
# --------------------------------------------------------------------------- #
# The full metaphor pipeline requires the LLM (MIPVU decision steps).
# This service produces *candidates* — lexical units whose contextual meaning
# may differ from a more basic / concrete meaning — which the LLM then triages
# and the human verifies. The human-verification gate is load-bearing (§8.17 +ADD).


@dataclass
class MetaphorCandidatesResult:
    candidates: list[dict]  # [{word, lemma, pos, sentence, evidence_id, reason}]
    pipeline: str  # "MIPVU-inspired, LLM-triaged, human-verified"
    verified_count: int  # always 0 here; only the human can mark verified


async def compute_metaphor_candidates(
    session: AsyncSession,
    corpus_id: str,
    *,
    limit: int = 50,
) -> MetaphorCandidatesResult:
    """Find metaphor candidates: words whose POS suggests a metaphor reading.

    Heuristic starter: verbs/nouns/adjectives used in non-concrete contexts.
    A real MIPVU implementation requires the LLM to compare contextual vs
    basic meaning — that's done by the AI Assistant via the metaphor_triage tool.
    This service just produces the candidate set.
    """
    version_id = await _latest_version_id(session, corpus_id)
    if not version_id:
        return MetaphorCandidatesResult(
            candidates=[], pipeline="MIPVU-inspired, LLM-triaged, human-verified", verified_count=0
        )

    sentences = await _load_parses(session, version_id)
    candidates: list[dict] = []

    # Heuristic: verbs with abstract subjects (not concrete nouns like "person"/"thing")
    # Phase 3+ will replace this with a proper embedding-based comparison.
    CONCRETE_NOUNS = {
        "person",
        "man",
        "woman",
        "child",
        "people",
        "thing",
        "object",
        "animal",
        "dog",
        "cat",
        "car",
        "house",
        "table",
        "chair",
        "book",
    }

    for sent in sentences:
        for tok in sent:
            if tok["pos"] != "VERB":
                continue
            lemma = (tok["lemma"] or "").lower()
            # Skip very common concrete-motion verbs
            if lemma in {"be", "have", "do", "say", "go", "come", "get", "make", "see", "know"}:
                continue
            # Find the subject
            subj = None
            for other in sent:
                if other["rel"] == "nsubj" and other["head"] - 1 == tok["idx"]:
                    subj = other
                    break
            if subj and subj["pos"] == "NOUN" and subj["lemma"].lower() not in CONCRETE_NOUNS:
                # Candidate: verb with abstract subject — likely metaphorical
                candidates.append(
                    {
                        "word": tok["text"],
                        "lemma": lemma,
                        "pos": tok["pos"],
                        "subject": subj["text"],
                        "subject_lemma": subj["lemma"],
                        "sentence": " ".join(t["text"] for t in sent),
                        "evidence_id": f"{tok['doc']}:{tok['sent']}:{tok['idx']}",
                        "reason": f"Verb '{lemma}' with abstract subject '{subj['lemma']}' - possible personification/metaphor",
                    }
                )
                if len(candidates) >= limit:
                    return MetaphorCandidatesResult(
                        candidates=candidates,
                        pipeline="MIPVU-inspired, LLM-triaged, human-verified",
                        verified_count=0,
                    )

    return MetaphorCandidatesResult(
        candidates=candidates,
        pipeline="MIPVU-inspired, LLM-triaged, human-verified",
        verified_count=0,
    )
