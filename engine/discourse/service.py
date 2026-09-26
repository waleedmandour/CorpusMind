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

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.logging import get_logger
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


async def _load_parses(session: AsyncSession, version_id: str) -> list[dict]:
    """Load tokens with their dep head/rel, grouped by sentence."""
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
    sentences: dict[tuple[str, int], list[dict]] = defaultdict(list)
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
}

# CLAWS-family semantic lens: the bundled USAS top-level lexicon
# (reference-data/tagsets/usas-<lang>-top.tsv, CC BY-NC-SA 4.0) re-read as
# discourse-functional groupings rather than a plain frequency list.
USAS_TAXONOMY_KEY = "usas"

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
    compare_corpus_id: str | None = None
    compare_total_tokens: int | None = None


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
            "citation": (
                "Rayson, P., Archer, D., Piao, S., & McEnery, T. (2004). "
                "The UCREL Semantic Analysis System. Lancaster: UCREL "
                "(CLAWS-family semantic tagset). Bundled top-level lexicon: "
                "CC BY-NC-SA 4.0 — lexicon-based lookup, not the licensed "
                "CLAWS/USAS tagger."
            ),
            "categories": sorted(USAS_DISCOURSE_GROUPS.keys()),
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
    spec = DISCOURSE_TAXONOMIES.get(key)
    if spec is None:
        raise ValueError(
            f"Unknown discourse taxonomy: {taxonomy}. Supported: "
            f"{[*DISCOURSE_TAXONOMIES.keys(), USAS_TAXONOMY_KEY]}"
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
                row.update(
                    _keyness_fields(
                        row["freq"], total_tokens,
                        c_counts.get(cat, 0), compare_total,
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
            citation=discourse_taxonomy_list()[-1]["citation"],
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
                row.update(
                    _keyness_fields(
                        row["freq"], total_tokens,
                        c_counts.get(tag, 0), compare_total,
                    )
                )

    unmatched = round((total_tokens - matched) / total_tokens * 100, 2) if total_tokens else 0.0
    return DiscourseResult(
        categories=categories,
        total_tokens=total_tokens,
        taxonomy="CLAWS/USAS semantic tagset (top-level)",
        taxonomy_key=USAS_TAXONOMY_KEY,
        citation=discourse_taxonomy_list()[-1]["citation"],
        unmatched_percent=unmatched,
        compare_corpus_id=compare_corpus_id if compare_total is not None else None,
        compare_total_tokens=compare_total,
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
    from pathlib import Path

    path = (
        Path(__file__).resolve().parent.parent.parent
        / "reference-data"
        / "wordlists"
        / "awl-sublists.tsv"
    )
    forms: set[str] = set()
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

    # Load bundled K1 wordlist
    from pathlib import Path

    k1_path = (
        Path(__file__).resolve().parent.parent.parent
        / "reference-data"
        / "wordlists"
        / "en"
        / "top200.tsv"
    )
    k1_set: set[str] = set()
    if k1_path.exists():
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
# §8.18 Sentiment analysis (lexicon-based, offline)
# --------------------------------------------------------------------------- #


# A small starter sentiment lexicon. Phase 3 will swap in VADER or a
# transformers-based sentiment model behind the same interface.
STARTER_POSITIVE = {
    "good",
    "great",
    "excellent",
    "wonderful",
    "amazing",
    "fantastic",
    "best",
    "better",
    "love",
    "like",
    "enjoy",
    "happy",
    "pleased",
    "delighted",
    "beautiful",
    "perfect",
    "brilliant",
    "superb",
    "outstanding",
    "remarkable",
    "success",
    "successful",
    "win",
    "victory",
    "triumph",
    "achieve",
    "benefit",
    "improve",
    "progress",
    "advance",
    "innovative",
    "positive",
    "strong",
    "powerful",
    "effective",
    "efficient",
    "valuable",
    "important",
    "significant",
}
STARTER_NEGATIVE = {
    "bad",
    "terrible",
    "awful",
    "horrible",
    "worst",
    "worse",
    "hate",
    "dislike",
    "sad",
    "unhappy",
    "angry",
    "furious",
    "disappointed",
    "frustrated",
    "ugly",
    "broken",
    "fail",
    "failure",
    "lose",
    "loss",
    "defeat",
    "decline",
    "weak",
    "poor",
    "negative",
    "wrong",
    "mistake",
    "error",
    "problem",
    "difficult",
    "hard",
    "painful",
    "suffering",
    "danger",
    "threat",
    "risk",
    "fear",
    "worry",
    "anxiety",
    "concern",
    "criticism",
    "attack",
    "damage",
}


@dataclass
class SentimentResult:
    total_sentences: int
    positive: int
    negative: int
    neutral: int
    avg_score: float  # -1 (very negative) to +1 (very positive)
    timeline: list[dict]  # [{doc, sent, score}] — for diachronic/narrative corpora


async def compute_sentiment(
    session: AsyncSession,
    corpus_id: str,
) -> SentimentResult:
    """Lexicon-based sentiment per sentence (§8.18).

    Each sentence gets a score in [-1, +1] = (pos_count - neg_count) / (pos + neg + 1).
    Phase 3 will swap in a proper sentiment model behind the same interface.
    """
    version_id = await _latest_version_id(session, corpus_id)
    if not version_id:
        return SentimentResult(
            total_sentences=0, positive=0, negative=0, neutral=0, avg_score=0.0, timeline=[]
        )

    sentences = await _load_parses(session, version_id)
    pos_count = neg_count = neu_count = 0
    total_score = 0.0
    timeline: list[dict] = []

    for sent in sentences:
        p = sum(1 for t in sent if t["text"].lower() in STARTER_POSITIVE)
        n = sum(1 for t in sent if t["text"].lower() in STARTER_NEGATIVE)
        score = (p - n) / (p + n + 1)  # +1 smoothing to avoid div-by-zero
        total_score += score
        if score > 0.05:
            pos_count += 1
        elif score < -0.05:
            neg_count += 1
        else:
            neu_count += 1
        timeline.append(
            {
                "doc": sent[0]["doc"] if sent else "",
                "sent": sent[0]["sent"] if sent else 0,
                "score": round(score, 3),
                "pos_hits": p,
                "neg_hits": n,
            }
        )

    total = len(sentences)
    avg = total_score / total if total else 0.0
    return SentimentResult(
        total_sentences=total,
        positive=pos_count,
        negative=neg_count,
        neutral=neu_count,
        avg_score=round(avg, 3),
        timeline=timeline,
    )


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
                        "reason": f"Verb '{lemma}' with abstract subject '{subj['lemma']}' — possible personification/metaphor",
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
