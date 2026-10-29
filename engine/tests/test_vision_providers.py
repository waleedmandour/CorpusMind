"""Tests for the vision-message wire format in ai/providers.py.

These tests were added as part of CorpusMind Lens build step 1:
extending `Message` with an `images: tuple[bytes, ...]` field and
threading it through both provider wire formats.

Two providers, two different wire shapes:

  - OllamaProvider (native /api/chat): a sibling `"images": [<b64>, ...]`
    field per message — `content` stays a plain string.
  - _OpenAICompatibleProvider (LM Studio + Cloud + Ollama tool-call
    fallback): `content` switches to a multipart array of
    {"type": "text", ...} + {"type": "image_url", ...} parts.

Both paths must produce byte-identical wire shapes for text-only messages
(the default — `images=()`) so existing call sites stay unchanged. Vision
messages must produce the correct shape AND survive a round-trip through
the provider's chat() method (the mock transport captures the request
body so we can assert against it).

These tests use httpx.MockTransport (built into httpx — no new dep) so
they run without any real Ollama / LM Studio instance. CI runs them on
every push.
"""
from __future__ import annotations

import base64
import json
import sys
from typing import Any

import httpx
import pytest

# Make the engine importable when run directly.
_ENGINE_DIR = "/home/z/my-project/CorpusMind/engine"
if _ENGINE_DIR not in sys.path:
    sys.path.insert(0, _ENGINE_DIR)

from ai.providers import (  # noqa: E402
    LMStudioProvider,
    Message,
    OllamaProvider,
    _build_ollama_message,
    _build_openai_message,
)
from app.settings import Settings  # noqa: E402

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

# A 1×1 transparent PNG. The smallest valid PNG. Tests need realistic
# bytes-to-base64-to-bytes round-tripping; using a real (if tiny) PNG
# rather than arbitrary bytes keeps the test honest against any future
# format sniffing the provider layer might add.
_PNG_BYTES = bytes.fromhex(
    "89504e470d0a1a0a0000000d49484452000000010000000108060000001f15c4"
    "890000000d49444154789c63000100000005000100"
    "0d0a2db4000000004945"
    "4e44ae426082"
)

# A 1×1 JPEG (also the smallest valid frame). Used to confirm the
# provider layer doesn't accidentally hard-code PNG-only behavior.
_JPEG_BYTES = bytes.fromhex(
    "ffd8ffe000104a46494600010100000100010000"
    "ffdb0043000302020302020303030304030304050805050404050a070706080c"
    "0a0c0c0b0a0b0b0d0e12100d0e110e0b0b1016101113141515150c0f17181614"
    "18141415"
    "ffc9000b080001000103011100ffcc00060010100501ffda00080101000003"
    "1100ffc0000806010001031100"
    "ffd9"
)


def _settings_for_ollama() -> Settings:
    """Build a Settings instance pointed at a fake Ollama URL.

    The URL is irrelevant — the mock transport intercepts before any
    network call. We just need a Settings object the provider can
    construct from.
    """
    # Build Settings without reading env vars that might leak the real
    # dev machine's Ollama URL into the test.
    return Settings(
        ollama_base_url="http://test-ollama.invalid:11434",
        ollama_default_model="llama3.2",
        lmstudio_base_url="http://test-lmstudio.invalid:1234/v1",
        lmstudio_default_model="test-model",
    )


def _settings_for_lmstudio() -> Settings:
    return _settings_for_ollama()  # same settings shape; URL differs per provider


def _make_mock_transport(handler: Any) -> httpx.MockTransport:
    """Wrap a request-handler callable in an httpx.MockTransport.

    The handler receives the httpx.Request and returns an httpx.Response.
    """
    return httpx.MockTransport(handler)


def _attach_mock_transport(provider: Any, transport: httpx.MockTransport) -> Any:
    """Replace a provider's internal httpx.AsyncClient with one that uses
    the given MockTransport. Returns the original client so the caller
    can restore it (we don't want to leak the mock across tests)."""
    original = provider._client
    provider._client = httpx.AsyncClient(
        base_url=original.base_url,
        headers=original.headers,
        transport=transport,
        # Match the production timeout config so tests don't accidentally
        # pass by timing out on a different code path.
        timeout=httpx.Timeout(5.0, connect=2.0),
    )
    return original


# ---------------------------------------------------------------------------
# Wire-format unit tests (no HTTP — pure function tests)
# ---------------------------------------------------------------------------


class TestOpenAIWireFormat:
    """_build_openai_message() — the pure function that translates one
    Message into the OpenAI /v1/chat/completions message shape."""

    def test_text_only_message_unchanged_shape(self):
        """Text-only messages must produce the exact same flat shape the
        provider has always sent — no `images` key, no array `content`.
        This is the load-bearing backward-compat assertion: if it fails,
        every existing text-only call site in the codebase would break.
        """
        m = Message(role="user", content="hello world")
        wire = _build_openai_message(m)
        assert wire == {"role": "user", "content": "hello world"}

    def test_text_only_message_with_name_preserves_name(self):
        """Tool messages include `name`. The fast path must preserve it."""
        m = Message(role="tool", content="result", name="search_concordance")
        wire = _build_openai_message(m)
        assert wire == {
            "role": "tool",
            "content": "result",
            "name": "search_concordance",
        }

    def test_system_message_with_images_still_works(self):
        """System messages with images aren't typical, but the function
        must not crash on them — content becomes a single text part
        followed by image parts."""
        m = Message(role="system", content="You are a vision model.", images=(_PNG_BYTES,))
        wire = _build_openai_message(m)
        assert wire["role"] == "system"
        assert isinstance(wire["content"], list)
        assert wire["content"][0] == {"type": "text", "text": "You are a vision model."}
        assert wire["content"][1]["type"] == "image_url"
        assert "url" in wire["content"][1]["image_url"]

    def test_vision_message_produces_multipart_content(self):
        """A user message with one image must switch `content` to a list
        of {type: text} + {type: image_url} parts, in that order."""
        m = Message(role="user", content="describe this", images=(_PNG_BYTES,))
        wire = _build_openai_message(m)

        assert wire["role"] == "user"
        assert isinstance(wire["content"], list)
        assert len(wire["content"]) == 2

        # Text part comes first
        assert wire["content"][0] == {"type": "text", "text": "describe this"}

        # Image part comes second
        img_part = wire["content"][1]
        assert img_part["type"] == "image_url"
        assert "image_url" in img_part
        url = img_part["image_url"]["url"]
        assert url.startswith("data:image/png;base64,")

        # The base64 payload must round-trip back to the original bytes
        b64_payload = url.split(",", 1)[1]
        decoded = base64.b64decode(b64_payload)
        assert decoded == _PNG_BYTES

    def test_vision_message_with_multiple_images(self):
        """Multiple images must produce one image_url part per image,
        in the order they appear in the tuple."""
        m = Message(
            role="user",
            content="compare these",
            images=(_PNG_BYTES, _JPEG_BYTES),
        )
        wire = _build_openai_message(m)
        assert len(wire["content"]) == 3  # 1 text + 2 images
        assert wire["content"][0]["type"] == "text"
        assert wire["content"][1]["type"] == "image_url"
        assert wire["content"][2]["type"] == "image_url"

    def test_vision_message_empty_content_omits_text_part(self):
        """If content is empty, the text part is omitted — only image
        parts are sent. (Some vision models reject an empty text part.)"""
        m = Message(role="user", content="", images=(_PNG_BYTES,))
        wire = _build_openai_message(m)
        assert isinstance(wire["content"], list)
        assert len(wire["content"]) == 1
        assert wire["content"][0]["type"] == "image_url"

    def test_vision_message_with_name_preserves_name(self):
        """Even vision messages must preserve the `name` field if set."""
        m = Message(
            role="user",
            content="describe this",
            name="vision_user",
            images=(_PNG_BYTES,),
        )
        wire = _build_openai_message(m)
        assert wire["name"] == "vision_user"


class TestOllamaWireFormat:
    """_build_ollama_message() — the pure function that translates one
    Message into the Ollama /api/chat message shape."""

    def test_text_only_message_unchanged_shape(self):
        """Text-only messages must produce the exact same flat shape the
        OllamaProvider has always sent — no `images` key."""
        m = Message(role="user", content="hello world")
        wire = _build_ollama_message(m)
        assert wire == {"role": "user", "content": "hello world"}

    def test_text_only_message_with_name_preserves_name(self):
        m = Message(role="tool", content="result", name="search_concordance")
        wire = _build_ollama_message(m)
        assert wire == {
            "role": "tool",
            "content": "result",
            "name": "search_concordance",
        }

    def test_vision_message_adds_sibling_images_field(self):
        """A message with images must add a sibling `"images"` field
        containing base64-encoded strings. `content` stays a plain
        string — this is the key difference from the OpenAI path."""
        m = Message(role="user", content="describe this", images=(_PNG_BYTES,))
        wire = _build_ollama_message(m)

        # content stays a plain string
        assert wire["role"] == "user"
        assert wire["content"] == "describe this"
        assert isinstance(wire["content"], str)

        # images rides alongside as a sibling field
        assert "images" in wire
        assert isinstance(wire["images"], list)
        assert len(wire["images"]) == 1
        assert isinstance(wire["images"][0], str)

        # The base64 string must round-trip back to the original bytes
        decoded = base64.b64decode(wire["images"][0])
        assert decoded == _PNG_BYTES

    def test_vision_message_with_multiple_images(self):
        m = Message(
            role="user",
            content="compare these",
            images=(_PNG_BYTES, _JPEG_BYTES),
        )
        wire = _build_ollama_message(m)
        assert len(wire["images"]) == 2
        assert base64.b64decode(wire["images"][0]) == _PNG_BYTES
        assert base64.b64decode(wire["images"][1]) == _JPEG_BYTES

    def test_vision_message_empty_images_tuple_omits_field(self):
        """An empty images tuple must NOT add an `images` key — keep the
        text-only wire shape byte-identical for backward compat."""
        m = Message(role="user", content="hello", images=())
        wire = _build_ollama_message(m)
        assert "images" not in wire

    def test_vision_message_with_name_preserves_name(self):
        m = Message(
            role="user",
            content="describe this",
            name="vision_user",
            images=(_PNG_BYTES,),
        )
        wire = _build_ollama_message(m)
        assert wire["name"] == "vision_user"


# ---------------------------------------------------------------------------
# End-to-end provider tests (HTTP-mocked, no real backend needed)
# ---------------------------------------------------------------------------


class TestOllamaProviderChatWithImages:
    """End-to-end: OllamaProvider.chat() with a vision Message must
    actually send the correct wire format over the wire. Uses
    httpx.MockTransport to intercept the request and assert against it."""

    @pytest.mark.asyncio
    async def test_vision_chat_sends_images_field(self):
        """The mock handler captures the request body; we assert the
        `images` field is present on the user message, base64-encoded,
        and round-trips to the original bytes."""
        captured: dict[str, Any] = {}

        def handler(req: httpx.Request) -> httpx.Response:
            captured["url"] = str(req.url)
            captured["body"] = json.loads(req.content.decode("utf-8"))
            return httpx.Response(
                200,
                json={
                    "model": "llama3.2",
                    "message": {"role": "assistant", "content": "It's a 1x1 PNG."},
                    "done": True,
                },
            )

        provider = OllamaProvider(_settings_for_ollama())
        original_client = _attach_mock_transport(provider, _make_mock_transport(handler))

        try:
            m = Message(role="user", content="describe this", images=(_PNG_BYTES,))
            r = await provider.chat([m], model="llama3.2")

            # Response sanity check
            assert r.content == "It's a 1x1 PNG."
            assert r.model == "llama3.2"
            assert r.provider == "ollama"

            # Wire-format assertions
            assert captured["url"].endswith("/api/chat")
            assert captured["body"]["model"] == "llama3.2"
            msgs = captured["body"]["messages"]
            assert len(msgs) == 1
            assert msgs[0]["role"] == "user"
            assert msgs[0]["content"] == "describe this"
            assert "images" in msgs[0]
            assert len(msgs[0]["images"]) == 1
            assert base64.b64decode(msgs[0]["images"][0]) == _PNG_BYTES
        finally:
            await provider._client.aclose()
            provider._client = original_client

    @pytest.mark.asyncio
    async def test_text_only_chat_unchanged_wire_format(self):
        """A text-only Message must produce the exact same request body
        the provider sent before this extension — no `images` key
        anywhere. This is the regression guard: if a future refactor
        accidentally adds an empty `images: []` field, real Ollama
        servers may reject it."""
        captured: dict[str, Any] = {}

        def handler(req: httpx.Request) -> httpx.Response:
            captured["body"] = json.loads(req.content.decode("utf-8"))
            return httpx.Response(
                200,
                json={
                    "model": "llama3.2",
                    "message": {"role": "assistant", "content": "Hello!"},
                    "done": True,
                },
            )

        provider = OllamaProvider(_settings_for_ollama())
        original_client = _attach_mock_transport(provider, _make_mock_transport(handler))

        try:
            m = Message(role="user", content="hello")
            r = await provider.chat([m], model="llama3.2")

            assert r.content == "Hello!"
            msgs = captured["body"]["messages"]
            assert len(msgs) == 1
            # Critical: NO images field on text-only messages
            assert "images" not in msgs[0]
            # Shape must be exactly role+content
            assert set(msgs[0].keys()) == {"role", "content"}
        finally:
            await provider._client.aclose()
            provider._client = original_client


class TestLMStudioProviderChatWithImages:
    """End-to-end: LMStudioProvider.chat() (extends
    _OpenAICompatibleProvider) with a vision Message must send the
    multipart content array shape."""

    @pytest.mark.asyncio
    async def test_vision_chat_sends_multipart_content(self):
        captured: dict[str, Any] = {}

        def handler(req: httpx.Request) -> httpx.Response:
            captured["url"] = str(req.url)
            captured["body"] = json.loads(req.content.decode("utf-8"))
            return httpx.Response(
                200,
                json={
                    "model": "test-model",
                    "choices": [
                        {
                            "message": {"role": "assistant", "content": "It's a tiny image."},
                            "finish_reason": "stop",
                            "index": 0,
                        }
                    ],
                },
            )

        provider = LMStudioProvider(_settings_for_lmstudio())
        original_client = _attach_mock_transport(provider, _make_mock_transport(handler))

        try:
            m = Message(role="user", content="describe this", images=(_PNG_BYTES,))
            r = await provider.chat([m], model="test-model")

            assert r.content == "It's a tiny image."

            # Wire-format assertions
            assert captured["url"].endswith("/v1/chat/completions")
            msgs = captured["body"]["messages"]
            assert len(msgs) == 1
            assert msgs[0]["role"] == "user"
            # content is now a list, not a string
            assert isinstance(msgs[0]["content"], list)
            assert msgs[0]["content"][0] == {"type": "text", "text": "describe this"}
            assert msgs[0]["content"][1]["type"] == "image_url"
            url = msgs[0]["content"][1]["image_url"]["url"]
            assert url.startswith("data:image/png;base64,")
            b64 = url.split(",", 1)[1]
            assert base64.b64decode(b64) == _PNG_BYTES
        finally:
            await provider._client.aclose()
            provider._client = original_client

    @pytest.mark.asyncio
    async def test_text_only_chat_unchanged_wire_format(self):
        """Text-only Message must produce the exact same request body
        the OpenAI-compatible provider sent before this extension."""
        captured: dict[str, Any] = {}

        def handler(req: httpx.Request) -> httpx.Response:
            captured["body"] = json.loads(req.content.decode("utf-8"))
            return httpx.Response(
                200,
                json={
                    "model": "test-model",
                    "choices": [
                        {
                            "message": {"role": "assistant", "content": "Hello!"},
                            "finish_reason": "stop",
                            "index": 0,
                        }
                    ],
                },
            )

        provider = LMStudioProvider(_settings_for_lmstudio())
        original_client = _attach_mock_transport(provider, _make_mock_transport(handler))

        try:
            m = Message(role="user", content="hello")
            r = await provider.chat([m], model="test-model")

            assert r.content == "Hello!"
            msgs = captured["body"]["messages"]
            assert len(msgs) == 1
            # Critical: content stays a plain string, NOT a list
            assert isinstance(msgs[0]["content"], str)
            assert msgs[0]["content"] == "hello"
            # Shape must be exactly role+content
            assert set(msgs[0].keys()) == {"role", "content"}
        finally:
            await provider._client.aclose()
            provider._client = original_client


# ---------------------------------------------------------------------------
# Cross-provider consistency
# ---------------------------------------------------------------------------


class TestProviderConsistency:
    """Both providers must agree on backward-compat: text-only messages
    produce NO images-related keys in the wire format. This is the
    guard against a refactor that accidentally adds `images: []` or
    `content: []` for text-only messages, which would silently change
    the request body shape every existing call site sends."""

    def test_ollama_text_only_has_no_images_key(self):
        m = Message(role="user", content="hello")
        wire = _build_ollama_message(m)
        assert "images" not in wire

    def test_openai_text_only_has_no_images_key(self):
        m = Message(role="user", content="hello")
        wire = _build_openai_message(m)
        assert "images" not in wire
        assert isinstance(wire["content"], str)

    def test_both_providers_preserve_message_order(self):
        """A multi-turn conversation (system → user → assistant → user)
        must preserve message order in the wire format for both
        providers. This catches any accidental reordering in the
        list-comprehension that builds the messages array."""
        msgs = [
            Message(role="system", content="You are helpful."),
            Message(role="user", content="First question."),
            Message(role="assistant", content="First answer."),
            Message(role="user", content="Follow-up."),
        ]
        ollama_wire = [_build_ollama_message(m) for m in msgs]
        openai_wire = [_build_openai_message(m) for m in msgs]

        for wire in (ollama_wire, openai_wire):
            assert [m["role"] for m in wire] == [
                "system",
                "user",
                "assistant",
                "user",
            ]
            assert [m["content"] for m in wire] == [
                "You are helpful.",
                "First question.",
                "First answer.",
                "Follow-up.",
            ]
