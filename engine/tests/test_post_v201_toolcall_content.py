"""post-v2.0.1 — tool-call replies without `content` are valid, not a shape error.

Regression: ``_OpenAICompatibleProvider.chat()`` read
``data["choices"][0]["message"]["content"]`` directly. OpenAI-compatible
backends (LM Studio, any /v1 gateway, Gemini's OpenAI-compat endpoint) may
omit the ``content`` key or send ``"content": null`` when the model answers
with ``tool_calls`` only — that raised a spurious
``ModelProviderError: unexpected response shape`` and killed the turn.

The Ollama /v1 tool-call path already guarded this with the
``msg.get("content") or ""`` idiom (``OllamaProvider._chat_openai_compat``);
``_OpenAICompatibleProvider.chat`` now does the same.

Fixture: an httpx.MockTransport reply carrying ``tool_calls`` and NO
``content`` key — the exact shape LM Studio / Gemini OpenAI-compat emit —
asserted for the missing-key and explicit-null variants, plus a plain-content
reply to prove the happy path is unchanged.
"""

from __future__ import annotations

import json
import sys
from typing import Any

import httpx
import pytest

# Make the engine importable when run directly.
_ENGINE_DIR = "/home/z/my-project/CorpusMind/engine"
if _ENGINE_DIR not in sys.path:
    sys.path.insert(0, _ENGINE_DIR)

from ai.providers import LMStudioProvider, Message  # noqa: E402
from app.settings import Settings  # noqa: E402

# A minimal tool_calls reply body, the shape that triggered the regression:
# message has NO `content` key at all.
_TOOLCALL_REPLY_NO_CONTENT_KEY: dict[str, Any] = {
    "model": "test-model",
    "choices": [
        {
            "index": 0,
            "finish_reason": "tool_calls",
            "message": {
                "role": "assistant",
                "tool_calls": [
                    {
                        "id": "call_1",
                        "type": "function",
                        "function": {
                            "name": "search_corpus",
                            "arguments": "{\"query\": \"قضايا المرأة\"}",
                        },
                    }
                ],
            },
        }
    ],
}

# Same reply, but with `"content": null` (the other emitted variant).
_TOOLCALL_REPLY_NULL_CONTENT = json.loads(json.dumps(_TOOLCALL_REPLY_NO_CONTENT_KEY))
_TOOLCALL_REPLY_NULL_CONTENT["choices"][0]["message"]["content"] = None

_PLAIN_REPLY: dict[str, Any] = {
    "model": "test-model",
    "choices": [
        {
            "index": 0,
            "finish_reason": "stop",
            "message": {"role": "assistant", "content": "مرحبا"},
        }
    ],
}


def _settings() -> Settings:
    return Settings(
        ollama_base_url="http://test-ollama.invalid:11434",
        ollama_default_model="llama3.2",
        lmstudio_base_url="http://test-lmstudio.invalid:1234/v1",
        lmstudio_default_model="test-model",
    )


def _wire(reply: dict[str, Any]) -> LMStudioProvider:
    """LM Studio provider wired to a MockTransport returning `reply`."""

    def handler(req: httpx.Request) -> httpx.Response:
        assert str(req.url).endswith("/v1/chat/completions")
        return httpx.Response(200, json=reply)

    provider = LMStudioProvider(_settings())
    original = provider._client
    provider._client = httpx.AsyncClient(
        base_url=original.base_url,
        headers=original.headers,
        transport=httpx.MockTransport(handler),
        timeout=httpx.Timeout(5.0, connect=2.0),
    )
    return provider


@pytest.mark.asyncio
async def test_tool_call_reply_without_content_key_is_valid() -> None:
    provider = _wire(_TOOLCALL_REPLY_NO_CONTENT_KEY)
    try:
        r = await provider.chat([Message(role="user", content="ابحث")], model="test-model")
        assert r.content == ""  # empty, NOT a ModelProviderError
        # tool calls stay reachable on raw for the caller
        msg = r.raw["choices"][0]["message"]
        assert msg["tool_calls"][0]["function"]["name"] == "search_corpus"
        assert r.provider == "lmstudio"
    finally:
        await provider._client.aclose()


@pytest.mark.asyncio
async def test_tool_call_reply_with_null_content_is_valid() -> None:
    provider = _wire(_TOOLCALL_REPLY_NULL_CONTENT)
    try:
        r = await provider.chat([Message(role="user", content="ابحث")], model="test-model")
        assert r.content == ""
        assert r.raw["choices"][0]["message"]["tool_calls"][0]["id"] == "call_1"
    finally:
        await provider._client.aclose()


@pytest.mark.asyncio
async def test_plain_content_reply_unchanged() -> None:
    provider = _wire(_PLAIN_REPLY)
    try:
        r = await provider.chat([Message(role="user", content="مرحبا")], model="test-model")
        assert r.content == "مرحبا"
        assert r.model == "test-model"
    finally:
        await provider._client.aclose()
