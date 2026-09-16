"""v1.2.4 regression tests — model management, warm-up, tunable embed timeout.

User-driven follow-up to v1.2.3: a host whose cold bge-m3 load exceeds
120 s x2 got an honest 503 embedding_timeout but had to open a terminal to
run the curl warm-up command. v1.2.4 adds:

1. CORPUSMIND_EMBED_TIMEOUT_S — env-tunable embed timeout (floor 30 s),
   honoured by both ai.providers.OllamaProvider and semantic.vector_kwic.
2. POST /api/v1/ollama/warmup (+ /status) — load the model into Ollama's
   memory from the app, no terminal needed; pulls of embedding models
   auto-warm on success.
3. DELETE /api/v1/ollama/models — remove any downloaded model (UI adds an
   X button with a confirmation dialog).
4. Vector KWIC accepts an explicit embedding model in the UI, so
   nomic-embed-text (~275 MB, fast loads) can replace bge-m3 on
   English-only corpora.
"""
from __future__ import annotations

import asyncio
import json
import os
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from types import SimpleNamespace

import httpx
import pytest

# Canonical in-memory-DB env (mirrors test_vector_kwic.py) BEFORE engine imports.
os.environ["CORPUSMIND_DB_URL"] = "sqlite+aiosqlite:///:memory:"
os.environ["CORPUSMIND_DATA_DIR"] = "/tmp/cm-test-v124-models"
os.environ["CORPUSMIND_OLLAMA_BASE_URL"] = "http://127.0.0.1:1"  # no real Ollama

from ai.providers import (
    ModelProviderError,
    OllamaModelNotFoundError,
    OllamaProvider,
)
from semantic.vector_kwic import EMBED_TIMEOUT_S, _embed_texts, embed_timeout_s

# --------------------------------------------------------------------------- #
# Helpers
# --------------------------------------------------------------------------- #


class _FakeSettings:
    ollama_base_url = "http://127.0.0.1:11434"
    ollama_default_model = "llama3.2:3b"


def _make_provider(handler) -> OllamaProvider:
    p = OllamaProvider(_FakeSettings())
    p._client = httpx.AsyncClient(
        base_url="http://ollama.test",
        transport=httpx.MockTransport(handler),
    )
    return p


class _Resp:
    """Minimal embed response double for fakes without embed_batch."""

    def __init__(self, vector: list[float], model: str | None):
        self.vector = vector
        self.model = model or "test-embed"
        self.provider = "ollama"


class RecordingEmbedProvider:
    """No embed_batch → _embed_texts falls back to the per-text embed loop,
    letting us capture the (model, timeout) actually passed per call."""

    name = "ollama"

    def __init__(self):
        self.calls: list[tuple[str, str | None, float | None]] = []

    async def embed(self, text: str, *, model=None, timeout=None):
        self.calls.append((text, model, timeout))
        return _Resp([0.1, 0.2], model)

    async def list_models(self):
        return None  # probe unavailable → let the embed call decide


# --------------------------------------------------------------------------- #
# 1. CORPUSMIND_EMBED_TIMEOUT_S
# --------------------------------------------------------------------------- #


def test_embed_timeout_env_override(monkeypatch):
    monkeypatch.setenv("CORPUSMIND_EMBED_TIMEOUT_S", "300")
    assert embed_timeout_s() == 300.0

    monkeypatch.setenv("CORPUSMIND_EMBED_TIMEOUT_S", "5")  # below the 30 s floor
    assert embed_timeout_s() == 30.0

    monkeypatch.setenv("CORPUSMIND_EMBED_TIMEOUT_S", "banana")  # bad value
    assert embed_timeout_s() == EMBED_TIMEOUT_S

    monkeypatch.delenv("CORPUSMIND_EMBED_TIMEOUT_S")
    assert embed_timeout_s() == EMBED_TIMEOUT_S == 120.0


def test_provider_embed_timeout_env(monkeypatch):
    p = OllamaProvider(_FakeSettings())
    monkeypatch.setenv("CORPUSMIND_EMBED_TIMEOUT_S", "240")
    assert p._embed_timeout(None) == 240.0
    assert p._embed_timeout(60.0) == 60.0  # explicit arg still wins

    monkeypatch.delenv("CORPUSMIND_EMBED_TIMEOUT_S")
    assert p._embed_timeout(None) == 120.0


def test_embed_texts_passes_env_timeout(monkeypatch):
    provider = RecordingEmbedProvider()
    provider.calls = []
    monkeypatch.setenv("CORPUSMIND_EMBED_TIMEOUT_S", "240")
    vecs = asyncio.run(_embed_texts(provider, ["hello", "world"], "bge-m3"))
    assert len(vecs) == 2
    assert all((m, t) == ("bge-m3", 240.0) for _, m, t in provider.calls)


# --------------------------------------------------------------------------- #
# 2. Provider-level delete (DELETE /api/delete)
# --------------------------------------------------------------------------- #


def test_provider_delete_model_success():
    seen: dict = {}

    def handler(request: httpx.Request) -> httpx.Response:
        seen["method"] = request.method
        seen["path"] = request.url.path
        seen["payload"] = json.loads(request.content.decode())
        return httpx.Response(200, json={})

    p = _make_provider(handler)
    try:
        asyncio.run(p.delete_model("bge-m3"))  # must not raise
    finally:
        asyncio.run(p._client.aclose())
    assert seen["method"] == "DELETE"
    assert seen["path"] == "/api/delete"
    assert seen["payload"] == {"model": "bge-m3"}


def test_provider_delete_model_missing_404():
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(404, json={"error": "model 'bge-m3' not found"})

    p = _make_provider(handler)
    try:
        with pytest.raises(OllamaModelNotFoundError):
            asyncio.run(p.delete_model("bge-m3"))
    finally:
        asyncio.run(p._client.aclose())


def test_provider_delete_model_error_wrapped():
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(500, json={"error": "boom"})

    p = _make_provider(handler)
    try:
        with pytest.raises(ModelProviderError) as ei:
            asyncio.run(p.delete_model("bge-m3"))
        assert "boom" in str(ei.value)
        assert not isinstance(ei.value, OllamaModelNotFoundError)
    finally:
        asyncio.run(p._client.aclose())


# --------------------------------------------------------------------------- #
# 3. API layer: explicit model for Vector KWIC (nomic-embed-text selectable)
# --------------------------------------------------------------------------- #


class NomicRecordingProvider:
    """Installed list carries :latest tags (real Ollama behaviour);
    embed records the model per call so the test can assert the
    request-level model flowed through the whole chain."""

    name = "ollama"

    def __init__(self):
        self.embed_models: list[str | None] = []

    async def list_models(self):
        return ["llama3.2:3b", "bge-m3:latest", "nomic-embed-text:latest"]

    async def embed(self, text: str, *, model=None, timeout=None):
        self.embed_models.append(model)
        return _Resp([0.1, 0.2, 0.3], model)


@pytest.fixture
async def client_vk():
    from httpx import ASGITransport, AsyncClient

    import storage.session as _ss
    from app.main import app
    from storage.session import dispose_db
    from tests.test_vector_kwic import _seed_corpus

    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as ac:
        async with app.router.lifespan_context(app):
            cid = await _seed_corpus(_ss._sessionmaker)
            yield ac, cid
    await dispose_db()


async def test_vector_kwic_uses_explicit_nomic_model(client_vk):
    ac, cid = client_vk
    provider = NomicRecordingProvider()
    from app.main import app

    app.state.providers._instances["ollama"] = provider
    r = await ac.post(f"/api/v1/corpora/{cid}/concordance/vector", json={
        "query": "climate policy", "model": "nomic-embed-text",
    })
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["model"] == "nomic-embed-text"
    assert provider.embed_models and all(
        m == "nomic-embed-text" for m in provider.embed_models
    )


# --------------------------------------------------------------------------- #
# 4. API layer: DELETE /ollama/models
# --------------------------------------------------------------------------- #


class _DeleteFake:
    def __init__(self, *, raise_on_delete: Exception | None = None):
        self.deleted: list[str] = []
        self._raise = raise_on_delete

    async def delete_model(self, name: str) -> None:
        if self._raise:
            raise self._raise
        self.deleted.append(name)


async def _delete_model(ac, fake, name: str):
    from app.main import app

    app.state.providers._instances["ollama"] = fake
    return await ac.request("DELETE", "/api/v1/ollama/models", json={"model": name})


async def test_delete_endpoint_ok(client_vk):
    ac, _ = client_vk
    fake = _DeleteFake()
    r = await _delete_model(ac, fake, "bge-m3")
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["ok"] is True
    assert body["model"] == "bge-m3"
    assert fake.deleted == ["bge-m3"]


async def test_delete_endpoint_missing_model_404(client_vk):
    ac, _ = client_vk
    fake = _DeleteFake(raise_on_delete=OllamaModelNotFoundError("not installed"))
    r = await _delete_model(ac, fake, "ghost-model")
    assert r.status_code == 404, r.text
    assert "not installed" in r.json()["detail"]


async def test_delete_endpoint_generic_failure_502(client_vk):
    ac, _ = client_vk
    fake = _DeleteFake(raise_on_delete=ModelProviderError("[ollama] delete failed: X"))
    r = await _delete_model(ac, fake, "bge-m3")
    assert r.status_code == 502, r.text


async def test_delete_endpoint_requires_model_name(client_vk):
    ac, _ = client_vk
    r = await ac.request("DELETE", "/api/v1/ollama/models", json={"model": ""})
    assert r.status_code == 422, r.text  # pydantic min_length


# --------------------------------------------------------------------------- #
# 5. API layer: warm-up + auto-warm
# --------------------------------------------------------------------------- #


class _FakeOllamaHTTP(BaseHTTPRequestHandler):
    """Tiny Ollama double for _do_warmup's real HTTP calls."""

    def log_message(self, *a):  # silence test output
        pass

    def do_POST(self):  # stdlib BaseHTTPRequestHandler protocol name, not our choice
        length = int(self.headers.get("Content-Length", 0))
        self.rfile.read(length)
        body = json.dumps({"model": "bge-m3", "embeddings": [[0.1, 0.2]]}).encode()
        self.send_response(200)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)


@pytest.fixture
async def fake_ollama_url():
    srv = ThreadingHTTPServer(("127.0.0.1", 0), _FakeOllamaHTTP)
    thread = threading.Thread(target=srv.serve_forever, daemon=True)
    thread.start()
    yield f"http://127.0.0.1:{srv.server_port}"
    srv.shutdown()
    srv.server_close()


async def test_warmup_endpoint_reaches_warm(client_vk, fake_ollama_url, monkeypatch):
    """POST /ollama/warmup → status warming → (coroutine run) → status warm.

    The endpoint schedules _do_warmup as a background task; on loaded CI
    runners that task can starve past a fixed polling window (observed as a
    flake: status stuck at 'warming'), so the test cancels the scheduled
    task and awaits the very same coroutine directly — deterministic, real
    TCP to the fake Ollama, no scheduling race. The endpoint wiring
    (POST → task + warming status → GET status shape) is still asserted.
    """
    import asyncio

    import api.system as system_mod

    monkeypatch.setattr(
        system_mod,
        "get_settings",
        lambda: SimpleNamespace(ollama_base_url=fake_ollama_url),
    )
    ac, _ = client_vk
    r = await ac.post("/api/v1/ollama/warmup", json={"model": "bge-m3"})
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["ok"] is True
    assert body["already_running"] is False

    # Status endpoint reports the warm-up (warming now, or already warm when
    # the background task finished within the response's own yields).
    s = await ac.get("/api/v1/ollama/warmup/status", params={"model": "bge-m3"})
    assert s.json()["status"] in ("warming", "warm"), s.json()

    # Replace scheduling with a deterministic await of the same coroutine.
    task = system_mod._warmup_tasks.get("bge-m3")
    assert task is not None
    if not task.done():
        task.cancel()
        try:
            await task
        except asyncio.CancelledError:
            pass
    await system_mod._do_warmup("bge-m3")

    s = await ac.get("/api/v1/ollama/warmup/status", params={"model": "bge-m3"})
    body = s.json()
    assert body["status"] == "warm", body
    assert body["error"] is None
    assert body["seconds"] >= 0

    # A POST while a warm-up is already running reports it, not a restart.
    system_mod._warmup_status.pop("bge-m3", None)
    system_mod._warmup_status["bge-m3"] = {"status": "warming", "seconds": 0, "error": None}
    r2 = await ac.post("/api/v1/ollama/warmup", json={"model": "bge-m3"})
    assert r2.status_code == 200, r2.text
    assert r2.json()["already_running"] is True


async def test_warmup_status_not_started(client_vk):
    ac, _ = client_vk
    s = await ac.get("/api/v1/ollama/warmup/status", params={"model": "never-warmed"})
    assert s.status_code == 200
    assert s.json()["status"] == "not_started"


async def test_autowarm_hook_selects_embedding_models_only(client_vk, fake_ollama_url, monkeypatch):
    import asyncio

    import api.system as system_mod

    monkeypatch.setattr(
        system_mod,
        "get_settings",
        lambda: SimpleNamespace(ollama_base_url=fake_ollama_url),
    )
    # Text LLM → no warm-up.
    assert system_mod._start_warmup_if_embedding("llama3.2:3b") is False
    assert "llama3.2:3b" not in system_mod._warmup_status
    # Tagged embedding model → warm-up task scheduled with the auto flag.
    started = system_mod._start_warmup_if_embedding("nomic-embed-text:latest")
    assert started is True
    assert system_mod._warmup_status["nomic-embed-text:latest"]["status"] == "warming"
    assert system_mod._warmup_status["nomic-embed-text:latest"]["auto"] is True
    # Complete the scheduled task deterministically (no scheduling race).
    task = system_mod._warmup_tasks.get("nomic-embed-text:latest")
    assert task is not None
    if not task.done():
        await asyncio.wait({task}, timeout=30)
    if not task.done():  # starved past the window → run the coroutine inline
        task.cancel()
        try:
            await task
        except asyncio.CancelledError:
            pass
        await system_mod._do_warmup("nomic-embed-text:latest")
    st = system_mod._warmup_status["nomic-embed-text:latest"]
    assert st["status"] == "warm", st
    assert st["auto"] is True
