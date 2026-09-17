"""v1.2.5 regression tests — chunked /api/embed batches (CPU-host fix).

Background (user field report, Windows 11, CPU-only Ollama): Vector KWIC
embeds up to 1500 context windows; they used to go out as ONE /api/embed
request. A CPU-only Ollama needs minutes to answer that, so the client
ReadTimeout fired even though the model had just been warmed (2-3 s) —
and the automatic retry queued behind the still-running first attempt,
guaranteeing a second timeout.

v1.2.5 splits large batches into sequential sub-requests of
_embed_chunk_size() texts (default 64, CORPUSMIND_EMBED_BATCH override):
each request stays in the seconds range on CPU, results concatenate in
input order, and the timeout error now names BOTH failure modes
(cold load vs warm-large-batch-on-CPU) with the request size.
"""
from __future__ import annotations

import asyncio
import json
import os

import httpx
import pytest

os.environ.setdefault("CORPUSMIND_DB_URL", "sqlite+aiosqlite:///:memory:")
os.environ.setdefault("CORPUSMIND_DATA_DIR", "/tmp/cm-test-v125-chunking")

from ai.providers import EmbeddingTimeoutError, OllamaProvider


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


def _echo_ollama(request: httpx.Request) -> httpx.Response:
    """Reply with one vector per input text; the vector carries the text's
    numeric value so the test can verify exact ordering across chunks."""
    payload = json.loads(request.content.decode())
    return httpx.Response(
        200,
        json={
            "model": payload["model"],
            "embeddings": [[float(t)] for t in payload["input"]],
        },
    )


# --------------------------------------------------------------------------- #
# 1. Chunking behaviour
# --------------------------------------------------------------------------- #


def test_large_batch_is_chunked_and_order_preserved():
    """100 texts, default chunk 64 → requests of [64, 36]; concatenated
    vectors land in input order (the re-rank depends on it)."""
    seen_sizes: list[int] = []

    def handler(request: httpx.Request) -> httpx.Response:
        payload = json.loads(request.content.decode())
        seen_sizes.append(len(payload["input"]))
        assert payload["keep_alive"], "keep_alive must pin the model across chunks"
        return httpx.Response(
            200,
            json={
                "model": payload["model"],
                "embeddings": [[float(t)] for t in payload["input"]],
            },
        )

    p = _make_provider(handler)
    try:
        texts = [str(i) for i in range(100)]
        resps = asyncio.run(p.embed_batch(texts, model="nomic-embed-text"))
    finally:
        asyncio.run(p._client.aclose())

    assert seen_sizes == [64, 36]
    assert [r.vector[0] for r in resps] == [float(i) for i in range(100)]
    assert all(r.model == "nomic-embed-text" for r in resps)


def test_batch_at_chunk_boundary_stays_single_request():
    """64 texts (== chunk) → ONE request; 65 → two. No off-by-one."""
    seen_sizes: list[int] = []

    def handler(request: httpx.Request) -> httpx.Response:
        payload = json.loads(request.content.decode())
        seen_sizes.append(len(payload["input"]))
        return httpx.Response(
            200,
            json={
                "model": payload["model"],
                "embeddings": [[0.0] for _ in payload["input"]],
            },
        )

    p = _make_provider(handler)
    try:
        texts = [f"t{i}" for i in range(64)]
        asyncio.run(p.embed_batch(texts, model="bge-m3"))
        assert seen_sizes == [64]
        asyncio.run(p.embed_batch([*texts, "one-more"], model="bge-m3"))
        assert seen_sizes == [64, 64, 1]
    finally:
        asyncio.run(p._client.aclose())


def test_chunk_size_env_override(monkeypatch):
    """CORPUSMIND_EMBED_BATCH: honoured, floored at 1, bad values ignored."""
    p = OllamaProvider(_FakeSettings())

    monkeypatch.setenv("CORPUSMIND_EMBED_BATCH", "10")
    assert p._embed_chunk_size() == 10

    monkeypatch.setenv("CORPUSMIND_EMBED_BATCH", "0")  # below the floor
    assert p._embed_chunk_size() == 1

    monkeypatch.setenv("CORPUSMIND_EMBED_BATCH", "-5")  # negative → floor
    assert p._embed_chunk_size() == 1

    monkeypatch.setenv("CORPUSMIND_EMBED_BATCH", "banana")  # bad value → default
    assert p._embed_chunk_size() == OllamaProvider._EMBED_BATCH_CHUNK == 64

    monkeypatch.delenv("CORPUSMIND_EMBED_BATCH")
    assert p._embed_chunk_size() == 64

    monkeypatch.setenv("CORPUSMIND_EMBED_BATCH", "25")
    seen_sizes: list[int] = []

    def handler(request: httpx.Request) -> httpx.Response:
        payload = json.loads(request.content.decode())
        seen_sizes.append(len(payload["input"]))
        return httpx.Response(
            200,
            json={
                "model": payload["model"],
                "embeddings": [[0.0] for _ in payload["input"]],
            },
        )

    p2 = _make_provider(handler)
    try:
        asyncio.run(p2.embed_batch([f"t{i}" for i in range(30)], model="bge-m3"))
    finally:
        asyncio.run(p2._client.aclose())
    assert seen_sizes == [25, 5]


# --------------------------------------------------------------------------- #
# 2. Timeout semantics under chunking
# --------------------------------------------------------------------------- #


def test_timeout_error_names_batch_size_and_cpu_mode():
    """A timed-out request reports how many texts it carried and points
    warm-model users at the CPU-large-batch cause — not just cold load."""

    calls = {"n": 0}

    def handler(request: httpx.Request) -> httpx.Response:
        calls["n"] += 1
        raise httpx.ReadTimeout("simulated slow CPU host")

    p = _make_provider(handler)
    try:
        with pytest.raises(EmbeddingTimeoutError) as ei:
            asyncio.run(p.embed_batch(["a", "b", "c", "d", "e"], model="bge-m3"))
    finally:
        asyncio.run(p._client.aclose())

    msg = str(ei.value)
    assert calls["n"] == 2, "the timed-out attempt must still be retried once"
    assert "5 text(s)" in msg
    assert "CPU-only" in msg
    assert "CORPUSMIND_EMBED_TIMEOUT_S" in msg
    assert ei.value.timeout_s == 120.0  # default when no env/explicit override


def test_chunked_batch_timeout_identifies_failing_chunk_size():
    """With a 1-per-request override, the timeout message must reflect the
    chunk actually in flight (1 text), not the original batch size."""
    monkeypatch_env = {"CORPUSMIND_EMBED_BATCH": "1"}
    old = {k: os.environ.get(k) for k in monkeypatch_env}
    os.environ.update(monkeypatch_env)
    try:

        def handler(request: httpx.Request) -> httpx.Response:
            raise httpx.ReadTimeout("simulated slow CPU host")

        p = _make_provider(handler)
        try:
            with pytest.raises(EmbeddingTimeoutError) as ei:
                asyncio.run(
                    p.embed_batch(["first", "second"], model="bge-m3", timeout=30.0)
                )
        finally:
            asyncio.run(p._client.aclose())
        # First chunk ("first", 1 text) timed out twice → surfaced size is 1.
        assert "1 text(s)" in str(ei.value)
        assert ei.value.timeout_s == 30.0
    finally:
        for k, v in old.items():
            if v is None:
                os.environ.pop(k, None)
            else:
                os.environ[k] = v


# --------------------------------------------------------------------------- #
# 3. Legacy fallback unchanged under chunking
# --------------------------------------------------------------------------- #


def test_legacy_404_fallback_still_works_per_chunk():
    """Ollama < 0.1.32 (no /api/embed): each chunk falls back to per-text
    /api/embeddings and results still concatenate in order."""
    seen: list[tuple[str, str]] = []  # (path, prompt)

    def handler(request: httpx.Request) -> httpx.Response:
        payload = json.loads(request.content.decode())
        if request.url.path == "/api/embed":
            return httpx.Response(404, json={"error": "not found"})
        seen.append((request.url.path, payload["prompt"]))
        return httpx.Response(200, json={"embedding": [float(payload["prompt"])]})

    p = _make_provider(handler)
    try:
        resps = asyncio.run(
            p.embed_batch(["10", "20", "30"], model="bge-m3")
        )
    finally:
        asyncio.run(p._client.aclose())

    assert [path for path, _ in seen] == ["/api/embeddings"] * 3
    assert [r.vector[0] for r in resps] == [10.0, 20.0, 30.0]
