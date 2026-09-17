"""v1.2.5 regression tests — dropped/refused Ollama connections no longer
masquerade as a missing model (Windows 11 field report).

Background: Ollama crashed/restarted under RAM pressure mid-embed and the
client saw httpx.RemoteProtocolError ("Server disconnected without sending
a response"). That error is NOT a timeout and does not contain "not found",
so it fell into the generic EmbeddingModelError bucket → the API answered
409 embedding_model_missing ("Run: ollama pull bge-m3") — wrong advice when
the model IS installed (the /api/tags pre-flight had already passed).

v1.2.5: the embed retry now covers ANY httpx.TransportError (one cheap
retry), a exhausted budget on a non-timeout transport error raises
EmbeddingConnectionError → semantic EmbeddingModelUnreachableError →
API 502 embedding_unreachable with a restart hint. The 409 is reserved
for genuinely missing models.
"""
from __future__ import annotations

import asyncio
import os

import httpx
import pytest

os.environ.setdefault("CORPUSMIND_DB_URL", "sqlite+aiosqlite:///:memory:")
os.environ.setdefault("CORPUSMIND_DATA_DIR", "/tmp/cm-test-v125-unreachable")

from ai.providers import (
    EmbeddingConnectionError,
    EmbeddingTimeoutError,
    OllamaProvider,
)
from semantic.vector_kwic import (
    EmbeddingModelError,
    EmbeddingModelTimeoutError,
    EmbeddingModelUnreachableError,
    _embed_texts,
)


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


# --------------------------------------------------------------------------- #
# 1. Provider layer: transport errors retry once, then raise the typed error
# --------------------------------------------------------------------------- #


@pytest.mark.parametrize("exc", [httpx.RemoteProtocolError("boom"), httpx.ConnectError("no")])
def test_connection_errors_retry_once_then_typed_error(exc):
    calls = {"n": 0}

    def handler(request: httpx.Request) -> httpx.Response:
        calls["n"] += 1
        raise exc

    p = _make_provider(handler)
    try:
        with pytest.raises(EmbeddingConnectionError) as ei:
            asyncio.run(p.embed_batch(["a", "b"], model="bge-m3"))
    finally:
        asyncio.run(p._client.aclose())

    assert calls["n"] == 2, "a dropped/refused connection must get the one retry"
    msg = str(ei.value)
    assert "connection failed" in msg
    assert "2 text(s)" in msg
    assert "no pull is needed" in msg
    assert isinstance(ei.value, EmbeddingConnectionError)


def test_timeout_still_raises_embedding_timeout_error():
    """The widened retryable set must not change the timeout classification."""

    def handler(request: httpx.Request) -> httpx.Response:
        raise httpx.ReadTimeout("simulated")

    p = _make_provider(handler)
    try:
        with pytest.raises(EmbeddingTimeoutError) as ei:
            asyncio.run(p.embed_batch(["a"], model="bge-m3", timeout=30.0))
    finally:
        asyncio.run(p._client.aclose())

    assert ei.value.timeout_s == 30.0


def test_connection_error_is_not_a_timeout_error():
    """The two classes must stay distinct so the API can answer 502 vs 503."""
    assert not issubclass(EmbeddingConnectionError, EmbeddingTimeoutError)


# --------------------------------------------------------------------------- #
# 2. Semantic layer: unreachable, NOT missing
# --------------------------------------------------------------------------- #


class _DroppingProvider:
    """Mimics a provider whose embed_batch hits a crashed Ollama."""

    async def list_models(self):
        return ["bge-m3:latest"]  # pre-flight PASSES — the model is installed

    async def embed_batch(self, texts, *, model=None, timeout=None):
        from ai.providers import EmbeddingConnectionError as E

        raise E("[ollama] embed connection failed: RemoteProtocolError")


class _LegacyGenericProvider:
    """Non-timeout, non-connection failures keep the old 409 mapping."""

    async def list_models(self):
        return ["bge-m3:latest"]

    async def embed_batch(self, texts, *, model=None, timeout=None):
        raise RuntimeError("Embedding failed with model 'bge-m3': 404 not found")


def test_embed_texts_maps_connection_error_to_unreachable():
    with pytest.raises(EmbeddingModelUnreachableError) as ei:
        asyncio.run(_embed_texts(_DroppingProvider(), ["x"], "bge-m3"))
    assert "Server disconnected" in ei.value.detail or "connection failed" in ei.value.detail
    assert ei.value.model == "bge-m3"


def test_unreachable_is_a_model_error_subclass_for_backward_compat():
    """Older callers catching EmbeddingModelError keep working."""
    assert issubclass(EmbeddingModelUnreachableError, EmbeddingModelError)


def test_embed_texts_keeps_genuine_404_as_missing_model():
    with pytest.raises(EmbeddingModelError) as ei:
        asyncio.run(_embed_texts(_LegacyGenericProvider(), ["x"], "bge-m3"))
    assert "not installed" in str(ei.value)
    assert not isinstance(ei.value, EmbeddingModelUnreachableError)


def test_embed_texts_keeps_timeout_mapping():
    class _TimeoutProvider:
        async def list_models(self):
            return ["bge-m3:latest"]

        async def embed_batch(self, texts, *, model=None, timeout=None):
            from ai.providers import EmbeddingTimeoutError as E

            raise E("[ollama] embed timed out: ReadTimeout after 120s x2 attempts",
                    timeout_s=120.0)

    with pytest.raises(EmbeddingModelTimeoutError):
        asyncio.run(_embed_texts(_TimeoutProvider(), ["x"], "bge-m3"))


# --------------------------------------------------------------------------- #
# 3. API layer: 502 embedding_unreachable (before the 409 handler)
# --------------------------------------------------------------------------- #


class _UnreachableBatchProvider:
    """Raises the PROVIDER-layer error, mirroring the real OllamaProvider
    (the semantic-layer mapping in _embed_texts does the translation)."""

    async def embed_batch(self, texts, *, model=None, timeout=None):
        raise EmbeddingConnectionError(
            "[ollama] embed connection failed: RemoteProtocolError after 2 "
            "attempts (model 'bge-m3', 1500 text(s) in the request)."
        )


@pytest.fixture
async def client_unreachable_provider():
    from httpx import ASGITransport, AsyncClient

    import storage.session as _ss
    from app.main import app
    from storage.session import dispose_db
    from tests.test_vector_kwic import _seed_corpus

    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as ac:
        async with app.router.lifespan_context(app):
            cid = await _seed_corpus(_ss._sessionmaker)
            app.state.providers._instances["ollama"] = _UnreachableBatchProvider()
            yield ac, cid
    await dispose_db()


async def test_vector_kwic_connection_drop_answers_502_embedding_unreachable(
    client_unreachable_provider,
):
    ac, cid = client_unreachable_provider
    r = await ac.post(f"/api/v1/corpora/{cid}/concordance/vector", json={
        "query": "climate policy", "node": "climate", "model": "bge-m3",
    })
    assert r.status_code == 502, r.text
    detail = r.json()["detail"]
    assert detail["error"] == "embedding_unreachable"
    assert detail["model"] == "bge-m3"
    # Restart advice, never the misleading "run ollama pull".
    assert "ollama pull" not in detail["hint"]
    assert "installed" in detail["hint"]
    assert "Ollama" in detail["hint"]
    assert "RemoteProtocolError" in detail["note"]
