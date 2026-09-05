"""v1.2.0 tests — Ollama tool-call robustness (user-reported HTTP 502).

User's error:  HTTP 502: {"detail":"Model call failed: [ollama] tool-call
request failed: Client error '400 Bad Request' for url
'http://127.0.0.1:11434/v1/chat/completions'"}

Root causes fixed here (defense in depth):
  1. TOOL_SCHEMAS carried non-portable JSON-Schema keywords
     (default/minimum/maximum) that older Ollama releases 400 on —
     sanitize_tools_for_compat() strips them on the /v1 path.
  2. Models whose template lacks tool support 400 on ANY tool payload —
     _chat_openai_compat() now retries once WITHOUT tools (answer instead
     of a hard 502).
  3. Auto-selection picked the first /api/tags model, frequently an
     embedding model — pick_default_model() prefers a 'tools'-capable one,
     and supports_tools() lets the assistant skip the tool surface.
"""

from __future__ import annotations

import json
from typing import Any

import httpx
import pytest

from ai.providers import (
    Message,
    ModelProviderError,
    OllamaProvider,
    sanitize_tools_for_compat,
)


def _settings_for_ollama():
    from app.settings import Settings

    return Settings(
        ollama_base_url="http://test-ollama.invalid:11434",
        ollama_default_model="llama3.2",
        lmstudio_base_url="http://test-lmstudio.invalid:1234/v1",
        lmstudio_default_model="test-model",
    )


def _attach_mock_transport(provider: OllamaProvider, transport: httpx.MockTransport):
    original = provider._client
    provider._client = httpx.AsyncClient(
        base_url=original.base_url,
        headers=original.headers,
        transport=transport,
        timeout=httpx.Timeout(5.0, connect=2.0),
    )
    return original


# --------------------------------------------------------------------------- #
# Schema sanitizer
# --------------------------------------------------------------------------- #


def test_sanitize_strips_nonportable_keywords():
    """default/minimum/maximum (the keywords most likely to trip older
    Ollama Go structs) must not survive sanitization; portable keys and
    the description must."""
    tools = [
        {
            "type": "function",
            "function": {
                "name": "search_concordance",
                "description": "Search the corpus",
                "parameters": {
                    "type": "object",
                    "properties": {
                        "query": {
                            "type": "string",
                            "description": "The search term",
                            "default": "hello",
                            "minLength": 1,
                        },
                        "window": {
                            "type": "integer",
                            "default": 5,
                            "minimum": 1,
                            "maximum": 20,
                        },
                    },
                    "required": ["query"],
                },
            },
        }
    ]

    clean = sanitize_tools_for_compat(tools)
    props = clean[0]["function"]["parameters"]["properties"]

    assert set(props["query"].keys()) == {"type", "description"}
    assert set(props["window"].keys()) == {"type"}
    assert clean[0]["function"]["parameters"]["required"] == ["query"]
    assert clean[0]["function"]["description"] == "Search the corpus"


def test_sanitize_handles_bare_object_properties_and_missing_required():
    """The vision tools ship bare {\"type\": \"object\"} properties and the
    ping tool has no 'required' at all — both must survive sanitization
    (with a synthesized empty required array)."""
    tools = [
        {
            "type": "function",
            "function": {
                "name": "visual_grammar",
                "description": "Analyze image grammar",
                "parameters": {
                    "type": "object",
                    "properties": {
                        "colours": {"type": "object", "description": "colour dict"},
                        "ocr": {"type": "object", "description": "ocr dict"},
                    },
                    "required": ["colours", "composition", "ocr"],
                },
            },
        },
        {
            "type": "function",
            "function": {
                "name": "ping",
                "description": "Health-check tool.",
                "parameters": {"type": "object", "properties": {}},
            },
        },
    ]

    clean = sanitize_tools_for_compat(tools)
    vg_params = clean[0]["function"]["parameters"]
    assert vg_params["properties"]["colours"] == {
        "type": "object",
        "description": "colour dict",
    }
    assert vg_params["required"] == ["colours", "composition", "ocr"]

    ping_params = clean[1]["function"]["parameters"]
    assert ping_params["required"] == []  # synthesized


def test_sanitize_preserves_enum_and_items():
    tools = [
        {
            "type": "function",
            "function": {
                "name": "arabic_morphology",
                "parameters": {
                    "type": "object",
                    "properties": {
                        "dialect": {
                            "type": "string",
                            "enum": ["msa", "egy", "glf", "lev"],
                            "default": "msa",
                        },
                        "tags": {
                            "type": "array",
                            "items": {"type": "string", "minLength": 1},
                        },
                    },
                },
            },
        }
    ]
    clean = sanitize_tools_for_compat(tools)
    props = clean[0]["function"]["parameters"]["properties"]
    assert props["dialect"]["enum"] == ["msa", "egy", "glf", "lev"]
    assert "default" not in props["dialect"]
    assert props["tags"]["items"] == {"type": "string"}


# --------------------------------------------------------------------------- #
# No-tools fallback on 400
# --------------------------------------------------------------------------- #


def _tools_payload() -> list[dict[str, Any]]:
    return [
        {
            "type": "function",
            "function": {
                "name": "get_frequency",
                "description": "Word frequencies",
                "parameters": {
                    "type": "object",
                    "properties": {"corpus_id": {"type": "string"}},
                    "required": ["corpus_id"],
                },
            },
        }
    ]


@pytest.mark.asyncio
async def test_compat_400_retries_without_tools():
    """A 400 on the tools payload must be retried without tools; the user
    gets an answer (un-grounded) instead of 'HTTP 502: Model call failed'.
    The retry must carry the fallback hint and NO tools key."""
    calls: list[dict[str, Any]] = []

    def handler(req: httpx.Request) -> httpx.Response:
        body = json.loads(req.content.decode("utf-8"))
        calls.append(body)
        if "tools" in body:
            return httpx.Response(400, json={"error": "model does not support tools"})
        return httpx.Response(
            200,
            json={
                "model": "llama3.2",
                "choices": [
                    {
                        "message": {
                            "role": "assistant",
                            "content": "Tools were unavailable, but here is my answer.",
                        },
                    }
                ],
            },
        )

    provider = OllamaProvider(_settings_for_ollama())
    original = _attach_mock_transport(provider, httpx.MockTransport(handler))
    try:
        resp = await provider.chat(
            [Message(role="user", content="What are the top words?")],
            model="llama3.2",
            tools=_tools_payload(),
        )
    finally:
        await provider._client.aclose()
        provider._client = original

    assert resp.content == "Tools were unavailable, but here is my answer."
    assert resp.raw.get("_tools_fallback") is True
    assert len(calls) == 2
    assert "tools" in calls[0]  # first attempt carries tools
    assert "tools" not in calls[1]  # retry does not
    assert "tools" not in calls[1].get("response_format", {})
    hint_msgs = [
        m for m in calls[1]["messages"] if "Tool calling was rejected" in (m.get("content") or "")
    ]
    assert hint_msgs, "fallback hint system message missing from retry"


@pytest.mark.asyncio
async def test_compat_400_without_tools_includes_server_body():
    """When even the no-tools retry fails, the raised error must carry the
    server's body so users see WHY (was: bare httpx string, no detail)."""

    def handler(req: httpx.Request) -> httpx.Response:
        return httpx.Response(400, json={"error": "model 'x' not found"})

    provider = OllamaProvider(_settings_for_ollama())
    original = _attach_mock_transport(provider, httpx.MockTransport(handler))
    try:
        with pytest.raises(ModelProviderError) as exc_info:
            await provider.chat(
                [Message(role="user", content="hi")],
                model="x",
                tools=_tools_payload(),
            )
    finally:
        await provider._client.aclose()
        provider._client = original

    msg = str(exc_info.value)
    assert "server said" in msg
    assert "model 'x' not found" in msg


@pytest.mark.asyncio
async def test_compat_sends_sanitized_schemas_on_the_wire():
    """The schemas that actually go over the wire must be the SANITIZED
    ones (no default/minimum/maximum), not the raw TOOL_SCHEMAS."""
    captured: dict[str, Any] = {}

    def handler(req: httpx.Request) -> httpx.Response:
        captured["body"] = json.loads(req.content.decode("utf-8"))
        return httpx.Response(
            200,
            json={
                "model": "llama3.2",
                "choices": [{"message": {"role": "assistant", "content": "ok"}}],
            },
        )

    provider = OllamaProvider(_settings_for_ollama())
    original = _attach_mock_transport(provider, httpx.MockTransport(handler))
    try:
        await provider.chat(
            [Message(role="user", content="hi")],
            model="llama3.2",
            tools=_tools_payload(),
        )
    finally:
        await provider._client.aclose()
        provider._client = original

    wire_props = captured["body"]["tools"][0]["function"]["parameters"]["properties"]
    assert "default" not in wire_props["corpus_id"]
    assert wire_props["corpus_id"]["type"] == "string"
    assert captured["body"]["tools"][0]["function"]["parameters"]["required"] == ["corpus_id"]


# --------------------------------------------------------------------------- #
# Capability gate + smarter auto-selection
# --------------------------------------------------------------------------- #


def _tags_response(models: list[dict[str, Any]]) -> httpx.Response:
    return httpx.Response(200, json={"models": models})


@pytest.mark.asyncio
async def test_supports_tools_reads_capabilities():
    cases = [
        ({"name": "nomic-embed-text", "capabilities": ["embedding"]}, False),
        ({"name": "llama3.1:8b", "capabilities": ["completion", "tools"]}, True),
        # Older Ollama: no capability info → assume tools work (the
        # no-tools fallback covers whatever it rejects).
        ({"name": "old-model"}, True),
    ]
    for model_entry, expected in cases:
        provider = OllamaProvider(_settings_for_ollama())

        def handler(req: httpx.Request, _e=model_entry) -> httpx.Response:
            assert str(req.url).endswith("/api/tags")
            return _tags_response([_e])

        original = _attach_mock_transport(provider, httpx.MockTransport(handler))
        try:
            got = await provider.supports_tools(model_entry["name"])
        finally:
            await provider._client.aclose()
            provider._client = original
        assert got is expected, f"{model_entry}: expected {expected}, got {got}"


@pytest.mark.asyncio
async def test_pick_default_model_prefers_tools_capability():
    """Auto-selection must skip embedding models: they made every grounded
    turn fail with 400 before v1.2.0."""
    models = [
        {"name": "nomic-embed-text:latest", "capabilities": ["embedding"]},
        {"name": "llama3.1:8b", "capabilities": ["completion", "tools"]},
        {"name": "moondream:latest", "capabilities": ["vision"]},
    ]
    provider = OllamaProvider(_settings_for_ollama())
    original = _attach_mock_transport(
        provider, httpx.MockTransport(lambda req: _tags_response(models))
    )
    try:
        picked = await provider.pick_default_model()
    finally:
        await provider._client.aclose()
        provider._client = original
    assert picked == "llama3.1:8b"


@pytest.mark.asyncio
async def test_pick_default_model_falls_back_to_first():
    provider = OllamaProvider(_settings_for_ollama())
    models = [{"name": "legacy-model"}]  # no capability info at all
    original = _attach_mock_transport(
        provider, httpx.MockTransport(lambda req: _tags_response(models))
    )
    try:
        picked = await provider.pick_default_model()
    finally:
        await provider._client.aclose()
        provider._client = original
    assert picked == "legacy-model"


@pytest.mark.asyncio
async def test_tools_fallback_only_retries_once_on_400():
    """A persistent 400 (even on the no-tools retry) must raise rather
    than loop forever."""

    def handler(req: httpx.Request) -> httpx.Response:
        body = json.loads(req.content.decode("utf-8"))
        status = 400 if "tools" in body else 500
        return httpx.Response(status, json={"error": "still broken"})

    provider = OllamaProvider(_settings_for_ollama())
    original = _attach_mock_transport(provider, httpx.MockTransport(handler))
    try:
        with pytest.raises(ModelProviderError):
            await provider.chat(
                [Message(role="user", content="hi")],
                model="llama3.2",
                tools=_tools_payload(),
            )
    finally:
        await provider._client.aclose()
        provider._client = original


if __name__ == "__main__":
    pytest.main([__file__, "-v", "--tb=short"])
