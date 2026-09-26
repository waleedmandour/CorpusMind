"""v1.2.7 (§4) — Persuasion Index lens (persuasion_gong2026).

The persuasion-index package (Wang & Gong 2026, Apache-2.0) is an OPTIONAL
dependency: positive-path tests skip when it is absent, and the API degrades
to an honest 503 rather than a crash.
"""
from __future__ import annotations

import io
import os
import sys

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


async def _setup_corpus(client: AsyncClient, docs: list[bytes], name: str = "C") -> str:
    r = await client.post("/api/v1/projects", json={"name": f"P-{name}", "language": "en"})
    pid = r.json()["id"]
    r = await client.post(f"/api/v1/projects/{pid}/corpora", json={"name": name, "language": "en"})
    cid = r.json()["id"]
    for i, content in enumerate(docs):
        await client.post(
            f"/api/v1/corpora/{cid}/documents",
            files={"files": (f"d{i}.txt", io.BytesIO(content), "text/plain")},
        )
    return cid


PERSUASIVE = (
    b"Scientists have proven beyond doubt that emissions rise every year. "
    b"Therefore, we must act now, because climate change threatens everyone. "
    b"Join us today and fight for our shared future!"
)

pi = pytest.importorskip("persuasion_index", reason="persuasion-index optional dependency not installed")


@pytest.mark.asyncio
async def test_persuasion_lens_fifteen_dimensions(client):
    cid = await _setup_corpus(client, [PERSUASIVE], name="PI")
    r = await client.post(f"/api/v1/corpora/{cid}/discourse", json={"taxonomy": "persuasion_gong2026"})
    assert r.status_code == 200
    data = r.json()
    assert data["taxonomy_key"] == "persuasion_gong2026"
    assert "persuasion-index" in data["citation"]
    assert data["scored_documents"] == 1
    cats = data["categories"]
    assert len(cats) == 15  # the full dimension inventory
    families = {info["group"] for info in cats.values()}
    assert families == {"logos", "ethos", "pathos"}
    # v1.2.8 (review #1): the grouping must mirror the package's own
    # inventory exactly — Logos 5, Ethos 4, Pathos 6 — with Style in ethos
    # and Engagement/Reciprocity in pathos. A silent misfile is a bug.
    by_family = {f: [k for k, info in cats.items() if info["group"] == f] for f in families}
    assert len(by_family["logos"]) == 5
    assert len(by_family["ethos"]) == 4
    assert len(by_family["pathos"]) == 6
    assert "pi.ethos.Style" in cats
    assert "pi.pathos.Engagement" in cats
    assert "pi.pathos.Reciprocity" in cats
    assert "pi.ethos.Engagement" not in cats
    for key, info in cats.items():
        assert key.startswith("pi.")
        assert 0.0 <= info["freq"] <= 100.0
        assert info["per_million"] is None  # scores, not token frequencies
        assert info["dp"] is None
    # a strongly argumentative text scores non-zero on at least one logos dim
    logos_scores = [info["freq"] for k, info in cats.items() if ".logos." in k]
    assert any(s > 0 for s in logos_scores)


@pytest.mark.asyncio
async def test_persuasion_lens_score_batch_multi_doc(client):
    """v1.2.8 (review #3): multi-document corpora go through the package's
    index-preserving score_batch path; every document counts."""
    cid = await _setup_corpus(client, [PERSUASIVE, PERSUASIVE, b"Birds fly south in winter."], name="B")
    r = await client.post(f"/api/v1/corpora/{cid}/discourse", json={"taxonomy": "persuasion_gong2026"})
    assert r.status_code == 200
    data = r.json()
    assert data["scored_documents"] == 3
    # all 15 dimensions present even when a document scores zeros
    assert len(data["categories"]) == 15


@pytest.mark.asyncio
async def test_persuasion_lens_registry(client):
    cid = await _setup_corpus(client, [PERSUASIVE], name="PI")
    r = await client.get(f"/api/v1/corpora/{cid}/discourse/taxonomies")
    keys = [t["key"] for t in r.json()["taxonomies"]]
    assert keys == [
        "hyland2005", "hallidayhasan1976", "martinwhite2005",
        "usas", "sfg_hm2014", "persuasion_gong2026",
    ]


@pytest.mark.asyncio
async def test_persuasion_lens_rejects_compare_corpus(client):
    """Document-level scores cannot key against a second corpus — explicit 400."""
    cid_a = await _setup_corpus(client, [PERSUASIVE], name="A")
    cid_b = await _setup_corpus(client, [PERSUASIVE], name="B")
    r = await client.post(
        f"/api/v1/corpora/{cid_a}/discourse",
        json={"taxonomy": "persuasion_gong2026", "compare_corpus_id": cid_b},
    )
    assert r.status_code == 400
    assert "persuasion" in r.json()["detail"].lower()


@pytest.mark.asyncio
async def test_persuasion_lens_missing_package_503(client, monkeypatch):
    """Without the optional package the API answers 503 with an install hint."""
    cid = await _setup_corpus(client, [PERSUASIVE], name="X")
    monkeypatch.setitem(sys.modules, "persuasion_index", None)
    r = await client.post(f"/api/v1/corpora/{cid}/discourse", json={"taxonomy": "persuasion_gong2026"})
    assert r.status_code == 503
    assert "pip install" in r.json()["detail"]


@pytest.mark.asyncio
async def test_persuasion_health_endpoint(client):
    """v1.2.8 (review #2): the health endpoint mirrors `doctor --json` and is
    a 200 status payload — installed + which resources are active/degraded."""
    r = await client.get("/api/v1/discourse/persuasion/health")
    assert r.status_code == 200
    data = r.json()
    # persuasion-index is installed in the dev/CI environment ([dev] extra)
    assert data["installed"] is True
    assert data["version"]  # e.g. "0.3.0"
    assert data["resources_required"] is False  # ships on bundled lexicons
    assert isinstance(data["resources"], dict)
    for name in ("spacy_model", "single_word_concreteness", "multiword_concreteness", "liwc", "nrc_vad"):
        assert name in data["resources"]
        res = data["resources"][name]
        assert isinstance(res["available"], bool)
        if not res["available"]:
            assert res["detail"]
            assert res["features"]
    assert isinstance(data["missing"], list)
    assert data["complete"] == (len(data["missing"]) == 0)


@pytest.mark.asyncio
async def test_persuasion_health_endpoint_missing_package(client, monkeypatch):
    """Without the package the health endpoint stays 200 but reports it."""
    monkeypatch.setitem(sys.modules, "persuasion_index", None)
    r = await client.get("/api/v1/discourse/persuasion/health")
    assert r.status_code == 200
    data = r.json()
    assert data["installed"] is False
    assert "pip install" in data["install_hint"]
