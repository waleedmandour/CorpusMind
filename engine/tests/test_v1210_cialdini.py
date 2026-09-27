"""v1.2.10 — Cialdini 2007 persuasion cue lens (7th discourse lens).

Scope pinned by the approved plan: Influence, Revised Edition 2007,
chapters 2-7 only (reciprocation, commitment & consistency, social proof,
liking, authority, scarcity). The 2021 seventh principle (Unity) is
explicitly NOT covered — the registry citation says so and the tests pin
it. The lens rides the generic cue machinery (multi-word = sentence
substring, single-word = exact token match), so it inherits the v1.2.7
keyness battery, DP dispersion and comparison support for free.
"""
from __future__ import annotations

import io
import os
from collections.abc import AsyncIterator

import pytest
from httpx import ASGITransport, AsyncClient


@pytest.fixture
async def client() -> AsyncIterator[AsyncClient]:
    os.environ["CORPUSMIND_DB_URL"] = "sqlite+aiosqlite:///:memory:"
    os.environ["CORPUSMIND_DATA_DIR"] = "/tmp/cm-test-data"
    from app.settings import get_settings

    get_settings.cache_clear()
    from app.main import app
    from storage.session import dispose_db

    async with AsyncClient(
        transport=ASGITransport(app=app), base_url="http://test"
    ) as ac:
        async with app.router.lifespan_context(app):
            yield ac
    await dispose_db()


async def _setup_corpus(client: AsyncClient, content: bytes, name: str = "Cialdini") -> str:
    r = await client.post("/api/v1/projects", json={"name": name, "language": "en"})
    pid = r.json()["id"]
    r = await client.post(
        f"/api/v1/projects/{pid}/corpora", json={"name": "C", "language": "en"}
    )
    cid: str = r.json()["id"]
    await client.post(
        f"/api/v1/corpora/{cid}/documents",
        files={"files": ("persuasion.txt", io.BytesIO(content), "text/plain")},
    )
    return cid


# One sentence per principle so each category gets at least one hit; s1 is
# deliberately multi-label (free + act now) to pin that a sentence counts
# in EVERY category it matches, not just the first.
PERSUASION_TEXT = (
    b"This free trial comes with no obligation, so act now while supplies last. "
    b"Take a stand and make a pledge; people who commit stay consistent. "
    b"Everyone knows it: most people choose the best-selling option. "
    b"Just like you, your friend will enjoy this great taste. "
    b"Research shows that leading experts and doctors recommend it. "
    b"Limited time only: the offer ends soon, so this is your last chance. "
    b"The photosynthesis of chlorophyll requires sunlight and water. "
)


EXPECTED_PRINCIPLES = {
    "reciprocation",
    "commitment_consistency",
    "social_proof",
    "liking",
    "authority",
    "scarcity",
}


def test_registry_entry_shape() -> None:
    from discourse.service import CIALDINI_2007, DISCOURSE_TAXONOMIES

    spec = DISCOURSE_TAXONOMIES["cialdini2007"]
    assert spec["name"] == "Cialdini 2007"
    # Citation pins the edition and the chapter scope; Unity is excluded.
    assert "2007" in spec["citation"]
    assert "Revised Edition" in spec["citation"]
    assert "Chapters 2-7" in spec["citation"]
    assert "not covered" in spec["citation"]
    assert set(CIALDINI_2007) == EXPECTED_PRINCIPLES
    # The Unity exclusion is pinned NEGATIVELY, not just by the positive
    # six-principle set above: exactly six categories, no 'unity' category,
    # and no Unity-coded registry key (e.g. a future 'cialdini2021') may
    # appear unless a review deliberately changes this test.
    assert len(CIALDINI_2007) == 6
    assert "unity" not in {c.lower() for c in CIALDINI_2007}
    assert not any("unity" in c.lower() for c in CIALDINI_2007)
    assert "cialdini2021" not in DISCOURSE_TAXONOMIES
    assert not any("unity" in key for key in DISCOURSE_TAXONOMIES)
    # Language-coverage badge traceability: declared in the registry, not
    # hardcoded in the UI (same contract as hyland2005/usas below).
    assert spec["languages"] == ["en"]
    for cat, cues in CIALDINI_2007.items():
        assert cues, f"category {cat} must not be empty"
        assert all(c == c.lower() for c in cues), "cues are matched lowercased"


async def test_taxonomies_endpoint_lists_cialdini(client: AsyncClient) -> None:
    cid = await _setup_corpus(client, PERSUASION_TEXT)
    r = await client.get(f"/api/v1/corpora/{cid}/discourse/taxonomies")
    assert r.status_code == 200
    items = {tx["key"]: tx for tx in r.json()["taxonomies"]}
    assert "cialdini2007" in items
    assert items["cialdini2007"]["name"] == "Cialdini 2007"
    assert set(items["cialdini2007"]["categories"]) == EXPECTED_PRINCIPLES
    # Language coverage flows from the registry through the API so the UI
    # badge is traceable: English-only cue lenses vs the bilingual USAS.
    assert items["cialdini2007"]["languages"] == ["en"]
    assert items["hyland2005"]["languages"] == ["en"]
    assert items["martinwhite2005"]["languages"] == ["en"]
    assert items["hallidayhasan1976"]["languages"] == ["en"]
    assert items["usas"]["languages"] == ["en", "ar"]


@pytest.mark.asyncio
async def test_cialdini_lens_counts_all_six_principles(client: AsyncClient) -> None:
    cid = await _setup_corpus(client, PERSUASION_TEXT)
    r = await client.post(
        f"/api/v1/corpora/{cid}/discourse", json={"taxonomy": "cialdini2007"}
    )
    assert r.status_code == 200
    data = r.json()
    assert data["taxonomy"] == "Cialdini 2007"
    assert data["taxonomy_key"] == "cialdini2007"
    assert "Cialdini" in data["citation"]
    cats = data["categories"]
    for principle in EXPECTED_PRINCIPLES:
        assert principle in cats, f"{principle} missing from response"
        assert cats[principle]["freq"] >= 1, f"{principle} scored zero"
    # The neutral science sentence must not be forced into a category: no
    # example may come from it (multi-cue counting per sentence is expected
    # and fine — the tripwire is specifically false positives on neutral text).
    for principle in EXPECTED_PRINCIPLES:
        for e in cats[principle]["examples"]:
            assert "photosynthesis" not in e["sentence_preview"], (
                f"neutral sentence matched under {principle}"
            )


@pytest.mark.asyncio
async def test_cialdini_multilabel_sentence_counts_in_both(client: AsyncClient) -> None:
    """s1 matches reciprocation (free trial, no obligation) AND scarcity
    (act now, while supplies last). Cue counting is multi-label by
    construction — the sentence must add to BOTH counters."""
    cid = await _setup_corpus(client, PERSUASION_TEXT)
    r = await client.post(
        f"/api/v1/corpora/{cid}/discourse", json={"taxonomy": "cialdini2007"}
    )
    data = r.json()
    cats = data["categories"]
    recip_examples = cats["reciprocation"]["examples"]
    scarc_examples = cats["scarcity"]["examples"]
    assert any("free trial" in e["sentence_preview"] for e in recip_examples)
    assert any("act now" in e["sentence_preview"] for e in scarc_examples)
    assert cats["reciprocation"]["freq"] >= 1
    assert cats["scarcity"]["freq"] >= 1


@pytest.mark.asyncio
async def test_cialdini_cooccurrence_counts_shared_sentences(client: AsyncClient) -> None:
    """Co-occurrence is a GENERIC cue-lens capability exposed on the same
    response as the frequency counts. In the seed text only s1 matches two
    categories (reciprocation: 'free'/'trial'/'no obligation'; scarcity:
    'act now'/'while supplies last') — exactly that unordered pair must be
    reported with sentence count 1, canonical alphabetical ordering, and
    no self-pairs or phantom categories."""
    cid = await _setup_corpus(client, PERSUASION_TEXT)
    r = await client.post(
        f"/api/v1/corpora/{cid}/discourse", json={"taxonomy": "cialdini2007"}
    )
    assert r.status_code == 200
    data = r.json()
    assert data["cooccurrence"] is not None
    pairs = {(p["a"], p["b"]): p["sentences"] for p in data["cooccurrence"]}
    assert pairs.get(("reciprocation", "scarcity")) == 1
    for (a, b), n in pairs.items():
        assert a < b, "pair keys must be canonically ordered"
        assert a in EXPECTED_PRINCIPLES and b in EXPECTED_PRINCIPLES
        assert n >= 1
    # Deterministic serialization: count desc, then alphabetical.
    counts_in_order = [p["sentences"] for p in data["cooccurrence"]]
    assert counts_in_order == sorted(counts_in_order, reverse=True)


@pytest.mark.asyncio
async def test_cooccurrence_is_generic_across_cue_lenses(client: AsyncClient) -> None:
    """The response field is populated for the PRE-EXISTING cue lenses too
    (hyland2005) — this is registry-wide capability, not Cialdini sugar.
    The lexicon/parse/persuasion lenses legitimately return null."""
    cid = await _setup_corpus(client, PERSUASION_TEXT, name="Generic")
    r = await client.post(
        f"/api/v1/corpora/{cid}/discourse", json={"taxonomy": "hyland2005"}
    )
    assert r.status_code == 200
    assert isinstance(r.json()["cooccurrence"], list)
    r2 = await client.post(
        f"/api/v1/corpora/{cid}/discourse", json={"taxonomy": "usas"}
    )
    assert r2.status_code == 200
    assert r2.json()["cooccurrence"] is None
