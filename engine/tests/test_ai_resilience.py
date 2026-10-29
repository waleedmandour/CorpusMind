"""v2.0.1 tests — transient-failure retry for model-provider calls.

User report: the AI assistant chat intermittently died with
"HTTP 502: Model call failed" on the FIRST transient hiccup (Ollama
restarting under RAM pressure, LM Studio keep-alive drops, cloud-gateway
502/503/429 blips). The provider layer now retries per the policy in
ai/resilience.py: transport errors and 408/425/429/5xx with full-jitter
exponential backoff, honoring Retry-After; 4xx client errors fail fast;
streaming retries only the connect/headers phase.
"""

from __future__ import annotations

import json
from typing import Any

import httpx
import pytest

from ai.providers import LMStudioProvider, Message, ModelProviderError, OllamaProvider
from ai.resilience import (
    RETRYABLE_STATUS,
    next_wait_s,
    post_with_resilience,
    stream_with_resilience,
)


def _settings_for_ollama() -> Any:
    from app.settings import Settings

    return Settings(
        ollama_base_url="http://test-ollama.invalid:11434",
        ollama_default_model="llama3.2",
        lmstudio_base_url="http://test-lmstudio.invalid:1234/v1",
        lmstudio_default_model="test-model",
    )


def _client(transport: httpx.MockTransport) -> httpx.AsyncClient:
    return httpx.AsyncClient(
        base_url="http://test.invalid",
        transport=transport,
        timeout=httpx.Timeout(5.0, connect=2.0),
    )


class _RecordingSleep:
    """Awaitable fake sleep that records waits instead of stalling tests."""

    def __init__(self) -> None:
        self.waits: list[float] = []

    async def __call__(self, seconds: float) -> None:
        self.waits.append(seconds)


def _ok_chat(body: dict[str, Any] | None = None) -> httpx.Response:
    payload = body or {
        "choices": [{"message": {"content": "hello"}, "model": "test-model"}]
    }
    return httpx.Response(200, json=payload)


# --------------------------------------------------------------------------- #
# policy unit tests
# --------------------------------------------------------------------------- #
def test_next_wait_is_full_jitter_bounded() -> None:
    for attempt in range(1, 8):
        for _ in range(50):
            w = next_wait_s(attempt, None)
            assert 0.0 <= w <= min(8.0, 0.5 * (2 ** (attempt - 1))) + 1e-9


def test_next_wait_honors_retry_after_with_cap() -> None:
    assert next_wait_s(1, 0.25) == 0.25
    assert next_wait_s(1, 3.0) == 3.0
    # a hostile / oversized Retry-After is capped at 15s
    assert next_wait_s(1, 120.0) == 15.0
    assert next_wait_s(5, 120.0) == 15.0


def test_retryable_status_set_is_conservative() -> None:
    # transient family present...
    assert {408, 429, 500, 502, 503, 504} <= RETRYABLE_STATUS
    # ...deterministic client errors NEVER retried
    assert not RETRYABLE_STATUS & {400, 401, 403, 404, 409, 422}


# --------------------------------------------------------------------------- #
# post_with_resilience
# --------------------------------------------------------------------------- #
async def test_post_retries_transport_error_then_succeeds() -> None:
    attempts: dict[str, int] = {"n": 0}

    def handler(request: httpx.Request) -> httpx.Response:
        attempts["n"] += 1
        if attempts["n"] < 3:
            raise httpx.ConnectError("server disconnected", request=request)
        return _ok_chat()

    sleep = _RecordingSleep()
    async with _client(httpx.MockTransport(handler)) as c:
        r = await post_with_resilience(c, "/v1/chat/completions", json={}, label="t", sleep=sleep)
    assert r.status_code == 200
    assert attempts["n"] == 3
    assert len(sleep.waits) == 2
    assert all(0.0 <= w <= 8.0 for w in sleep.waits)


async def test_post_retries_503_then_succeeds() -> None:
    attempts: dict[str, int] = {"n": 0}

    def handler(request: httpx.Request) -> httpx.Response:
        attempts["n"] += 1
        if attempts["n"] == 1:
            return httpx.Response(503, json={"error": "overloaded"})
        return _ok_chat()

    sleep = _RecordingSleep()
    async with _client(httpx.MockTransport(handler)) as c:
        r = await post_with_resilience(c, "/api/chat", json={}, label="t", sleep=sleep)
    assert r.status_code == 200
    assert attempts["n"] == 2


async def test_post_429_waits_retry_after() -> None:
    attempts: dict[str, int] = {"n": 0}

    def handler(request: httpx.Request) -> httpx.Response:
        attempts["n"] += 1
        if attempts["n"] == 1:
            return httpx.Response(429, json={"error": "rate limited"}, headers={"Retry-After": "0.25"})
        return _ok_chat()

    sleep = _RecordingSleep()
    async with _client(httpx.MockTransport(handler)) as c:
        r = await post_with_resilience(c, "/api/chat", json={}, label="t", sleep=sleep)
    assert r.status_code == 200
    assert sleep.waits == [0.25]


async def test_post_never_retries_4xx_client_errors() -> None:
    attempts: dict[str, int] = {"n": 0}

    def handler(request: httpx.Request) -> httpx.Response:
        attempts["n"] += 1
        return httpx.Response(401, json={"error": "bad key"})

    sleep = _RecordingSleep()
    async with _client(httpx.MockTransport(handler)) as c:
        r = await post_with_resilience(c, "/v1/chat/completions", json={}, label="t", sleep=sleep)
    assert r.status_code == 401
    assert attempts["n"] == 1
    assert sleep.waits == []


async def test_post_exhausts_budget_and_reraises_transport_error() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        raise httpx.ConnectError("refused", request=request)

    sleep = _RecordingSleep()
    async with _client(httpx.MockTransport(handler)) as c:
        with pytest.raises(httpx.ConnectError):
            await post_with_resilience(c, "/api/chat", json={}, label="t", sleep=sleep, attempts=3)
    assert len(sleep.waits) == 2  # waited between the 3 attempts


async def test_post_returns_final_retryable_response_when_exhausted() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(502, json={"error": "bad gateway"})

    sleep = _RecordingSleep()
    async with _client(httpx.MockTransport(handler)) as c:
        r = await post_with_resilience(c, "/api/chat", json={}, label="t", sleep=sleep)
    assert r.status_code == 502  # caller's raise_for_status handles it, as before


# --------------------------------------------------------------------------- #
# stream_with_resilience — connect/headers phase only
# --------------------------------------------------------------------------- #
async def test_stream_retries_connect_phase_then_streams() -> None:
    attempts: dict[str, int] = {"n": 0}

    def handler(request: httpx.Request) -> httpx.Response:
        attempts["n"] += 1
        if attempts["n"] == 1:
            raise httpx.ConnectError("reset", request=request)
        return httpx.Response(
            200,
            content=b'data: {"choices": [{"delta": {"content": "hi"}}]}\n\ndata: [DONE]\n\n',
            headers={"content-type": "text/event-stream"},
        )

    sleep = _RecordingSleep()
    async with _client(httpx.MockTransport(handler)) as c:
        r = await stream_with_resilience(c, "POST", "/v1/chat/completions", json={}, label="t", sleep=sleep)
        assert attempts["n"] == 2
        chunks: list[str] = []
        try:
            r.raise_for_status()
            async for line in r.aiter_lines():
                if line.startswith("data: ") and line[6:] != "[DONE]":
                    chunks.append(json.loads(line[6:])["choices"][0]["delta"]["content"])
        finally:
            await r.aclose()
    assert chunks == ["hi"]
    assert len(sleep.waits) == 1


async def test_stream_retryable_status_is_closed_and_retried() -> None:
    attempts: dict[str, int] = {"n": 0}

    def handler(request: httpx.Request) -> httpx.Response:
        attempts["n"] += 1
        if attempts["n"] == 1:
            return httpx.Response(504, json={"error": "gateway timeout"})
        return httpx.Response(
            200,
            content=b'data: {"choices": [{"delta": {"content": "ok"}}]}\n\n',
            headers={"content-type": "text/event-stream"},
        )

    sleep = _RecordingSleep()
    async with _client(httpx.MockTransport(handler)) as c:
        r = await stream_with_resilience(c, "POST", "/v1/chat/completions", json={}, label="t", sleep=sleep)
        try:
            r.raise_for_status()
            body = [line async for line in r.aiter_lines() if line.strip()]
        finally:
            await r.aclose()
    assert attempts["n"] == 2
    assert body and "ok" in body[0]


# --------------------------------------------------------------------------- #
# provider-level integration: chat() survives transient drops
# --------------------------------------------------------------------------- #
async def test_ollama_provider_chat_recovers_from_transient_drop() -> None:
    provider = OllamaProvider(_settings_for_ollama())
    attempts: dict[str, int] = {"n": 0}

    def handler(request: httpx.Request) -> httpx.Response:
        attempts["n"] += 1
        if request.url.path == "/api/chat":
            if attempts["n"] == 1:
                raise httpx.RemoteProtocolError(
                    "Server disconnected without sending a response", request=request
                )
            return httpx.Response(
                200,
                json={"message": {"role": "assistant", "content": "recovered"}, "done": True},
            )
        return httpx.Response(200, json={"models": []})

    original = provider._client
    provider._client = httpx.AsyncClient(
        base_url=original.base_url, transport=httpx.MockTransport(handler)
    )
    try:
        resp = await provider.chat([Message(role="user", content="hi")], timeout=5.0)
        assert resp.content == "recovered"
        assert attempts["n"] == 2
    finally:
        await provider._client.aclose()
        provider._client = original


async def test_lmstudio_provider_chat_surfaces_permanent_4xx_immediately() -> None:
    provider = LMStudioProvider(_settings_for_ollama())
    attempts: dict[str, int] = {"n": 0}

    def handler(request: httpx.Request) -> httpx.Response:
        attempts["n"] += 1
        return httpx.Response(401, json={"error": {"message": "invalid api key"}})

    original = provider._client
    provider._client = httpx.AsyncClient(
        base_url=original.base_url, transport=httpx.MockTransport(handler)
    )
    try:
        with pytest.raises(ModelProviderError, match="401"):
            await provider.chat([Message(role="user", content="hi")], timeout=5.0)
        assert attempts["n"] == 1
    finally:
        await provider._client.aclose()
        provider._client = original
