"""
Phase 2 corpus-analysis services: n-grams, POS patterns, grammar queries,
dependency queries, discourse (Hyland's metadiscourse), vocabulary profiling,
sentiment.

All functions take an async SQLAlchemy session and return plain Python data
structures. Every result includes reproducibility info (parameters used).
"""
from __future__ import annotations

from collections import Counter, defaultdict
from dataclasses import dataclass

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.logging import get_logger
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
    rows: list[dict]   # [{ngram, freq, per_million, range (distinct docs), range_percent}]
    min_freq: int
    min_range: int     # minimum distinct documents required (§8.8 lexical bundles)


async def compute_ngrams(
    session: AsyncSession,
    corpus_id: str,
    *,
    n: int = 2,
    min_freq: int = 5,
    min_range: int = 1,    # §8.8: lexical bundles require min distinct docs
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
        select(Token.document_id, Token.sentence_idx, Token.token_idx, Token.text, Token.is_punct, Token.is_stop, Token.pos)
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
        rows.append({
            "ngram": ngram,
            "freq": freq,
            "per_million": round(per_million, 2),
            "range": range_count,
            "range_percent": round((range_count / total_docs * 100) if total_docs else 0.0, 2),
        })
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
    distribution: list[dict]      # [{pos, freq, percent}]
    pos_ngrams: list[dict]        # [{pattern, freq}] — top POS n-grams
    n: int


async def compute_pos_analysis(
    session: AsyncSession,
    corpus_id: str,
    *,
    n: int = 2,                   # POS n-gram size (1=distribution, 2=bigrams, etc.)
    min_freq: int = 2,
    limit: int = 100,
) -> POSResult:
    version_id = await _latest_version_id(session, corpus_id)
    if not version_id:
        return POSResult(total_tokens=0, distribution=[], pos_ngrams=[], n=n)

    # Distribution
    dist_stmt = (
        select(Token.pos, func.count(Token.id))
        .where(Token.version_id == version_id, _is_real_token())
        .group_by(Token.pos)
        .order_by(func.count(Token.id).desc())
    )
    dist_rows = (await session.execute(dist_stmt)).all()
    total = sum(c for _, c in dist_rows)
    distribution = [{"pos": p, "freq": c, "percent": round(c / total * 100, 3) if total else 0}
                    for p, c in dist_rows]

    # POS n-grams
    stmt = (
        select(Token.document_id, Token.sentence_idx, Token.token_idx, Token.pos, Token.is_punct)
        .where(Token.version_id == version_id)
        .order_by(Token.document_id, Token.sentence_idx, Token.token_idx)
    )
    rows_raw = (await session.execute(stmt)).all()

    # Build per-sentence POS sequences
    sentences: dict[tuple[str, int], list[str]] = defaultdict(list)
    for doc_id, sent_idx, _, pos, is_punct in rows_raw:
        if is_punct or pos == "SPACE":
            continue
        sentences[(doc_id, sent_idx)].append(pos)

    pos_ngram_counter: Counter = Counter()
    for sent_pos in sentences.values():
        for i in range(len(sent_pos) - n + 1):
            pattern = " ".join(sent_pos[i : i + n])
            pos_ngram_counter[pattern] += 1

    pos_ngrams = [{"pattern": p, "freq": c}
                  for p, c in pos_ngram_counter.most_common(limit) if c >= min_freq]

    return POSResult(total_tokens=total, distribution=distribution, pos_ngrams=pos_ngrams, n=n)


# --------------------------------------------------------------------------- #
# §8.12 Grammar analysis (dependency-driven pattern detectors)
# --------------------------------------------------------------------------- #


@dataclass
class GrammarResult:
    patterns: dict[str, list[dict]]   # {pattern_name: [{doc, sent, text, ...}]}
    counts: dict[str, int]


# Grammar detectors — each inspects the dependency parse and returns matches.
# These are pattern detectors over UD parses, not regex over surface text (§8.12).


async def _load_parses(session: AsyncSession, version_id: str) -> list[dict]:
    """Load tokens with their dep head/rel, grouped by sentence."""
    stmt = (
        select(
            Token.document_id, Token.sentence_idx, Token.token_idx,
            Token.text, Token.lemma, Token.pos, Token.dep_head, Token.dep_rel, Token.morph,
        )
        .where(Token.version_id == version_id)
        .order_by(Token.document_id, Token.sentence_idx, Token.token_idx)
    )
    rows = (await session.execute(stmt)).all()
    sentences: dict[tuple[str, int], list[dict]] = defaultdict(list)
    for doc_id, sent_idx, tok_idx, text, lemma, pos, dep_head, dep_rel, morph in rows:
        sentences[(doc_id, sent_idx)].append({
            "idx": tok_idx, "text": text, "lemma": lemma, "pos": pos,
            "head": dep_head, "rel": dep_rel, "morph": morph,
            "doc": doc_id, "sent": sent_idx,
        })
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
                matches.append({
                    "pattern": "passive_voice",
                    "doc": tok["doc"], "sent": tok["sent"],
                    "verb": head["text"], "verb_lemma": head["lemma"],
                    "aux": tok["text"],
                    "evidence_id": f"{tok['doc']}:{tok['sent']}:{tok['idx']}",
                })
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
                matches.append({
                    "pattern": "modal",
                    "doc": tok["doc"], "sent": tok["sent"],
                    "modal": tok["text"], "verb": head["text"], "verb_lemma": head["lemma"],
                    "evidence_id": f"{tok['doc']}:{tok['sent']}:{tok['idx']}",
                })
    return matches


def _detect_negation(sentence: list[dict]) -> list[dict]:
    """Detect negation: 'not' / 'n't' as 'advmod' or 'neg' dependency."""
    matches = []
    for tok in sentence:
        if tok["rel"] == "neg" or (tok["pos"] == "PART" and "Neg" in (tok["morph"] or "")):
            matches.append({
                "pattern": "negation",
                "doc": tok["doc"], "sent": tok["sent"],
                "negator": tok["text"],
                "evidence_id": f"{tok['doc']}:{tok['sent']}:{tok['idx']}",
            })
    return matches


def _detect_relative_clauses(sentence: list[dict]) -> list[dict]:
    """Detect relative clauses: acl:relc (UD v2) or relcl (spaCy legacy) dependency."""
    matches = []
    for tok in sentence:
        if tok["rel"] in ("acl:relc", "relcl"):
            matches.append({
                "pattern": "relative_clause",
                "doc": tok["doc"], "sent": tok["sent"],
                "marker": tok["text"],
                "evidence_id": f"{tok['doc']}:{tok['sent']}:{tok['idx']}",
            })
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
            matches.append({
                "pattern": "complex_np",
                "doc": head["doc"], "sent": head["sent"],
                "head": head["text"], "modifiers": [m["text"] for m in mods],
                "evidence_id": f"{head['doc']}:{head['sent']}:{head['idx']}",
            })
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
            matches.append({
                "pattern": f"tense_{tense}",
                "doc": tok["doc"], "sent": tok["sent"],
                "verb": tok["text"], "lemma": tok["lemma"],
                "evidence_id": f"{tok['doc']}:{tok['sent']}:{tok['idx']}",
            })
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
    relation: str            # nsubj / obj / iobj / etc.
    rows: list[dict]         # [{governor, dependent, relation, freq, examples}]


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

    rows = [{
        "governor": gov, "dependent": dep, "relation": relation,
        "freq": freq,
        "examples": ex,
    } for (gov, dep), freq in pair_counter.most_common(limit) for ex in [examples[(gov, dep)]]]

    return DependencyResult(relation=relation, rows=rows)


# --------------------------------------------------------------------------- #
# §8.15 Discourse analysis — Hyland's metadiscourse taxonomy
# --------------------------------------------------------------------------- #


# Hyland's interactive + interactional metadiscourse markers (§8.15 +ADD).
# These are open-class lexical cue lists — Phase 2 ships a starter set;
# Phase 3+ may swap in a learned classifier. Each category is citable
# because it's pinned to a named taxonomy.

HYLAND_INTERACTIVE = {
    "transitions": {  # logical relations between propositions
        "moreover", "however", "therefore", "thus", "furthermore", "in addition",
        "consequently", "nevertheless", "nonetheless", "instead", "rather",
        "in contrast", "similarly", "likewise", "accordingly", "hence",
    },
    "frame_markers": {  # sequence, topic, discourse-stage
        "first", "second", "third", "finally", "to begin", "in conclusion",
        "to summarize", "in short", "turning to", "with regard to",
    },
    "endophoric_markers": {  # reference to other parts of the text
        "see figure", "see table", "as noted above", "as discussed below",
        "as mentioned earlier", "as shown in",
    },
    "evidentials": {  # attribution to other sources
        "according to", "cited in", "quoted in", "as X argues", "as X claims",
        "X suggests", "X states", "X found that",
    },
    "code_glosses": {  # reformulation / explanation
        "namely", "in other words", "that is", "for example", "for instance",
        "such as", "e.g.", "i.e.", "to put it differently",
    },
}

HYLAND_INTERACTIONAL = {
    "hedges": {  # withhold full commitment to a proposition
        "perhaps", "possibly", "probably", "likely", "may", "might", "could",
        "would", "appear to", "seem to", "tend to", "suggest", "indicate",
        "in general", "in most cases", "to some extent",
    },
    "boosters": {  # emphasize certainty
        "clearly", "obviously", "evidently", "demonstrably", "of course",
        "undoubtedly", "certainly", "definitely", "indeed", "in fact",
        "necessarily", "undeniably",
    },
    "attitude_markers": {  # express writer's attitude
        "surprisingly", "interestingly", "importantly", "remarkably",
        "unfortunately", "fortunately", "strikingly", "notably", "significantly",
        "I believe", "I argue", "I contend",
    },
    "self_mentions": {  # first-person pronouns referring to the writer
        "I", "me", "my", "mine", "we", "us", "our", "ours",
    },
    "engagement_markers": {  # explicitly address the reader
        "you", "your", "yours", "consider", "note that", "recall that",
        "imagine", "let us", "as you can see",
    },
}


@dataclass
class DiscourseResult:
    categories: dict[str, dict]    # {category: {freq, per_million, examples}}
    total_tokens: int
    taxonomy: str                  # always "Hyland 2005"


async def compute_discourse_analysis(
    session: AsyncSession,
    corpus_id: str,
    *,
    limit_examples: int = 5,
) -> DiscourseResult:
    """Detect Hyland's metadiscourse markers across the corpus (§8.15)."""
    version_id = await _latest_version_id(session, corpus_id)
    if not version_id:
        return DiscourseResult(categories={}, total_tokens=0, taxonomy="Hyland 2005")

    total_tokens = await _corpus_size(session, version_id)
    sentences = await _load_parses(session, version_id)

    # Build a flat token stream with positions for example citation
    category_counts: Counter = Counter()
    category_examples: dict[str, list[dict]] = defaultdict(list)

    all_categories = {}
    all_categories.update({f"interactive.{k}": v for k, v in HYLAND_INTERACTIVE.items()})
    all_categories.update({f"interactional.{k}": v for k, v in HYLAND_INTERACTIONAL.items()})

    for sent in sentences:
        sent_text_tokens = [t["text"].lower() for t in sent]
        sent_lower = " ".join(sent_text_tokens)
        for cat_name, cue_set in all_categories.items():
            for cue in cue_set:
                # Multi-word cues: check if it appears as a substring of the sentence
                if " " in cue:
                    if cue in sent_lower:
                        if len(category_examples[cat_name]) < limit_examples:
                            category_examples[cat_name].append({
                                "cue": cue,
                                "evidence_id": f"{sent[0]['doc']}:{sent[0]['sent']}:0",
                                "sentence_preview": sent_lower[:120],
                            })
                        category_counts[cat_name] += 1
                else:
                    # Single-word: match against individual tokens
                    for tok in sent:
                        if tok["text"].lower() == cue:
                            if len(category_examples[cat_name]) < limit_examples:
                                category_examples[cat_name].append({
                                    "cue": cue,
                                    "evidence_id": f"{tok['doc']}:{tok['sent']}:{tok['idx']}",
                                    "sentence_preview": sent_lower[:120],
                                })
                            category_counts[cat_name] += 1

    categories = {}
    for cat, count in category_counts.most_common():
        per_million = (count / total_tokens * 1_000_000) if total_tokens else 0.0
        categories[cat] = {
            "freq": count,
            "per_million": round(per_million, 2),
            "examples": category_examples[cat],
        }

    return DiscourseResult(
        categories=categories,
        total_tokens=total_tokens,
        taxonomy="Hyland 2005",
    )


# --------------------------------------------------------------------------- #
# §8.10 Vocabulary profiling
# --------------------------------------------------------------------------- #


@dataclass
class VocabProfileResult:
    total_tokens: int
    total_types: int
    bands: list[dict]               # [{band, freq, percent, examples}]
    rare_words: list[dict]          # off the open frequency list
    academic_words: list[dict]      # in the academic word list


# A small starter Academic Word List (AWL) — Phase 3 will expand.
# This is a subset of Coxhead's AWL (2000), which is open for research use.
STARTER_AWL = {
    "analyze", "approach", "area", "assess", "assume", "authority", "available",
    "benefit", "concept", "consistent", "constitute", "context", "contract",
    "create", "data", "define", "derive", "distribute", "economy", "environment",
    "establish", "estimate", "evident", "export", "factor", "finance", "formula",
    "function", "identify", "income", "indicate", "individual", "interpret",
    "involve", "issue", "labour", "legal", "legislate", "major", "method",
    "occur", "percent", "period", "policy", "principle", "proceed", "process",
    "require", "research", "respond", "section", "sector", "significant",
    "similar", "source", "specific", "structure", "theory", "vary",
}


async def compute_vocab_profile(
    session: AsyncSession,
    corpus_id: str,
    *,
    rare_threshold: int = 1,    # appears <= this many times in the corpus
    limit: int = 100,
) -> VocabProfileResult:
    """Profile vocabulary into frequency bands (K1, K2, K3-9, AWL, off-list).

    Uses the bundled open English top-200 wordlist as K1 approximation.
    Phase 3 will swap in a proper open frequency corpus.
    """
    version_id = await _latest_version_id(session, corpus_id)
    if not version_id:
        return VocabProfileResult(total_tokens=0, total_types=0, bands=[], rare_words=[], academic_words=[])

    # Load bundled K1 wordlist
    from pathlib import Path
    k1_path = Path(__file__).resolve().parent.parent.parent / "reference-data" / "wordlists" / "en" / "top200.tsv"
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

    bands = {"K1": 0, "K2_K9": 0, "AWL": 0, "Off-list": 0}
    rare_words = []
    academic_words = []

    for lemma, text, freq in rows:
        lemma_lower = (lemma or text).lower()
        if lemma_lower in k1_set:
            bands["K1"] += freq
        elif lemma_lower in STARTER_AWL:
            bands["AWL"] += freq
            if len(academic_words) < limit:
                academic_words.append({"word": lemma_lower, "freq": freq})
        else:
            bands["Off-list"] += freq
            if freq <= rare_threshold and len(rare_words) < limit:
                rare_words.append({"word": lemma_lower, "freq": freq})

    band_rows = [{
        "band": name, "freq": freq,
        "percent": round(freq / total_tokens * 100, 2) if total_tokens else 0,
    } for name, freq in bands.items()]

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
    "good", "great", "excellent", "wonderful", "amazing", "fantastic", "best",
    "better", "love", "like", "enjoy", "happy", "pleased", "delighted",
    "beautiful", "perfect", "brilliant", "superb", "outstanding", "remarkable",
    "success", "successful", "win", "victory", "triumph", "achieve", "benefit",
    "improve", "progress", "advance", "innovative", "positive", "strong",
    "powerful", "effective", "efficient", "valuable", "important", "significant",
}
STARTER_NEGATIVE = {
    "bad", "terrible", "awful", "horrible", "worst", "worse", "hate", "dislike",
    "sad", "unhappy", "angry", "furious", "disappointed", "frustrated",
    "ugly", "broken", "fail", "failure", "lose", "loss", "defeat", "decline",
    "weak", "poor", "negative", "wrong", "mistake", "error", "problem",
    "difficult", "hard", "painful", "suffering", "danger", "threat", "risk",
    "fear", "worry", "anxiety", "concern", "criticism", "attack", "damage",
}


@dataclass
class SentimentResult:
    total_sentences: int
    positive: int
    negative: int
    neutral: int
    avg_score: float           # -1 (very negative) to +1 (very positive)
    timeline: list[dict]       # [{doc, sent, score}] — for diachronic/narrative corpora


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
        return SentimentResult(total_sentences=0, positive=0, negative=0, neutral=0, avg_score=0.0, timeline=[])

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
        timeline.append({
            "doc": sent[0]["doc"] if sent else "",
            "sent": sent[0]["sent"] if sent else 0,
            "score": round(score, 3),
            "pos_hits": p,
            "neg_hits": n,
        })

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
    candidates: list[dict]   # [{word, lemma, pos, sentence, evidence_id, reason}]
    pipeline: str            # "MIPVU-inspired, LLM-triaged, human-verified"
    verified_count: int      # always 0 here; only the human can mark verified


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
        return MetaphorCandidatesResult(candidates=[], pipeline="MIPVU-inspired, LLM-triaged, human-verified", verified_count=0)

    sentences = await _load_parses(session, version_id)
    candidates: list[dict] = []

    # Heuristic: verbs with abstract subjects (not concrete nouns like "person"/"thing")
    # Phase 3+ will replace this with a proper embedding-based comparison.
    CONCRETE_NOUNS = {"person", "man", "woman", "child", "people", "thing", "object",
                      "animal", "dog", "cat", "car", "house", "table", "chair", "book"}

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
                candidates.append({
                    "word": tok["text"],
                    "lemma": lemma,
                    "pos": tok["pos"],
                    "subject": subj["text"],
                    "subject_lemma": subj["lemma"],
                    "sentence": " ".join(t["text"] for t in sent),
                    "evidence_id": f"{tok['doc']}:{tok['sent']}:{tok['idx']}",
                    "reason": f"Verb '{lemma}' with abstract subject '{subj['lemma']}' — possible personification/metaphor",
                })
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
