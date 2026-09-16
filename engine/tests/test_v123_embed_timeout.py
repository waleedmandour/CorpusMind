"""v1.2.3 regression tests — Vector KWIC embed TIMEOUT misclassification.

User-reported failure on v1.2.2: the first Vector KWIC call after Ollama
starts must load bge-m3 (~1.2 GB) into RAM. That cold load routinely exceeded
the old implicit 30 s timeout; httpx timeouts stringify to an EMPTY string,
so the user saw `Embedding failed with model 'bge-m3': ` and the API layer
answered 409 embedding_model_missing ("run ollama pull") — wrong advice, the
model WAS installed.

Fixes covered here:
1. OllamaProvider embeds via the modern batch /api/embed endpoint with
   request-level keep_alive (model stays resident) and a 120 s default.
2. One automatic retry on timeout; a timeout that survives the retry raises
   EmbeddingTimeoutError (typed, non-empty message) instead of a bare
   ModelProviderError with an empty string.
3. _embed_texts maps ai.providers.EmbeddingTimeoutError →
   semantic.vector_kwic.EmbeddingModelTimeoutError.
4. The API answers 503 embedding_timeout (warm-up hint) — never again the
   misleading 409 embedding_model_missing for an installed-but-cold model.
5. Ancient Ollama (< 0.1.32, no /api/embed) falls back to legacy
   /api/embeddings instead of failing.
"""
from __future__ import annotations

import asyncio
import json
import os

import httpx
import pytest

# Canonical in-memory-DB env (mirrors test_vector_kwic.py) BEFORE engine imports.
os.environ["CORPUSMIND_DB_URL"] = "sqlite+aiosqlite:///:memory:"
os.environ["CORPUSMIND_DATA_DIR"] = "/tmp/cm-test-v123-embed-timeout"
os.environ["CORPUSMIND_OLLAMA_BASE_URL"] = "http://127.0.0.1:1"  # no real Ollama

from ai.providers import EmbeddingTimeoutError, OllamaProvider  # provider-layer class
from semantic.vector_kwic import (  # semantic-layer wrapper (distinct name on purpose)
    EmbeddingModelError,
    EmbeddingModelTimeoutError,
    _embed_texts,
)

# --------------------------------------------------------------------------- #
# Helpers: OllamaProvider wired to an httpx.MockTransport "Ollama"
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


def test_embed_batch_uses_modern_api_with_keep_alive():
    """Batch embed → ONE POST /api/embed with input[] list + keep_alive pin."""
    seen: dict = {}

    def handler(request: httpx.Request) -> httpx.Response:
        seen["path"] = request.url.path
        seen["payload"] = json.loads(request.content.decode())
        return httpx.Response(200, json={
            "model": "bge-m3",
            "embeddings": [[0.1, 0.2, 0.3], [0.4, 0.5, 0.6]],
        })

    p = _make_provider(handler)
    try:
        resps = asyncio.run(p.embed_batch(["hello", "world"], model="bge-m3"))
    finally:
        asyncio.run(p._client.aclose())

    assert seen["path"] == "/api/embed"
    assert seen["payload"]["input"] == ["hello", "world"]      # batch input list
    assert seen["payload"]["keep_alive"]                        # model stays resident
    assert [list(r.vector) for r in resps] == [[0.1, 0.2, 0.3], [0.4, 0.5, 0.6]]
    assert all(r.model == "bge-m3" for r in resps)


def test_embed_timeout_retries_once_then_succeeds():
    """A slow (cold-load) first call must be retried — not failed outright.

    Uses a REAL TCP server: MockTransport handlers run on the event loop, so
    a sleeping handler there can never be interrupted by a timeout."""
    import threading
    from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

    calls = {"n": 0}

    class SlowThenFastOllama(BaseHTTPRequestHandler):
        def log_message(self, *a):  # silence test output
            pass

        def do_POST(self):  # stdlib BaseHTTPRequestHandler protocol name, not our choice
            calls["n"] += 1
            length = int(self.headers.get("Content-Length", 0))
            self.rfile.read(length)
            if calls["n"] == 1:
                import time

                time.sleep(0.4)  # cold load blows past the tiny client timeout
            body = json.dumps({"model": "bge-m3", "embeddings": [[1.0, 2.0]]}).encode()
            try:
                self.send_response(200)
                self.send_header("Content-Type", "application/json")
                self.send_header("Content-Length", str(len(body)))
                self.end_headers()
                self.wfile.write(body)
            except (BrokenPipeError, ConnectionResetError):
                pass  # client already timed out and disconnected

    srv = ThreadingHTTPServer(("127.0.0.1", 0), SlowThenFastOllama)
    threading.Thread(target=srv.serve_forever, daemon=True).start()
    try:
        s = _FakeSettings()
        s.ollama_base_url = f"http://127.0.0.1:{srv.server_address[1]}"
        p = OllamaProvider(s)
        try:
            resps = asyncio.run(p.embed_batch(["warmup"], model="bge-m3", timeout=0.1))
        finally:
            asyncio.run(p._client.aclose())
        assert calls["n"] == 2, "the timed-out first attempt must be retried once"
        assert resps[0].vector == [1.0, 2.0]
    finally:
        srv.shutdown()


def test_embed_timeout_after_retry_raises_typed_nonempty_error():
    """A timeout that survives the retry → EmbeddingTimeoutError whose message
    names the exception type (the v1.2.2 bug surfaced an EMPTY message)."""
    import threading
    from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

    class AlwaysSlowOllama(BaseHTTPRequestHandler):
        def log_message(self, *a):  # silence test output
            pass

        def do_POST(self):  # stdlib BaseHTTPRequestHandler protocol name, not our choice
            length = int(self.headers.get("Content-Length", 0))
            self.rfile.read(length)
            import time

            time.sleep(0.3)  # always exceeds the tiny client timeout
            body = b"{}"
            try:
                self.send_response(200)
                self.send_header("Content-Length", str(len(body)))
                self.end_headers()
                self.wfile.write(body)
            except (BrokenPipeError, ConnectionResetError):
                pass  # client already timed out and disconnected

    srv = ThreadingHTTPServer(("127.0.0.1", 0), AlwaysSlowOllama)
    threading.Thread(target=srv.serve_forever, daemon=True).start()
    try:
        s = _FakeSettings()
        s.ollama_base_url = f"http://127.0.0.1:{srv.server_address[1]}"
        p = OllamaProvider(s)
        try:
            with pytest.raises(EmbeddingTimeoutError) as ei:
                asyncio.run(p.embed_batch(["warmup"], model="bge-m3", timeout=0.05))
        finally:
            asyncio.run(p._client.aclose())
    finally:
        srv.shutdown()

    msg = str(ei.value)
    assert msg.strip(), "timeout message must never be empty"
    assert "timed out" in msg
    assert "Timeout" in msg  # httpx exception type name included
    assert ei.value.timeout_s == pytest.approx(0.05)
    # Exactly the typed subclass — callers depend on the distinction.
    assert type(ei.value) is EmbeddingTimeoutError


def test_embed_batch_falls_back_to_legacy_on_404():
    """Ollama < 0.1.32 (no /api/embed) → legacy /api/embeddings per text."""

    def handler(request: httpx.Request) -> httpx.Response:
        if request.url.path == "/api/embed":
            return httpx.Response(404, json={"error": "not found"})
        assert request.url.path == "/api/embeddings"
        payload = json.loads(request.content.decode())
        return httpx.Response(200, json={"embedding": [0.9, 0.8], "model": payload["model"]})

    p = _make_provider(handler)
    try:
        resps = asyncio.run(p.embed_batch(["a", "b"], model="bge-m3"))
    finally:
        asyncio.run(p._client.aclose())

    assert [list(r.vector) for r in resps] == [[0.9, 0.8], [0.9, 0.8]]


# --------------------------------------------------------------------------- #
# _embed_texts mapping (provider layer → semantic layer)
# --------------------------------------------------------------------------- #


def test_embed_texts_maps_provider_timeout_to_embedding_timeout():
    class ColdProvider:
        name = "ollama"

        async def list_models(self):
            return ["bge-m3:latest"]  # pre-flight PASSES (model installed)

        async def embed_batch(self, texts, *, model=None, timeout=None):
            raise EmbeddingTimeoutError(
                "[ollama] embed timed out: ReadTimeout after 120s x2 attempts",
                timeout_s=timeout,
            )

    with pytest.raises(EmbeddingModelTimeoutError) as ei:
        asyncio.run(_embed_texts(ColdProvider(), ["x"], "bge-m3"))
    assert "timed out" in ei.value.detail
    assert ei.value.model == "bge-m3"


def test_embed_texts_missing_model_still_maps_to_model_missing():
    """Non-timeout failures keep the v1.2.0 mapping (409-grade error)."""

    class AbsentProvider:
        name = "ollama"

        async def list_models(self):
            return []  # nothing installed → pre-flight fails

        async def embed_batch(self, texts, *, model=None, timeout=None):  # pragma: no cover
            raise AssertionError("pre-flight must reject before embedding")

    with pytest.raises(EmbeddingModelError):
        asyncio.run(_embed_texts(AbsentProvider(), ["x"], "bge-m3"))


# --------------------------------------------------------------------------- #
# API layer: installed-but-cold model → 503 embedding_timeout (NOT 409)
# --------------------------------------------------------------------------- #


class TimeoutBatchProvider:
    """Pre-flight passes, then the batch embed times out — the exact
    v1.2.2 user scenario (model pulled successfully, embed still 'failed')."""

    name = "ollama"

    async def list_models(self):
        return ["llama3.2:3b", "bge-m3:latest"]

    async def embed(self, text, *, model=None, timeout=None):  # pragma: no cover
        raise AssertionError("batch path must be used")

    async def embed_batch(self, texts, *, model=None, timeout=None):
        raise EmbeddingTimeoutError(
            f"[ollama] embed timed out: ReadTimeout after {timeout:.0f}s x2 attempts "
            f"(model '{model}')",
            timeout_s=timeout,
        )


@pytest.fixture
async def client_timeout_provider():
    from httpx import ASGITransport, AsyncClient

    import storage.session as _ss
    from app.main import app
    from storage.session import dispose_db
    from tests.test_vector_kwic import _seed_corpus

    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as ac:
        async with app.router.lifespan_context(app):
            cid = await _seed_corpus(_ss._sessionmaker)
            app.state.providers._instances["ollama"] = TimeoutBatchProvider()
            yield ac, cid
    await dispose_db()


async def test_vector_kwic_timeout_answers_503_embedding_timeout(client_timeout_provider):
    ac, cid = client_timeout_provider
    r = await ac.post(f"/api/v1/corpora/{cid}/concordance/vector", json={
        "query": "climate policy", "node": "climate", "model": "bge-m3",
    })
    assert r.status_code == 503, r.text
    detail = r.json()["detail"]
    assert detail["error"] == "embedding_timeout"
    assert detail["model"] == "bge-m3"
    # Warm-up guidance instead of the misleading "run ollama pull".
    assert "ollama pull" not in detail["hint"]
    assert "load" in detail["hint"].lower()
    assert "curl" in detail["warmup_cmd"]
    assert "bge-m3" in detail["warmup_cmd"]
