"""Phase 1 integration tests — exercise the full API surface.

Uses httpx's ASGITransport to test the FastAPI app without binding a port.
"""
from __future__ import annotations

import io

import pytest
from httpx import ASGITransport, AsyncClient


@pytest.fixture
async def client():
    """Spawn the FastAPI app with a fresh in-memory DB per test."""
    import os
    os.environ["CORPUSMIND_DB_URL"] = "sqlite+aiosqlite:///:memory:"
    os.environ["CORPUSMIND_DATA_DIR"] = "/tmp/cm-test-data"

    # Reset module-level state so the new env vars take effect
    from app.settings import get_settings
    get_settings.cache_clear()
    from storage.session import _engine, dispose_db
    _engine.clear() if hasattr(_engine, "clear") else None

    from app.main import app
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as ac:
        async with app.router.lifespan_context(app):
            yield ac
    await dispose_db()


@pytest.mark.asyncio
async def test_health(client):
    r = await client.get("/api/v1/health")
    assert r.status_code == 200
    data = r.json()
    assert data["status"] == "ok"
    assert data["engine"] == "corpusmind-engine"


@pytest.mark.asyncio
async def test_create_project_and_corpus(client):
    r = await client.post("/api/v1/projects", json={"name": "Test", "language": "en"})
    assert r.status_code == 200
    pid = r.json()["id"]

    r = await client.post(f"/api/v1/projects/{pid}/corpora", json={"name": "C1", "language": "en"})
    assert r.status_code == 200
    cid = r.json()["id"]

    r = await client.get(f"/api/v1/projects/{pid}/corpora")
    assert r.status_code == 200
    assert len(r.json()) == 1
    assert r.json()[0]["id"] == cid


@pytest.mark.asyncio
async def test_upload_and_concordance(client):
    # Create project + corpus
    r = await client.post("/api/v1/projects", json={"name": "Test", "language": "en"})
    pid = r.json()["id"]
    r = await client.post(f"/api/v1/projects/{pid}/corpora", json={"name": "C", "language": "en"})
    cid = r.json()["id"]

    # Upload a small text file
    content = b"The quick brown fox jumps over the lazy dog. The dog barked. Foxes are clever."
    r = await client.post(
        f"/api/v1/corpora/{cid}/documents",
        files={"files": ("test.txt", io.BytesIO(content), "text/plain")},
    )
    assert r.status_code == 200
    assert len(r.json()) == 1
    doc = r.json()[0]
    assert doc["filename"] == "test.txt"
    assert doc["format"] == "txt"

    # Run a concordance search for "fox" at lemma level
    r = await client.post(
        f"/api/v1/corpora/{cid}/concordance",
        json={"query": "fox", "level": "lemma", "window": 5, "limit": 10},
    )
    assert r.status_code == 200
    data = r.json()
    assert data["total"] >= 2  # "fox" + "Foxes" both lemma "fox"
    assert len(data["lines"]) >= 2
    # Line ID format: doc:sentence:token
    assert ":" in data["lines"][0]["line_id"]


@pytest.mark.asyncio
async def test_frequency(client):
    r = await client.post("/api/v1/projects", json={"name": "T", "language": "en"})
    pid = r.json()["id"]
    r = await client.post(f"/api/v1/projects/{pid}/corpora", json={"name": "C", "language": "en"})
    cid = r.json()["id"]

    content = b"The cat sat. The dog ran. The bird flew. The fish swam."
    await client.post(
        f"/api/v1/corpora/{cid}/documents",
        files={"files": ("test.txt", io.BytesIO(content), "text/plain")},
    )

    r = await client.post(f"/api/v1/corpora/{cid}/frequency", json={"unit": "word", "limit": 10})
    assert r.status_code == 200
    data = r.json()
    assert data["total_tokens"] > 0
    # "the" should be the most frequent
    assert data["rows"][0]["item"].lower() == "the"
    assert data["rows"][0]["freq"] == 4


@pytest.mark.asyncio
async def test_collocations(client):
    r = await client.post("/api/v1/projects", json={"name": "T", "language": "en"})
    pid = r.json()["id"]
    r = await client.post(f"/api/v1/projects/{pid}/corpora", json={"name": "C", "language": "en"})
    cid = r.json()["id"]

    # Repeat the same sentence many times so collocations are statistically strong
    content = b" ".join([b"the quick brown fox jumps"] * 20)
    await client.post(
        f"/api/v1/corpora/{cid}/documents",
        files={"files": ("test.txt", io.BytesIO(content), "text/plain")},
    )

    r = await client.post(
        f"/api/v1/corpora/{cid}/collocations",
        json={"node": "fox", "level": "lemma", "window": 5, "min_freq": 1},
    )
    assert r.status_code == 200
    data = r.json()
    assert len(data["rows"]) > 0
    # "brown" should be a strong collocate of "fox"
    collocates = [row["collocate"] for row in data["rows"]]
    assert "brown" in collocates
    # Every row should have all 7 measures
    for row in data["rows"]:
        for measure in ["mi", "t_score", "log_likelihood", "dice", "log_dice", "chi_square"]:
            assert measure in row, f"missing {measure} in {row}"


@pytest.mark.asyncio
async def test_keyness(client):
    r = await client.post("/api/v1/projects", json={"name": "T", "language": "en"})
    pid = r.json()["id"]
    r = await client.post(f"/api/v1/projects/{pid}/corpora", json={"name": "Target", "language": "en"})
    target = r.json()["id"]
    r = await client.post(f"/api/v1/projects/{pid}/corpora", json={"name": "Ref", "language": "en"})
    ref = r.json()["id"]

    target_content = b" ".join([b"cats dogs birds fish lions tigers bears"] * 5)
    ref_content = b" ".join([b"the of and to a in that is was he for"] * 5)

    await client.post(f"/api/v1/corpora/{target}/documents",
        files={"files": ("t.txt", io.BytesIO(target_content), "text/plain")})
    await client.post(f"/api/v1/corpora/{ref}/documents",
        files={"files": ("r.txt", io.BytesIO(ref_content), "text/plain")})

    r = await client.post(
        f"/api/v1/corpora/{target}/keyness",
        json={"reference_corpus_id": ref, "min_freq": 1, "limit": 20},
    )
    assert r.status_code == 200
    data = r.json()
    assert data["N1"] > 0
    assert data["N2"] > 0
    assert len(data["positive_keywords"]) > 0
    # Every positive keyword must carry BOTH significance AND effect-size measures
    for kw in data["positive_keywords"]:
        assert "log_likelihood" in kw  # significance
        assert "log_ratio" in kw       # effect size
        assert "pct_diff" in kw        # effect size
        assert "odds_ratio" in kw      # effect size


@pytest.mark.asyncio
async def test_export_excel(client):
    r = await client.post("/api/v1/projects", json={"name": "T", "language": "en"})
    pid = r.json()["id"]
    r = await client.post(f"/api/v1/projects/{pid}/corpora", json={"name": "C", "language": "en"})
    cid = r.json()["id"]

    await client.post(
        f"/api/v1/corpora/{cid}/documents",
        files={"files": ("test.txt", io.BytesIO(b"The quick brown fox."), "text/plain")},
    )

    r = await client.post(f"/api/v1/corpora/{cid}/export/frequency.xlsx", json={"unit": "word", "limit": 50})
    assert r.status_code == 200
    assert "spreadsheetml" in r.headers["content-type"]
    assert len(r.content) > 1000  # non-trivial xlsx


@pytest.mark.asyncio
async def test_export_methods_pdf(client):
    r = await client.post("/api/v1/projects", json={"name": "T", "language": "en"})
    pid = r.json()["id"]
    r = await client.post(f"/api/v1/projects/{pid}/corpora", json={"name": "C", "language": "en"})
    cid = r.json()["id"]

    await client.post(
        f"/api/v1/corpora/{cid}/documents",
        files={"files": ("test.txt", io.BytesIO(b"The quick brown fox."), "text/plain")},
    )

    r = await client.get(f"/api/v1/corpora/{cid}/methods.pdf")
    assert r.status_code == 200
    assert r.headers["content-type"] == "application/pdf"
    assert r.content[:4] == b"%PDF"


@pytest.mark.asyncio
async def test_ai_tools_list(client):
    r = await client.get("/api/v1/ai/tools")
    assert r.status_code == 200
    data = r.json()
    tool_names = {t["name"] for t in data["tools"]}
    assert "search_concordance" in tool_names
    assert "get_frequency" in tool_names
    assert "compute_collocations" in tool_names
    assert "compute_keyness" in tool_names
    assert "get_dispersion" in tool_names
    assert "ping" in tool_names
