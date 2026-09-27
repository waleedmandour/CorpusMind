"""Small LRU cache for per-version token loads (v1.2.10, classroom scale).

WHY
---
Discourse-lens / grammar / dependency endpoints load a corpus version's
full token+parse stream from SQLite into Python structures on EVERY query
(``discourse.service._load_parses``). README §"Practical scale" documents
this honestly (MVP; FTS5 is roadmap). In Student Mode a classroom of up to
20 students runs the SAME analysis queries against the SAME immutable
version in bursts, so the same load was paid 20× for data that never
changed between the first and last request.

WHAT
----
An ``OrderedDict``-based LRU keyed by ``AnnotationVersion.id``. Annotation
versions are append-only (a re-tokenize creates a NEW version id), so a
cached entry can only go stale when the version's token rows are mutated
in place — document deletion cascades its tokens under existing versions.
That is why :func:`invalidate_all` MUST be called from every endpoint that
deletes documents or corpora (api/corpora.py does).

MEMORY BOUND
------------
Each cached entry is the full parse stream: ~50-80 MB per 100K tokens.
Default capacity is 3 versions (~worst case a few hundred MB on huge
corpora); override with ``CORPUSMIND_PARSE_CACHE_ENTRIES`` (0 disables
caching entirely). The Student Mode seat probe already budgets RAM
conservatively (85% of available memory, MAX_STUDENTS=20 ceiling), and
this cache is accounted inside that budget.

CONCURRENCY
-----------
Single uvicorn event loop: dict/OrderedDict operations between awaits are
atomic enough; the loader runs exactly once per key under normal traffic
(two concurrent first-requests may both load — the last write wins and
both callers get correct data; the cache is a memo, not a lock).
"""

from __future__ import annotations

import os
from collections import OrderedDict
from collections.abc import Awaitable, Callable
from functools import lru_cache
from typing import Any

_CACHE: OrderedDict[str, Any] = OrderedDict()


@lru_cache(maxsize=1)
def _max_entries() -> int:
    """Cache capacity; CORPUSMIND_PARSE_CACHE_ENTRIES=0 disables caching."""
    raw = os.environ.get("CORPUSMIND_PARSE_CACHE_ENTRIES", "").strip()
    if raw == "":
        return 3
    try:
        return max(0, int(raw))
    except ValueError:
        return 3


def reset_for_tests() -> None:
    """Clear the cache AND the capacity memo (test isolation)."""
    _CACHE.clear()
    _max_entries.cache_clear()


async def get_or_load(version_id: str, loader: Callable[[], Awaitable[Any]]) -> Any:
    """Return the cached load for ``version_id``, or run ``loader`` once."""
    limit = _max_entries()
    if limit == 0 or not version_id:
        return await loader()
    cached = _CACHE.get(version_id)
    if cached is not None:
        _CACHE.move_to_end(version_id)
        return cached
    value = await loader()
    _CACHE[version_id] = value
    while len(_CACHE) > limit:
        _CACHE.popitem(last=False)
    return value


def invalidate_all() -> None:
    """Drop every cached version load.

    Called after document/corpus deletion, which mutates token rows under
    EXISTING version ids (cascade) — the one stale-cache path. Re-tokenize
    does NOT need this (it creates a new version id).
    """
    _CACHE.clear()
