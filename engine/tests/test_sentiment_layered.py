"""Tests for the layered, Appraisal-grounded sentiment analysis
(v1.2.8, review #8): grammar-driven negation/boosters, the Appraisal
profile, honest lexicon reporting, the optional NRC EmoLex upgrade path,
and backward compatibility with the v1.0 endpoint shape.
"""

from __future__ import annotations

import io
import os

import pytest
from httpx import ASGITransport, AsyncClient

from sentiment.lexicons import (
    APPRAISAL_CUES,
    STARTER_VALENCE_AR,
    STARTER_VALENCE_EN,
    load_emolex,
)
from sentiment.service import (
    _lookup,
    _score_sentence,
)


def tok(idx, text, *, lemma=None, pos="ADJ", rel="", head=0):
    return {
        "idx": idx,
        "text": text,
        "lemma": lemma or text,
        "pos": pos,
        "rel": rel,
        "head": head,
        "doc": "d",
        "sent": 0,
    }


def setup_module(module):
    load_emolex.cache_clear()


def teardown_module(module):
    load_emolex.cache_clear()


# --------------------------------------------------------------------------- #
# Unit: grammar layer
# --------------------------------------------------------------------------- #


def test_positive_sentence_scores_positive():
    s = _score_sentence([tok(0, "good")], "en", STARTER_VALENCE_EN, None)
    assert s["score"] > 0.05
    assert s["pos_w"] > s["neg_w"]


def test_negation_flips_polarity():
    plain = _score_sentence([tok(0, "good")], "en", STARTER_VALENCE_EN, None)
    # UD: the negation particle is the DEPENDENT; its head is "good" (1-based).
    negated = _score_sentence(
        [tok(0, "not", pos="PART", rel="advmod", head=2), tok(1, "good", head=0)],
        "en",
        STARTER_VALENCE_EN,
        None,
    )
    assert plain["score"] > 0
    assert negated["score"] < 0, "a `neg` dependent must flip its head's polarity"


def test_negation_propagates_through_copula():
    """Real spaCy parse of 'It is not good': neg attaches to the copula
    'is', not to 'good' — the flip must travel through the acomp chain."""
    sent = [
        tok(0, "It", pos="PRON", rel="nsubj", head=2),
        tok(1, "is", pos="AUX", rel="ROOT", head=0),
        tok(2, "not", pos="PART", rel="neg", head=2),
        tok(3, "good", pos="ADJ", rel="acomp", head=2),
    ]
    s = _score_sentence(sent, "en", STARTER_VALENCE_EN, None)
    assert s["score"] < 0, "copular negation scope must reach the adjective"


def test_booster_intensifies():
    plain = _score_sentence([tok(0, "good")], "en", STARTER_VALENCE_EN, None)
    boosted = _score_sentence(
        [
            tok(0, "very", pos="ADV", rel="advmod", head=2),
            tok(1, "good", head=0),
        ],
        "en",
        STARTER_VALENCE_EN,
        None,
    )
    assert boosted["score"] > plain["score"]


def test_negated_positive_is_negative_sentence_classification():
    s = _score_sentence(
        [tok(0, "not", pos="PART", rel="advmod", head=3), tok(1, "very", pos="ADV", rel="advmod", head=3), tok(2, "good", head=0)],
        "en",
        STARTER_VALENCE_EN,
        None,
    )
    # booster under negation still flips to negative overall
    assert s["score"] < 0


def test_arabic_lookup_strips_diacritics():
    diacritic = "\u0633\u064e\u0639\u0650\u064a\u062f"  # سَعِيد
    entry = _lookup(
        {"lemma": diacritic, "text": diacritic}, "ar", STARTER_VALENCE_AR, None
    )
    assert entry is not None
    assert entry.polarity == 1
    assert "joy" in entry.emotions


# --------------------------------------------------------------------------- #
# Unit: optional NRC EmoLex upgrade path
# --------------------------------------------------------------------------- #


def test_emolex_optional_load_and_precedence(tmp_path, monkeypatch):
    lex_dir = tmp_path / "sent"
    lex_dir.mkdir()
    (lex_dir / "nrc-emolex-en.tsv").write_text(
        "lemma\temotions\tpolarity\n"
        "good\tjoy,trust\t1\n"
        "sleepy\t\t0\n",
        encoding="utf-8",
    )
    monkeypatch.setenv("CORPUSMIND_SENTIMENT_LEXICON_DIR", str(lex_dir))
    from app.settings import get_settings

    get_settings.cache_clear()
    load_emolex.cache_clear()
    try:
        lex = load_emolex("en")
        assert lex is not None, "configured EmoLex must load"
        assert lex["good"].polarity == 1
        assert lex["good"].emotions == ("joy", "trust")
        # EmoLex wins over the starter lexicon (emotions differ there).
        entry = _lookup({"lemma": "good", "text": "good"}, "en", STARTER_VALENCE_EN, lex)
        assert entry.emotions == ("joy", "trust")
        # Not-configured languages still return None (honest fallback).
        assert load_emolex("de") is None
    finally:
        monkeypatch.undo()
        get_settings.cache_clear()
        load_emolex.cache_clear()


def test_emolex_absent_reports_starter(monkeypatch):
    monkeypatch.delenv("CORPUSMIND_SENTIMENT_LEXICON_DIR", raising=False)
    from app.settings import get_settings

    get_settings.cache_clear()
    load_emolex.cache_clear()
    try:
        status = __import__("sentiment.lexicons", fromlist=["emolex_status"]).emolex_status("en")
        assert status["available"] is False
        assert status["coverage"] == "starter"
        assert "not redistribute" in status["upgrade_hint"] or "forbid" in status["upgrade_hint"]
    finally:
        get_settings.cache_clear()
        load_emolex.cache_clear()


# --------------------------------------------------------------------------- #
# Integration: endpoint behavior (backward-compatible shape + new layers)
# --------------------------------------------------------------------------- #


@pytest.fixture
async def client():
    os.environ["CORPUSMIND_DB_URL"] = "sqlite+aiosqlite:///:memory:"
    os.environ["CORPUSMIND_DATA_DIR"] = "/tmp/cm-test-sentiment"
    from app.settings import get_settings

    get_settings.cache_clear()
    from app.main import app
    from storage.session import dispose_db

    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as ac:
        async with app.router.lifespan_context(app):
            yield ac
    await dispose_db()


async def _setup_corpus(client: AsyncClient, content: bytes) -> str:
    r = await client.post("/api/v1/projects", json={"name": "P", "language": "en"})
    pid = r.json()["id"]
    r = await client.post(f"/api/v1/projects/{pid}/corpora", json={"name": "C", "language": "en"})
    cid = r.json()["id"]
    await client.post(
        f"/api/v1/corpora/{cid}/documents",
        files={"files": ("test.txt", io.BytesIO(content), "text/plain")},
    )
    return cid


@pytest.mark.asyncio
async def test_sentiment_endpoint_layered_and_backward_compatible(client):
    content = (
        b"The film was wonderful and brilliant. "
        b"The ending was terrible and disappointing. "
        b"It is not good at all, which is worrying. "
        b"Obviously the director is very talented. "
        b"The critics published an impressive and honest account."
    )
    cid = await _setup_corpus(client, content)
    r = await client.post(f"/api/v1/corpora/{cid}/sentiment")
    assert r.status_code == 200, r.text
    d = r.json()

    # Backward-compatible top-level fields (v1.0 contract)
    for key in ("total_sentences", "positive", "negative", "neutral", "avg_score", "timeline"):
        assert key in d, key

    # The nuance: negation flips the valence sentence to negative
    assert d["negative"] >= 2, d
    assert d["positive"] >= 1, d

    # Layered fields (v1.2.8, review #8)
    assert d["method"] == "appraisal-nuanced-v1"
    assert d["lexicons"]["emolex"]["coverage"] == "starter"
    assert d["lexicons"]["appraisal_cues"]["available"] is True
    assert d["appraisal"]["available"] is True
    assert set(d["appraisal"]["categories"]) == set(APPRAISAL_CUES)
    assert d["appraisal"]["categories"]["attitude.appreciation"]["count"] >= 1
    assert d["appraisal"]["categories"]["attitude.judgment"]["count"] >= 1
    assert set(d["emotions"]) == {
        "anger", "anticipation", "disgust", "fear",
        "joy", "sadness", "surprise", "trust",
    }
    assert d["emotions"]["joy"] >= 1
    assert d["top_emotional"], "valenced lemmas must be listed"
    assert any(w["lemma"] == "wonderful" for w in d["top_emotional"])
    # Timeline entries carry the nuance annotations
    assert any(t["dominant_emotion"] for t in d["timeline"])
    assert any(t["attitude"] for t in d["timeline"])


@pytest.mark.asyncio
async def test_sentiment_empty_corpus_reports_layers_honestly(client):
    r = await client.post("/api/v1/projects", json={"name": "P2", "language": "en"})
    pid = r.json()["id"]
    r = await client.post(f"/api/v1/projects/{pid}/corpora", json={"name": "C2", "language": "en"})
    cid = r.json()["id"]
    resp = await client.post(f"/api/v1/corpora/{cid}/sentiment")
    assert resp.status_code == 200
    d = resp.json()
    assert d["total_sentences"] == 0
    assert d["emotions"] == {e: 0 for e in ("anger", "anticipation", "disgust", "fear", "joy", "sadness", "surprise", "trust")}
    assert d["lexicons"]["emolex"]["available"] in (True, False)  # honest either way
