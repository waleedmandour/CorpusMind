"""r4: Arabic Tools can analyze a corpus uploaded via 'Your Corpus'.

The bulk Arabic analysis job (v1.2.11) accepted only raw text — useful for
scripts, useless for the app's own workflow: the browser does not have the
corpus bytes, so a "select your uploaded corpus" UI needs the ENGINE to load
the stored cleaned text. r4 therefore teaches POST /arabic/analyze/job to
accept corpus_id (exactly one of text/corpus_id), load the corpus's documents
server-side in ingestion order, and run the same chunked/aggregated job, with
the corpus name echoed back as the job's `source`.

Everything here runs WITHOUT the CAMeL data pack or network: analyze is
stubbed with real ArabicToken objects (same technique as
test_v1211_arabic_followup.py), and corpus/project rows are seeded directly
via session_scope — the same in-memory DB the API client reads (proven
pattern: test_batch_view.py, test_learner.py).
"""
from __future__ import annotations

import os
import time
from collections.abc import AsyncIterator, Iterator
from typing import TYPE_CHECKING, Any

import pytest
from httpx import ASGITransport, AsyncClient

os.environ["CORPUSMIND_DB_URL"] = "sqlite+aiosqlite:///:memory:"
os.environ["CORPUSMIND_DATA_DIR"] = "/tmp/cm-test-data"
from app.settings import get_settings

get_settings.cache_clear()

if TYPE_CHECKING:
    from pytest import MonkeyPatch

    from app.arabic_bulk import ArabicBulkJob
    from nlp.arabic.pipeline import ArabicAnalysis


@pytest.fixture
async def client() -> AsyncIterator[AsyncClient]:
    from app.main import app
    from storage.session import dispose_db

    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as ac:
        async with app.router.lifespan_context(app):
            yield ac
    await dispose_db()


@pytest.fixture(autouse=True)
def _reset_gates() -> Iterator[None]:
    """Fresh bulk-job singleton (and quiet gates) for every test."""
    from app import arabic_bulk, arabic_concurrency, arabic_installer

    arabic_concurrency.gate.reset_for_tests()
    arabic_installer.reset_installer_for_tests()
    arabic_bulk.reset_bulk_job_for_tests()
    yield
    arabic_concurrency.gate.reset_for_tests()
    arabic_installer.reset_installer_for_tests()
    arabic_bulk.reset_bulk_job_for_tests()


def _fake_analysis(text: str) -> ArabicAnalysis:
    """Real ArabicToken objects — the aggregator's actual input type."""
    from nlp.arabic.pipeline import ArabicAnalysis, ArabicToken

    tokens = [
        ArabicToken(
            text=w, lemma=w, root="ك.ت.ب", pattern="1َ2َ3َل", pos="noun",
            stem=w, buckwalter="ktb", dediacritized=w,
        )
        for w in text.split()
    ]
    return ArabicAnalysis(text=text, tokens=tokens, detected_dialect="msa", backend="camel")


def _wait_for_state(job: ArabicBulkJob, want: set[str], timeout: float = 30.0) -> dict[str, Any]:
    deadline = time.time() + timeout
    while time.time() < deadline:
        s = job.status()
        if s.get("state") in want:
            return s
        time.sleep(0.05)
    pytest.fail(f"bulk job never reached {want}; last: {job.status()}")


async def _seed_corpus(texts: list[str], name: str = "Arabic news corpus") -> str:
    """Insert a project + Arabic corpus + documents; return the corpus id."""
    from storage.models import Corpus, Document, Project
    from storage.session import session_scope

    async with session_scope() as s:
        p = Project(name="P", language="ar")
        s.add(p)
        # Flush so the Python-side id default (_uuid) lands on p.id before
        # the corpus FK references it.
        await s.flush()
        c = Corpus(project_id=p.id, name=name, language="ar")
        s.add(c)
        await s.flush()
        for i, t in enumerate(texts):
            s.add(Document(corpus_id=c.id, filename=f"doc{i}.txt", cleaned_text=t))
        await s.flush()
        return c.id


# --------------------------------------------------------------------------- #
# Corpus-driven start
# --------------------------------------------------------------------------- #


@pytest.mark.asyncio
async def test_corpus_start_runs_and_aggregates(client: AsyncClient, monkeypatch: MonkeyPatch) -> None:
    """corpus_id start: engine loads the stored cleaned text, the job runs to
    done, and the aggregated result is downloadable with the corpus name as
    the job source."""
    import app.arabic_bulk as bulk_mod

    monkeypatch.setattr(bulk_mod, "analyze_arabic", lambda text, **kw: _fake_analysis(text))
    cid = await _seed_corpus(["الطلاب يدرسون في المكتبة", "كتب الكاتب كتابا مفيدا"])

    r = await client.post("/api/v1/arabic/analyze/job", json={"corpus_id": cid})
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["state"] == "running"
    assert body["source"] == "Arabic news corpus"
    assert body["tokens_total"] == 8  # 4 + 4 words

    job = bulk_mod.get_bulk_job()
    s = _wait_for_state(job, {"done"})
    assert s["chunks_done"] == s["chunks_total"] == 1
    assert s["source"] == "Arabic news corpus"

    r = await client.get("/api/v1/arabic/analyze/job/result")
    assert r.status_code == 200
    payload = r.json()
    assert payload["token_count"] == 8
    assert payload["unique_tokens"] == 8
    assert payload["pos_distribution"].get("noun") == 8
    assert ["ك.ت.ب", 8] in payload["top_roots"]


@pytest.mark.asyncio
async def test_corpus_start_skips_blank_documents(client: AsyncClient, monkeypatch: MonkeyPatch) -> None:
    """Blank documents contribute nothing; a corpus with ONLY blank documents
    is a 422, not a doomed job."""
    import app.arabic_bulk as bulk_mod

    monkeypatch.setattr(bulk_mod, "analyze_arabic", lambda text, **kw: _fake_analysis(text))
    cid = await _seed_corpus(["", "   ", "كتاب"])
    r = await client.post("/api/v1/arabic/analyze/job", json={"corpus_id": cid})
    assert r.status_code == 200
    assert r.json()["tokens_total"] == 1
    _wait_for_state(bulk_mod.get_bulk_job(), {"done"})

    empty = await _seed_corpus(["", "   "], name="Empty corpus")
    r = await client.post("/api/v1/arabic/analyze/job", json={"corpus_id": empty})
    assert r.status_code == 422
    assert "no text content" in r.json()["detail"]


@pytest.mark.asyncio
async def test_corpus_start_unknown_corpus_404(client: AsyncClient) -> None:
    r = await client.post("/api/v1/arabic/analyze/job", json={"corpus_id": "does-not-exist"})
    assert r.status_code == 404
    assert "Corpus not found" in r.json()["detail"]


@pytest.mark.asyncio
async def test_start_rejects_both_and_neither_sources(client: AsyncClient) -> None:
    """Exactly one of text / corpus_id — the old body (text only) stays valid."""
    r = await client.post(
        "/api/v1/arabic/analyze/job", json={"text": "كتاب", "corpus_id": "abc"}
    )
    assert r.status_code == 422
    assert "exactly one" in r.json()["detail"]

    r = await client.post("/api/v1/arabic/analyze/job", json={})
    assert r.status_code == 422
    assert "exactly one" in r.json()["detail"]


@pytest.mark.asyncio
async def test_corpus_start_busy_409_and_status_has_source(client: AsyncClient, monkeypatch: MonkeyPatch) -> None:
    """While a job runs, a corpus start answers 409 like a text start; the
    running status carries the source label for the UI."""
    import app.arabic_bulk as bulk_mod

    def _slow(text: str, **kw: Any) -> ArabicAnalysis:
        time.sleep(1.2)
        return _fake_analysis(text)

    monkeypatch.setattr(bulk_mod, "analyze_arabic", _slow)
    cid = await _seed_corpus(["كتاب كبير"] * 50)
    r = await client.post("/api/v1/arabic/analyze/job", json={"corpus_id": cid})
    assert r.status_code == 200

    r2 = await client.post("/api/v1/arabic/analyze/job", json={"text": "كتاب"})
    assert r2.status_code == 409
    assert "already running" in r2.json()["detail"]

    st = (await client.get("/api/v1/arabic/analyze/job/status")).json()
    assert st["busy"] is True
    assert st["source"] == "Arabic news corpus"

    c = await client.post("/api/v1/arabic/analyze/job/cancel")
    assert c.status_code == 200
    _wait_for_state(bulk_mod.get_bulk_job(), {"cancelled", "done"}, timeout=10.0)


# --------------------------------------------------------------------------- #
# r5: the start route must NEVER surface a bare 500. Environment-level
# failures (a locked/busy local DB, disk pressure, anything unexpected) get
# actionable details + a server-side traceback; a bare "Internal Server
# Error" with no cause is exactly the field report this pin exists for.
# --------------------------------------------------------------------------- #


@pytest.mark.asyncio
async def test_corpus_start_db_error_returns_actionable_503(
    client: AsyncClient, monkeypatch: MonkeyPatch
) -> None:
    """A busy/locked local DB (e.g. a large ingestion commit still flushing)
    is a 503 with an actionable message — not a bare 500."""
    from sqlalchemy.exc import OperationalError

    import api.arabic_bulk as api_bulk

    async def _locked(_session: Any, _cid: str) -> tuple[str, str]:
        raise OperationalError(
            "SELECT ...", {}, Exception("database is locked")
        )

    monkeypatch.setattr(api_bulk, "_corpus_text", _locked)
    r = await client.post("/api/v1/arabic/analyze/job", json={"corpus_id": "whatever"})
    assert r.status_code == 503
    detail = r.json()["detail"]
    assert "local database" in detail
    assert "OperationalError" in detail
    assert "wait a moment" in detail


@pytest.mark.asyncio
async def test_corpus_start_load_error_returns_503(
    client: AsyncClient, monkeypatch: MonkeyPatch
) -> None:
    """Disk/memory pressure while loading the corpus text is a 503 that names
    the underlying OS error."""
    import api.arabic_bulk as api_bulk

    async def _no_space(_session: Any, _cid: str) -> tuple[str, str]:
        raise OSError(28, "No space left on device")

    monkeypatch.setattr(api_bulk, "_corpus_text", _no_space)
    r = await client.post("/api/v1/arabic/analyze/job", json={"corpus_id": "whatever"})
    assert r.status_code == 503
    detail = r.json()["detail"]
    assert "could not be loaded" in detail
    assert "No space left on device" in detail


@pytest.mark.asyncio
async def test_corpus_start_unexpected_error_is_labeled_500(
    client: AsyncClient, monkeypatch: MonkeyPatch
) -> None:
    """An unknown failure is a LABELED 500 ('<ErrClass>: <msg>', same
    convention as the interactive route) — never a detail-less Internal
    Server Error, and the traceback is logged server-side."""
    import api.arabic_bulk as api_bulk

    async def _boom(_session: Any, _cid: str) -> tuple[str, str]:
        raise RuntimeError("disk exploding")

    monkeypatch.setattr(api_bulk, "_corpus_text", _boom)
    r = await client.post("/api/v1/arabic/analyze/job", json={"corpus_id": "whatever"})
    assert r.status_code == 500
    assert "RuntimeError: disk exploding" in r.json()["detail"]
