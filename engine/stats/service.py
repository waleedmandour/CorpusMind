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
    chi_square_2x2,
    compute_keyness_row,
    delta_p,
    dice_coefficient,
    gries_dp,
    juillands_d,
    log_dice,
    log_likelihood_2x2,
    mutual_information,
    sttr,
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


async def _corpus_size(session: AsyncSession, version_id: str) -> int:
    """Total token count for a version (excluding punctuation and whitespace)."""
    stmt = select(func.count(Token.id)).where(
        Token.version_id == version_id,
        Token.is_punct == False,  # noqa: E712
        Token.pos != "SPACE",
    )
    return await session.scalar(stmt) or 0


def _is_real_token():
    """SQL condition for 'this token is a real word, not punct/whitespace."""
    return (Token.is_punct == False) & (Token.pos != "SPACE")  # noqa: E712


# --------------------------------------------------------------------------- #
# Search & Concordance (§8.3, §8.4)
# --------------------------------------------------------------------------- #


@dataclass(frozen=True, slots=True)
class ConcordanceLine:
    """One KWIC line. `line_id` is stable — cited by the AI Assistant (§11.1)."""
    line_id: str           # f"{doc_id}:{sent_idx}:{tok_idx}"
    document_id: str
    document_filename: str
    sentence_idx: int
    token_idx: int
    left: str              # tokens to the left of the node
    node: str              # the matched token(s)
    right: str             # tokens to the right
    pos: str               # UPOS of the node
    lemma: str             # lemma of the node


@dataclass
class ConcordanceResult:
    lines: list[ConcordanceLine]
    total: int
    query: dict


async def search_concordance(
    session: AsyncSession,
    corpus_id: str,
    query: str,
    *,
    level: Literal["word", "lemma", "pos"] = "word",
    case_sensitive: bool = False,
    window: int = 5,
    limit: int = 100,
    offset: int = 0,
) -> ConcordanceResult:
    """KWIC search. `query` is matched against the chosen `level` (word/lemma/POS).

    Phase 1 supports: exact match (case-insensitive by default), wildcard `*`
    (any sequence), and a POS-tag query (e.g. `NOUN` or `VERB.*`).
    Phase 2 will add CQL-style structured queries (§8.3).
    """
    version_id = await _latest_version_id(session, corpus_id)
    if not version_id:
        return ConcordanceResult(lines=[], total=0, query={"q": query, "level": level})

    # Build the column to match on
    col = {"word": Token.text, "lemma": Token.lemma, "pos": Token.pos}[level]

    # Translate wildcard patterns to SQL LIKE
    if "*" in query or "?" in query:
        # SQL LIKE: % = any sequence, _ = single char
        like_pattern = query.replace("*", "%").replace("?", "_")
        if not case_sensitive:
            cond = col.ilike(like_pattern)
        else:
            cond = col.like(like_pattern)
    else:
        if case_sensitive:
            cond = col == query
        else:
            cond = func.lower(col) == func.lower(query)

    # Exclude punctuation + whitespace tokens from the node itself
    cond = cond & _is_real_token()

    # Count first
    count_stmt = select(func.count(Token.id)).where(Token.version_id == version_id, cond)
    total = await session.scalar(count_stmt) or 0

    # Fetch the matching tokens with pagination
    stmt = (
        select(Token, Document.filename)
        .join(Document, Token.document_id == Document.id)
        .where(Token.version_id == version_id, cond)
        .order_by(Token.document_id, Token.sentence_idx, Token.token_idx)
        .limit(limit)
        .offset(offset)
    )
    rows = (await session.execute(stmt)).all()

    lines: list[ConcordanceLine] = []
    for tok, filename in rows:
        # Fetch window tokens in a single query per match (could be batched
        # for very high-throughput use; Phase 1 MVP is fine).
        win_stmt = (
            select(Token.text)
            .where(
                Token.version_id == version_id,
                Token.document_id == tok.document_id,
                Token.sentence_idx == tok.sentence_idx,
            )
            .order_by(Token.token_idx)
        )
        sent_tokens = [r[0] for r in (await session.execute(win_stmt)).all()]
        idx_in_sent = tok.token_idx
        left = " ".join(sent_tokens[max(0, idx_in_sent - window) : idx_in_sent])
        right = " ".join(sent_tokens[idx_in_sent + 1 : idx_in_sent + 1 + window])
        lines.append(ConcordanceLine(
            line_id=f"{tok.document_id}:{tok.sentence_idx}:{tok.token_idx}",
            document_id=tok.document_id,
            document_filename=filename,
            sentence_idx=tok.sentence_idx,
            token_idx=tok.token_idx,
            left=left,
            node=tok.text,
            right=right,
            pos=tok.pos,
            lemma=tok.lemma,
        ))

    return ConcordanceResult(
        lines=lines,
        total=total,
        query={"q": query, "level": level, "window": window, "case_sensitive": case_sensitive},
    )


# --------------------------------------------------------------------------- #
# Frequency (§8.5)
# --------------------------------------------------------------------------- #


@dataclass
class FrequencyResult:
    unit: str            # "word" | "lemma" | "pos"
    total_tokens: int
    total_types: int
    rows: list[dict]     # [{item, freq, per_million, percent}]
    sttr: float          # standardized TTR over 1000-token chunks


async def compute_frequency(
    session: AsyncSession,
    corpus_id: str,
    *,
    unit: Literal["word", "lemma", "pos"] = "word",
    min_freq: int = 1,
    limit: int = 1000,
    include_punct: bool = False,
) -> FrequencyResult:
    version_id = await _latest_version_id(session, corpus_id)
    if not version_id:
        return FrequencyResult(unit=unit, total_tokens=0, total_types=0, rows=[], sttr=0.0)

    col = {"word": Token.text, "lemma": Token.lemma, "pos": Token.pos}[unit]

    # Aggregate counts
    stmt = (
        select(col, func.count(Token.id).label("freq"))
        .where(Token.version_id == version_id)
        .group_by(col)
        .order_by(func.count(Token.id).desc())
        .limit(limit)
    )
    if not include_punct:
        stmt = stmt.where(_is_real_token())

    rows_raw = (await session.execute(stmt)).all()
    total_tokens = await _corpus_size(session, version_id)
    total_types = len(rows_raw)

    # STTR requires the ordered token stream (not just the aggregate).
    # We compute it on the fly when unit == "word".
    sttr_value = 0.0
    if unit == "word":
        tok_stmt = (
            select(Token.text)
            .where(Token.version_id == version_id, _is_real_token())
            .order_by(Token.document_id, Token.sentence_idx, Token.token_idx)
        )
        tokens_list = [r[0] for r in (await session.execute(tok_stmt)).all()]
        sttr_value = sttr(tokens_list, chunk_size=1000) if tokens_list else 0.0

    rows = []
    for item, freq in rows_raw:
        if freq < min_freq:
            continue
        per_million = (freq / total_tokens * 1_000_000) if total_tokens else 0.0
        percent = (freq / total_tokens * 100) if total_tokens else 0.0
        rows.append({
            "item": item,
            "freq": freq,
            "per_million": round(per_million, 2),
            "percent": round(percent, 4),
        })

    return FrequencyResult(
        unit=unit,
        total_tokens=total_tokens,
        total_types=total_types,
        rows=rows,
        sttr=round(sttr_value, 4),
    )


# --------------------------------------------------------------------------- #
# Collocation (§8.6)
# --------------------------------------------------------------------------- #


@dataclass
class CollocationResult:
    node: str
    window: int
    min_freq: int
    measures: list[str]
    rows: list[dict]


async def compute_collocations(
    session: AsyncSession,
    corpus_id: str,
    node: str,
    *,
    level: Literal["word", "lemma"] = "word",
    window: int = 5,
    min_freq: int = 3,
    measures: list[str] | None = None,
    limit: int = 100,
) -> CollocationResult:
    """Compute collocation measures for `node` against all co-occurring tokens.

    For each candidate collocate y, counts:
      O  = co-occurrences of node + y within ±window tokens, same sentence
      fx = total freq of node
      fy = total freq of y
      N  = corpus size
    Then computes every requested measure (default: all of them).
    """
    if measures is None:
        measures = ["mi", "t_score", "log_likelihood", "dice", "log_dice", "chi_square", "delta_p"]

    version_id = await _latest_version_id(session, corpus_id)
    if not version_id:
        return CollocationResult(node=node, window=window, min_freq=min_freq, measures=measures, rows=[])

    col = {"word": Token.text, "lemma": Token.lemma}[level]

    # Case-insensitive node match
    node_lower = node.lower()

    # Phase 1 MVP: load the relevant token stream into memory.
    # For corpora in the hundreds-of-millions-of-tokens range this would
    # need an actual positional index (§7.3); for Phase 1's MVP scale
    # (single documents of <1 MB) this is the simplest correct implementation.
    stmt = (
        select(Token.document_id, Token.sentence_idx, Token.token_idx, col.label("text"), Token.is_punct, Token.pos)
        .where(Token.version_id == version_id)
        .order_by(Token.document_id, Token.sentence_idx, Token.token_idx)
    )
    rows_raw = (await session.execute(stmt)).all()

    # Group by (doc, sentence) and build per-sentence token lists
    # Filter out punct + SPACE tokens at load time so collocation windows are clean
    sentences: dict[tuple[str, int], list[tuple[int, str, bool]]] = defaultdict(list)
    for doc_id, sent_idx, tok_idx, text, is_punct, pos in rows_raw:
        if is_punct or pos == "SPACE":
            continue
        sentences[(doc_id, sent_idx)].append((tok_idx, text, is_punct))

    # Frequency marginals (exclude punct + whitespace)
    fx = 0
    fy_counter: Counter = Counter()
    N = 0
    for toks in sentences.values():
        for _, text, is_punct in toks:
            if is_punct:
                continue
            # Skip SPACE tokens by checking the text — we don't have pos here
            # in the per-sentence loop, but space tokens have text that's all whitespace
            if text.isspace():
                continue
            N += 1
            t_low = text.lower()
            if t_low == node_lower:
                fx += 1
            fy_counter[text] += 1

    # Co-occurrence counts O(node, y) within ±window in the same sentence
    O_counter: Counter = Counter()
    for toks in sentences.values():
        # Build a clean list of (idx, text) excluding punct + SPACE for window scan.
        # `toks` is already filtered (we skipped is_punct + SPACE at load time).
        clean = [(idx, text) for idx, text, _ in toks]
        for i, (_idx, text) in enumerate(clean):
            if text.lower() != node_lower:
                continue
            # Window: tokens i-window..i+window excluding i itself
            for j in range(max(0, i - window), min(len(clean), i + window + 1)):
                if j == i:
                    continue
                collocate_text = clean[j][1]
                O_counter[collocate_text] += 1

    # Compute measures for each candidate
    candidates = []
    for y, o in O_counter.items():
        if o < min_freq:
            continue
        fy = fy_counter[y]
        if fy == 0:
            continue
        # 2×2 contingency table for LL/chi-square:
        #   a = co-occurrence count (capped at min(fx, fy) — overlapping windows
        #      can over-count, but the contingency table must have a ≤ fx, a ≤ fy)
        #   b = fx - a (node without collocate)
        #   c = fy - a (collocate without node)
        #   d = N - fx - fy + a (neither)
        a = min(o, fx, fy)
        b = fx - a
        c = fy - a
        d = N - fx - fy + a
        if b < 0 or c < 0 or d < 0:
            continue  # shouldn't happen after the cap, but be safe

        row = {"collocate": y, "O": a, "fx": fx, "fy": fy, "N": N}
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
        if "delta_p" in measures:
            dp_yx, dp_xy = delta_p(joint=o, fx=fx, fy=fy, N=N)
            row["delta_p_y_given_x"] = round(dp_yx, 4)
            row["delta_p_x_given_y"] = round(dp_xy, 4)
        candidates.append(row)

    # Sort by log_likelihood descending if present, else by O
    def _sort_key(r: dict) -> float:
        return r.get("log_likelihood") or r.get("mi") or r.get("O") or 0.0
    candidates.sort(key=_sort_key, reverse=True)

    return CollocationResult(
        node=node,
        window=window,
        min_freq=min_freq,
        measures=measures,
        rows=candidates[:limit],
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


async def compute_keyness(
    session: AsyncSession,
    target_corpus_id: str,
    reference_corpus_id: str,
    *,
    min_freq: int = 5,
    measures: list[str] | None = None,
    limit: int = 100,
) -> KeynessResult:
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
    async def _freqs(vid: str) -> Counter:
        stmt = (
            select(Token.text, func.count(Token.id))
            .where(Token.version_id == vid, _is_real_token())
            .group_by(Token.text)
        )
        return Counter({text: count for text, count in (await session.execute(stmt)).all()})

    target_freqs = await _freqs(target_vid)
    ref_freqs = await _freqs(ref_vid)
    N1 = sum(target_freqs.values())
    N2 = sum(ref_freqs.values())

    all_words = set(target_freqs) | set(ref_freqs)
    rows: list[KeynessRow_dict] = []
    for word in all_words:
        f1 = target_freqs.get(word, 0)
        f2 = ref_freqs.get(word, 0)
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
    per_part_freqs: list[int]


async def compute_dispersion(
    session: AsyncSession,
    corpus_id: str,
    term: str,
    *,
    level: Literal["word", "lemma"] = "word",
) -> DispersionResult:
    """Compute Juilland's D and Gries' DP across documents (as corpus parts)."""
    version_id = await _latest_version_id(session, corpus_id)
    if not version_id:
        return DispersionResult(term=term, juillands_d=0.0, gries_dp=0.0, per_part_freqs=[])

    col = {"word": Token.text, "lemma": Token.lemma}[level]

    # Frequency per document
    stmt = (
        select(Token.document_id, func.count(Token.id))
        .where(Token.version_id == version_id, func.lower(col) == term.lower())
        .group_by(Token.document_id)
    )
    per_doc_counter: Counter = Counter()
    for doc_id, cnt in (await session.execute(stmt)).all():
        per_doc_counter[doc_id] = cnt

    # All documents in the corpus as parts (including those with 0 frequency)
    docs_stmt = select(Document.id).where(Document.corpus_id == corpus_id)
    all_doc_ids = [r[0] for r in (await session.execute(docs_stmt)).all()]
    per_part = [per_doc_counter.get(did, 0) for did in all_doc_ids]

    return DispersionResult(
        term=term,
        juillands_d=round(juillands_d(per_part), 4),
        gries_dp=round(gries_dp(per_part), 4),
        per_part_freqs=per_part,
    )
