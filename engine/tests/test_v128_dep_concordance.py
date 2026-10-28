"""v1.2.8 (review #2) — dependency concordance endpoint.

The syntax panel's per-instance sentence dropdown is replaced by a
KWIC-style concordance table (one row per hit: left | node | right | head |
relation | source). These tests pin the row contract the UI renders.
"""
from __future__ import annotations

import io
import os

import pytest
from httpx import ASGITransport, AsyncClient

os.environ["CORPUSMIND_DB_URL"] = "sqlite+aiosqlite:///:memory:"
os.environ["CORPUSMIND_DATA_DIR"] = "/tmp/cm-test-dep-conc"


@pytest.fixture
async def client():
    from app.settings import get_settings

    get_settings.cache_clear()
    from app.main import app
    from storage.session import dispose_db

    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as ac:
        async with app.router.lifespan_context(app):
            yield ac
    await dispose_db()


async def _setup_corpus(client: AsyncClient, content: bytes, name: str = "C") -> str:
    r = await client.post("/api/v1/projects", json={"name": f"P-{name}", "language": "en"})
    pid = r.json()["id"]
    r = await client.post(f"/api/v1/projects/{pid}/corpora", json={"name": name, "language": "en"})
    cid = r.json()["id"]
    await client.post(
        f"/api/v1/corpora/{cid}/documents",
        files={"files": ("test.txt", io.BytesIO(content), "text/plain")},
    )
    return cid


CONTENT = b"The quick brown fox jumps over the lazy dog. The dog was bitten by a snake."


@pytest.mark.asyncio
async def test_dep_concordance_node_query_row_shape(client):
    """The row contract: left | node | right | head | relation | source."""
    cid = await _setup_corpus(client, CONTENT, name="R")
    r = await client.post(
        f"/api/v1/corpora/{cid}/dep-concordance",
        json={"node_query": "fox", "window": 6},
    )
    assert r.status_code == 200, r.text
    data = r.json()
    assert data["total"] >= 1
    row = next(row for row in data["rows"] if row["node"].lower() == "fox")
    for field in (
        "evidence_id", "document_filename", "doc", "sentence_idx", "token_idx",
        "left", "node", "node_pos", "node_lemma", "relation", "head", "head_pos", "right",
    ):
        assert field in row, f"missing row field: {field}"
    assert row["relation"].startswith("nsubj")
    assert row["head"].lower() == "jumps"
    assert "quick" in row["left"]
    assert "jumps" in row["right"]
    assert row["document_filename"] == "test.txt"
    assert row["evidence_id"].count(":") == 2


@pytest.mark.asyncio
async def test_dep_concordance_relation_filter_matches_subtype(client):
    """Filtering by base relation also catches subtypes (nsubj -> nsubj:pass)."""
    cid = await _setup_corpus(client, CONTENT, name="S")
    r = await client.post(
        f"/api/v1/corpora/{cid}/dep-concordance",
        json={"relation": "nsubj"},
    )
    assert r.status_code == 200
    nodes = {row["node"].lower() for row in r.json()["rows"]}
    assert "fox" in nodes        # plain nsubj
    assert "dog" in nodes        # nsubj:pass of "was bitten"
    # subtype rendered in parentheses on the label (en_core_web_sm stores the
    # legacy spaCy label 'nsubjpass'; the base relation is normalized to nsubj)
    dog_row = next(row for row in r.json()["rows"] if row["node"].lower() == "dog")
    assert "nsubjpass" in dog_row["relation"]
    assert dog_row["relation"].startswith("nsubj")
    assert dog_row["head"].lower() == "bitten"


@pytest.mark.asyncio
async def test_dep_concordance_pos_filter_and_wildcard(client):
    cid = await _setup_corpus(client, CONTENT, name="W")
    r = await client.post(
        f"/api/v1/corpora/{cid}/dep-concordance",
        json={"node_query": "qu*", "pos": "ADJ"},
    )
    assert r.status_code == 200
    data = r.json()
    assert data["total"] >= 1
    assert all(row["node_pos"] == "ADJ" for row in data["rows"])
    assert any(row["node"].lower() == "quick" for row in data["rows"])


@pytest.mark.asyncio
async def test_dep_concordance_requires_some_filter(client):
    cid = await _setup_corpus(client, CONTENT, name="E")
    r = await client.post(f"/api/v1/corpora/{cid}/dep-concordance", json={})
    assert r.status_code == 422


@pytest.mark.asyncio
async def test_dep_concordance_corpus_missing_404(client):
    r = await client.post(
        "/api/v1/corpora/does-not-exist/dep-concordance",
        json={"node_query": "fox"},
    )
    assert r.status_code == 404
