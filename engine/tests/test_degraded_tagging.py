"""v1.2.12 — degraded (blank-fallback) tagging must be recorded and surfaced.

Field report: a user explores POS in KWIC on an uploaded corpus and finds
nothing. Root cause chain: the packaged engine could not load its NLP model,
SpaCyPipeline silently degraded to spacy.blank() (tokenization only), every
token was stored with pos='X' — and NOTHING recorded that, so the version
rows kept claiming the requested model name and no UI could detect or repair
the corpus. These tests pin the honest-recording contract:

1. SpaCyPipeline reports degraded=True and pos='X' tokens when the model is
   missing (simulated with a model name that cannot resolve).
2. Ingestion under a degraded pipeline writes a :degraded-blank version row
   and pipeline_recipe["degraded"]=True; the corpus list/detail APIs surface
   tagging_degraded=True.
3. Recompile with a REAL pipeline re-tags and clears the flag; its response
   reports degraded=False.
4. Recompile under a still-missing model stays honest: response degraded=True.
"""
from __future__ import annotations

import os
from collections.abc import AsyncIterator

import pytest
from httpx import ASGITransport, AsyncClient

from nlp.general.pipeline import ParsedDocument, ParsedSentence, ParsedToken, PipelineInfo


@pytest.fixture
async def client() -> AsyncIterator[AsyncClient]:
    """Fresh app + in-memory DB per test (same pattern as test_api.py)."""
    os.environ["CORPUSMIND_DB_URL"] = "sqlite+aiosqlite:///:memory:"
    os.environ["CORPUSMIND_DATA_DIR"] = "/tmp/cm-test-data"

    from app.settings import get_settings
    get_settings.cache_clear()
    from storage.session import _engine, dispose_db
    getattr(_engine, "clear", lambda: None)()

    from app.main import app
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as ac:
        async with app.router.lifespan_context(app):
            yield ac
    await dispose_db()


def _blank_doc(text: str) -> ParsedDocument:
    """What a blank (tokenizer-only) pipeline produces: pos='X', surface lemma."""
    toks = [
        ParsedToken(
            text=w, lemma=w, pos="X", pos_fine="", morph="",
            dep_head=0, dep_rel="dep", is_punct=False, is_stop=False,
        )
        for w in text.split()
    ]
    return ParsedDocument(sentences=[ParsedSentence(tokens=toks)])


class _DegradedFakePipeline:
    """Stands in for SpaCyPipeline when the real model cannot be loaded."""

    def __init__(self) -> None:
        self._info = PipelineInfo(
            backend="spacy", model_name="en_core_web_sm", model_version="0.0.0",
            spacy_version="test", language="en", degraded=True,
        )

    def info(self) -> PipelineInfo:
        return self._info

    def parse(self, text: str):  # type: ignore[no-untyped-def]
        yield self.parse_document(text).sentences[0]

    def parse_document(self, text: str) -> ParsedDocument:
        return _blank_doc(text)


class _RealFakePipeline(_DegradedFakePipeline):
    """A properly-tagging pipeline (degraded=False, plausible UPOS values)."""

    def __init__(self) -> None:
        super().__init__()
        self._info = PipelineInfo(
            backend="spacy", model_name="en_core_web_sm", model_version="3.8.0",
            spacy_version="test", language="en", degraded=False,
        )

    def parse_document(self, text: str) -> ParsedDocument:
        toks = []
        for w in text.split():
            pos = "NOUN" if w.endswith("og") or w.endswith("at") else "ADJ"
            toks.append(ParsedToken(
                text=w, lemma=w.lower(), pos=pos, pos_fine="", morph="",
                dep_head=0, dep_rel="dep", is_punct=False, is_stop=False,
            ))
        return ParsedDocument(sentences=[ParsedSentence(tokens=toks)])


async def _make_corpus_with_doc(client: AsyncClient) -> str:
    r = await client.post("/api/v1/projects", json={"name": "P"})
    pid: str = r.json()["id"]
    r = await client.post(f"/api/v1/projects/{pid}/corpora", json={"name": "C", "language": "en"})
    cid: str = r.json()["id"]
    r = await client.post(
        f"/api/v1/corpora/{cid}/documents",
        files={"files": ("a.txt", b"The quick brown fox jumps over the lazy dog")},
    )
    assert r.status_code == 200
    return cid


@pytest.mark.asyncio
async def test_missing_model_reports_degraded_and_pos_x() -> None:
    """Strategy-4 fallback must be VISIBLE on PipelineInfo — no more silent blank."""
    from nlp.general.pipeline import get_pipeline

    p = get_pipeline(backend="spacy", language="en", model_name="xx_no_such_model_xx")
    info = p.info()
    assert info.degraded is True
    doc = p.parse_document("The quick brown fox jumps over the lazy dog")
    poss = [t.pos for s in doc.sentences for t in s.tokens]
    assert poss and set(poss) == {"X"}
    # lemmas collapse to surface forms in the blank pipeline
    assert all(t.lemma == t.text for s in doc.sentences for t in s.tokens)


@pytest.mark.asyncio
async def test_degraded_ingestion_surfaces_tagging_degraded(client: AsyncClient) -> None:
    """Upload under a missing model → version row + recipe + API all say degraded."""
    import ingestion.service as ing_service
    import nlp.general.pipeline as nlp_pipeline

    fake = _DegradedFakePipeline()
    monkeypatches = [
        pytest.MonkeyPatch(), pytest.MonkeyPatch(),
    ]
    try:
        monkeypatches[0].setattr(ing_service, "get_pipeline", lambda **kw: fake)
        monkeypatches[1].setattr(nlp_pipeline, "get_pipeline", lambda **kw: fake)

        cid = await _make_corpus_with_doc(client)

        r = await client.get(f"/api/v1/corpora/{cid}")
        assert r.status_code == 200
        body = r.json()
        assert body["tagging_degraded"] is True
        assert body["pipeline_recipe"]["degraded"] is True

        # list endpoint carries the badge too
        pid = body["project_id"]
        r = await client.get(f"/api/v1/projects/{pid}/corpora")
        assert any(c["tagging_degraded"] for c in r.json())
    finally:
        for m in monkeypatches:
            m.undo()


@pytest.mark.asyncio
async def test_recompile_with_real_model_clears_flag(client: AsyncClient) -> None:
    """Degraded corpus + recompile under a working model → re-tagged, flag cleared."""
    import ingestion.service as ing_service
    import nlp.general.pipeline as nlp_pipeline

    degraded = _DegradedFakePipeline()
    real = _RealFakePipeline()
    m1, m2 = pytest.MonkeyPatch(), pytest.MonkeyPatch()
    try:
        m1.setattr(ing_service, "get_pipeline", lambda **kw: degraded)
        m2.setattr(nlp_pipeline, "get_pipeline", lambda **kw: degraded)
        cid = await _make_corpus_with_doc(client)
    finally:
        m1.undo()
        m2.undo()

    # Sanity: the corpus IS flagged degraded after the degraded upload.
    r = await client.get(f"/api/v1/corpora/{cid}")
    assert r.json()["tagging_degraded"] is True

    # Recompile with a working pipeline.
    m3, m4 = pytest.MonkeyPatch(), pytest.MonkeyPatch()
    try:
        m3.setattr(ing_service, "get_pipeline", lambda **kw: real)
        m4.setattr(nlp_pipeline, "get_pipeline", lambda **kw: real)
        r = await client.post(f"/api/v1/corpora/{cid}/recompile")
    finally:
        m3.undo()
        m4.undo()

    assert r.status_code == 200
    body = r.json()
    assert body["success"] is True
    assert body["degraded"] is False

    r = await client.get(f"/api/v1/corpora/{cid}")
    assert r.json()["tagging_degraded"] is False

    # And the re-tagged tokens actually carry real POS now — POS-KWIC works.
    r = await client.post(
        f"/api/v1/corpora/{cid}/concordance",
        json={"query": "NOUN", "level": "pos", "window": 2},
    )
    assert r.status_code == 200
    assert r.json()["total"] > 0


@pytest.mark.asyncio
async def test_recompile_still_missing_model_stays_honest(client: AsyncClient) -> None:
    """Recompiling while the model is STILL absent reports degraded=True."""
    import ingestion.service as ing_service
    import nlp.general.pipeline as nlp_pipeline

    fake = _DegradedFakePipeline()
    m1, m2 = pytest.MonkeyPatch(), pytest.MonkeyPatch()
    try:
        m1.setattr(ing_service, "get_pipeline", lambda **kw: fake)
        m2.setattr(nlp_pipeline, "get_pipeline", lambda **kw: fake)
        cid = await _make_corpus_with_doc(client)
        r = await client.post(f"/api/v1/corpora/{cid}/recompile")
    finally:
        m1.undo()
        m2.undo()

    assert r.status_code == 200
    body = r.json()
    assert body["success"] is True
    assert body["degraded"] is True
