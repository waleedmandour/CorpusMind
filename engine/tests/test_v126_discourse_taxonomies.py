"""v1.2.6 — Discourse page multi-taxonomy tests.

The discourse endpoint accepts an optional taxonomy selector:
  hyland2005 (default, backward compatible) | hallidayhasan1976 |
  martinwhite2005 | usas (CLAWS/USAS top-level semantic tagset).
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
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as ac:
        async with app.router.lifespan_context(app):
            yield ac
    await dispose_db()


async def _setup_corpus(client: AsyncClient, content: bytes, name: str = "Test") -> str:
    """Helper: create project + corpus + upload one document. Returns corpus_id."""
    r = await client.post("/api/v1/projects", json={"name": name, "language": "en"})
    pid = r.json()["id"]
    r = await client.post(f"/api/v1/projects/{pid}/corpora", json={"name": "C", "language": "en"})
    cid = r.json()["id"]
    await client.post(
        f"/api/v1/corpora/{cid}/documents",
        files={"files": ("test.txt", io.BytesIO(content), "text/plain")},
    )
    return cid


CONTENT = (
    b"However, the researchers collected the data very carefully. "
    b"The researchers clearly did not trust the first results. "
    b"Therefore, they repeated the measurements. "
    b"Perhaps it seems surprising, but the findings are valid. "
    b"In other words, the method works."
)


@pytest.mark.asyncio
async def test_discourse_default_bodyless_post_is_hyland(client):
    """Backward compatibility: a bodyless POST keeps the Hyland 2005 lens."""
    cid = await _setup_corpus(client, CONTENT)
    r = await client.post(f"/api/v1/corpora/{cid}/discourse")
    assert r.status_code == 200
    data = r.json()
    assert data["taxonomy"] == "Hyland 2005"
    assert data["taxonomy_key"] == "hyland2005"
    assert "Hyland" in data["citation"]
    cats = data["categories"]
    assert "interactive.transitions" in cats  # however / therefore
    assert "interactive.code_glosses" in cats  # in other words


@pytest.mark.asyncio
async def test_discourse_halliday_hasan_cohesion(client):
    cid = await _setup_corpus(client, CONTENT)
    r = await client.post(
        f"/api/v1/corpora/{cid}/discourse",
        json={"taxonomy": "hallidayhasan1976"},
    )
    assert r.status_code == 200
    data = r.json()
    assert data["taxonomy"] == "Halliday & Hasan 1976"
    assert data["taxonomy_key"] == "hallidayhasan1976"
    assert "Halliday" in data["citation"]
    cats = data["categories"]
    assert "conjunction.adversative" in cats  # however / but
    assert "conjunction.causal" in cats  # therefore
    assert "reference.pronouns" in cats  # they / it
    # lexical cohesion: "researchers" repeats across adjacent sentences
    assert "lexical.repetition" in cats
    assert cats["lexical.repetition"]["freq"] >= 1


@pytest.mark.asyncio
async def test_discourse_martin_white_appraisal(client):
    cid = await _setup_corpus(client, CONTENT)
    r = await client.post(
        f"/api/v1/corpora/{cid}/discourse",
        json={"taxonomy": "martinwhite2005"},
    )
    assert r.status_code == 200
    data = r.json()
    assert data["taxonomy"] == "Martin & White 2005"
    assert data["taxonomy_key"] == "martinwhite2005"
    cats = data["categories"]
    assert "engagement.deny" in cats  # not
    assert "engagement.proclaim" in cats  # clearly
    assert "engagement.entertain" in cats  # perhaps
    assert "graduation.force" in cats  # very


@pytest.mark.asyncio
async def test_discourse_usas_semantic_tagset(client):
    """The CLAWS/USAS lens reuses the bundled top-level lexicon."""
    cid = await _setup_corpus(client, CONTENT)
    r = await client.post(
        f"/api/v1/corpora/{cid}/discourse",
        json={"taxonomy": "usas"},
    )
    assert r.status_code == 200
    data = r.json()
    assert data["taxonomy_key"] == "usas"
    assert data["taxonomy"] == "CLAWS/USAS semantic tagset (top-level)"
    assert "UCREL" in data["citation"]
    assert data["total_tokens"] > 0
    assert len(data["categories"]) > 0
    for cat, info in data["categories"].items():
        assert len(cat) == 1  # top-level USAS letter categories
        assert info["label"]
        assert info["group"]  # discourse-functional grouping
    assert data["unmatched_percent"] is not None
    assert 0.0 <= data["unmatched_percent"] <= 100.0


@pytest.mark.asyncio
async def test_discourse_unknown_taxonomy_400(client):
    cid = await _setup_corpus(client, CONTENT)
    r = await client.post(
        f"/api/v1/corpora/{cid}/discourse",
        json={"taxonomy": "not-a-taxonomy"},
    )
    assert r.status_code == 400
    assert "Supported" in r.json()["detail"]


@pytest.mark.asyncio
async def test_discourse_taxonomies_registry(client):
    cid = await _setup_corpus(client, CONTENT)
    r = await client.get(f"/api/v1/corpora/{cid}/discourse/taxonomies")
    assert r.status_code == 200
    taxonomies = r.json()["taxonomies"]
    keys = [t["key"] for t in taxonomies]
    assert keys == ["hyland2005", "hallidayhasan1976", "martinwhite2005", "usas"]
    for t in taxonomies:
        assert t["name"]
        assert t["citation"]
        assert isinstance(t["categories"], list) and t["categories"]


@pytest.mark.asyncio
async def test_discourse_usas_missing_lexicon_503(client):
    """A language with no bundled USAS lexicon degrades to an honest 503."""
    r = await client.post("/api/v1/projects", json={"name": "Fr", "language": "fr"})
    pid = r.json()["id"]
    r = await client.post(f"/api/v1/projects/{pid}/corpora", json={"name": "C", "language": "fr"})
    cid = r.json()["id"]
    await client.post(
        f"/api/v1/corpora/{cid}/documents",
        files={"files": ("f.txt", io.BytesIO(b"Le chat dort. Le chien mange."), "text/plain")},
    )
    r = await client.post(f"/api/v1/corpora/{cid}/discourse", json={"taxonomy": "usas"})
    assert r.status_code == 503
    assert "lexicon" in r.json()["detail"]
