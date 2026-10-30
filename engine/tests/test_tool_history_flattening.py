"""post-v2.0.1 — pass-2 tool results are FLATTENED, never sent as bare tool messages.

Product bug (not a Gemini quirk): OpenAI's /v1/chat/completions contract
requires every ``role: "tool"`` message to follow an assistant message that
carries ``tool_calls`` (with matching ids). The assistant's grounded pass 2
appends bare ``Message(role="tool", ...)`` entries after a plain assistant
placeholder, so strict OpenAI-compatible backends (OpenAI itself, Gemini's
OpenAI-compat endpoint, Mistral, ...) answered 400 on every grounded cloud
turn. The 2026-10-30 3-question Gemini probe reproduced it end-to-end
(G-004: 502 wrapping Gemini's 400 on the pass-2 message sequence).

Fix: ``_OpenAICompatibleProvider`` flattens each run of tool messages into
ONE plain user block at the wire layer (``_flatten_tool_history``); it never
replays a synthetic ``tool_calls`` assistant message (Gemini 3.x attaches
thought signatures to tool calls that a replay would have to echo
byte-exactly — flattening avoids that question entirely). OllamaProvider's
native /api/chat path accepts bare tool messages and is untouched.

The mock server below ENFORCES the OpenAI rule — a message with role
"tool" whose predecessor is not an assistant message with "tool_calls"
gets the real OpenAI 400 body. That makes the regression test falsifiable:
the old wire shape fails against it, the new one passes.
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

from ai.providers import CloudProvider, Message, _build_ollama_message  # noqa: E402
from app.settings import Settings  # noqa: E402

_OPENAI_400_BODY = {
    "error": {
        "message": (
            "Invalid parameter: messages with role 'tool' must be a response to a "
            "preceding message with 'tool_calls'."
        ),
        "type": "invalid_request_error",
        "param": "messages.[2].role",
        "code": "invalid_value",
    }
}

_PASS2_REPLY: dict[str, Any] = {
    "model": "gemini-test",
    "choices": [
        {
            "index": 0,
            "finish_reason": "stop",
            "message": {"role": "assistant", "content": "The corpus has 12,345 tokens."},
        }
    ],
    "usage": {"prompt_tokens": 10, "completion_tokens": 5},
}


class _StrictServer:
    """Mock OpenAI-compat backend that enforces the tool_calls precondition."""

    def __init__(self) -> None:
        self.requests: list[dict[str, Any]] = []

    def handler(self, req: httpx.Request) -> httpx.Response:
        assert str(req.url).endswith("/v1/chat/completions")
        body = json.loads(req.content)
        self.requests.append(body)
        msgs = body.get("messages", [])
        for idx, m in enumerate(msgs):
            if m.get("role") != "tool":
                continue
            prev = msgs[idx - 1] if idx > 0 else None
            if (
                prev is None
                or prev.get("role") != "assistant"
                or "tool_calls" not in prev
            ):
                return httpx.Response(400, json=_OPENAI_400_BODY)
        return httpx.Response(200, json=_PASS2_REPLY)


def _cloud_settings(**overrides: Any) -> Settings:
    return Settings(
        cloud_provider="gemini",
        cloud_api_key="test-key",
        cloud_default_model="gemini-test",
        **overrides,
    )


def _wired_cloud(server: _StrictServer, settings: Settings | None = None) -> CloudProvider:
    provider = CloudProvider(settings or _cloud_settings())
    original = provider._client
    provider._client = httpx.AsyncClient(
        base_url=original.base_url,
        headers=original.headers,
        transport=httpx.MockTransport(server.handler),
        timeout=httpx.Timeout(5.0, connect=2.0),
    )
    return provider


# The exact message shape the assistant builds for grounded pass 2
# (assistant.py appends the placeholder, then one tool message per call).
def _pass2_history(interim: str = "") -> list[Message]:
    return [
        Message(role="system", content="You are the CorpusMind assistant."),
        Message(role="user", content="How many tokens are in the corpus?"),
        Message(role="assistant", content=interim or "(tool call)"),
        Message(
            role="tool",
            name="get_frequency",
            content=json.dumps({"total_tokens": 12345, "unit": "word"}),
        ),
        Message(
            role="tool",
            name="search_concordance",
            content=json.dumps({"lines": [{"line_id": 42}]}),
        ),
    ]


@pytest.mark.asyncio
async def test_pass2_tool_history_passes_strict_backend() -> None:
    """Grounded pass 2 must get 200 from a backend that enforces the rule."""
    server = _StrictServer()
    provider = _wired_cloud(server)
    try:
        r = await provider.chat(_pass2_history(), model="gemini-test")
        assert r.content == "The corpus has 12,345 tokens."
    finally:
        await provider._client.aclose()

    assert len(server.requests) == 1
    sent = server.requests[0]["messages"]
    # No role:"tool" message reaches the wire.
    assert all(m.get("role") != "tool" for m in sent)
    # The tool run became ONE user block, tool names + results preserved.
    blocks = [m for m in sent if m.get("role") == "user"]
    assert len(blocks) == 2  # the real user turn + the flattened tool block
    flat = blocks[-1]["content"]
    assert "[tool:get_frequency]" in flat and '"total_tokens": 12345' in flat.replace("'", '"')
    assert "[tool:search_concordance]" in flat
    # The placeholder assistant turn is gone.
    assert not any(
        m.get("role") == "assistant" and m.get("content") == "(tool call)" for m in sent
    )


@pytest.mark.asyncio
async def test_real_interim_assistant_text_is_kept() -> None:
    """If pass 1 emitted text alongside the tool calls, it stays in the history."""
    server = _StrictServer()
    provider = _wired_cloud(server)
    try:
        await provider.chat(_pass2_history(interim="Let me check the corpus."), model="gemini-test")
    finally:
        await provider._client.aclose()
    sent = server.requests[0]["messages"]
    assert any(
        m.get("role") == "assistant" and m.get("content") == "Let me check the corpus."
        for m in sent
    )


@pytest.mark.asyncio
async def test_history_without_tools_is_byte_identical() -> None:
    """No tool messages → no flattening; the plain path is unchanged."""
    server = _StrictServer()
    provider = _wired_cloud(server)
    try:
        await provider.chat(
            [Message(role="user", content="مرحبا")], model="gemini-test"
        )
    finally:
        await provider._client.aclose()
    sent = server.requests[0]["messages"]
    assert [m["role"] for m in sent] == ["user"]
    assert sent[0]["content"] == "مرحبا"


@pytest.mark.asyncio
async def test_old_wire_shape_rejected_by_the_same_server() -> None:
    """Control: the pre-fix payload (bare tool message) fails the strict rule.

    Posts the old shape directly through the same mock transport, proving
    the mock is not vacuously green.
    """
    server = _StrictServer()
    provider = _wired_cloud(server)
    old_style_payload = {
        "model": "gemini-test",
        "messages": [
            {"role": "system", "content": "s"},
            {"role": "user", "content": "q"},
            {"role": "assistant", "content": "(tool call)"},
            {"role": "tool", "name": "get_frequency", "content": "{}"},
        ],
        "temperature": 0.2,
        "stream": False,
    }
    try:
        r = await provider._client.post("/v1/chat/completions", json=old_style_payload)
        assert r.status_code == 400
        assert "tool_calls" in r.json()["error"]["message"]
    finally:
        await provider._client.aclose()


@pytest.mark.asyncio
async def test_reasoning_effort_sent_when_configured() -> None:
    server = _StrictServer()
    provider = _wired_cloud(server, _cloud_settings(cloud_reasoning_effort="low"))
    try:
        await provider.chat(_pass2_history(), model="gemini-test")
    finally:
        await provider._client.aclose()
    assert server.requests[0].get("reasoning_effort") == "low"


@pytest.mark.asyncio
async def test_reasoning_effort_absent_by_default() -> None:
    server = _StrictServer()
    provider = _wired_cloud(server)
    try:
        await provider.chat(_pass2_history(), model="gemini-test")
    finally:
        await provider._client.aclose()
    assert "reasoning_effort" not in server.requests[0]


def test_ollama_native_path_still_sends_role_tool() -> None:
    """Local-first path unchanged: Ollama's /api/chat keeps bare tool messages."""
    m = _build_ollama_message(Message(role="tool", content="result", name="get_frequency"))
    assert m["role"] == "tool" and m["name"] == "get_frequency"
