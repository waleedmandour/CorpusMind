"""Tests for the per-version parse-stream LRU cache (v1.2.10).

The classroom burst problem: up to 20 students issue the SAME analysis
queries against the SAME immutable annotation version, and the loader used
to re-read the full token stream from SQLite per request. The cache is a
memo keyed by version id with three invariants that these tests pin:

  1. a warm entry never re-invokes the loader;
  2. capacity evicts least-recently-used entries;
  3. document/corpus deletion (the ONLY in-place token mutation path)
     invalidates everything via invalidate_all().

CORPUSMIND_PARSE_CACHE_ENTRIES=0 disables the cache entirely (escape hatch
for memory-constrained hosts).
"""

from __future__ import annotations

import pytest

from app import version_cache


@pytest.fixture(autouse=True)
def _clean_cache():
    version_cache.reset_for_tests()
    yield
    version_cache.reset_for_tests()


async def test_warm_entry_skips_loader() -> None:
    calls = {"n": 0}

    async def loader() -> list[int]:
        calls["n"] += 1
        return [1, 2, 3]

    a = await version_cache.get_or_load("v1", loader)
    b = await version_cache.get_or_load("v1", loader)
    assert a == b == [1, 2, 3]
    assert calls["n"] == 1, "second get_or_load must be served from cache"


async def test_distinct_versions_load_separately() -> None:
    seen: list[str] = []

    async def loader() -> str:
        seen.append("load")
        return "data"

    await version_cache.get_or_load("v1", loader)
    await version_cache.get_or_load("v2", loader)
    assert len(seen) == 2


async def test_lru_eviction_at_capacity(monkeypatch) -> None:
    monkeypatch.setenv("CORPUSMIND_PARSE_CACHE_ENTRIES", "2")

    async def loader() -> int:
        return 1

    await version_cache.get_or_load("v1", loader)
    await version_cache.get_or_load("v2", loader)
    await version_cache.get_or_load("v1", loader)  # v1 becomes MRU
    await version_cache.get_or_load("v3", loader)  # evicts v2 (LRU)
    await version_cache.get_or_load("v2", loader)  # re-loads; evicts v1
    # At capacity 2 the survivors are exactly the two most recent keys.
    assert set(version_cache._CACHE.keys()) == {"v3", "v2"}


async def test_zero_entries_disables_cache(monkeypatch) -> None:
    monkeypatch.setenv("CORPUSMIND_PARSE_CACHE_ENTRIES", "0")

    calls = {"n": 0}

    async def loader() -> None:
        calls["n"] += 1

    await version_cache.get_or_load("v1", loader)
    await version_cache.get_or_load("v1", loader)
    assert calls["n"] == 2
    assert not version_cache._CACHE


def test_invalidate_all_clears_everything() -> None:
    version_cache._CACHE["v1"] = object()
    version_cache._CACHE["v2"] = object()
    version_cache.invalidate_all()
    assert not version_cache._CACHE


async def test_invalidated_entry_reloads() -> None:
    calls = {"n": 0}

    async def loader() -> int:
        calls["n"] += 1
        return calls["n"]

    first = await version_cache.get_or_load("v1", loader)
    version_cache.invalidate_all()  # document deletion happened
    second = await version_cache.get_or_load("v1", loader)
    assert first == 1
    assert second == 2, "entry must be re-loaded after invalidation"
