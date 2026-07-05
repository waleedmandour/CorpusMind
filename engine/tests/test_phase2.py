"""Phase 2 integration tests — n-grams, POS, grammar, dependency, discourse,
vocabulary, sentiment, metaphor candidates."""
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


@pytest.mark.asyncio
async def test_ngrams(client):
    content = b"The quick brown fox jumps. The lazy dog sleeps. The quick cat runs."
    cid = await _setup_corpus(client, content)
    r = await client.post(f"/api/v1/corpora/{cid}/ngrams",
        json={"n": 2, "min_freq": 1, "min_range": 1, "limit": 50})
    assert r.status_code == 200
    data = r.json()
    assert data["n"] == 2
    assert data["total_tokens"] > 0
    # "The quick" should appear twice
    ngrams = {row["ngram"]: row["freq"] for row in data["rows"]}
    assert "The quick" in ngrams
    assert ngrams["The quick"] == 2


@pytest.mark.asyncio
async def test_ngrams_respects_min_range(client):
    content = b"The quick brown fox jumps. The lazy dog sleeps."
    cid = await _setup_corpus(client, content)
    # min_range=2 should reject everything (only 1 document)
    r = await client.post(f"/api/v1/corpora/{cid}/ngrams",
        json={"n": 2, "min_freq": 1, "min_range": 2, "limit": 50})
    assert r.status_code == 200
    data = r.json()
    assert len(data["rows"]) == 0


@pytest.mark.asyncio
async def test_pos_analysis(client):
    content = b"The cat sat. The dog ran. The bird flew."
    cid = await _setup_corpus(client, content)
    r = await client.post(f"/api/v1/corpora/{cid}/pos-analysis",
        json={"n": 1, "min_freq": 1, "limit": 20})
    assert r.status_code == 200
    data = r.json()
    assert data["total_tokens"] > 0
    # DET and NOUN should both be present
    pos_tags = {row["pos"] for row in data["distribution"]}
    assert "DET" in pos_tags
    assert "NOUN" in pos_tags


@pytest.mark.asyncio
async def test_pos_bigrams(client):
    content = b"The cat sat. The dog ran."
    cid = await _setup_corpus(client, content)
    r = await client.post(f"/api/v1/corpora/{cid}/pos-analysis",
        json={"n": 2, "min_freq": 1, "limit": 20})
    assert r.status_code == 200
    data = r.json()
    # "DET NOUN" should appear twice
    patterns = {row["pattern"]: row["freq"] for row in data["pos_ngrams"]}
    assert "DET NOUN" in patterns
    assert patterns["DET NOUN"] == 2


@pytest.mark.asyncio
async def test_grammar_passive(client):
    # "The dog was bitten" → passive voice
    content = b"The dog was bitten by a snake. The man walked home."
    cid = await _setup_corpus(client, content)
    r = await client.post(f"/api/v1/corpora/{cid}/grammar",
        json={"patterns": ["passive_voice"], "limit": 10})
    assert r.status_code == 200
    data = r.json()
    assert data["counts"]["passive_voice"] >= 1
    assert len(data["patterns"]["passive_voice"]) >= 1
    assert data["patterns"]["passive_voice"][0]["verb"] == "bitten"


@pytest.mark.asyncio
async def test_grammar_modal(client):
    content = b"You must finish the work. The cat may sleep."
    cid = await _setup_corpus(client, content)
    r = await client.post(f"/api/v1/corpora/{cid}/grammar",
        json={"patterns": ["modal"], "limit": 10})
    assert r.status_code == 200
    data = r.json()
    assert data["counts"]["modal"] >= 2  # "must" + "may"


@pytest.mark.asyncio
async def test_grammar_negation(client):
    content = b"The dog did not bark. The cat was not happy."
    cid = await _setup_corpus(client, content)
    r = await client.post(f"/api/v1/corpora/{cid}/grammar",
        json={"patterns": ["negation"], "limit": 10})
    assert r.status_code == 200
    data = r.json()
    assert data["counts"]["negation"] >= 2


@pytest.mark.asyncio
async def test_dependency_query(client):
    content = b"The cat sat. The dog ran. The bird flew."
    cid = await _setup_corpus(client, content)
    r = await client.post(f"/api/v1/corpora/{cid}/dependencies",
        json={"relation": "nsubj", "limit": 20})
    assert r.status_code == 200
    data = r.json()
    assert data["relation"] == "nsubj"
    # Most common nsubj pair should involve a verb of motion
    assert len(data["rows"]) > 0


@pytest.mark.asyncio
async def test_discourse_analysis(client):
    content = b"However, the results were surprising. Therefore, we conclude that the method works. In other words, the approach is valid."
    cid = await _setup_corpus(client, content)
    r = await client.post(f"/api/v1/corpora/{cid}/discourse")
    assert r.status_code == 200
    data = r.json()
    assert data["taxonomy"] == "Hyland 2005"
    assert data["total_tokens"] > 0
    # Should find "however" (transition), "therefore" (transition), "in other words" (code_gloss)
    cats = data["categories"]
    found_categories = set(cats.keys())
    assert "interactive.transitions" in found_categories
    assert "interactive.code_glosses" in found_categories


@pytest.mark.asyncio
async def test_vocab_profile(client):
    content = b"The research approach was significant. The method demonstrated clear results."
    cid = await _setup_corpus(client, content)
    r = await client.post(f"/api/v1/corpora/{cid}/vocab-profile",
        json={"rare_threshold": 1, "limit": 50})
    assert r.status_code == 200
    data = r.json()
    assert data["total_tokens"] > 0
    bands = {b["band"]: b["freq"] for b in data["bands"]}
    # All 4 bands should be present
    assert set(bands.keys()) == {"K1", "K2_K9", "AWL", "Off-list"}
    # "research", "approach", "method", "significant" should be in AWL
    assert bands["AWL"] > 0


@pytest.mark.asyncio
async def test_sentiment(client):
    content = b"This is a great and wonderful day. The terrible disaster was awful. The meeting was held."
    cid = await _setup_corpus(client, content)
    r = await client.post(f"/api/v1/corpora/{cid}/sentiment")
    assert r.status_code == 200
    data = r.json()
    assert data["total_sentences"] == 3
    assert data["positive"] >= 1   # "great and wonderful"
    assert data["negative"] >= 1   # "terrible disaster awful"
    assert data["neutral"] >= 1    # "meeting was held"


@pytest.mark.asyncio
async def test_metaphor_candidates(client):
    # "Time flows" → verb "flow" with abstract subject "time" → metaphor candidate
    content = b"Time flows like a river. The idea took root. The economy collapsed."
    cid = await _setup_corpus(client, content)
    r = await client.post(f"/api/v1/corpora/{cid}/metaphor-candidates",
        json={"limit": 20})
    assert r.status_code == 200
    data = r.json()
    assert data["pipeline"] == "MIPVU-inspired, LLM-triaged, human-verified"
    assert data["verified_count"] == 0  # nothing verified yet
    # Should find at least one candidate (flow / take / collapse)
    assert len(data["candidates"]) >= 1
    # Each candidate must have a stable evidence_id for citation
    for cand in data["candidates"]:
        assert "evidence_id" in cand
        assert ":" in cand["evidence_id"]


@pytest.mark.asyncio
async def test_grammar_patterns_list(client):
    r = await client.get("/api/v1/corpora/abc/grammar/patterns")
    assert r.status_code == 200
    data = r.json()
    expected = {"passive_voice", "modal", "negation", "relative_clause", "complex_np", "tense"}
    assert set(data["patterns"]) == expected


@pytest.mark.asyncio
async def test_phase2_tools_registered(client):
    """All 8 Phase 2 tools should be in the AI tools list."""
    r = await client.get("/api/v1/ai/tools")
    assert r.status_code == 200
    tool_names = {t["name"] for t in r.json()["tools"]}
    # Phase 1 tools
    for name in ["search_concordance", "get_frequency", "compute_collocations",
                 "compute_keyness", "get_dispersion", "ping"]:
        assert name in tool_names, f"missing Phase 1 tool: {name}"
    # Phase 2 tools
    for name in ["get_ngrams", "get_pos_analysis", "grammar_query", "dependency_query",
                 "discourse_analysis", "vocab_profile", "sentiment", "metaphor_candidates"]:
        assert name in tool_names, f"missing Phase 2 tool: {name}"
