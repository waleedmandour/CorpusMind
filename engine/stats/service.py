"""
Corpus query services: search, concordance, frequency, collocation, keyness.

All functions take an async SQLAlchemy session and return plain Python data
structures (dicts / lists / dataclasses) — no ORM objects leak through the
API boundary. Every result that has a stable ID (a concordance line, a
statistic) includes that ID so the AI Assistant can cite it (§11.1).
"""
from __future__ import annotations

from collections import Counter, defaultdict
from dataclasses import dataclass
from typing import Literal

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.logging import get_logger
from stats.measures import (
    chi2_min_expected,
    chi_square_2x2,
    compute_keyness_row,
    delta_p,
    dice_coefficient,
    fisher_exact_2x2,
    gries_dp,
    gries_dp_norm,
    juillands_d,
    log_dice,
    log_likelihood_2x2,
    mutual_information,
    t_score,
)
from storage.models import AnnotationVersion, Document, Token

log = get_logger(__name__)


# --------------------------------------------------------------------------- #
# Helpers
# --------------------------------------------------------------------------- #


async def _latest_version_id(session: AsyncSession, corpus_id: str) -> str | None:
    """Return the most recent AnnotationVersion id for a corpus."""
    stmt = (
        select(AnnotationVersion.id)
        .where(AnnotationVersion.corpus_id == corpus_id)
        .order_by(AnnotationVersion.created_at.desc())
        .limit(1)
    )
    return await session.scalar(stmt)


# Issue 17: hard cap on rows fetched for random sampling (memory guard).
_SAMPLING_FETCH_CAP = 20_000


async def _corpus_size(
    session: AsyncSession, version_id: str, document_ids: list[str] | None = None
) -> int:
    """Total token count for a version (excluding punctuation and whitespace).

    Issue 2: when ``document_ids`` is provided (subcorpus restriction), only
    tokens belonging to those documents are counted.
    """
    stmt = select(func.count(Token.id)).where(
        Token.version_id == version_id,
        Token.is_punct == False,  # noqa: E712
        Token.pos != "SPACE",
    )
    if document_ids is not None:
        stmt = stmt.where(Token.document_id.in_(document_ids))
    return await session.scalar(stmt) or 0


def _is_real_token():
    """SQL condition for 'this token is a real word, not punct/whitespace."""
    return (Token.is_punct == False) & (Token.pos != "SPACE")  # noqa: E712


# --------------------------------------------------------------------------- #
# Search & Concordance (§8.3, §8.4)
# --------------------------------------------------------------------------- #

# v1.0.1: fetch cap for phrase-verification / sorting / sampling — all three
# features need the FULL match set (not a page), so they are bounded here.
_CONCORDANCE_FETCH_CAP = 20_000

_CONCORDANCE_LEVELS = ("word", "lemma", "pos", "root", "pattern")


def _fold(text: str) -> str:
    """Case-fold + strip diacritics (NFD combining marks). Used for matching
    AND aggregation so 'The'/'the' and كِتَاب/كتاب collapse to one row."""
    import unicodedata

    lowered = text.lower()
    return "".join(
        c for c in unicodedata.normalize("NFD", lowered) if not unicodedata.combining(c)
    )


def _morph_component_cond(component: str, query: str, case_sensitive: bool):
    """SQL condition matching one morph component (root|pattern).

    `morph` is stored as 'root=X|stem=Y|pattern=Z'. Without wildcards the
    match is bounded by the '|' separator or end-of-string; with wildcards
    it degrades to a prefix match (documented trade-off).
    """
    wildcard = "*" in query or "?" in query
    q = query.replace("*", "%").replace("?", "_") if wildcard else query
    if wildcard:
        return Token.morph.like(f"{component}={q}%")
    # exact: 'root=Q' at end of string OR 'root=Q|' before the next component
    return (Token.morph.like(f"{component}={q}") | Token.morph.like(f"{component}={q}|%"))


@dataclass(frozen=True, slots=True)
class ConcordanceLine:
    """One KWIC line. `line_id` is stable — cited by the AI Assistant (§11.1)."""
    line_id: str           # f"{doc_id}:{sent_idx}:{tok_idx}"
    document_id: str
    document_filename: str
    sentence_idx: int
    token_idx: int
    left: str              # tokens to the left of the node
    node: str              # the matched token(s) — space-joined span for phrases
    right: str             # tokens to the right
    pos: str               # UPOS of the (first) node token
    lemma: str             # lemma of the (first) node token


@dataclass
class ConcordanceResult:
    lines: list[ConcordanceLine]
    total: int
    query: dict


def _part_condition(col, part: str, *, regex: bool, case_sensitive: bool):
    """Match condition for one query token (word/lemma/pos levels)."""
    if regex:
        pattern = part if case_sensitive else f"(?i){part}"
        return col.op("REGEXP")(pattern)
    if "*" in part or "?" in part:
        like_pattern = part.replace("*", "%").replace("?", "_")
        return col.ilike(like_pattern) if not case_sensitive else col.like(like_pattern)
    if case_sensitive:
        return col == part
    return func.lower(col) == func.lower(part)


def _sort_token(sent_tokens: list[tuple[str, str, str]], idx: int) -> str:
    """Sort key token at a sentence index (empty when out of range)."""
    if 0 <= idx < len(sent_tokens):
        return sent_tokens[idx][0]
    return ""


async def search_concordance(
    session: AsyncSession,
    corpus_id: str,
    query: str,
    *,
    level: str = "word",
    case_sensitive: bool = False,
    window: int = 5,
    limit: int = 100,
    offset: int = 0,
    document_ids: list[str] | None = None,
    random_sample: int | None = None,
    sample_seed: int | None = None,
    regex: bool = False,
    sort: list[dict] | None = None,
) -> ConcordanceResult:
    """KWIC search.

    v1.0.1 capabilities:
      * levels: word | lemma | pos | root | pattern (root/pattern read the
        Arabic morph layer: 'root=ك ت ب|stem=…|pattern=…').
      * regex queries (Python re syntax; case flag handled via (?i)).
      * phrase queries: any whitespace in `query` starts multi-word sequence
        matching (word/lemma levels only; each part may carry wildcards).
      * KWIC sorting: `sort` is a list of up to 3 {side: left|right,
        offset: 1-3} specs applied AntConc-style (1L, 1R, 2L …). Sorting
        happens over the full (capped) match set, then pagination.
    """
    if level not in _CONCORDANCE_LEVELS:
        level = "word"
    version_id = await _latest_version_id(session, corpus_id)
    if not version_id:
        return ConcordanceResult(lines=[], total=0, query={"q": query, "level": level})

    col = {"word": Token.text, "lemma": Token.lemma, "pos": Token.pos}.get(level, Token.text)
    query_stripped = query.strip()
    parts = query_stripped.split() if level in ("word", "lemma") else [query_stripped]
    phrase = len(parts) > 1

    # ---- node condition -------------------------------------------------- #
    if level in ("root", "pattern"):
        cond = _morph_component_cond(level, query_stripped, case_sensitive) & _is_real_token()
    elif phrase:
        cond = _part_condition(col, parts[0], regex=regex, case_sensitive=case_sensitive) & _is_real_token()
    else:
        cond = _part_condition(col, query_stripped, regex=regex, case_sensitive=case_sensitive) & _is_real_token()

    # ---- count (single-token modes only; phrase totals come from Python) -- #
    if phrase:
        total = None
    else:
        count_stmt = select(func.count(Token.id)).where(Token.version_id == version_id, cond)
        if document_ids is not None:
            count_stmt = count_stmt.where(Token.document_id.in_(document_ids))
        total = await session.scalar(count_stmt) or 0

    # ---- fetch matching tokens (full set when sorting/sampling/phrase) ---- #
    need_all = phrase or bool(sort) or bool(random_sample)
    stmt = (
        select(Token, Document.filename)
        .join(Document, Token.document_id == Document.id)
        .where(Token.version_id == version_id, cond)
        .order_by(Token.document_id, Token.sentence_idx, Token.token_idx)
    )
    if document_ids is not None:
        stmt = stmt.where(Token.document_id.in_(document_ids))
    stmt = stmt.limit(_CONCORDANCE_FETCH_CAP if need_all else limit).offset(0 if need_all else offset)
    rows = (await session.execute(stmt)).all()

    # ---- phrase verification over sentence token lists -------------------- #
    phrase_spans: list[tuple[object, str, int, int]] = []  # (Token, filename, start_idx, end_idx)
    if phrase:
        # group candidate (first-part) tokens by sentence
        by_sentence: dict[tuple[str, int], list[object]] = {}
        filenames: dict[str, str] = {}
        for tok, filename in rows:
            by_sentence.setdefault((tok.document_id, tok.sentence_idx), []).append(tok)
            filenames[tok.document_id] = filename
        # fetch the level-column values for every candidate sentence
        needed = list(by_sentence.keys())
        from sqlalchemy import or_ as _or

        level_values: dict[tuple[str, int], list[str]] = {}
        CHUNK = 400
        for i in range(0, len(needed), CHUNK):
            chunk = needed[i : i + CHUNK]
            batch_stmt = (
                select(Token.document_id, Token.sentence_idx, Token.token_idx, col)
                .where(Token.version_id == version_id)
                .where(
                    _or(*[
                        (Token.document_id == d) & (Token.sentence_idx == s)
                        for d, s in chunk
                    ])
                )
                .order_by(Token.document_id, Token.sentence_idx, Token.token_idx)
            )
            for doc_id, sent_idx, _tok_idx, value in (await session.execute(batch_stmt)).all():
                level_values.setdefault((doc_id, sent_idx), []).append(value or "")
        for key, toks in by_sentence.items():
            values = level_values.get(key, [])
            for tok in toks:
                start = tok.token_idx
                if start + len(parts) > len(values):
                    continue
                seg = values[start : start + len(parts)]
                ok = True
                for part, actual in zip(parts, seg, strict=False):
                    if regex:
                        import re as _re

                        flags = 0 if case_sensitive else _re.IGNORECASE
                        if not _re.search(part, actual, flags):
                            ok = False
                            break
                    elif "*" in part or "?" in part:
                        import fnmatch as _fn

                        pat = part  # fnmatch uses * and ? natively
                        hay = actual if case_sensitive else actual.lower()
                        needle = pat if case_sensitive else pat.lower()
                        if not _fn.fnmatch(hay, needle):
                            ok = False
                            break
                    elif case_sensitive:
                        if actual != part:
                            ok = False
                            break
                    else:
                        if actual.lower() != part.lower():
                            ok = False
                            break
                if ok:
                    phrase_spans.append((tok, filenames.get(tok.document_id, ""), start, start + len(parts) - 1))
        verified = phrase_spans
        total = len(verified)
        if len(rows) >= _CONCORDANCE_FETCH_CAP:
            total = None  # cap hit — the count is a lower bound
    else:
        verified = [(tok, filename, tok.token_idx, tok.token_idx) for tok, filename in rows]

    if random_sample and total:
        import random as _random

        rng = _random.Random(sample_seed)
        k = min(random_sample, len(verified))
        verified = sorted(
            rng.sample(list(verified), k),
            key=lambda t: (t[0].document_id, t[0].sentence_idx, t[1]),
        )

    # ---- batched sentence-context fetch (text, lemma, pos for sort keys) -- #
    needed_sentences: set[tuple[str, int]] = {
        (tok.document_id, tok.sentence_idx) for tok, _, _, _ in verified
    }
    sentence_cache: dict[tuple[str, int], list[tuple[str, str, str]]] = {}
    if needed_sentences:
        from sqlalchemy import or_

        batch_stmt = (
            select(Token.document_id, Token.sentence_idx, Token.token_idx, Token.text, Token.lemma, Token.pos)
            .where(Token.version_id == version_id)
            .where(
                or_(*[
                    (Token.document_id == doc_id) & (Token.sentence_idx == sent_idx)
                    for doc_id, sent_idx in needed_sentences
                ])
            )
            .order_by(Token.document_id, Token.sentence_idx, Token.token_idx)
        )
        batch_rows = (await session.execute(batch_stmt)).all()
        for doc_id, sent_idx, _tok_idx, text, lemma, pos in batch_rows:
            sentence_cache.setdefault((doc_id, sent_idx), []).append((text, lemma, pos))

    lines: list[ConcordanceLine] = []
    for tok, filename, start_idx, end_idx in verified:
        sent_tokens = sentence_cache.get((tok.document_id, tok.sentence_idx), [])
        texts = [t[0] for t in sent_tokens]
        left = " ".join(texts[max(0, start_idx - window) : start_idx])
        node = " ".join(texts[start_idx : end_idx + 1])
        right = " ".join(texts[end_idx + 1 : end_idx + 1 + window])
        lines.append(ConcordanceLine(
            line_id=f"{tok.document_id}:{tok.sentence_idx}:{start_idx}",
            document_id=tok.document_id,
            document_filename=filename,
            sentence_idx=tok.sentence_idx,
            token_idx=start_idx,
            left=left,
            node=node,
            right=right,
            pos=sent_tokens[start_idx][2] if start_idx < len(sent_tokens) else "",
            lemma=sent_tokens[start_idx][1] if start_idx < len(sent_tokens) else "",
        ))

    # ---- KWIC sort (AntConc-style L1/R1/L2/R2, up to 3 levels) ------------ #
    if sort:
        def sort_key(line: ConcordanceLine):
            sent_tokens = sentence_cache.get((line.document_id, line.sentence_idx), [])
            keys = []
            for spec in sort[:3]:
                side = spec.get("side", "right")
                off = max(1, min(3, int(spec.get("offset", 1))))
                if side == "left":
                    keys.append(_sort_token(sent_tokens, line.token_idx - off).lower())
                else:
                    keys.append(_sort_token(sent_tokens, line.token_idx + off).lower())
            return keys
        lines.sort(key=sort_key)
        lines = lines[offset : offset + limit]
    elif phrase and total is None:
        # cap hit: page out of the verified prefix (already ordered by corpus)
        lines = lines[offset : offset + limit]

    query_meta: dict = {
        "q": query, "level": level, "window": window,
        "case_sensitive": case_sensitive, "regex": regex,
    }
    if phrase:
        query_meta["phrase"] = parts
    if sort:
        query_meta["sort"] = sort
    if random_sample:
        query_meta["random_sample"] = random_sample
        query_meta["sample_seed"] = sample_seed
    if total is None:
        query_meta["total_capped"] = True
        total = len(verified)
    return ConcordanceResult(lines=lines, total=total, query=query_meta)


# --------------------------------------------------------------------------- #
# Frequency (§8.5)
# --------------------------------------------------------------------------- #


@dataclass
class FrequencyResult:
    unit: str            # "word" | "lemma" | "pos" | "root" | "pattern"
    total_tokens: int
    total_types: int
    rows: list[dict]     # [{item, freq, per_million, percent, range, range_percent}]
    sttr: float          # standardized TTR over 1000-token chunks
    lexical_diversity: dict  # {ttr, sttr, mattr, mtld, guiraud}


async def compute_frequency(
    session: AsyncSession,
    corpus_id: str,
    *,
    unit: str = "word",
    min_freq: int = 1,
    limit: int = 1000,
    include_punct: bool = False,
    document_ids: list[str] | None = None,
    stopword_set: set[str] | None = None,
) -> FrequencyResult:
    """Word/lemma/POS/root/pattern frequency list.

    v1.0.1: root & pattern units aggregate the Arabic morph layer;
    every row carries `range` (documents containing the item) and
    `range_percent`; an optional `stopword_set` removes function words
    from the aggregation (and the totals); and the result carries the
    full lexical-diversity battery (TTR, STTR, MATTR, MTLD, Guiraud).
    """
    if unit not in ("word", "lemma", "pos", "root", "pattern"):
        unit = "word"
    # Issue 2: ``document_ids`` optionally restricts all counts to a subcorpus.
    version_id = await _latest_version_id(session, corpus_id)
    if not version_id:
        return FrequencyResult(unit=unit, total_tokens=0, total_types=0, rows=[],
                               sttr=0.0, lexical_diversity={})

    col = {"word": Token.text, "lemma": Token.lemma, "pos": Token.pos}.get(unit)
    morph_unit = unit in ("root", "pattern")

    stop_cond = None
    if stopword_set and unit in ("word", "lemma"):
        lowered = func.lower(col)
        stop_cond = lowered.not_in([s.lower() for s in stopword_set])

    def _base_where(stmt):
        if not include_punct:
            stmt = stmt.where(_is_real_token())
        if document_ids is not None:
            stmt = stmt.where(Token.document_id.in_(document_ids))
        if stop_cond is not None:
            stmt = stmt.where(stop_cond)
        return stmt

    if not morph_unit:
        # Aggregate counts + document range in one grouped query
        stmt = _base_where(
            select(
                col,
                func.count(Token.id).label("freq"),
                func.count(func.distinct(Token.document_id)).label("rng"),
            )
            .where(Token.version_id == version_id)
            .group_by(col)
            .order_by(func.count(Token.id).desc())
            .limit(limit)
        )
        rows_raw = (await session.execute(stmt)).all()
        total_tokens = await _corpus_size(session, version_id, document_ids)
        if stop_cond is not None:
            cnt_stmt = _base_where(
                select(func.count(Token.id)).where(Token.version_id == version_id)
            )
            total_tokens = await session.scalar(cnt_stmt) or 0
        total_types = len(rows_raw)
        agg_rows = [(item, freq, rng) for item, freq, rng in rows_raw]
    else:
        # root/pattern: parse the morph layer in Python (streamed)
        from sqlalchemy.orm import load_only

        tok_stmt = _base_where(
            select(Token)
            .options(load_only(Token.text, Token.morph, Token.document_id))
            .where(Token.version_id == version_id)
        )
        agg: dict[str, int] = {}
        docs: dict[str, set] = {}
        total_tokens = 0
        result = await session.stream(tok_stmt)
        async for tok in result.scalars():
            component = ""
            for piece in (tok.morph or "").split("|"):
                if piece.startswith(f"{unit}="):
                    component = piece[len(unit) + 1:]
                    break
            if not component:
                continue
            total_tokens += 1
            agg[component] = agg.get(component, 0) + 1
            docs.setdefault(component, set()).add(tok.document_id)
        ordered = sorted(agg.items(), key=lambda kv: kv[1], reverse=True)
        agg_rows = [(item, freq, len(docs.get(item, ()))) for item, freq in ordered]
        total_types = len(agg_rows)

    # Lexical diversity battery (word level only — needs the token stream)
    sttr_value = 0.0
    diversity: dict = {}
    if unit == "word":
        from sqlalchemy.orm import load_only

        tok_stmt = (
            select(Token)
            .options(load_only(Token.text))
            .where(Token.version_id == version_id, _is_real_token())
            .order_by(Token.document_id, Token.sentence_idx, Token.token_idx)
            .execution_options(stream_results=True)
        )
        if document_ids is not None:
            tok_stmt = tok_stmt.where(Token.document_id.in_(document_ids))
        chunk_ttrs: list[float] = []
        chunk: list[str] = []
        all_tokens: list[str] = []
        chunk_size = 1000
        result = await session.stream(tok_stmt)
        async for row in result.scalars():
            t = row.text.lower()
            if stopword_set and t in stopword_set:
                continue
            chunk.append(t)
            all_tokens.append(t)
            if len(chunk) >= chunk_size:
                chunk_ttrs.append(len(set(chunk)) / len(chunk))
                chunk = []
        # Drop the trailing short chunk (standard practice)
        if chunk_ttrs:
            sttr_value = sum(chunk_ttrs) / len(chunk_ttrs)
        elif chunk:
            sttr_value = len(set(chunk)) / len(chunk)

        from stats.measures import guiraud, mattr, mtld, type_token_ratio

        diversity = {
            "ttr": round(type_token_ratio(all_tokens), 4) if all_tokens else 0.0,
            "sttr": round(sttr_value, 4),
            "mattr": round(mattr(all_tokens), 4) if all_tokens else 0.0,
            "mtld": round(mtld(all_tokens), 2) if all_tokens else 0.0,
            "guiraud": round(guiraud(all_tokens), 4) if all_tokens else 0.0,
        }
        if stopword_set:
            total_tokens = len(all_tokens)

    rows = []
    for item, freq, rng in agg_rows:
        if freq < min_freq:
            continue
        per_million = (freq / total_tokens * 1_000_000) if total_tokens else 0.0
        percent = (freq / total_tokens * 100) if total_tokens else 0.0
        rows.append({
            "item": item,
            "freq": freq,
            "per_million": round(per_million, 2),
            "percent": round(percent, 4),
            "range": rng,
            "range_percent": None,  # filled below against docs in scope
        })

    # Fill range_percent against the number of documents in scope
    n_docs = await _doc_count(session, corpus_id, document_ids)
    for r in rows:
        r["range_percent"] = round(r["range"] / n_docs * 100, 2) if n_docs else 0.0

    return FrequencyResult(
        unit=unit,
        total_tokens=total_tokens,
        total_types=total_types,
        rows=rows,
        sttr=round(sttr_value, 4),
        lexical_diversity=diversity,
    )


async def _doc_count(
    session: AsyncSession, corpus_id: str, document_ids: list[str] | None = None
) -> int:
    """Number of documents in the corpus (or subcorpus scope)."""
    stmt = select(func.count(Document.id)).where(Document.corpus_id == corpus_id)
    if document_ids is not None:
        stmt = stmt.where(Document.id.in_(document_ids))
    return await session.scalar(stmt) or 0


# --------------------------------------------------------------------------- #
# Collocation (§8.6)
# --------------------------------------------------------------------------- #


@dataclass
class CollocationResult:
    node: str
    window: int
    span_left: int
    span_right: int
    min_freq: int
    measures: list[str]
    rows: list[dict]
    warnings: list[str]


async def compute_collocations(
    session: AsyncSession,
    corpus_id: str,
    node: str,
    *,
    level: Literal["word", "lemma"] = "word",
    window: int = 5,
    span_left: int | None = None,
    span_right: int | None = None,
    min_freq: int = 3,
    measures: list[str] | None = None,
    limit: int = 100,
    document_ids: list[str] | None = None,
    pos_include: list[str] | None = None,
    pos_exclude: list[str] | None = None,
    stopword_set: set[str] | None = None,
) -> CollocationResult:
    """Compute collocation measures for `node` against all co-occurring tokens.

    v1.0.1 methodological alignment (Church & Hanks 1990 / Sketch Engine
    convention): the marginals are WHOLE-CORPUS frequencies —

      O  = co-occurrences of node + y within the span, same sentence
      fx = corpus frequency of node (accent/case-folded)
      fy = corpus frequency of y (accent/case-folded)
      N  = corpus size (real tokens)

    Previously fy and N were computed only within node-containing
    sentences, which made rankings incomparable with other tools. Span
    may be asymmetric (span_left / span_right default to `window`).
    Collocates aggregate under the same folding rule as the node, so
    'The'/'the' and كِتَاب/كتاب are single rows. ``pos_include`` /
    ``pos_exclude`` filter collocates by UPOS prefix; ``stopword_set``
    removes function words from the candidate pool. `warnings` carries
    methodological notices (e.g. χ² Cochran validity) for the UI.
    """
    if measures is None:
        measures = [
            "mi", "t_score", "log_likelihood", "dice", "log_dice",
            "chi_square", "delta_p", "fisher",
        ]
    sl = window if span_left is None else max(0, min(20, span_left))
    sr = window if span_right is None else max(0, min(20, span_right))
    warnings: list[str] = []

    version_id = await _latest_version_id(session, corpus_id)
    if not version_id:
        return CollocationResult(node=node, window=window, span_left=sl, span_right=sr,
                                 min_freq=min_freq, measures=measures, rows=[], warnings=warnings)

    col = {"word": Token.text, "lemma": Token.lemma}[level]

    node_lower = node.lower()
    node_folded = _fold(node)

    # --- 1. node sentences (window scan scope) ---------------------------- #
    node_cond = (
        ((func.lower(col) == node_lower) | (func.lower(col) == node_folded))
        & _is_real_token()
    )
    node_sent_stmt = (
        select(Token.document_id, Token.sentence_idx)
        .where(Token.version_id == version_id, node_cond)
        .distinct()
    )
    if document_ids is not None:
        node_sent_stmt = node_sent_stmt.where(Token.document_id.in_(document_ids))
    node_sentences = {
        (r[0], r[1]) for r in (await session.execute(node_sent_stmt)).all()
    }
    if not node_sentences:
        return CollocationResult(node=node, window=window, span_left=sl, span_right=sr,
                                 min_freq=min_freq, measures=measures, rows=[], warnings=warnings)

    # --- 2. whole-corpus vocabulary (folded) for marginals ---------------- #
    vocab_stmt = (
        select(col, func.count(Token.id))
        .where(Token.version_id == version_id, _is_real_token())
        .group_by(col)
    )
    if document_ids is not None:
        vocab_stmt = vocab_stmt.where(Token.document_id.in_(document_ids))
    folded_counts: Counter = Counter()
    for text, cnt in (await session.execute(vocab_stmt)).all():
        if text and not text.isspace():
            folded_counts[_fold(text)] += cnt
    N = sum(folded_counts.values())
    fx = folded_counts.get(node_folded, 0)
    if fx == 0:
        return CollocationResult(node=node, window=window, span_left=sl, span_right=sr,
                                 min_freq=min_freq, measures=measures, rows=[], warnings=warnings)

    # --- 3. fetch node-sentence tokens for the window scan ---------------- #
    from sqlalchemy import or_
    sent_filter = or_(*[
        (Token.document_id == doc_id) & (Token.sentence_idx == sent_idx)
        for doc_id, sent_idx in node_sentences
    ])
    stmt = (
        select(Token.document_id, Token.sentence_idx, Token.token_idx, col.label("text"), Token.is_punct, Token.pos)
        .where(Token.version_id == version_id, sent_filter)
        .order_by(Token.document_id, Token.sentence_idx, Token.token_idx)
    )
    if document_ids is not None:
        stmt = stmt.where(Token.document_id.in_(document_ids))
    rows_raw = (await session.execute(stmt)).all()

    sentences: dict[tuple[str, int], list[tuple[int, str, str]]] = defaultdict(list)
    for doc_id, sent_idx, tok_idx, text, is_punct, pos in rows_raw:
        if is_punct or pos == "SPACE" or (text and text.isspace()):
            continue
        sentences[(doc_id, sent_idx)].append((tok_idx, text, pos or ""))

    # --- 4. window scan with folding + filters ---------------------------- #
    inc = [p.upper() for p in (pos_include or [])]
    exc = [p.upper() for p in (pos_exclude or [])]

    def _pos_allowed(pos: str) -> bool:
        if inc and not any(pos.startswith(p) for p in inc):
            return False
        if exc and any(pos.startswith(p) for p in exc):
            return False
        return True

    O_counter: Counter = Counter()
    surfaces: dict[str, Counter] = defaultdict(Counter)
    skipped_stop = 0
    for toks in sentences.values():
        clean = [(idx, text, pos) for idx, text, pos in toks]
        for i, (_idx, text, _pos) in enumerate(clean):
            if _fold(text) != node_folded:
                continue
            lo = max(0, i - sl)
            hi = min(len(clean), i + sr + 1)
            for j in range(lo, hi):
                if j == i:
                    continue
                collocate_text, collocate_pos = clean[j][1], clean[j][2]
                if stopword_set and collocate_text.lower() in stopword_set:
                    skipped_stop += 1
                    continue
                if not _pos_allowed(collocate_pos):
                    continue
                key = _fold(collocate_text)
                O_counter[key] += 1
                surfaces[key][collocate_text] += 1

    # --- 5. measures per candidate ----------------------------------------- #
    candidates = []
    chi2_warned = False
    for key, o in O_counter.items():
        if o < min_freq:
            continue
        fy = folded_counts.get(key, 0)
        if fy == 0:
            continue
        a = min(o, fx, fy)
        b = fx - a
        c = fy - a
        d = N - fx - fy + a
        if b < 0 or c < 0 or d < 0:
            continue

        display = surfaces[key].most_common(1)[0][0]
        row = {"collocate": display, "O": a, "fx": fx, "fy": fy, "N": N}
        if "mi" in measures:
            row["mi"] = round(mutual_information(O=o, R=fx, C=fy, N=N), 4)
        if "t_score" in measures:
            row["t_score"] = round(t_score(O=o, R=fx, C=fy, N=N), 4)
        if "log_likelihood" in measures:
            row["log_likelihood"] = round(log_likelihood_2x2(a, b, c, d), 4)
        if "dice" in measures:
            row["dice"] = round(dice_coefficient(joint=o, fx=fx, fy=fy), 4)
        if "log_dice" in measures:
            row["log_dice"] = round(log_dice(joint=o, fx=fx, fy=fy), 4)
        if "chi_square" in measures:
            row["chi_square"] = round(chi_square_2x2(a, b, c, d), 4)
            row["chi2_min_expected"] = round(chi2_min_expected(a, b, c, d), 4)
            if not chi2_warned and row["chi2_min_expected"] < 5:
                warnings.append(
                    "Some χ² expected cell counts are below 5 (Cochran rule) — "
                    "treat χ² as indicative for sparse pairs; prefer log-likelihood or Fisher."
                )
                chi2_warned = True
        if "fisher" in measures:
            row["fisher"] = round(fisher_exact_2x2(a, b, c, d), 6)
        if "delta_p" in measures:
            dp_yx, dp_xy = delta_p(joint=o, fx=fx, fy=fy, N=N)
            row["delta_p_y_given_x"] = round(dp_yx, 4)
            row["delta_p_x_given_y"] = round(dp_xy, 4)
        candidates.append(row)

    def _sort_key(r: dict) -> float:
        return r.get("log_likelihood", 0.0) or r.get("mi", 0.0) or float(r.get("O", 0))
    candidates.sort(key=_sort_key, reverse=True)

    if skipped_stop and stopword_set:
        warnings.append(f"{skipped_stop} collocate tokens were excluded as stopwords.")

    return CollocationResult(
        node=node,
        window=window,
        span_left=sl,
        span_right=sr,
        min_freq=min_freq,
        measures=measures,
        rows=candidates[:limit],
        warnings=warnings,
    )


# --------------------------------------------------------------------------- #
# Keyness (§8.7) — significance + effect size, always together (§4 Principle 3)
# --------------------------------------------------------------------------- #


@dataclass
class KeynessResult:
    target_corpus_id: str
    reference_corpus_id: str
    measures: list[str]
    positive_keywords: list[dict]   # over-represented in target
    negative_keywords: list[dict]   # under-represented in target
    N1: int
    N2: int
    warnings: list = None  # methodological notices for the UI

    def __post_init__(self):
        if self.warnings is None:
            self.warnings = []


async def compute_keyness(
    session: AsyncSession,
    target_corpus_id: str,
    reference_corpus_id: str,
    *,
    min_freq: int = 5,
    measures: list[str] | None = None,
    limit: int = 100,
    target_document_ids: list[str] | None = None,
    stopword_set: set[str] | None = None,
) -> KeynessResult:
    # Issue 2: ``target_document_ids`` optionally restricts the TARGET corpus
    # side of the comparison to a subcorpus (the reference side is unaffected).
    """Compare target vs reference corpus. Returns both significance and
    effect-size measures (§4 Principle 3) — never present one without the other.

    Raises ``ValueError`` if either corpus has no ingested annotation version.
    Previously the function silently returned an empty KeynessResult
    (N1=0, N2=0, no keywords), which made "fake-loaded" reference corpora
    (a corpus row with no documents/tokens) look like "keyness found no
    keywords" — a misleading non-failure. The API layer now surfaces this
    as a 422 so the UI can tell the user *why* keyness is empty instead
    of pretending it succeeded.
    """
    if measures is None:
        measures = ["log_likelihood", "chi_square", "log_ratio", "pct_diff", "simple_maths", "odds_ratio"]

    target_vid = await _latest_version_id(session, target_corpus_id)
    ref_vid = await _latest_version_id(session, reference_corpus_id)
    if not target_vid:
        raise ValueError(
            f"Target corpus '{target_corpus_id}' has no ingested annotation version. "
            f"Upload documents to it first (Your Corpus → Upload)."
        )
    if not ref_vid:
        raise ValueError(
            f"Reference corpus '{reference_corpus_id}' has no ingested annotation version. "
            f"The reference corpus must contain real tokens for keyness to be meaningful. "
            f"If you used 'Bundled → Load' to create this reference, that flow only "
            f"created an empty corpus row — use the new /api/v1/reference-corpora/ "
            f"endpoints to install a real bundled reference, or upload a reference "
            f"corpus file via the Upload tab."
        )

    # Word freqs in each corpus
    # Fix #10: Pre-filter words by min_freq at the SQL level to reduce
    # the vocabulary set by 80-95% before computing keyness statistics.
    #
    # Group by lower(text), not raw text. Without this, a word split across
    # case variants (sentence-initial "The" vs. mid-sentence "the") is
    # counted as two separate types, which both (a) undercounts common
    # words and can push them below min_freq spuriously, and (b) makes this
    # function inconsistent with compute_keyness_with_reference_list() in
    # reference_corpus/keyness_bridge.py, which already lowercases target
    # tokens to match the lowercase bundled frequency lists (BE06, Leipzig,
    # etc). Before this fix, the *same* target corpus could get different
    # keyword rankings depending on whether the reference was a bundled
    # frequency list or an uploaded reference Corpus -- a validity trap for
    # exactly the comparison this feature exists to support.
    async def _freqs(vid: str, document_ids: list[str] | None = None) -> Counter:
        text_norm = func.lower(Token.text)
        stmt = (
            select(text_norm, func.count(Token.id))
            .where(Token.version_id == vid, _is_real_token())
            .group_by(text_norm)
            .having(func.count(Token.id) >= min_freq)  # Fix #10: pre-filter
        )
        if document_ids is not None:
            stmt = stmt.where(Token.document_id.in_(document_ids))
        counter = Counter({text: count for text, count in (await session.execute(stmt)).all()})
        if stopword_set:
            for sw in stopword_set:
                counter.pop(sw.lower(), None)
        return counter

    target_freqs = await _freqs(target_vid, target_document_ids)
    ref_freqs = await _freqs(ref_vid)
    N1 = sum(target_freqs.values())
    N2 = sum(ref_freqs.values())

    # Fix #10: Only iterate over words that appear in at least one corpus
    # with min_freq — the HAVING clause already filtered at SQL level,
    # so this set is 80-95% smaller than before.
    all_words = set(target_freqs) | set(ref_freqs)
    rows: list[KeynessRow_dict] = []
    for word in all_words:
        f1 = target_freqs.get(word, 0)
        f2 = ref_freqs.get(word, 0)
        # Both are >= min_freq due to HAVING, but double-check for safety
        if f1 < min_freq and f2 < min_freq:
            continue
        kr = compute_keyness_row(word, f1, f2, N1, N2, smooth=1.0)
        rows.append(kr)

    # Sort by log_likelihood descending
    rows.sort(key=lambda r: r.measures.get("log_likelihood", 0.0), reverse=True)

    positive = [r for r in rows if r.measures.get("log_ratio", 0) > 0][:limit]
    negative = [r for r in rows if r.measures.get("log_ratio", 0) < 0][:limit]

    return KeynessResult(
        target_corpus_id=target_corpus_id,
        reference_corpus_id=reference_corpus_id,
        measures=measures,
        positive_keywords=[{"term": r.term, "f1": r.f1, "f2": r.f2, **r.measures} for r in positive],
        negative_keywords=[{"term": r.term, "f1": r.f1, "f2": r.f2, **r.measures} for r in negative],
        N1=N1,
        N2=N2,
        warnings=(
            [f"{len(stopword_set)} stopwords excluded from both corpora."]
            if stopword_set else []
        ),
    )


# Type alias used internally above — the dataclass is in stats.measures
KeynessRow_dict = type(compute_keyness_row("x", 0, 0, 1, 1))


# --------------------------------------------------------------------------- #
# Dispersion (§8.9)
# --------------------------------------------------------------------------- #


@dataclass
class DispersionResult:
    term: str
    juillands_d: float
    gries_dp: float
    gries_dp_norm: float
    range: int            # documents containing the term
    range_percent: float
    per_part_freqs: list[int]
    part_sizes: list[int]  # tokens per document (for size-weighted DP)


async def compute_dispersion(
    session: AsyncSession,
    corpus_id: str,
    term: str,
    *,
    level: Literal["word", "lemma"] = "word",
) -> DispersionResult:
    """Dispersion across documents (corpus parts).

    v1.0.1: Gries' DP now uses size-weighted expected proportions (document
    token counts), DP-norm is reported for cross-corpus comparability, and
    range/range_percent are included. Juilland's D remains computed on raw
    part counts — it assumes roughly equal-sized parts, which the docstring
    flags; prefer DP for corpora with heterogeneous document lengths.
    """
    version_id = await _latest_version_id(session, corpus_id)
    if not version_id:
        return DispersionResult(term=term, juillands_d=0.0, gries_dp=0.0,
                                gries_dp_norm=0.0, range=0, range_percent=0.0,
                                per_part_freqs=[], part_sizes=[])

    col = {"word": Token.text, "lemma": Token.lemma}[level]

    # Frequency per document (term)
    stmt = (
        select(Token.document_id, func.count(Token.id))
        .where(Token.version_id == version_id, func.lower(col) == term.lower())
        .group_by(Token.document_id)
    )
    per_doc_counter: Counter = Counter()
    for doc_id, cnt in (await session.execute(stmt)).all():
        per_doc_counter[doc_id] = cnt

    # All documents as parts, with per-document token counts as part sizes
    docs_stmt = select(Document.id).where(Document.corpus_id == corpus_id)
    all_doc_ids = [r[0] for r in (await session.execute(docs_stmt)).all()]
    size_stmt = (
        select(Token.document_id, func.count(Token.id))
        .where(Token.version_id == version_id, _is_real_token())
        .group_by(Token.document_id)
    )
    doc_sizes = {doc_id: cnt for doc_id, cnt in (await session.execute(size_stmt)).all()}
    per_part = [per_doc_counter.get(did, 0) for did in all_doc_ids]
    sizes = [doc_sizes.get(did, 0) for did in all_doc_ids]

    in_range = sum(1 for f in per_part if f > 0)
    n_docs = len(all_doc_ids)
    return DispersionResult(
        term=term,
        juillands_d=round(juillands_d(per_part), 4),
        gries_dp=round(gries_dp(per_part, sizes=sizes), 4),
        gries_dp_norm=round(gries_dp_norm(per_part, sizes=sizes), 4),
        range=in_range,
        range_percent=round(in_range / n_docs * 100, 2) if n_docs else 0.0,
        per_part_freqs=per_part,
        part_sizes=sizes,
    )


# --------------------------------------------------------------------------- #
# v1.0.1 — Document statistics, metadata-group pivot, readability
# --------------------------------------------------------------------------- #


async def compute_document_stats(
    session: AsyncSession,
    corpus_id: str,
) -> list[dict]:
    """Per-document statistics table: tokens, types, sentences, TTR, LIX, RIX.

    Flesch formulas are computed per document only when the detected language
    is English (syllable counting is not valid for Arabic script); LIX/RIX
    are language-neutral and always reported.
    """
    from stats.readability import readability_from_counts

    version_id = await _latest_version_id(session, corpus_id)
    if not version_id:
        return []

    docs_stmt = select(Document).where(Document.corpus_id == corpus_id).order_by(Document.filename)
    documents = (await session.execute(docs_stmt)).scalars().all()

    tok_stmt = (
        select(Token.document_id, Token.sentence_idx, Token.text, Token.is_punct, Token.pos)
        .where(Token.version_id == version_id)
        .order_by(Token.document_id, Token.sentence_idx, Token.token_idx)
    )

    per_doc: dict[str, dict] = {}
    for doc_id, sent_idx, text, is_punct, pos in (await session.execute(tok_stmt)).all():
        d = per_doc.setdefault(doc_id, {
            "tokens": 0, "types": set(), "sentences": set(),
            "long_words": 0, "sent_token_texts": [],
        })
        if is_punct or pos == "SPACE" or (text and text.isspace()):
            continue
        d["tokens"] += 1
        d["types"].add(text.lower())
        d["sentences"].add(sent_idx)
        t = text.strip(".,;:!?'\"()[]{}")
        if len(t) > 6:
            d["long_words"] += 1

    out = []
    for doc in documents:
        d = per_doc.get(doc.id)
        if d is None:
            continue
        words = d["tokens"]
        sents = len(d["sentences"])
        language = doc.detected_language or ""
        panel = readability_from_counts(
            words=words, sentences=sents, syllables=0,
            long_words=d["long_words"], language=language,
        )
        out.append({
            "document_id": doc.id,
            "filename": doc.filename,
            "language": language,
            "tokens": words,
            "types": len(d["types"]),
            "sentences": sents,
            "ttr": round(len(d["types"]) / words, 4) if words else 0.0,
            "avg_sentence_length": panel["avg_sentence_length"],
            "lix": panel["lix"],
            "rix": panel["rix"],
        })
    return out


async def compute_corpus_readability(
    session: AsyncSession,
    corpus_id: str,
) -> dict:
    """Corpus-level readability panel.

    Words, sentences and long words come from the token tables; syllables
    are summed only over English documents (detected_language == 'en'), so
    the Flesch family is a corpus-weighted blend of its English parts.
    LIX/RIX are language-neutral and use every document.
    """
    from stats.readability import count_syllables_en, readability_from_counts

    version_id = await _latest_version_id(session, corpus_id)
    if not version_id:
        return {}

    docs_stmt = select(Document.id, Document.detected_language).where(Document.corpus_id == corpus_id)
    doc_langs: dict[str, str] = {
        doc_id: (lang or "") for doc_id, lang in (await session.execute(docs_stmt)).all()
    }

    tok_stmt = (
        select(Token.document_id, Token.sentence_idx, Token.text, Token.is_punct, Token.pos)
        .where(Token.version_id == version_id)
        .order_by(Token.document_id, Token.sentence_idx, Token.token_idx)
    )
    words = 0
    sentences: set[tuple[str, int]] = set()
    long_words = 0
    syllables = 0
    for doc_id, sent_idx, text, is_punct, pos in (await session.execute(tok_stmt)).all():
        if is_punct or pos == "SPACE" or (text and text.isspace()):
            continue
        words += 1
        sentences.add((doc_id, sent_idx))
        stripped = text.strip(".,;:!?'\"()[]{}")
        if len(stripped) > 6:
            long_words += 1
        if doc_langs.get(doc_id) == "en":
            syllables += count_syllables_en(text)

    panel = readability_from_counts(
        words=words, sentences=len(sentences), syllables=syllables,
        long_words=long_words, language="en",
    )
    # If the corpus has no English documents at all, suppress the Flesch scores
    if not any(lang == "en" for lang in doc_langs.values()):
        panel["flesch_reading_ease"] = None
        panel["flesch_kincaid_grade"] = None
        panel["note"] = (
            "Flesch scores require English text (syllable counting); "
            "LIX/RIX are reported for every language."
        )
    panel["documents"] = len(doc_langs)
    return panel


async def compute_group_frequency(
    session: AsyncSession,
    corpus_id: str,
    meta_field: str,
    *,
    unit: str = "word",
    min_freq: int = 1,
    limit: int = 200,
    document_ids: list[str] | None = None,
    stopword_set: set[str] | None = None,
) -> dict:
    """Frequency pivot by a metadata variable (genre, year, register, …).

    v1.0.1 — the 'process metadata' workflow: documents are grouped by
    ``Document.meta[meta_field]`` (missing values become '(uncategorised)'),
    and per-group raw + per-million frequencies are returned side by side
    so categories can be compared directly.
    """
    if unit not in ("word", "lemma", "pos"):
        unit = "word"
    version_id = await _latest_version_id(session, corpus_id)
    if not version_id:
        return {"meta_field": meta_field, "unit": unit, "groups": [], "rows": []}

    docs_stmt = select(Document.id, Document.meta).where(Document.corpus_id == corpus_id)
    if document_ids is not None:
        docs_stmt = docs_stmt.where(Document.id.in_(document_ids))
    doc_group: dict[str, str] = {}
    for doc_id, meta in (await session.execute(docs_stmt)).all():
        value = (meta or {}).get(meta_field)
        doc_group[doc_id] = str(value) if value not in (None, "") else "(uncategorised)"

    col = {"word": Token.text, "lemma": Token.lemma, "pos": Token.pos}[unit]
    tok_stmt = (
        select(Token.document_id, col)
        .where(Token.version_id == version_id, _is_real_token())
    )
    if document_ids is not None:
        tok_stmt = tok_stmt.where(Token.document_id.in_(document_ids))

    stop_lower = {s.lower() for s in stopword_set} if stopword_set else set()
    freqs: dict[str, Counter] = defaultdict(Counter)
    group_tokens: Counter = Counter()
    for doc_id, text in (await session.execute(tok_stmt)).all():
        group = doc_group.get(doc_id, "(uncategorised)")
        key = text if unit == "pos" else text.lower()
        if stop_lower and unit != "pos" and key in stop_lower:
            continue
        freqs[group][key] += 1
        group_tokens[group] += 1

    groups = sorted(freqs.keys())
    totals: Counter = Counter()
    for g in groups:
        totals.update(freqs[g])
    top_items = [item for item, _ in totals.most_common(limit) if totals[item] >= min_freq]

    rows = []
    for item in top_items:
        row = {"item": item, "total": totals[item], "groups": {}}
        for g in groups:
            f = freqs[g].get(item, 0)
            n = group_tokens[g]
            row["groups"][g] = {
                "freq": f,
                "per_million": round(f / n * 1_000_000, 2) if n else 0.0,
            }
        rows.append(row)

    return {
        "meta_field": meta_field,
        "unit": unit,
        "groups": [
            {"name": g, "documents": sum(1 for v in doc_group.values() if v == g),
             "tokens": group_tokens[g]}
            for g in groups
        ],
        "rows": rows,
    }
