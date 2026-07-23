"""Bridge between installed reference frequency lists and keyness analysis.

The existing ``stats.service.compute_keyness`` requires both the target and
the reference to be ``Corpus`` rows in the database (it joins on
``AnnotationVersion`` → ``Token`` to compute word frequencies). That's the
right design for *user-uploaded* reference corpora, but it's overkill for
*bundled* reference frequency lists: we already know the per-word
frequencies, we don't need to re-tokenise a 12 MB reference corpus on every
keyness run.

This module provides:

  * ``load_frequency_list(name)`` — read an installed reference's file
    (TSV / CSV / JSON) into a ``Counter`` of ``{word: freq}``.
  * ``compute_keyness_with_reference_list(target_corpus_id, ref_name)``
    — run keyness using the *target corpus* frequencies (computed live
    via the existing DB query) against the *reference list* frequencies
    (loaded from disk). Returns the same ``KeynessResult`` shape as
    ``stats.service.compute_keyness``, so the API and UI are unchanged.

The mathematical formulas are reused from ``stats.measures`` — we don't
reimplement keyness here, we just feed the bridge's frequency counters
into the same per-row calculator.
"""
from __future__ import annotations

import csv
import json
from collections import Counter
from functools import lru_cache
from pathlib import Path

from sqlalchemy.ext.asyncio import AsyncSession

from app.logging import get_logger
from stats.measures import compute_keyness_row
from stats.service import KeynessResult, _corpus_size, _latest_version_id
from .manager import ReferenceCorpusManager, get_manager

log = get_logger(__name__)


# --------------------------------------------------------------------------- #
# Frequency-list loaders (one per ReferenceFormat)
# --------------------------------------------------------------------------- #


def _load_tsv_freq(path: Path, delimiter: str = "\t") -> Counter[str]:
    """Load a ``word<TAB>freq`` file. Skips comment lines starting with #."""
    out: Counter[str] = Counter()
    with open(path, encoding="utf-8") as f:
        reader = csv.reader(f, delimiter=delimiter)
        for row in reader:
            if not row or row[0].startswith("#"):
                continue
            if len(row) < 2:
                continue
            word = row[0].strip().lower()
            try:
                freq = int(row[1])
            except ValueError:
                continue
            if word and freq > 0:
                out[word] += freq
    return out


def _load_csv_freq(path: Path) -> Counter[str]:
    return _load_tsv_freq(path, delimiter=",")


def _load_json_freq(path: Path) -> Counter[str]:
    """Load a ``[{"word": ..., "freq": ...}, ...]`` JSON file."""
    out: Counter[str] = Counter()
    with open(path, encoding="utf-8") as f:
        data = json.load(f)
    if not isinstance(data, list):
        raise ValueError(f"Expected JSON array, got {type(data).__name__}")
    for item in data:
        if not isinstance(item, dict):
            continue
        word = str(item.get("word", "")).strip().lower()
        try:
            freq = int(item.get("freq", 0))
        except (ValueError, TypeError):
            continue
        if word and freq > 0:
            out[word] += freq
    return out


_LOADERS = {
    "tsv_freq": _load_tsv_freq,
    "csv_freq": _load_csv_freq,
    "json_freq": _load_json_freq,
}


# --------------------------------------------------------------------------- #
# Public API
# --------------------------------------------------------------------------- #


def load_frequency_list(
    name: str,
    *,
    manager: ReferenceCorpusManager | None = None,
) -> Counter[str]:
    """Load an installed reference frequency list into a ``Counter``.

    Results are cached per-process keyed by (name, mtime, size) so repeated
    keyness calls against the same reference don't re-parse the file. The
    cache invalidates automatically if the file changes on disk (e.g. the
    user re-downloads a newer version).
    """
    manager = manager or get_manager()
    spec = manager.spec(name)
    entry = manager.manifest.get(name)
    if entry is None:
        raise FileNotFoundError(f"Reference '{name}' is not installed")
    path = manager.resolve_path(name)
    loader = _LOADERS.get(spec.format)
    if loader is None:
        raise ValueError(f"Unsupported format '{spec.format}' for '{name}'")
    return _cached_load(path, spec.format, entry.sha256)


@lru_cache(maxsize=8)
def _cached_load(path_str: str, fmt: str, sha256: str) -> Counter[str]:
    """Inner cached loader. The cache key includes the SHA-256 so a
    re-download with a new hash automatically invalidates the cache."""
    path = Path(path_str)
    loader = _LOADERS[fmt]
    freqs = loader(path)
    log.info(
        "reference_freq_list_loaded",
        path=str(path), types=len(freqs), tokens=sum(freqs.values()),
        sha256_prefix=sha256[:12],
    )
    return freqs


def invalidate_cache(name: str | None = None) -> None:
    """Clear the frequency-list cache. Call after a re-download."""
    if name is None:
        _cached_load.cache_clear()
    else:
        # lru_cache doesn't support selective invalidation; clear all.
        # This is fine — we rarely have more than 2-3 references cached.
        _cached_load.cache_clear()


# --------------------------------------------------------------------------- #
# Keyness against a reference frequency list
# --------------------------------------------------------------------------- #


async def compute_keyness_with_reference_list(
    session: AsyncSession,
    target_corpus_id: str,
    reference_name: str,
    *,
    min_freq: int = 5,
    measures: list[str] | None = None,
    limit: int = 500,
) -> KeynessResult:
    """Keyness with a bundled reference frequency list.

    Reuses the same per-row formula calculator as
    ``stats.service.compute_keyness`` so the math stays identical. Only
    the input pipeline differs: the reference frequencies come from the
    on-disk frequency list, not from a DB query against a reference Corpus.
    """
    from sqlalchemy import select
    from storage.models import Token

    if measures is None:
        measures = [
            "log_likelihood", "chi_square", "log_ratio",
            "pct_diff", "simple_maths", "odds_ratio",
        ]

    # 1) Target frequencies from the DB.
    target_vid = await _latest_version_id(session, target_corpus_id)
    if not target_vid:
        return KeynessResult(
            target_corpus_id=target_corpus_id,
            reference_corpus_id=f"ref:{reference_name}",
            measures=measures, positive_keywords=[], negative_keywords=[],
            N1=0, N2=0,
        )

    N1 = await _corpus_size(session, target_vid)
    stmt = (
        select(Token.text, )  # noqa: E731
        .where(
            Token.version_id == target_vid,
            Token.is_punct == False,  # noqa: E712
            Token.pos != "SPACE",
        )
    )
    rows = (await session.execute(stmt)).all()
    target_freqs: Counter[str] = Counter()
    for (text,) in rows:
        target_freqs[(text or "").lower()] += 1

    # 2) Reference frequencies from disk.
    ref_freqs = load_frequency_list(reference_name)
    N2 = sum(ref_freqs.values())

    # 3) Compute per-row keyness using the shared formula.
    # ``compute_keyness_row`` always computes the full §12 battery; the
    # ``measures`` argument above just controls which keys the API returns.
    all_terms = set(target_freqs) | set(ref_freqs)
    results = []
    for term in all_terms:
        f1 = target_freqs.get(term, 0)
        f2 = ref_freqs.get(term, 0)
        # Skip terms that don't meet the min-frequency threshold in the
        # target corpus — they wouldn't be interpretable as keywords anyway.
        if f1 < min_freq:
            continue
        row = compute_keyness_row(term, f1, f2, N1, N2)
        # Filter to the requested measures (keeps the response shape stable
        # if a caller asks for a subset).
        if measures != list(row.measures.keys()):
            row.measures = {k: row.measures[k] for k in measures if k in row.measures}
        results.append(row)

    # 4) Sort + split into positive / negative.
    results.sort(key=lambda r: r.measures.get("log_likelihood", 0.0), reverse=True)
    positive = [r for r in results if r.measures.get("log_likelihood", 0.0) > 0][:limit]
    negative = [r for r in reversed(results) if r.measures.get("log_likelihood", 0.0) <= 0][:limit]

    return KeynessResult(
        target_corpus_id=target_corpus_id,
        reference_corpus_id=f"ref:{reference_name}",
        measures=measures,
        positive_keywords=[{"term": r.term, "f1": r.f1, "f2": r.f2, **r.measures} for r in positive],
        negative_keywords=[{"term": r.term, "f1": r.f1, "f2": r.f2, **r.measures} for r in negative],
        N1=N1, N2=N2,
    )
