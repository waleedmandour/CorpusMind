"""v1.2.0 tests — tagset selection (Issue 4).

Covers:
  - the tagset registry (valid per language, defaults)
  - PTB → CLAWS-7 mapping behavior
  - /corpora/{cid}/pos-analysis with tagset=ptb / claws7 (endpoint level)
  - the new USAS semantic-analysis endpoint (lexicon-based)
  - PATCH /corpora/{cid}/tagset persistence (and 422 on invalid)
"""

from __future__ import annotations

import os

import pytest
from httpx import ASGITransport, AsyncClient


@pytest.fixture
async def client():
    os.environ["CORPUSMIND_DB_URL"] = "sqlite+aiosqlite:///:memory:"
    os.environ["CORPUSMIND_DATA_DIR"] = "/tmp/cm-test-tagsets"

    from app.settings import get_settings

    get_settings.cache_clear()
    from storage.session import _engine, dispose_db

    _engine.clear() if hasattr(_engine, "clear") else None

    from app.main import app

    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as ac:
        async with app.router.lifespan_context(app):
            yield ac
    await dispose_db()


async def _make_corpus(client: AsyncClient, language: str = "en") -> str:
    r = await client.post(
        "/api/v1/projects", json={"name": f"P-{language}-{id(object())}", "language": language}
    )
    pid = r.json()["id"]
    r = await client.post(
        f"/api/v1/projects/{pid}/corpora", json={"name": f"C-{language}", "language": language}
    )
    cid = r.json()["id"]
    # Ingest a small document so tokens exist (upload → clean → ingest pipeline)
    files = {
        "files": (
            "doc.txt",
            b"The government announced new economic research funding.",
            "text/plain",
        )
    }
    r = await client.post(f"/api/v1/corpora/{cid}/documents", files=files)
    assert r.status_code == 200, r.text
    return cid


# --------------------------------------------------------------------------- #
# Registry
# --------------------------------------------------------------------------- #


def test_valid_tagsets_per_language():
    from nlp.tagsets import valid_tagsets_for_language

    assert valid_tagsets_for_language("en") == ["upos", "ptb", "claws7"]
    assert valid_tagsets_for_language("ar") == ["upos", "calima"]
    assert valid_tagsets_for_language("fr") == ["upos"]
    # default = first entry
    assert valid_tagsets_for_language("en")[0] == "upos"


def test_map_tag_claws7_uses_fine_layer_and_falls_back():
    from nlp.tagsets import map_tag

    # PTB fine tag present → direct map
    assert map_tag("claws7", pos="NOUN", pos_fine="NN", language="en") == "NN1"
    assert map_tag("claws7", pos="VERB", pos_fine="VBD", language="en") == "VVD"
    # Unmapped fine tag → UPOS coarse fallback
    assert map_tag("claws7", pos="NOUN", pos_fine="NOT-A-TAG", language="en") == "NN1"
    # Nothing usable → UNC
    assert map_tag("claws7", pos="", pos_fine="", language="en") == "UNC"
    # ptb tagset returns the fine layer as-is
    assert map_tag("ptb", pos="NOUN", pos_fine="NNS", language="en") == "NNS"
    # calima tagset for Arabic returns the raw CAMeL tag
    assert map_tag("calima", pos="NOUN", pos_fine="noun", language="ar") == "noun"
    # wrong language → degrade to UPOS
    assert map_tag("ptb", pos="NOUN", pos_fine="NN", language="ar") == "NOUN"


# --------------------------------------------------------------------------- #
# POS endpoint with tagset
# --------------------------------------------------------------------------- #


@pytest.mark.asyncio
async def test_pos_analysis_tagset_ptb_and_claws7(client):
    cid = await _make_corpus(client, "en")

    r = await client.post(
        f"/api/v1/corpora/{cid}/pos-analysis", json={"n": 1, "tagset": "ptb"}
    )
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["tagset"] == "ptb"
    assert body["distribution"], "expected PTB distribution rows"
    # en_core_web_sm fine tags look like PTB (NN*, VBD, IN, AT/DT...)
    assert any(row["pos"] for row in body["distribution"])

    r2 = await client.post(
        f"/api/v1/corpora/{cid}/pos-analysis", json={"n": 1, "tagset": "claws7"}
    )
    body2 = r2.json()
    assert body2["tagset"] == "claws7"
    assert body2["distribution"]
    # CLAWS-7 noun singular is NN1 — present whenever a PTB NN was tagged
    tags2 = {row["pos"] for row in body2["distribution"]}
    assert tags2.issubset(
        set(__import__("nlp.tagsets", fromlist=["PTB_TO_CLAWS7"]).PTB_TO_CLAWS7.values()) | {"UNC"}
    )


@pytest.mark.asyncio
async def test_pos_analysis_rejects_wrong_language_tagset(client):
    cid = await _make_corpus(client, "en")
    r = await client.post(
        f"/api/v1/corpora/{cid}/pos-analysis", json={"n": 1, "tagset": "calima"}
    )
    assert r.status_code == 422, r.text
    assert "calima" in r.json()["detail"]


# --------------------------------------------------------------------------- #
# Semantic analysis (USAS)
# --------------------------------------------------------------------------- #


@pytest.mark.asyncio
async def test_semantic_analysis_returns_usas_distribution(client):
    cid = await _make_corpus(client, "en")
    r = await client.post(f"/api/v1/corpora/{cid}/semantic-analysis", json={"limit": 50})
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["tagset"] == "usas"
    assert body["matched_tokens"] > 0, (
        "lexicon should match common words like 'government', 'economic'"
    )
    tags = {row["tag"] for row in body["distribution"]}
    # 'government' → G, 'economic' → I, 'research' → X in the top-level lexicon
    assert tags <= set("ABCDEFGHIJKLMNOPQRSTUVWXYZ")
    assert 0 <= body["unmatched_percent"] <= 100


# --------------------------------------------------------------------------- #
# Tagset persistence
# --------------------------------------------------------------------------- #


@pytest.mark.asyncio
async def test_patch_tagset_persists_and_validates(client):
    cid = await _make_corpus(client, "en")

    r = await client.patch(f"/api/v1/corpora/{cid}/tagset", json={"tagset": "claws7"})
    assert r.status_code == 200, r.text
    assert r.json()["ok"] is True

    corpus = (await client.get(f"/api/v1/corpora/{cid}")).json()
    assert corpus["pipeline_recipe"]["tagset"] == "claws7"

    r2 = await client.patch(f"/api/v1/corpora/{cid}/tagset", json={"tagset": "calima"})
    assert r2.status_code == 422, r2.text

    r3 = await client.patch(f"/api/v1/corpora/{cid}/tagset", json={"tagset": "bogus"})
    assert r3.status_code == 422, r3.text


if __name__ == "__main__":
    pytest.main([__file__, "-v", "--tb=short"])
