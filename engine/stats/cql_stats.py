"""CQL statistics consumers (v1.2.13-2): frequency, collocations, dispersion,
and n-grams computed over the CQL match node.

All four share ONE implementation path — ``stats.cql.find_cql_spans`` — so
every consumer inherits the matcher's guards (work budget, wall-clock
deadline, max span bound, thread offloading) and the identical matching
semantics documented in stats/cql.py. The "node" for statistics is the match
span's surface (the KWIC node column); dispersion counts matches per
document; n-grams are node-initial lexical bundles.

Collocation conventions mirror ``compute_collocations`` exactly:
  O  = co-occurrences of the CQL node span and the collocate within the span
  fx = number of CQL match spans
  fy = corpus frequency of the collocate (raw word form)
  N  = corpus size (non-punctuation tokens)
Association measures come from stats.measures (shared with the simple
collocations endpoint, so numbers are directly comparable).
"""
from __future__ import annotations

from collections import Counter, defaultdict
from dataclasses import dataclass

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from stats.cql import MatchLimits, find_cql_spans
from stats.measures import (
    chi2_min_expected,
    chi_square_2x2,
    dice_coefficient,
    delta_p,
    fisher_exact_2x2,
    gries_dp,
    gries_dp_norm,
    juillands_d,
    log_dice,
    log_likelihood_2x2,
    mutual_information,
    t_score,
)
from stats.service import _is_real_token, DispersionResult
from discourse.service import NGramResult
from storage.models import Document, Token


DEFAULT_MEASURES = ["mi", "t_score", "log_likelihood", "dice", "log_dice"]


async def _corpus_size_and_word_freqs(
    session: AsyncSession,
    version_id: str,
) -> tuple[int, Counter]:
    """N (non-punctuation tokens) and per-word corpus frequencies."""
    stmt = (
        select(Token.text, func.count(Token.id))
        .where(Token.version_id == version_id, _is_real_token())
        .group_by(Token.text)
    )
    freqs: Counter = Counter()
    for text, cnt in (await session.execute(stmt)).all():
        freqs[text or ""] += cnt
    return sum(freqs.values()), freqs


async def compute_cql_frequency(
    session: AsyncSession,
    corpus_id: str,
    query: str,
    *,
    unit: str = "word",
    min_freq: int = 1,
    limit: int = 1000,
    document_ids: list[str] | None = None,
    normalize: bool | None = None,
    normalize_arabic: bool = False,
    zwnj: str = "keep",
    cqp_compat: bool = False,
    limits: MatchLimits | None = None,
) -> dict:
    """Frequency over the CQL match node.

    ``unit`` selects which attribute of each match's FIRST token is counted:
    word | lemma | pos (the span surface is also reported as ``node``).
    Returns the same row shape as the simple frequency endpoint
    ({item, freq, per_million, percent}) so the client renders it unchanged;
    STTR/lexical-diversity metrics do not apply to a node list and are
    deliberately omitted (``sttr`` is 0.0, ``lexical_diversity`` empty).
    """
    if unit not in ("word", "lemma", "pos"):
        unit = "word"
    match_set = await find_cql_spans(
        session, corpus_id, query,
        document_ids=document_ids, normalize=normalize,
        normalize_arabic=normalize_arabic, zwnj=zwnj,
        cqp_compat=cqp_compat, limits=limits,
    )
    counter: Counter = Counter()
    for views in match_set.node_views():
        first = views[0]
        item = {"word": first.text, "lemma": first.lemma, "pos": first.pos}[unit] or ""
        counter[item] += 1
    total = sum(counter.values())
    rows = [
        {
            "item": item,
            "freq": freq,
            "per_million": round(freq / total * 1_000_000, 2) if total else 0.0,
            "percent": round(freq / total * 100, 2) if total else 0.0,
        }
        for item, freq in counter.most_common()
        if freq >= min_freq
    ][:limit]
    return {
        "unit": unit,
        "total_tokens": total,
        "total_types": len(counter),
        "rows": rows,
        "sttr": 0.0,
        "lexical_diversity": {},
        "cql_query": query,
        "total_capped": match_set.capped,
    }


async def compute_cql_collocations(
    session: AsyncSession,
    corpus_id: str,
    query: str,
    *,
    window: int = 5,
    min_freq: int = 3,
    measures: list[str] | None = None,
    limit: int = 100,
    document_ids: list[str] | None = None,
    normalize: bool | None = None,
    normalize_arabic: bool = False,
    zwnj: str = "keep",
    cqp_compat: bool = False,
    limits: MatchLimits | None = None,
) -> dict:
    """Collocates of the CQL match node (spans) within ``window`` tokens.

    Same measure conventions as the simple collocations endpoint; ``fx`` is
    the number of match spans (the node's frequency under the pattern).
    """
    if measures is None:
        measures = list(DEFAULT_MEASURES)
    match_set = await find_cql_spans(
        session, corpus_id, query,
        document_ids=document_ids, normalize=normalize,
        normalize_arabic=normalize_arabic, zwnj=zwnj,
        cqp_compat=cqp_compat, limits=limits,
    )
    N, word_freqs = await _corpus_size_and_word_freqs(session, match_set.version_id)
    fx = len(match_set.spans)

    O_counter: Counter = Counter()
    surfaces: dict[str, Counter] = defaultdict(Counter)
    for d, s, e in match_set.spans:
        stream = match_set.streams[d]
        lo = max(0, s - window)
        hi = min(len(stream), e + window + 1)
        for i in range(lo, hi):
            if s <= i <= e:
                continue  # the node itself is not its own collocate
            text = stream[i].text or ""
            if not text:
                continue
            O_counter[text] += 1
            surfaces[text][text] += 1

    chi2_warned = False
    warnings: list[str] = []
    rows: list[dict] = []
    for collocate, o in O_counter.items():
        if o < min_freq:
            continue
        fy = word_freqs.get(collocate, 0)
        if fy == 0:
            continue
        a = min(o, fx, fy)
        b = fx - a
        c = fy - a
        dcell = N - fx - fy + a
        if b < 0 or c < 0 or dcell < 0:
            continue
        row = {"collocate": collocate, "O": a, "fx": fx, "fy": fy, "N": N}
        if "mi" in measures:
            row["mi"] = round(mutual_information(O=o, R=fx, C=fy, N=N), 4)
        if "t_score" in measures:
            row["t_score"] = round(t_score(O=o, R=fx, C=fy, N=N), 4)
        if "log_likelihood" in measures:
            row["log_likelihood"] = round(log_likelihood_2x2(a, b, c, dcell), 4)
        if "dice" in measures:
            row["dice"] = round(dice_coefficient(joint=o, fx=fx, fy=fy), 4)
        if "log_dice" in measures:
            row["log_dice"] = round(log_dice(joint=o, fx=fx, fy=fy), 4)
        if "chi_square" in measures:
            row["chi_square"] = round(chi_square_2x2(a, b, c, dcell), 4)
            row["chi2_min_expected"] = round(chi2_min_expected(a, b, c, dcell), 4)
            if not chi2_warned and row["chi2_min_expected"] < 5:
                warnings.append(
                    "Some χ² expected cell counts are below 5 (Cochran rule) - "
                    "treat χ² as indicative for sparse pairs; prefer log-likelihood or Fisher."
                )
                chi2_warned = True
        if "fisher" in measures:
            row["fisher"] = round(fisher_exact_2x2(a, b, c, dcell), 6)
        if "delta_p" in measures:
            dp_yx, dp_xy = delta_p(joint=o, fx=fx, fy=fy, N=N)
            row["delta_p_y_given_x"] = round(dp_yx, 4)
            row["delta_p_x_given_y"] = round(dp_xy, 4)
        rows.append(row)

    def _sort_key(r: dict) -> float:
        return r.get("log_likelihood", 0.0) or r.get("mi", 0.0) or float(r.get("O", 0))

    rows.sort(key=_sort_key, reverse=True)
    return {
        "node": query,
        "is_cql": True,
        "window": window,
        "span_left": window,
        "span_right": window,
        "min_freq": min_freq,
        "measures": measures,
        "rows": rows[:limit],
        "warnings": warnings,
        "total_capped": match_set.capped,
    }


async def compute_cql_dispersion(
    session: AsyncSession,
    corpus_id: str,
    query: str,
    *,
    document_ids: list[str] | None = None,
    normalize: bool | None = None,
    normalize_arabic: bool = False,
    zwnj: str = "keep",
    cqp_compat: bool = False,
    limits: MatchLimits | None = None,
) -> DispersionResult:
    """Dispersion of a CQL pattern across documents (Gries' DP, range, etc.).

    Same math and result shape as the simple dispersion endpoint; the counts
    are CQL match spans per document instead of a term's frequency.
    """
    match_set = await find_cql_spans(
        session, corpus_id, query,
        document_ids=document_ids, normalize=normalize,
        normalize_arabic=normalize_arabic, zwnj=zwnj,
        cqp_compat=cqp_compat, limits=limits,
    )
    per_doc = match_set.per_document()

    docs_stmt = select(Document.id).where(Document.corpus_id == corpus_id)
    all_doc_ids = [r[0] for r in (await session.execute(docs_stmt)).all()]
    if match_set.version_id:
        size_stmt = (
            select(Token.document_id, func.count(Token.id))
            .where(Token.version_id == match_set.version_id, _is_real_token())
            .group_by(Token.document_id)
        )
        doc_sizes = {doc_id: cnt for doc_id, cnt in (await session.execute(size_stmt)).all()}
    else:
        doc_sizes = {}
    per_part = [per_doc.get(did, 0) for did in all_doc_ids]
    sizes = [doc_sizes.get(did, 0) for did in all_doc_ids]
    in_range = sum(1 for f in per_part if f > 0)
    n_docs = len(all_doc_ids)
    return DispersionResult(
        term=query,
        juillands_d=round(juillands_d(per_part), 4),
        gries_dp=round(gries_dp(per_part, sizes=sizes), 4),
        gries_dp_norm=round(gries_dp_norm(per_part, sizes=sizes), 4),
        range=in_range,
        range_percent=round(in_range / n_docs * 100, 2) if n_docs else 0.0,
        per_part_freqs=per_part,
        part_sizes=sizes,
    )


async def compute_cql_ngrams(
    session: AsyncSession,
    corpus_id: str,
    query: str,
    *,
    n: int = 2,
    min_freq: int = 2,
    min_range: int = 1,
    limit: int = 200,
    skip_punct: bool = True,
    document_ids: list[str] | None = None,
    normalize: bool | None = None,
    normalize_arabic: bool = False,
    zwnj: str = "keep",
    cqp_compat: bool = False,
    limits: MatchLimits | None = None,
) -> NGramResult:
    """Node-initial n-grams: lexical bundles that START at a CQL match.

    For every match span, the next ``n`` stream tokens (punctuation skipped
    unless ``skip_punct=False``) form one candidate bundle counted once per
    span; frequency and document range follow the §8.8 criterion used by the
    regular n-grams endpoint.
    """
    if n < 2 or n > 8:
        n = 2
    match_set = await find_cql_spans(
        session, corpus_id, query,
        document_ids=document_ids, normalize=normalize,
        normalize_arabic=normalize_arabic, zwnj=zwnj,
        cqp_compat=cqp_compat, limits=limits,
    )
    counter: Counter = Counter()
    doc_spread: dict[str, set[str]] = defaultdict(set)
    for d, s, _e in match_set.spans:
        stream = match_set.streams[d]
        toks: list[str] = []
        i = s
        while i < len(stream) and len(toks) < n:
            v = stream[i]
            if skip_punct and v.pos == "PUNCT":
                i += 1
                continue
            toks.append(v.text or "")
            i += 1
        if len(toks) < n:
            continue
        bundle = " ".join(toks)
        counter[bundle] += 1
        doc_spread[bundle].add(d)

    total = sum(counter.values())
    rows = [
        {
            "ngram": bundle,
            "freq": freq,
            "per_million": round(freq / total * 1_000_000, 2) if total else 0.0,
            "range": len(doc_spread[bundle]),
            "range_percent": round(len(doc_spread[bundle]) / max(1, len(match_set.streams)) * 100, 2),
        }
        for bundle, freq in counter.most_common()
        if freq >= min_freq and len(doc_spread[bundle]) >= min_range
    ][:limit]
    return NGramResult(
        n=n,
        total_tokens=total,
        rows=rows,
        min_freq=min_freq,
        min_range=min_range,
    )
