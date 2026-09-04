"""Regression tests for the post-v1.0.0 Priority-0 fixes (Issues 1 & 2).

Issue 1: POST /corpora/{cid}/recompile was a silent no-op — it referenced
``parsed.tokens`` (an attribute that does not exist on ParsedDocument) inside
a broad try/except, so every document failed and the endpoint returned
HTTP 200 with ``recompiled: 0``.

Issue 2: subcorpus filtering was broken (``session.get_sync`` does not exist
on AsyncSession) and not wired to any analysis endpoint. These tests pin the
wiring: concordance / frequency / collocations / keyness all accept an
optional ``subcorpus_id`` and actually restrict results.
"""
from __future__ import annotations

import io

import pytest
from httpx import ASGITransport, AsyncClient

NEWS_TEXT = (
    "Officials announced a new policy on climate. The policy targets emissions. "
    "Reporters covered the announcement extensively."
)
FICTION_TEXT = (
    "The old sailor watched the sea. He remembered storms from his youth. "
    "The gulls cried over the harbour."
)


@pytest.fixture
async def client():
    """Spawn the FastAPI app with a fresh in-memory DB per test."""
    import os
    os.environ["CORPUSMIND_DB_URL"] = "sqlite+aiosqlite:///:memory:"
    os.environ["CORPUSMIND_DATA_DIR"] = "/tmp/cm-test-data"

    from app.settings import get_settings
    get_settings.cache_clear()
    from storage.session import _engine, dispose_db
    _engine.clear() if hasattr(_engine, "clear") else None

    from app.main import app
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as ac:
        async with app.router.lifespan_context(app):
            yield ac
    await dispose_db()


async def _make_corpus_with_two_tagged_docs(client) -> tuple[str, str, str]:
    """Create project + corpus, upload two docs, tag them genre=news / genre=fiction.

    Returns (cid, news_doc_id, fiction_doc_id).
    """
    r = await client.post("/api/v1/projects", json={"name": "P", "language": "en"})
    pid = r.json()["id"]
    r = await client.post(f"/api/v1/projects/{pid}/corpora", json={"name": "C", "language": "en"})
    cid = r.json()["id"]

    r = await client.post(
        f"/api/v1/corpora/{cid}/documents",
        files={"files": ("news.txt", io.BytesIO(NEWS_TEXT.encode()), "text/plain")},
    )
    assert r.status_code == 200, r.text
    news_doc_id = r.json()[0]["id"]

    r = await client.post(
        f"/api/v1/corpora/{cid}/documents",
        files={"files": ("fiction.txt", io.BytesIO(FICTION_TEXT.encode()), "text/plain")},
    )
    assert r.status_code == 200, r.text
    fiction_doc_id = r.json()[0]["id"]

    # Tag metadata so the subcorpus filter can distinguish the documents
    r = await client.patch(
        f"/api/v1/corpora/{cid}/documents/{news_doc_id}/meta",
        json={"meta": {"genre": "news"}},
    )
    assert r.status_code == 200, r.text
    r = await client.patch(
        f"/api/v1/corpora/{cid}/documents/{fiction_doc_id}/meta",
        json={"meta": {"genre": "fiction"}},
    )
    assert r.status_code == 200, r.text
    return cid, news_doc_id, fiction_doc_id


async def _make_subcorpus(client, cid: str, criteria: dict) -> str:
    r = await client.post(
        f"/api/v1/corpora/{cid}/subcorpora",
        json={"name": "News only", "filter_criteria": criteria},
    )
    assert r.status_code == 200, r.text
    return r.json()["id"]


# --------------------------------------------------------------------------- #
# Issue 1 — recompile actually recompiles
# --------------------------------------------------------------------------- #


@pytest.mark.asyncio
async def test_issue1_recompile_recompiles_all_documents(client):
    cid, _news, _fiction = await _make_corpus_with_two_tagged_docs(client)

    r = await client.post(f"/api/v1/corpora/{cid}/recompile")
    assert r.status_code == 200, r.text
    data = r.json()
    # The bug: this used to be 0 for every document (AttributeError swallowed).
    assert data["recompiled"] == data["total_documents"] == 2
    assert data["success"] is True
    assert data["failed"] == []
    assert data["token_count"] > 0

    # The corpus stats must reflect a real token count
    r = await client.get(f"/api/v1/corpora/{cid}")
    assert r.status_code == 200
    stats = r.json().get("stats") or {}
    assert stats.get("token_count", 0) > 0


@pytest.mark.asyncio
async def test_issue1_recompile_creates_new_annotation_version_with_tokens(client):
    cid, _news, _fiction = await _make_corpus_with_two_tagged_docs(client)

    # Frequency before recompile (documents ingest on upload → a version exists)
    r = await client.post(f"/api/v1/corpora/{cid}/frequency", json={"unit": "word"})
    before_total = r.json()["total_tokens"]

    r = await client.post(f"/api/v1/corpora/{cid}/recompile")
    assert r.status_code == 200
    assert r.json()["recompiled"] == 2

    # After a successful recompile, the (new) latest version must contain
    # the same tokens — i.e., analysis keeps working with real counts.
    r = await client.post(f"/api/v1/corpora/{cid}/frequency", json={"unit": "word"})
    after_total = r.json()["total_tokens"]
    assert after_total == before_total > 0


# --------------------------------------------------------------------------- #
# Issue 2 — subcorpus restriction works on all four analyses
# --------------------------------------------------------------------------- #


@pytest.mark.asyncio
async def test_issue2_concordance_respects_subcorpus(client):
    cid, _news, _fiction = await _make_corpus_with_two_tagged_docs(client)
    sub_id = await _make_subcorpus(client, cid, {"genre": "news"})

    # Without subcorpus: both documents contribute hits for "the"
    r = await client.post(
        f"/api/v1/corpora/{cid}/concordance",
        json={"query": "the", "level": "word"},
    )
    assert r.status_code == 200
    unfiltered_total = r.json()["total"]
    unfiltered_docs = {line["document_id"] for line in r.json()["lines"]}
    assert unfiltered_total > 0
    assert len(unfiltered_docs) == 2

    # With subcorpus: only the news document
    r = await client.post(
        f"/api/v1/corpora/{cid}/concordance",
        json={"query": "the", "level": "word", "subcorpus_id": sub_id},
    )
    assert r.status_code == 200
    filtered = r.json()
    assert 0 < filtered["total"] < unfiltered_total
    assert {line["document_id"] for line in filtered["lines"]} == {_news}


@pytest.mark.asyncio
async def test_issue2_frequency_respects_subcorpus(client):
    cid, _news, _fiction = await _make_corpus_with_two_tagged_docs(client)
    sub_id = await _make_subcorpus(client, cid, {"genre": "news"})

    r = await client.post(f"/api/v1/corpora/{cid}/frequency", json={"unit": "word"})
    full_total = r.json()["total_tokens"]

    r = await client.post(
        f"/api/v1/corpora/{cid}/frequency",
        json={"unit": "word", "subcorpus_id": sub_id},
    )
    assert r.status_code == 200
    sub_total = r.json()["total_tokens"]
    assert 0 < sub_total < full_total


@pytest.mark.asyncio
async def test_issue2_collocations_respects_subcorpus(client):
    cid, _news, _fiction = await _make_corpus_with_two_tagged_docs(client)
    sub_id = await _make_subcorpus(client, cid, {"genre": "news"})

    # "policy" occurs only in the news document
    r = await client.post(
        f"/api/v1/corpora/{cid}/collocations",
        json={"node": "policy", "window": 3, "min_freq": 1},
    )
    assert r.status_code == 200
    full_rows = r.json()["rows"]
    assert len(full_rows) > 0

    r = await client.post(
        f"/api/v1/corpora/{cid}/collocations",
        json={"node": "policy", "window": 3, "min_freq": 1, "subcorpus_id": sub_id},
    )
    assert r.status_code == 200
    assert len(r.json()["rows"]) > 0  # all hits already in news doc

    # A node that occurs only in the fiction document must vanish under the filter
    r = await client.post(
        f"/api/v1/corpora/{cid}/collocations",
        json={"node": "sailor", "window": 3, "min_freq": 1, "subcorpus_id": sub_id},
    )
    assert r.status_code == 200
    assert r.json()["rows"] == []


@pytest.mark.asyncio
async def test_issue2_keyness_respects_subcorpus(client):
    cid, _news, _fiction = await _make_corpus_with_two_tagged_docs(client)
    sub_id = await _make_subcorpus(client, cid, {"genre": "news"})

    # Use the same corpus as its own reference is invalid; create a reference
    # corpus with tokens by uploading to a second corpus.
    r = await client.post("/api/v1/projects", json={"name": "P2", "language": "en"})
    pid2 = r.json()["id"]
    r = await client.post(f"/api/v1/projects/{pid2}/corpora", json={"name": "Ref", "language": "en"})
    ref_cid = r.json()["id"]
    r = await client.post(
        f"/api/v1/corpora/{ref_cid}/documents",
        files={"files": ("ref.txt", io.BytesIO((NEWS_TEXT + " " + FICTION_TEXT).encode()), "text/plain")},
    )
    assert r.status_code == 200

    # Unrestricted keyness target
    r = await client.post(
        f"/api/v1/corpora/{cid}/keyness",
        json={"reference_corpus_id": ref_cid, "min_freq": 1},
    )
    assert r.status_code == 200, r.text
    full_n1 = r.json()["N1"]

    # Restricted to the news subcorpus → N1 shrinks
    r = await client.post(
        f"/api/v1/corpora/{cid}/keyness",
        json={"reference_corpus_id": ref_cid, "min_freq": 1, "subcorpus_id": sub_id},
    )
    assert r.status_code == 200, r.text
    sub_n1 = r.json()["N1"]
    assert 0 < sub_n1 < full_n1


@pytest.mark.asyncio
async def test_issue2_unknown_subcorpus_returns_404(client):
    cid, _news, _fiction = await _make_corpus_with_two_tagged_docs(client)
    r = await client.post(
        f"/api/v1/corpora/{cid}/concordance",
        json={"query": "the", "subcorpus_id": "does-not-exist"},
    )
    assert r.status_code == 404


@pytest.mark.asyncio
async def test_issue2_empty_criteria_subcorpus_returns_empty_results(client):
    """A subcorpus with no criteria matches no documents — analyses must
    return empty results, NOT silently unrestricted results."""
    cid, _news, _fiction = await _make_corpus_with_two_tagged_docs(client)
    sub_id = await _make_subcorpus(client, cid, {})

    r = await client.post(
        f"/api/v1/corpora/{cid}/concordance",
        json={"query": "the", "subcorpus_id": sub_id},
    )
    assert r.status_code == 200
    assert r.json()["total"] == 0
