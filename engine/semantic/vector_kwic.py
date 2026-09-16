"""Vector KWIC — semantically re-ranked concordancing with sentence embeddings.

Method (v1.2.0), following Anthony, L. (2025). "Concordancing with AI:
Applications of word and sentence embeddings." *Applied Corpus Linguistics*
5(3), 100164:

- **Mode A (keyword + semantic re-rank).** Candidate lines come from the
  existing deterministic concordancer (:func:`stats.service.search_concordance`).
  Each line's context window (left + node + right) is embedded, and lines are
  re-ranked by cosine similarity between the context vector and the embedding
  of the user's *query* — so lines containing the keyword are ordered by
  semantic proximity to the research question, not by position.
- **Mode B (semantic search, no node word).** With no node query, the corpus
  is scanned sentence-by-sentence (capped, honestly reported) and the top-k
  sentences most similar to the query are returned — "find me meanings, not
  strings".

Honesty rules enforced here:
- Similarity is **raw cosine similarity** between sentence embeddings. No
  confidence claims, no fake percentages-of-certainty.
- The embedding model name is echoed in every response so results are
  reproducible (and citable). Default model: ``bge-m3`` (BAAI), multilingual
  (100+ languages, strong Arabic).
- A missing embedding model raises HTTP 409 with a one-line setup hint
  ("Run: ollama pull bge-m3") instead of a cryptic 500.
- Vectors are cached per (corpus, line key, model) in SQLite; the cache is
  only reused when the model name matches exactly.
"""
from __future__ import annotations

import json
from dataclasses import dataclass, field

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.logging import get_logger
from stats.service import search_concordance
from storage.models import KwicVectorCache, Token

log = get_logger(__name__)

# Default embedding model (model chain: request → settings → env → this).
DEFAULT_EMBED_MODEL = "bge-m3"

# Mode B scan cap: sentence-level semantic search is capped and the cap is
# reported in the response so users know the scan was bounded.
SENTENCE_SCAN_CAP = 6_000

# How many candidate lines to embed per request in Mode A (the deterministic
# concordancer already caps at 20k; embedding 20k lines would take minutes,
# so the semantic re-rank embeds a bounded, reported subset).
EMBED_CAP = 1_500


class EmbeddingModelError(RuntimeError):
    """Raised when the configured embedding model is not available."""

    def __init__(self, model: str, detail: str):
        self.model = model
        self.detail = detail
        super().__init__(detail)


class EmbeddingModelTimeoutError(RuntimeError):
    """v1.2.3: the embedding call TIMED OUT — raised separately from
    EmbeddingModelError so the API layer can answer 503 embedding_timeout
    ("model is loading / host is slow — try again") instead of the
    misleading 409 embedding_model_missing ("run ollama pull", which is
    wrong advice when the model is installed but cold)."""

    def __init__(self, model: str, detail: str):
        self.model = model
        self.detail = detail
        super().__init__(detail)


def resolve_embed_model(requested: str | None) -> str:
    """Model chain: request → settings (env-prefixed) → default bge-m3."""
    if requested and requested.strip():
        return requested.strip()
    try:
        from app.settings import get_settings

        s = get_settings().embedding_model
        if s and s.strip():
            return s.strip()
    except Exception:  # pragma: no cover — settings always load in practice
        pass
    return DEFAULT_EMBED_MODEL


def _normalize_for_embedding(text: str) -> str:
    """Optional Arabic normalization before embedding (item 4 + item 6)."""
    import re
    import unicodedata

    s = unicodedata.normalize("NFD", text)
    s = "".join(c for c in s if not unicodedata.combining(c))  # strip harakat
    s = re.sub("[\u0623\u0625\u0622]", "\u0627", s)   # أ إ آ → ا
    s = s.replace("\u0629", "\u0647")                 # ة → ه
    s = s.replace("\u0649", "\u064A")                 # ى → ي
    return s


def cosine(a: list[float], b: list[float]) -> float:
    """Pure-Python cosine similarity (no numpy dependency on this path)."""
    if not a or not b or len(a) != len(b):
        return 0.0
    dot = 0.0
    na = 0.0
    nb = 0.0
    for x, y in zip(a, b, strict=False):
        dot += x * y
        na += x * x
        nb += y * y
    if na == 0.0 or nb == 0.0:
        return 0.0
    return dot / ((na ** 0.5) * (nb ** 0.5))


# --------------------------------------------------------------------------- #
# Embedding provider access + 409-grade diagnostics
# --------------------------------------------------------------------------- #


# Timeout for embedding HTTP calls (v1.2.3: was an implicit 30 s that cold
# model loads — bge-m3 ≈ 1.2 GB paged into RAM on first use — blew through,
# and httpx timeout strings are empty so it surfaced as a bare
# "Embedding failed with model 'bge-m3': "). 120 s covers a cold load;
# the provider additionally retries once before giving up.
EMBED_TIMEOUT_S = 120.0

async def _embed_texts(provider, texts: list[str], model: str) -> list[list[float]]:
    """Embed texts via the provider; raise EmbeddingModelError when the model
    is missing and EmbeddingModelTimeoutError when the call times out, so the API layer
    can return HTTP 409 (setup hint) / HTTP 503 (warm-up hint) respectively.

    v1.2.3: uses provider.embed_batch (one batched request for Ollama
    /api/embed) instead of one HTTP call per line — the per-line loop used to
    multiply exposure to the cold-load timeout and hammer /api/embeddings."""
    # Pre-flight: is the model installed? (Ollama list_models hits /api/tags;
    # other providers implement it too.) Cheap 30s-cached call.
    # v1.2.1: compare canonical names — Ollama reports 'bge-m3:latest' for an
    # untagged 'bge-m3' pull, and exact matching used to 409 forever.
    try:
        installed = await provider.list_models()
    except Exception:
        installed = None  # probe failed — let the real embed call decide
    if installed is not None:
        from ai.providers import canonical_model_name

        installed_canon = {canonical_model_name(m) for m in installed}
        if canonical_model_name(model) not in installed_canon:
            raise EmbeddingModelError(
                model,
                f"Embedding model '{model}' is not installed. Run: ollama pull {model}",
            )

    # v1.2.3: batch path when the provider offers it (Ollama does); fall back
    # to the per-text loop for providers/fakes that only implement embed().
    batch = getattr(provider, "embed_batch", None)
    try:
        if batch is not None:
            responses = await batch(texts, model=model, timeout=EMBED_TIMEOUT_S)
        else:
            responses = [
                await provider.embed(t, model=model, timeout=EMBED_TIMEOUT_S) for t in texts
            ]
    except EmbeddingModelTimeoutError:
        # This module's own error — re-raise untouched (defensive).
        raise
    except Exception as e:
        # ai.providers.EmbeddingTimeoutError (timeout after provider-side
        # retries) → this module's EmbeddingModelTimeoutError; everything else
        # keeps the old mapping. The import is aliased so it cannot shadow
        # the module-level class used by the except clause above.
        from ai.providers import EmbeddingTimeoutError as ProviderTimeoutError

        if isinstance(e, ProviderTimeoutError):
            raise EmbeddingModelTimeoutError(model, str(e)) from e
        msg = str(e)
        if "not found" in msg.lower() or "404" in msg:
            raise EmbeddingModelError(
                model,
                f"Embedding model '{model}' is not installed. Run: ollama pull {model}",
            ) from e
        raise EmbeddingModelError(
            model, f"Embedding failed with model '{model}': {msg}"
        ) from e
    return [list(r.vector) for r in responses]


# --------------------------------------------------------------------------- #
# Vector cache (SQLite, kwic_vector_cache)
# --------------------------------------------------------------------------- #


def _line_key(line_id: str, window: int, mode: str) -> str:
    # The key embeds the window so widening it recomputes instead of
    # reusing vectors of a different context span.
    return f"{mode}:{line_id}|w{window}"


async def _load_cached_vectors(
    session: AsyncSession, corpus_id: str, model: str, keys: list[str]
) -> dict[str, list[float]]:
    if not keys:
        return {}
    stmt = select(KwicVectorCache.line_key, KwicVectorCache.vector).where(
        KwicVectorCache.corpus_id == corpus_id,
        KwicVectorCache.model == model,
        KwicVectorCache.line_key.in_(keys),
    )
    rows = (await session.execute(stmt)).all()
    out: dict[str, list[float]] = {}
    for key, vec in rows:
        try:
            v = json.loads(vec) if isinstance(vec, str) else list(vec)
            if isinstance(v, list) and v:
                out[key] = v
        except Exception:
            continue
    return out


async def _store_vectors(
    session: AsyncSession, corpus_id: str, model: str, pairs: dict[str, list[float]]
) -> None:
    if not pairs:
        return
    for key, vec in pairs.items():
        session.add(
            KwicVectorCache(corpus_id=corpus_id, line_key=key, model=model, vector=vec)
        )
    await session.flush()


# --------------------------------------------------------------------------- #
# Main entry point
# --------------------------------------------------------------------------- #


@dataclass
class VectorKwicResult:
    lines: list[dict]           # ConcordanceLine fields + similarity
    total: int                  # candidates scanned/embedded
    scanned: int                # sentences scanned (Mode B) — cap reported
    mode: str                   # "keyword" | "semantic"
    model: str                  # embedding model actually used
    query: dict = field(default_factory=dict)
    note: str = (
        "Similarity is raw cosine similarity between sentence-embedding "
        "vectors (higher = semantically closer to the query). It is not a "
        "confidence score and carries no certainty claim."
    )


async def vector_kwic(
    session: AsyncSession,
    corpus_id: str,
    query: str,
    *,
    provider,
    node: str | None = None,
    level: str = "word",
    regex: bool = False,
    window: int = 6,
    top_k: int = 50,
    min_similarity: float = 0.0,
    normalize_arabic: bool = False,
    model: str | None = None,
    case_sensitive: bool = False,
    document_ids: list[str] | None = None,
) -> VectorKwicResult:
    """Vector KWIC (Anthony 2025): semantic re-ranking / semantic search.

    Mode A — ``node`` given: deterministic KWIC candidates re-ranked by
    cosine similarity between each line's context embedding and the query
    embedding.
    Mode B — ``node`` empty: top-k corpus sentences most similar to the
    query (bounded scan, reported).

    ``provider`` is the embedding-capable model provider (normally the
    engine's Ollama provider, resolved by the API layer so tests can inject
    a deterministic mock).
    """
    embed_model = resolve_embed_model(model)

    query_text = _normalize_for_embedding(query) if normalize_arabic else query

    # ------------------------------------------------------------------ #
    # Mode A: keyword candidates → embed contexts → re-rank
    # ------------------------------------------------------------------ #
    if node and node.strip():
        conc = await search_concordance(
            session, corpus_id, node.strip(),
            level=level, case_sensitive=case_sensitive, regex=regex,
            window=window, limit=EMBED_CAP, offset=0,
            document_ids=document_ids,
        )
        candidates = conc.lines
        keys = [_line_key(l.line_id, window, "kwic") for l in candidates]
        cached = await _load_cached_vectors(session, corpus_id, embed_model, keys)

        to_embed: list[str] = []
        to_embed_keys: list[str] = []
        for line, key in zip(candidates, keys, strict=False):
            if key in cached:
                continue
            ctx = f"{line.left} {line.node} {line.right}".strip()
            if normalize_arabic:
                ctx = _normalize_for_embedding(ctx)
            to_embed.append(ctx)
            to_embed_keys.append(key)

        new_vecs: dict[str, list[float]] = {}
        if to_embed:
            embedded = await _embed_texts(provider, to_embed, embed_model)
            new_vecs = dict(zip(to_embed_keys, embedded, strict=False))
            await _store_vectors(session, corpus_id, embed_model, new_vecs)

        vectors = {**cached, **new_vecs}
        qvec = (await _embed_texts(provider, [query_text], embed_model))[0]

        scored: list[tuple[float, object]] = []
        for line, key in zip(candidates, keys, strict=False):
            vec = vectors.get(key)
            if not vec:
                continue
            sim = cosine(qvec, vec)
            if sim >= min_similarity:
                scored.append((sim, line))
        scored.sort(key=lambda p: p[0], reverse=True)
        scored = scored[:top_k]

        lines_out = []
        for sim, line in scored:
            d = {
                "line_id": line.line_id,
                "document_id": line.document_id,
                "document_filename": line.document_filename,
                "sentence_idx": line.sentence_idx,
                "token_idx": line.token_idx,
                "left": line.left,
                "node": line.node,
                "right": line.right,
                "pos": line.pos,
                "lemma": line.lemma,
                "similarity": round(sim, 4),
            }
            lines_out.append(d)
        return VectorKwicResult(
            lines=lines_out,
            total=len(candidates),
            scanned=len(candidates),
            mode="keyword",
            model=embed_model,
            query={"query": query, "node": node.strip(), "level": level,
                   "window": window, "top_k": top_k, "min_similarity": min_similarity,
                   "normalize_arabic": normalize_arabic},
        )

    # ------------------------------------------------------------------ #
    # Mode B: no node — top-k sentences most similar to the query
    # ------------------------------------------------------------------ #
    from storage.models import AnnotationVersion, Document

    version_id = (
        await session.scalar(
            select(AnnotationVersion.id)
            .where(AnnotationVersion.corpus_id == corpus_id)
            .order_by(AnnotationVersion.created_at.desc())
            .limit(1)
        )
    )
    if not version_id:
        return VectorKwicResult(
            lines=[], total=0, scanned=0, mode="semantic", model=embed_model,
            query={"query": query, "top_k": top_k},
        )

    # Reconstruct sentences from the token table (capped scan, ordered).
    stmt = (
        select(
            Token.document_id,
            Document.filename,
            Token.sentence_idx,
            Token.token_idx,
            Token.text,
            Token.lemma,
            Token.pos,
        )
        .join(Document, Token.document_id == Document.id)
        .where(
            Token.version_id == version_id,
            Token.is_punct == False,  # noqa: E712
            Token.pos != "SPACE",
        )
        .order_by(Token.document_id, Token.sentence_idx, Token.token_idx)
    )
    if document_ids is not None:
        stmt = stmt.where(Token.document_id.in_(document_ids))

    sentences: dict[tuple[str, int], dict] = {}
    scanned = 0
    rows = (await session.execute(stmt)).all()
    for doc_id, fname, sent_idx, tok_idx, text, lemma, pos in rows:
        key = (doc_id, sent_idx)
        entry = sentences.get(key)
        if entry is None:
            if len(sentences) >= SENTENCE_SCAN_CAP:
                continue  # cap the scan; `scanned` reports the honest bound
            entry = sentences[key] = {
                "document_id": doc_id,
                "document_filename": fname,
                "sentence_idx": sent_idx,
                "token_idx": tok_idx,
                "tokens": [],
                "pos": pos or "",
                "lemma": lemma or "",
            }
        entry["tokens"].append(text)
    scanned = len(sentences)

    keys = [_line_key(f"{d}:{s}", 0, "sent") for d, s in sentences]
    cached = await _load_cached_vectors(session, corpus_id, embed_model, keys)

    to_embed: list[str] = []
    to_embed_keys: list[str] = []
    for (key, entry) in zip(keys, sentences.values(), strict=False):
        if key in cached:
            continue
        text = " ".join(entry["tokens"])
        if normalize_arabic:
            text = _normalize_for_embedding(text)
        to_embed.append(text)
        to_embed_keys.append(key)

    new_vecs: dict[str, list[float]] = {}
    if to_embed:
        embedded = await _embed_texts(provider, to_embed, embed_model)
        new_vecs = dict(zip(to_embed_keys, embedded, strict=False))
        await _store_vectors(session, corpus_id, embed_model, new_vecs)

    vectors = {**cached, **new_vecs}
    qvec = (await _embed_texts(provider, [query_text], embed_model))[0]

    scored: list[tuple[float, tuple, dict]] = []
    for (sent_key, entry), key in zip(sentences.items(), keys, strict=False):
        vec = vectors.get(key)
        if not vec:
            continue
        sim = cosine(qvec, vec)
        if sim >= min_similarity:
            scored.append((sim, sent_key, entry))
    scored.sort(key=lambda p: p[0], reverse=True)
    scored = scored[:top_k]

    lines_out = []
    for sim, _key, entry in scored:
        toks = entry["tokens"]
        lines_out.append({
            "line_id": f"{entry['document_id']}:{entry['sentence_idx']}:{entry['token_idx']}",
            "document_id": entry["document_id"],
            "document_filename": entry["document_filename"],
            "sentence_idx": entry["sentence_idx"],
            "token_idx": entry["token_idx"],
            "left": "",
            "node": " ".join(toks),
            "right": "",
            "pos": entry["pos"],
            "lemma": entry["lemma"],
            "similarity": round(sim, 4),
        })
    return VectorKwicResult(
        lines=lines_out,
        total=len(lines_out),
        scanned=scanned,
        mode="semantic",
        model=embed_model,
        query={"query": query, "top_k": top_k, "min_similarity": min_similarity,
               "normalize_arabic": normalize_arabic, "scan_cap": SENTENCE_SCAN_CAP},
    )
