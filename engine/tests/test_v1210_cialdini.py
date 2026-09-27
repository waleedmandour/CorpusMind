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

import pytest
from httpx import ASGITransport, AsyncClient


@pytest.fixture
async def client():
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
    cid = r.json()["id"]
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
    for cat, cues in CIALDINI_2007.items():
        assert cues, f"category {cat} must not be empty"
        assert all(c == c.lower() for c in cues), "cues are matched lowercased"


async def test_taxonomies_endpoint_lists_cialdini(client) -> None:
    cid = await _setup_corpus(client, PERSUASION_TEXT)
    r = await client.get(f"/api/v1/corpora/{cid}/discourse/taxonomies")
    assert r.status_code == 200
    items = {tx["key"]: tx for tx in r.json()["taxonomies"]}
    assert "cialdini2007" in items
    assert items["cialdini2007"]["name"] == "Cialdini 2007"
    assert set(items["cialdini2007"]["categories"]) == EXPECTED_PRINCIPLES


@pytest.mark.asyncio
async def test_cialdini_lens_counts_all_six_principles(client) -> None:
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
async def test_cialdini_multilabel_sentence_counts_in_both(client) -> None:
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
