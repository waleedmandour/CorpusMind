"""Boot-stable (document-id-independent) ordering of analysis tool outputs.

Regression tests for the 2026-10-30 gold-diff findings (G-030..G-039,
G-067..G-072): every tool that truncates or orders tied rows / capped
example lists used to inherit the token scan order — and that scan follows
``document_id``, a fresh hex per boot. The SAME corpus produced different
row orders (and different limit-truncation survivors) on every boot, which
made the frozen grounding gold unreproducible.

Convention now enforced everywhere (mirrors the #43 keyness fix):
count/measure descending, then the CONTENT key ascending; example caps are
applied AFTER a content sort, never during collection.
"""
from __future__ import annotations

import os

import pytest
from httpx import ASGITransport, AsyncClient

os.environ["CORPUSMIND_DB_URL"] = "sqlite+aiosqlite:///:memory:"
os.environ["CORPUSMIND_DATA_DIR"] = "/tmp/cm-test-data"
from app.settings import get_settings  # noqa: E402

get_settings.cache_clear()

# Two bigrams tied at freq 2, plus singletons. With min_freq=2 the tie
# group is exactly {"a b", "x y"} — the deterministic order is ["a b", "x y"]
# and a limit=1 truncation must keep the lexicographically FIRST member.
TIE_TEXT = b"A b c d. A b e f. X y z w. X y q r."


@pytest.fixture
async def client():
    from app.main import app
    from storage.session import dispose_db

    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as ac:
        async with app.router.lifespan_context(app):
            yield ac
    await dispose_db()


async def _setup_corpus(client: AsyncClient, content: bytes, name: str = "Det") -> str:
    r = await client.post("/api/v1/projects", json={"name": name, "language": "en"})
    pid = r.json()["id"]
    r = await client.post(f"/api/v1/projects/{pid}/corpora", json={"name": "C", "language": "en"})
    cid = r.json()["id"]
    await client.post(
        f"/api/v1/corpora/{cid}/documents",
        files={"files": ("test.txt", __import__("io").BytesIO(content), "text/plain")},
    )
    return cid


@pytest.mark.asyncio
async def test_ngram_tie_order_and_truncation(client):
    cid = await _setup_corpus(client, TIE_TEXT)
    r = await client.post(
        f"/api/v1/corpora/{cid}/ngrams", json={"n": 2, "min_freq": 2, "min_range": 1, "limit": 50}
    )
    assert r.status_code == 200
    rows = r.json()["rows"]
    bigrams = [row["ngram"] for row in rows]
    # Both members of the tie group, lexicographically ascending.
    assert bigrams == sorted(bigrams)
    assert len(bigrams) >= 2
    # limit=1: the truncation must keep the lexicographically FIRST tied
    # n-gram — under the old boot-random order either member could win.
    r1 = await client.post(
        f"/api/v1/corpora/{cid}/ngrams", json={"n": 2, "min_freq": 2, "min_range": 1, "limit": 1}
    )
    assert r1.status_code == 200
    assert [row["ngram"] for row in r1.json()["rows"]] == bigrams[:1]


@pytest.mark.asyncio
async def test_ngram_rows_full_order_property(client):
    content = b"The quick brown fox jumps. The lazy dog sleeps. The quick cat runs. A cat naps."
    cid = await _setup_corpus(client, content, name="Det2")
    r = await client.post(
        f"/api/v1/corpora/{cid}/ngrams", json={"n": 2, "min_freq": 1, "min_range": 1, "limit": 50}
    )
    rows = r.json()["rows"]
    keys = [(-row["freq"], row["ngram"]) for row in rows]
    assert keys == sorted(keys)


@pytest.mark.asyncio
async def test_pos_ngrams_order_property(client):
    content = b"The cat sat. The dog ran. The bird flew. A cat sleeps."
    cid = await _setup_corpus(client, content, name="Det3")
    r = await client.post(
        f"/api/v1/corpora/{cid}/pos-analysis", json={"n": 2, "min_freq": 1, "limit": 50}
    )
    assert r.status_code == 200
    data = r.json()
    ngram_keys = [(-row["freq"], row["pattern"]) for row in data["pos_ngrams"]]
    assert ngram_keys == sorted(ngram_keys)
    dist_keys = [(-row["freq"], row["pos"]) for row in data["distribution"]]
    assert dist_keys == sorted(dist_keys)


@pytest.mark.asyncio
async def test_grammar_examples_sorted_and_capped(client):
    content = (
        b"The dog was bitten by a snake. The man walked home. "
        b"The cake was eaten by the kids. The song was sung loudly. "
        b"The ball was thrown far. The house was sold quickly."
    )
    cid = await _setup_corpus(client, content, name="Det4")
    r = await client.post(
        f"/api/v1/corpora/{cid}/grammar", json={"patterns": ["passive_voice"], "limit": 2}
    )
    assert r.status_code == 200
    matches = r.json()["patterns"]["passive_voice"]
    assert len(matches) <= 2
    from discourse.service import _grammar_example_key

    keys = [_grammar_example_key(m) for m in matches]
    assert keys == sorted(keys)


@pytest.mark.asyncio
async def test_discourse_examples_sorted_and_capped(client):
    # "my" (possessive_determiner) appears many times → more candidates
    # than the default limit_examples=5, so the cap is exercised.
    content = (
        b"My goal is clear. My plan works well. My friend agrees. "
        b"My results improve. My team wins. My report is done."
    )
    cid = await _setup_corpus(client, content, name="Det5")
    r = await client.post(f"/api/v1/corpora/{cid}/discourse", json={"taxonomy": "hyland2005"})
    assert r.status_code == 200
    categories = r.json()["categories"]
    from discourse.service import _cue_example_key

    for cat, block in categories.items():
        exs = block.get("examples", [])
        assert len(exs) <= 5, cat
        keys = [_cue_example_key(e) for e in exs]
        assert keys == sorted(keys), cat
