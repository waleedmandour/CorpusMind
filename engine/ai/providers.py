"""
ModelProvider abstraction (§11.4).

Three concrete implementations share one interface:
  - OllamaProvider   → http://127.0.0.1:11434  (native /api/chat + /api/tags)
  - LMStudioProvider → http://127.0.0.1:1234/v1 (OpenAI-compatible)
  - CloudProvider    → user-supplied API key, opt-in, OFF by default

OllamaProvider uses the NATIVE /api/chat endpoint (not /v1/chat/completions)
because:
  1. /api/chat is the recommended endpoint in Ollama's current API
  2. It supports the native "think": false parameter for Qwen3 models
  3. It handles system prompts more reliably with small models
  4. It returns a cleaner message.content structure

LMStudioProvider and CloudProvider use the OpenAI-compatible /v1 schema
because they don't have native alternatives.

All providers bypass proxies for loopback traffic (no_proxy=True) to
prevent corporate VPNs from silently intercepting localhost requests.
"""

from __future__ import annotations

import abc
import base64
import json
import time
from collections.abc import AsyncIterator
from dataclasses import dataclass, field
from typing import Any, Literal

import httpx

from app.logging import get_logger
from app.settings import Settings

log = get_logger(__name__)


# --------------------------------------------------------------------------- #
# Public types
# --------------------------------------------------------------------------- #

Role = Literal["system", "user", "assistant", "tool"]


@dataclass(frozen=True, slots=True)
class Message:
    role: Role
    content: str
    name: str | None = None  # for tool messages
    # Vision extension (CorpusMind Lens, build step 1): raw image bytes
    # attached to this message. PNG or JPEG. Empty tuple for text-only
    # messages (the default), so every existing text-only call site keeps
    # working unchanged. The provider layer is responsible for translating
    # this into the wire format expected by each backend:
    #   - OllamaProvider: sibling "images": [<base64 str>, ...] field per
    #     message in /api/chat. See https://github.com/ollama/ollama/blob/main/docs/api.md#generate-a-chat-completion
    #   - _OpenAICompatibleProvider (LM Studio + Cloud + Ollama tool-call
    #     fallback): content becomes a multipart array of
    #     {"type": "text", "text": ...} + {"type": "image_url",
    #     "image_url": {"url": "data:image/png;base64,<b64>"}} parts.
    # This field is intentionally a tuple (not a list) so the dataclass
    # stays hashable + safe to share between async tasks.
    images: tuple[bytes, ...] = ()


@dataclass(frozen=True, slots=True)
class ChatResponse:
    content: str
    model: str
    provider: str
    raw: dict[str, Any] = field(default_factory=dict)


@dataclass(frozen=True, slots=True)
class EmbeddingResponse:
    vector: list[float]
    model: str
    provider: str


def _debug_raw(data: Any) -> str:
    """Issue 13: raw provider responses can embed corpus-derived model output.

    Returning them inside error strings persists that content into logs and
    API error details (visible to other users on a shared engine). Raw bodies
    are only included when explicitly opted in via CORPUSMIND_DEBUG_RAW=1.
    """
    import os

    if os.environ.get("CORPUSMIND_DEBUG_RAW") == "1":
        return str(data)[:300]
    return "(raw response withheld — set CORPUSMIND_DEBUG_RAW=1 to include)"


class ModelProviderError(RuntimeError):
    """Base error for any provider failure (network, auth, model-missing, ...)."""


class CloudDisabledError(ModelProviderError):
    """Raised when cloud is hard-disabled in settings (§13.2 belt-and-suspenders)."""


# --------------------------------------------------------------------------- #
# Interface
# --------------------------------------------------------------------------- #


class ModelProvider(abc.ABC):
    """All providers implement chat(), stream(), and embed()."""

    name: str  # short identifier used in logs & UI badges

    @abc.abstractmethod
    async def chat(
        self,
        messages: list[Message],
        *,
        model: str | None = None,
        temperature: float = 0.2,
        tools: list[dict[str, Any]] | None = None,
        timeout: float | None = 60.0,
        json_mode: bool = False,
        max_tokens: int | None = None,
    ) -> ChatResponse: ...

    async def chat_json(
        self,
        messages: list[Message],
        *,
        model: str | None = None,
        temperature: float = 0.1,
        timeout: float | None = 60.0,
        max_tokens: int | None = None,
    ) -> ChatResponse:
        """Convenience wrapper that requests JSON-mode output.

        Issue 2b: small local models routinely wrap JSON in prose or code
        fences without a hard format constraint, causing json.loads() to
        fail in confidence.py and query_suggestions.py. This wrapper sets
        the provider-specific JSON-format flag so the model is forced to
        return valid JSON.

        Subclasses override chat() to honor the json_mode flag. The default
        implementation just calls chat() with json_mode=True.
        """
        return await self.chat(
            messages,
            model=model,
            temperature=temperature,
            timeout=timeout,
            json_mode=True,
            max_tokens=max_tokens,
        )

    @abc.abstractmethod
    async def stream(
        self,
        messages: list[Message],
        *,
        model: str | None = None,
        temperature: float = 0.2,
        timeout: float | None = None,
    ) -> AsyncIterator[str]: ...

    @abc.abstractmethod
    async def embed(
        self,
        text: str,
        *,
        model: str | None = None,
        timeout: float | None = 30.0,
    ) -> EmbeddingResponse: ...

    @abc.abstractmethod
    async def list_models(self) -> list[str]:
        """Return models currently available on this provider (best-effort)."""

    async def supports_tools(self, model: str | None = None) -> bool:
        """Whether ``model`` can do OpenAI-style tool calling.

        Default: assume yes. OllamaProvider overrides this using the
        ``capabilities`` list exposed by /api/tags so that embedding- or
        vision-only models never receive a tool payload (they 400 on it).
        """
        return True

    async def pick_default_model(self) -> str | None:
        """Model to auto-select when the caller didn't pick one.

        Default: first listed model. OllamaProvider prefers a model with
        the 'tools' capability so auto-selection doesn't silently disable
        grounding.
        """
        models = await self.list_models()
        return models[0] if models else None

    async def supports_vision(self, model: str | None = None) -> bool:
        """Whether ``model`` can accept image input (v1.2.0 Lens round).

        Default: False (assume NOT vision-capable). Providers that can
        answer reliably (Ollama via /api/tags capabilities, LM Studio via
        model-name heuristics) override this. Callers must treat a False
        as advisory: an explicit user-picked model is always honored.
        """
        return False

    async def pick_vision_model(self) -> str | None:
        """Vision-capable model to auto-select for image calls.

        Returns None when the provider cannot identify a vision-capable
        model — callers should then fall back to default resolution (or
        reject with an actionable message). Ollama/LM Studio override
        with capability-aware logic.
        """
        return None

    @abc.abstractmethod
    async def health(self) -> bool:
        """Return True iff the provider responds to a lightweight probe."""


# --------------------------------------------------------------------------- #
# Vision capability helpers (v1.2.0 Lens round)
# --------------------------------------------------------------------------- #

# Substrings that strongly suggest a model accepts image input. Used as a
# FALLBACK when a server doesn't expose per-model capabilities (older Ollama,
# LM Studio /v1/models which lists bare names).
_VISION_NAME_HINTS = (
    "vl",          # qwen2-vl, qwen2.5-vl, qwen3-vl
    "vision",      # llama3.2-vision, *vision*
    "llava",
    "moondream",
    "minicpm",
    "pixtral",
    "internvl",
    "gemma",       # gemma3 4b+ are multimodal
    "bakllava",
    "llama3.2-vision",
)


def _name_suggests_vision(name: str) -> bool:
    """Heuristic: does this model NAME suggest image input support?"""
    n = (name or "").lower()
    if not n:
        return False
    # gemma3 1b is text-only — exclude the small variant explicitly.
    if n.startswith("gemma3:1b") or n == "gemma3:1b":
        return False
    return any(h in n for h in _VISION_NAME_HINTS)


async def resolve_vision_model(provider: Any, explicit: str | None) -> str | None:
    """Resolve the model to use for a vision-LM call (describe/align/lenses).

    Resolution order:
      1. ``explicit`` — the user picked a model; always honored (even if the
         capability check would flag it — the user may know better).
      2. ``provider.pick_vision_model()`` — capability-aware pick (Ollama
         reads /api/tags 'vision' capability; LM Studio uses name hints).
      3. ``provider.default_model`` → first listed model — legacy fallback,
         kept for providers without a vision picker and for test doubles.

    Returns None when nothing resolvable. The vision-* endpoints turn a None
    into an actionable 400 rather than silently calling a text-only model.
    """
    if explicit:
        return explicit
    picker = getattr(provider, "pick_vision_model", None)
    if picker is not None:
        try:
            picked = picker()
            if hasattr(picked, "__await__"):
                picked = await picked
            if isinstance(picked, str) and picked:
                return picked
        except TypeError:
            # MagicMock-style test double whose auto-attribute isn't
            # awaitable — fall through to legacy resolution.
            pass
        except Exception as e:  # pragma: no cover — defensive
            log.warning("vision_model_pick_failed", error=str(e))
    model_name = getattr(provider, "default_model", None)
    if model_name:
        return model_name
    try:
        available = await provider.list_models()
        if available:
            return available[0]
    except Exception as e:
        log.warning("vision_model_list_failed", error=str(e))
    return None


async def check_vision_capability(provider: Any, model: str) -> bool | None:
    """Ask the provider whether ``model`` accepts image input.

    Returns True / False from a real capability check, or None when the
    provider cannot answer (no override, or a MagicMock-style test double
    whose auto-generated attribute isn't awaitable). Callers treat None as
    "proceed with legacy behavior".
    """
    checker = getattr(provider, "supports_vision", None)
    if checker is None:
        return None
    try:
        result = checker(model)
    except TypeError:
        return None
    if hasattr(result, "__await__"):
        try:
            return bool(await result)
        except TypeError:
            return None
        except Exception as e:  # pragma: no cover — defensive
            log.warning("vision_capability_check_failed", error=str(e))
            return None
    # Sync truthy (real override returned a bool, or a MagicMock placeholder)
    return bool(result)


# --------------------------------------------------------------------------- #
# Helper: Normalize Ollama base URL
# --------------------------------------------------------------------------- #


def _normalize_ollama_url(raw: str) -> str:
    """
    Normalize an Ollama base URL.

    Handles:
      - Bare host:port (e.g. "0.0.0.0:11434") -> "http://0.0.0.0:11434"
      - Bare host (e.g. "localhost") -> "http://localhost:11434"
      - Full URL with scheme -> used as-is
    """
    raw = raw.strip()
    if raw.startswith("http://") or raw.startswith("https://"):
        return raw.rstrip("/")
    if ":" in raw:
        return f"http://{raw.rstrip('/')}"
    return f"http://{raw}:11434".rstrip("/")


# --------------------------------------------------------------------------- #
# Helper: Strip thinking text from Qwen3 responses
# --------------------------------------------------------------------------- #


def _strip_thinking(text: str) -> str:
    """
    Strip Qwen3 thinking/reasoning text that leaks into the content field.

    Qwen3 sometimes puts English reasoning ("Okay, let's...") into content
    instead of the thinking field. This function finds the first non-English
    character and returns everything from that point.

    For corpus analysis tools, the "relevant" content is usually the actual
    answer, not the reasoning. We look for the first line that doesn't start
    with common thinking patterns.
    """
    trimmed = text.strip()
    if not trimmed:
        return ""

    # Strip <think>...</think> tags if present
    if "<think>" in trimmed:
        import re

        trimmed = re.sub(r"<think>.*?</think>", "", trimmed, flags=re.DOTALL).strip()

    if not trimmed:
        return ""

    # Common thinking patterns to strip from the beginning
    thinking_patterns = [
        "Okay, let's",
        "Let me",
        "The user wants",
        "I need to",
        "First, let's",
        "Alright,",
        "So,",
        "Now,",
        "Hmm,",
        "I should",
        "Let's think",
        "To answer",
    ]

    lines = trimmed.split("\n")
    result_lines = []
    in_thinking = True

    for line in lines:
        stripped = line.strip()
        if in_thinking:
            # Check if this line starts with a thinking pattern
            if any(stripped.lower().startswith(p.lower()) for p in thinking_patterns):
                continue  # Skip thinking lines
            # Check if this line looks like reasoning (starts with English
            # and contains thinking-like words)
            if stripped and stripped[0].isalpha() and stripped[0].isupper():
                if any(
                    w in stripped.lower()
                    for w in ["let's", "should", "need to", "going to", "first", "now i"]
                ):
                    continue
            # This line doesn't look like thinking
            in_thinking = False
        result_lines.append(line)

    result = "\n".join(result_lines).strip()
    return result if result else trimmed


# --------------------------------------------------------------------------- #
# Vision-message wire-format helpers (CorpusMind Lens, build step 1)
# --------------------------------------------------------------------------- #


def _build_openai_message(m: Message) -> dict[str, Any]:
    """Translate a Message into the OpenAI /v1/chat/completions message shape.

    Text-only messages (the default — `images` is empty) produce the same
    flat ``{"role", "content", "name"?}``` shape this provider has always
    sent, so existing text-only call sites are byte-identical before and
    after this change.

    Vision messages (any non-empty ``images`` tuple) switch `content` to
    the multipart array shape OpenAI introduced for GPT-4V and that every
    OpenAI-compatible vision endpoint (LM Studio, vLLM, LocalAI, Ollama's
    own /v1 endpoint, OpenAI itself, Anthropic's compat shim) accepts:
        content: [
            {"type": "text",      "text": "<the text content>"},
            {"type": "image_url", "image_url": {"url": "data:image/png;base64,<b64>"}},
            ...
        ]
    We use a base64 data URL rather than a plain URL because the image
    bytes already live in-process (the engine just fetched them from
    disk); going through a hosted URL would require either uploading
    them somewhere (violates local-first §4 Principle 1) or running a
    local file server inside the engine (a much larger change). The
    data URL is the standard pattern for local-first OpenAI-compatible
    vision clients.
    """
    if not m.images:
        # Fast path: text-only — preserve the exact pre-vision wire shape.
        msg: dict[str, Any] = {"role": m.role, "content": m.content}
        if m.name:
            msg["name"] = m.name
        return msg

    # Vision path: multipart content array.
    parts: list[dict[str, Any]] = []
    if m.content:
        parts.append({"type": "text", "text": m.content})
    for img_bytes in m.images:
        b64 = base64.b64encode(img_bytes).decode("ascii")
        # We don't sniff the format — the caller is responsible for passing
        # PNG or JPEG bytes (both supported by every OpenAI-compatible
        # vision endpoint). PNG is the safe default for screenshots /
        # synthetic test images; JPEG is the safe default for photographs.
        # The data URL scheme uses image/png as a generic label because
        # most OpenAI-compatible servers sniff the actual format from the
        # bytes rather than the MIME label, and the few that don't (real
        # OpenAI) accept either label for either format.
        parts.append(
            {
                "type": "image_url",
                "image_url": {"url": f"data:image/png;base64,{b64}"},
            }
        )
    msg = {"role": m.role, "content": parts}
    if m.name:
        msg["name"] = m.name
    return msg


def _build_ollama_message(m: Message) -> dict[str, Any]:
    """Translate a Message into the Ollama /api/chat message shape.

    Text-only messages produce the same flat shape OllamaProvider has
    always sent. Vision messages add a sibling ``"images"`` field
    containing base64-encoded strings — this is the native Ollama
    vision format (see Ollama's docs/api.md). Unlike the OpenAI path,
    Ollama does NOT switch `content` to an array; `content` stays a
    plain string and the images ride alongside it.
    """
    msg: dict[str, Any] = {"role": m.role, "content": m.content}
    if m.name:
        msg["name"] = m.name
    if m.images:
        msg["images"] = [base64.b64encode(b).decode("ascii") for b in m.images]
    return msg


# --------------------------------------------------------------------------- #
# OpenAI-compatible base (drives LM Studio and Cloud)
# --------------------------------------------------------------------------- #


class _OpenAICompatibleProvider(ModelProvider):
    """
    Shared implementation for anything that speaks OpenAI's /v1 schema.
    Concrete subclasses set `name`, `base_url`, and a default model.

    NOTE: OllamaProvider does NOT extend this class — it uses the native
    /api/chat endpoint instead. See OllamaProvider below.
    """

    name: str = "openai-compatible"
    base_url: str = ""
    default_model: str = ""
    tags_path: str = "/v1/models"
    auth_header: str | None = None

    def __init__(self, settings: Settings) -> None:
        self.settings = settings
        # Issue 7 fix: httpx CONCATENATES the client base path with the
        # request path (it does not follow RFC 3986 join semantics). With
        # base_url "https://api.openai.com/v1" and a request path
        # "/v1/chat/completions" the effective URL was
        # https://api.openai.com/v1/v1/chat/completions — a guaranteed 404
        # for BOTH cloud providers (openai and anthropic), verified with
        # httpx.build_request. The code writes full "/v1/..." paths, so the
        # client base must be host-root + any non-/v1 prefix.
        base = self.base_url.rstrip("/")
        if base.endswith("/v1"):
            base = base[: -len("/v1")]
        self._client = httpx.AsyncClient(
            base_url=base,
            timeout=httpx.Timeout(60.0, connect=5.0),
            headers=self._default_headers(),
            # Bypass proxies for loopback traffic (corporate VPN fix)
            proxy=None,
            trust_env=False,
        )

    def _default_headers(self) -> dict[str, str]:
        h = {"Content-Type": "application/json"}
        if self.auth_header:
            h["Authorization"] = self.auth_header
        return h

    async def aclose(self) -> None:
        await self._client.aclose()

    # --- chat ---
    async def chat(
        self,
        messages: list[Message],
        *,
        model: str | None = None,
        temperature: float = 0.2,
        tools: list[dict[str, Any]] | None = None,
        timeout: float | None = 60.0,
        json_mode: bool = False,
        max_tokens: int | None = None,
    ) -> ChatResponse:
        payload: dict[str, Any] = {
            "model": model or self.default_model,
            "messages": [_build_openai_message(m) for m in messages],
            "temperature": temperature,
            "stream": False,
        }
        if max_tokens:
            payload["max_tokens"] = max_tokens
        if tools:
            payload["tools"] = tools
        # Issue 2b: OpenAI-compatible JSON mode (supported by LM Studio and
        # most cloud providers). Sets response_format to json_object.
        if json_mode:
            payload["response_format"] = {"type": "json_object"}

        try:
            r = await self._client.post("/v1/chat/completions", json=payload, timeout=timeout)
            r.raise_for_status()
        except httpx.HTTPError as e:
            raise ModelProviderError(f"[{self.name}] chat request failed: {e}") from e

        data = r.json()
        try:
            content = data["choices"][0]["message"]["content"]
        except (KeyError, IndexError) as e:
            raise ModelProviderError(
                f"[{self.name}] unexpected response shape: {_debug_raw(data)}"
            ) from e
        return ChatResponse(
            content=content, model=data.get("model", payload["model"]), provider=self.name, raw=data
        )

    # --- stream ---
    async def stream(
        self,
        messages: list[Message],
        *,
        model: str | None = None,
        temperature: float = 0.2,
        timeout: float | None = None,
    ) -> AsyncIterator[str]:
        payload = {
            "model": model or self.default_model,
            "messages": [_build_openai_message(m) for m in messages],
            "temperature": temperature,
            "stream": True,
        }
        try:
            async with self._client.stream(
                "POST", "/v1/chat/completions", json=payload, timeout=timeout
            ) as r:
                r.raise_for_status()
                async for line in r.aiter_lines():
                    if not line or not line.startswith("data: "):
                        continue
                    body = line[6:].strip()
                    if body == "[DONE]":
                        return
                    try:
                        chunk = json.loads(body)
                        delta = chunk["choices"][0].get("delta", {}).get("content")
                        if delta:
                            yield delta
                    except (json.JSONDecodeError, KeyError, IndexError):
                        log.debug("unparsable_stream_chunk", provider=self.name, line=line[:200])
                        continue
        except httpx.HTTPError as e:
            raise ModelProviderError(f"[{self.name}] stream failed: {e}") from e

    # --- embed ---
    async def embed(
        self,
        text: str,
        *,
        model: str | None = None,
        timeout: float | None = 30.0,
    ) -> EmbeddingResponse:
        payload = {"model": model or "default", "input": text}
        try:
            r = await self._client.post("/v1/embeddings", json=payload, timeout=timeout)
            r.raise_for_status()
        except httpx.HTTPError as e:
            raise ModelProviderError(f"[{self.name}] embed failed: {e}") from e
        data = r.json()
        try:
            vec = data["data"][0]["embedding"]
        except (KeyError, IndexError) as e:
            raise ModelProviderError(f"[{self.name}] unexpected embedding shape: {data}") from e
        return EmbeddingResponse(
            vector=vec, model=data.get("model", payload["model"]), provider=self.name
        )

    # --- list models ---
    async def list_models(self) -> list[str]:
        try:
            r = await self._client.get(self.tags_path, timeout=10.0)
            r.raise_for_status()
        except httpx.HTTPError as e:
            log.warning("list_models_failed", provider=self.name, error=str(e))
            return []
        data = r.json()
        items = data.get("data") or data.get("models") or []
        return [m.get("id") or m.get("name") for m in items if isinstance(m, dict)]

    # --- health ---
    async def health(self) -> bool:
        try:
            r = await self._client.get(self.tags_path, timeout=5.0)
            return r.status_code == 200
        except httpx.HTTPError:
            return False


# --------------------------------------------------------------------------- #
# OllamaProvider — uses NATIVE /api/chat (not /v1/chat/completions)
# --------------------------------------------------------------------------- #


# --------------------------------------------------------------------------- #
# Tool-schema sanitization for OpenAI-compatible LOCAL servers
# --------------------------------------------------------------------------- #
# v1.2.0 (user-reported HTTP 502 "[ollama] tool-call request failed: 400").
# Older Ollama releases unmarshal tool parameters into a fixed Go struct
# that only knows {type, description, items, enum, properties, required} —
# any other JSON-Schema keyword (default/minimum/maximum/…) made the ENTIRE
# request fail with 400 Bad Request. Newer releases accept more keywords,
# but keep the payload conservative: these schemas go to LOCAL model
# servers (Ollama /v1, LM Studio) we don't control.

_COMPAT_SCHEMA_KEYS = frozenset(
    {
        "type",
        "description",
        "enum",
        "items",
        "properties",
        "required",
    }
)

# System hint injected when a server rejects the tool payload and we retry
# without tools, so the model explains itself instead of hallucinating runs.
_TOOL_FALLBACK_HINT = (
    "Tool calling was rejected by the local model server for this turn. "
    "Answer the user's question directly from the conversation so far, and "
    "briefly note that corpus tools could not be run for this answer."
)


def _sanitize_schema_node(node: Any) -> Any:
    """Recursively strip non-portable JSON-Schema keywords."""
    if isinstance(node, list):
        return [_sanitize_schema_node(item) for item in node]
    if not isinstance(node, dict):
        return node
    clean: dict[str, Any] = {}
    for key, value in node.items():
        if key not in _COMPAT_SCHEMA_KEYS:
            continue
        if key in ("items", "properties"):
            clean[key] = _sanitize_schema_node(value)
        else:
            clean[key] = value
    return clean


def sanitize_tools_for_compat(tools: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Make OpenAI function-tool schemas safe for local /v1 servers.

    - keeps only function-type tools,
    - recursively strips non-portable schema keywords,
    - guarantees a ``required`` array exists (some servers dislike its
      absence).
    """
    sanitized: list[dict[str, Any]] = []
    for tool in tools:
        if tool.get("type") != "function":
            continue
        fn = dict(tool.get("function") or {})
        params = fn.get("parameters")
        if isinstance(params, dict):
            params = dict(params)
            props = params.get("properties")
            if isinstance(props, dict):
                params["properties"] = {
                    name: _sanitize_schema_node(schema) for name, schema in props.items()
                }
            if not isinstance(params.get("required"), list):
                params["required"] = []
            fn["parameters"] = params
        sanitized.append({"type": "function", "function": fn})
    return sanitized


class OllamaProvider(ModelProvider):
    """
    Ollama provider using the NATIVE /api/chat endpoint.

    Why native /api/chat instead of /v1/chat/completions:
      1. Supports "think": false for Qwen3 thinking models
      2. More reliable with small models (1.5B-3B)
      3. Better error messages
      4. Cleaner message.content response structure

    Features ported from RDAT project:
      - Proxy bypass (trust_env=False, proxy=None)
      - think: false for Qwen3 models
      - Thinking-text stripping as safety net
      - Raw response capture for debugging
      - OLLAMA_HOST normalization
      - Multi-URL health check with 127.0.0.1 + localhost fallback
      - 5-second health timeout (was 3s)
    """

    name = "ollama"

    def __init__(self, settings: Settings) -> None:
        self.settings = settings
        self.base_url = _normalize_ollama_url(settings.ollama_base_url)
        self.default_model = settings.ollama_default_model

        # v1.2.0: short-lived /api/tags cache for capability lookups.
        self._tags_cache: list[dict[str, Any]] | None = None
        self._tags_cache_at: float = 0.0

        # httpx client with proxy bypass for loopback traffic
        self._client = httpx.AsyncClient(
            base_url=self.base_url,
            timeout=httpx.Timeout(120.0, connect=10.0),
            headers={"Content-Type": "application/json"},
            # CRITICAL: bypass proxies for loopback traffic.
            # Corporate VPNs and security software can silently intercept
            # requests to 127.0.0.1:11434 and route them through a proxy.
            proxy=None,
            trust_env=False,
        )

    async def aclose(self) -> None:
        await self._client.aclose()

    def _is_qwen3(self, model: str | None) -> bool:
        """Check if the model is a Qwen3 (thinking) model."""
        m = (model or self.default_model).lower()
        return "qwen3" in m

    # --- chat (native /api/chat) ---
    async def chat(
        self,
        messages: list[Message],
        *,
        model: str | None = None,
        temperature: float = 0.2,
        tools: list[dict[str, Any]] | None = None,
        timeout: float | None = 120.0,
        json_mode: bool = False,
        max_tokens: int | None = None,
    ) -> ChatResponse:
        model_name = model or self.default_model
        is_qwen3 = self._is_qwen3(model_name)

        # Build /api/chat request body
        payload: dict[str, Any] = {
            "model": model_name,
            "messages": [_build_ollama_message(m) for m in messages],
            "stream": False,
            "think": False,  # Disable thinking for ALL models (harmless for non-Qwen3)
            "options": {
                "temperature": temperature,
                # v1.2.0 Lens round: vision call sites pass max_tokens=2048 —
                # rich JSON claim sets (visual grammar, discourse lenses) were
                # getting truncated at 512, degrading to the single-claim
                # fallback in the defensive parser.
                "num_predict": max_tokens or (1024 if is_qwen3 else 512),
            },
        }

        # Issue 2b: Ollama's native /api/chat supports a "format": "json"
        # field that forces the model to return valid JSON. This is critical
        # for confidence.py and query_suggestions.py, which ask the model
        # for structured JSON output. Without it, small local models
        # routinely wrap JSON in prose or ```json fences, causing
        # json.loads() to fail silently and fall back to a hardcoded 0.5
        # confidence — making the "low confidence → answer MCQ first"
        # gating effectively random.
        if json_mode:
            payload["format"] = "json"

        # Ollama native API doesn't support OpenAI-style tools in /api/chat
        # the same way. If tools are needed, fall back to /v1/chat/completions.
        if tools:
            # Use OpenAI-compatible endpoint for tool calls
            # Issue 8: pass json_mode through so chat_json() works with tools
            return await self._chat_openai_compat(
                messages,
                model=model_name,
                temperature=temperature,
                tools=tools,
                timeout=timeout,
                json_mode=json_mode,
                max_tokens=max_tokens,
            )

        log.info(
            "ollama_chat_request",
            model=model_name,
            messages=len(messages),
            qwen3=is_qwen3,
            json_mode=json_mode,
        )

        try:
            r = await self._client.post("/api/chat", json=payload, timeout=timeout)
            r.raise_for_status()
        except httpx.HTTPError as e:
            raise ModelProviderError(f"[ollama] chat request failed: {e}") from e

        # Capture raw response text BEFORE parsing (for debugging)
        raw_text = r.text
        # Issue 13: preview gated behind CORPUSMIND_DEBUG_RAW=1
        log.debug("ollama_raw_response", length=len(raw_text), preview=_debug_raw(raw_text))

        try:
            data = json.loads(raw_text)
        except json.JSONDecodeError as e:
            raise ModelProviderError(
                f"[ollama] failed to parse response: {e}. Raw: {_debug_raw(raw_text)}"
            ) from e

        # Extract content from /api/chat response format:
        # { "message": { "role": "assistant", "content": "...", "thinking": "..." }, "done": true }
        content = ""
        if "message" in data:
            msg = data["message"]
            content = msg.get("content", "").strip()

            # If content is empty, try thinking field (Qwen3 fallback)
            if not content and "thinking" in msg:
                thinking = msg.get("thinking", "").strip()
                if thinking:
                    log.info("ollama_content_empty_using_thinking", thinking_len=len(thinking))
                    content = _strip_thinking(thinking)
        elif "response" in data:
            # Fallback: /api/generate response format
            content = data["response"].strip()

        # Strip thinking text that may have leaked into content (Qwen3 safety net)
        if is_qwen3 and content:
            content = _strip_thinking(content)

        if not content:
            raise ModelProviderError(
                f"[ollama] empty translation. Model: {model_name}. Raw: {_debug_raw(raw_text)}"
            )

        log.info("ollama_chat_success", model=model_name, content_len=len(content))
        return ChatResponse(
            content=content,
            model=data.get("model", model_name),
            provider=self.name,
            raw=data,
        )

    async def _chat_openai_compat(
        self,
        messages: list[Message],
        *,
        model: str,
        temperature: float,
        tools: list[dict[str, Any]],
        timeout: float | None,
        json_mode: bool = False,
        max_tokens: int | None = None,
    ) -> ChatResponse:
        """Fallback to /v1/chat/completions for tool-calling (Ollama supports both).

        Issue 8 fix: this method previously:
          1. Didn't pass json_mode through → chat_json() with tools lost JSON format
          2. Didn't strip Qwen3 thinking text → leaked into tool-call responses
          3. Didn't handle empty content (some models return null content
             when they only want to make tool calls)
          4. Didn't include the 'name' field for tool messages → Ollama
             rejected tool-result messages with 400 Bad Request
        """
        payload: dict[str, Any] = {
            "model": model,
            "messages": [_build_openai_message(m) for m in messages],
            "temperature": temperature,
            "stream": False,
        }
        if max_tokens:
            payload["max_tokens"] = max_tokens
        # v1.2.0: sanitize schemas for the local server (older Ollama 400s
        # on unknown JSON-Schema keywords like default/minimum/maximum).
        wire_tools = sanitize_tools_for_compat(tools) if tools else None
        if wire_tools:
            payload["tools"] = wire_tools
        # Issue 8: pass json_mode through so chat_json() works with tool calls
        if json_mode:
            payload["response_format"] = {"type": "json_object"}

        log.info(
            "ollama_openai_compat_request",
            model=model,
            messages=len(messages),
            has_tools=bool(wire_tools),
            json_mode=json_mode,
        )

        tools_fallback_used = False
        try:
            r = await self._client.post("/v1/chat/completions", json=payload, timeout=timeout)
            if r.status_code == 400 and wire_tools:
                # v1.2.0 no-tools fallback: some models (or older servers)
                # reject ANY tool payload with 400 — e.g. models whose
                # template lacks tool support. Retry ONCE without tools so
                # the user gets an answer instead of "HTTP 502: Model call
                # failed". The turn is then un-grounded by design; the hint
                # tells the model to say so instead of hallucinating runs.
                server_body = r.text[:300]
                log.warning(
                    "ollama_tools_rejected_retrying_without_tools",
                    model=model,
                    server_body=server_body,
                )
                tools_fallback_used = True
                fallback_messages = [
                    *messages,
                    Message(role="system", content=_TOOL_FALLBACK_HINT),
                ]
                retry_payload = {
                    **payload,
                    "messages": [_build_openai_message(m) for m in fallback_messages],
                }
                retry_payload.pop("tools", None)
                retry_payload.pop("response_format", None)
                r = await self._client.post(
                    "/v1/chat/completions", json=retry_payload, timeout=timeout
                )
            r.raise_for_status()
        except httpx.HTTPError as e:
            server_body = ""
            resp = getattr(e, "response", None)
            if resp is not None:
                try:
                    server_body = resp.text[:300]
                except Exception:
                    server_body = ""
            raise ModelProviderError(
                f"[ollama] tool-call request failed: {e}"
                + (f" — server said: {server_body}" if server_body else "")
            ) from e

        data = r.json()
        if tools_fallback_used:
            # Marker so callers (assistant) can tell the user grounding was
            # skipped for this turn.
            data["_tools_fallback"] = True
        try:
            choice = data["choices"][0]
            msg = choice["message"]
            content = msg.get("content") or ""
        except (KeyError, IndexError) as e:
            raise ModelProviderError(f"[ollama] unexpected tool-call response: {data}") from e

        # Issue 8: strip Qwen3 thinking text that leaks into content
        if self._is_qwen3(model) and content:
            content = _strip_thinking(content)

        # Issue 8: some models return empty content when they only want to
        # make tool calls — this is valid, not an error. Return the empty
        # content and let the caller check raw["choices"][0]["message"]
        # for tool_calls.
        if not content and not msg.get("tool_calls"):
            log.warning("ollama_openai_compat_empty_content", model=model, raw=_debug_raw(data))

        return ChatResponse(
            content=content, model=data.get("model", model), provider=self.name, raw=data
        )

    # --- stream (native /api/chat with stream=true) ---
    async def stream(
        self,
        messages: list[Message],
        *,
        model: str | None = None,
        temperature: float = 0.2,
        timeout: float | None = None,
    ) -> AsyncIterator[str]:
        model_name = model or self.default_model
        payload = {
            "model": model_name,
            "messages": [_build_ollama_message(m) for m in messages],
            "stream": True,
            "think": False,
            "options": {
                "temperature": temperature,
                "num_predict": 1024 if self._is_qwen3(model_name) else 512,
            },
        }
        try:
            async with self._client.stream("POST", "/api/chat", json=payload, timeout=timeout) as r:
                r.raise_for_status()
                async for line in r.aiter_lines():
                    if not line:
                        continue
                    try:
                        chunk = json.loads(line)
                        # /api/chat streaming: { "message": { "content": "..." }, "done": false }
                        msg = chunk.get("message", {})
                        delta = msg.get("content", "")
                        if delta:
                            yield delta
                        if chunk.get("done"):
                            return
                    except json.JSONDecodeError:
                        log.debug("ollama_stream_unparsable", line=line[:200])
                        continue
        except httpx.HTTPError as e:
            raise ModelProviderError(f"[ollama] stream failed: {e}") from e

    # --- embed (native /api/embeddings) ---
    async def embed(
        self,
        text: str,
        *,
        model: str | None = None,
        timeout: float | None = 30.0,
    ) -> EmbeddingResponse:
        payload = {"model": model or "nomic-embed-text", "prompt": text}
        try:
            r = await self._client.post("/api/embeddings", json=payload, timeout=timeout)
            r.raise_for_status()
        except httpx.HTTPError as e:
            raise ModelProviderError(f"[ollama] embed failed: {e}") from e
        data = r.json()
        try:
            vec = data["embedding"]
        except KeyError as e:
            raise ModelProviderError(f"[ollama] unexpected embedding shape: {data}") from e
        return EmbeddingResponse(
            vector=vec, model=data.get("model", payload["model"]), provider=self.name
        )

    # --- list models (native /api/tags) ---
    async def list_models(self) -> list[str]:
        try:
            r = await self._client.get("/api/tags", timeout=10.0)
            r.raise_for_status()
        except httpx.HTTPError as e:
            log.warning("ollama_list_models_failed", error=str(e))
            return []
        data = r.json()
        models = data.get("models", [])
        return [m.get("name", "") for m in models if m.get("name")]

    # --- v1.2.0: model capability lookups (tool support) ---
    async def _tags_models(self) -> list[dict[str, Any]]:
        """Raw /api/tags model entries, cached for 30 s (best-effort)."""
        now = time.monotonic()
        if self._tags_cache is not None and (now - self._tags_cache_at) < 30.0:
            return self._tags_cache
        try:
            r = await self._client.get("/api/tags", timeout=10.0)
            r.raise_for_status()
            self._tags_cache = r.json().get("models", [])
            self._tags_cache_at = now
        except httpx.HTTPError as e:
            log.debug("ollama_tags_lookup_failed", error=str(e))
        return self._tags_cache or []

    async def supports_tools(self, model: str | None = None) -> bool:
        """Whether the model advertises the 'tools' capability.

        Ollama ≥ 0.5 lists per-model ``capabilities`` in /api/tags;
        embedding/vision-only models 400 on tool payloads, so the caller
        should skip tools for them. Older Ollama (no capability info)
        returns True — the no-tools fallback in ``_chat_openai_compat``
        covers whatever that version still rejects.
        """
        wanted = model or self.default_model
        for m in await self._tags_models():
            name = m.get("name", "")
            if name == wanted or name.split(":")[0] == wanted.split(":")[0]:
                caps = m.get("capabilities")
                if not caps:
                    return True  # older Ollama — no capability info
                return "tools" in caps
        return True

    async def pick_default_model(self) -> str | None:
        """First tool-capable model, else first model, else None.

        Auto-selection used to take the FIRST installed model, which is
        frequently an embedding model (e.g. nomic-embed-text) — every
        grounded turn then died with a 400.
        """
        models = await self._tags_models()
        if not models:
            return None
        for m in models:
            caps = m.get("capabilities")
            if caps and "tools" in caps and m.get("name"):
                return m["name"]
        return models[0].get("name")

    async def supports_vision(self, model: str | None = None) -> bool:
        """Whether the model advertises the 'vision' capability (v1.2.0).

        Ollama lists per-model ``capabilities`` in /api/tags (e.g.
        ["vision", "tools", "completion"]). Older Ollama versions omit
        the field entirely — fall back to a name heuristic (vl/vision/
        llava/moondream/gemma…) rather than guessing True, because calling
        a text-only model with image bytes fails in confusing ways.
        """
        wanted = model or self.default_model
        for m in await self._tags_models():
            name = m.get("name", "")
            if name == wanted or name.split(":")[0] == wanted.split(":")[0]:
                caps = m.get("capabilities")
                if caps:
                    return "vision" in caps
                break  # found the model but no capability info → name heuristic
        return _name_suggests_vision(wanted)

    async def pick_vision_model(self) -> str | None:
        """First vision-capable model, else first name-hint match, else None.

        Returns None when nothing looks vision-capable — the vision
        endpoints turn that into an actionable 400 ("ollama pull
        qwen3-vl:2b") instead of silently calling a text-only model.
        """
        models = await self._tags_models()
        if not models:
            return None
        for m in models:
            caps = m.get("capabilities")
            if caps and "vision" in caps and m.get("name"):
                return m["name"]
        for m in models:
            name = m.get("name", "")
            if name and _name_suggests_vision(name):
                return name
        return None

    # --- health (multi-URL with fallback) ---
    async def health(self) -> bool:
        """
        Multi-URL health check with 5-second timeout.

        Tries in order:
          1. Configured base_url /api/tags
          2. http://127.0.0.1:11434/api/tags (IPv4 explicit)
          3. http://localhost:11434/api/tags (fallback)
        """
        urls = [
            f"{self.base_url}/api/tags",
            "http://127.0.0.1:11434/api/tags",
            "http://localhost:11434/api/tags",
        ]

        for url in urls:
            try:
                r = await self._client.get(url, timeout=5.0)
                if r.status_code == 200:
                    log.info("ollama_health_ok", url=url)
                    return True
                log.warning("ollama_health_status", url=url, status=r.status_code)
            except httpx.HTTPError as e:
                log.warning("ollama_health_failed", url=url, error=str(e))
                continue

        log.warning("ollama_health_all_failed")
        return False


# --------------------------------------------------------------------------- #
# Concrete providers (LM Studio, Cloud)
# --------------------------------------------------------------------------- #


class LMStudioProvider(_OpenAICompatibleProvider):
    name = "lmstudio"

    def __init__(self, settings: Settings) -> None:
        self.base_url = settings.lmstudio_base_url
        self.default_model = settings.lmstudio_default_model
        super().__init__(settings)

    async def supports_vision(self, model: str | None = None) -> bool:
        """LM Studio exposes no per-model capability list — use name hints.

        /v1/models returns bare names; qwen*-vl, gemma3, llava etc. accept
        images, plain chat models don't. Users can always pass an explicit
        model name to override the heuristic.
        """
        return _name_suggests_vision(model or self.default_model)

    async def pick_vision_model(self) -> str | None:
        """First installed model whose name suggests vision support."""
        try:
            models = await self.list_models()
        except Exception:
            return None
        for name in models:
            if _name_suggests_vision(name):
                return name
        return None


class CloudProvider(_OpenAICompatibleProvider):
    """
    Opt-in cloud provider (Anthropic / OpenAI / compatible gateways).

    OFF by default (§4 Principle 1). The UI shows an unmissable indicator when
    a request is routed here (§7.5). If `cloud_disabled_hard` is set in settings,
    every method raises CloudDisabledError — this is the belt-and-suspenders
    guarantee required by §13.2 for shared/institutional machines.
    """

    name = "cloud"

    def __init__(self, settings: Settings) -> None:
        if settings.cloud_provider == "none":
            self.base_url = ""
            self.default_model = ""
            self.auth_header = None
            self._disabled = True
            super().__init__(settings)
            return

        if settings.cloud_disabled_hard:
            raise CloudDisabledError(
                "Cloud provider is hard-disabled in settings (CORPUSMIND_CLOUD_DISABLED_HARD=1)."
            )

        if not settings.cloud_api_key:
            raise CloudDisabledError(
                "Cloud provider selected but CORPUSMIND_CLOUD_API_KEY is empty."
            )

        self.base_url = settings.cloud_base_url or self._default_base_url(settings.cloud_provider)
        self.default_model = settings.cloud_default_model
        self.auth_header = f"Bearer {settings.cloud_api_key}"
        self._disabled = False
        super().__init__(settings)

    @staticmethod
    def _default_base_url(provider: str) -> str:
        return {
            "openai": "https://api.openai.com/v1",
            "anthropic": "https://api.anthropic.com/v1",
        }.get(provider, "")

    async def pick_vision_model(self) -> str | None:
        """Cloud models are assumed multimodal-capable when explicitly set.

        The user configured ``cloud_default_model`` deliberately (gpt-4o,
        claude, gemini… — all accept images). If unset, first listed model.
        """
        return self.default_model or None

    def _default_headers(self) -> dict[str, str]:
        # Issue 7 fix: Anthropic requires an anthropic-version header on its
        # native API and accepts (documents) it on the OpenAI-compat endpoint.
        h = super()._default_headers()
        if self.settings.cloud_provider == "anthropic":
            h["anthropic-version"] = "2023-06-01"
        return h

    async def _enforce(self) -> None:
        if self._disabled or self.settings.cloud_disabled_hard:
            raise CloudDisabledError(
                "Cloud provider is disabled. Enable in Settings → AI → Cloud, and acknowledge the data-leaving-device indicator."
            )

    async def chat(self, *args, **kwargs):  # type: ignore[override]
        await self._enforce()
        return await super().chat(*args, **kwargs)

    async def stream(self, *args, **kwargs):  # type: ignore[override]
        await self._enforce()
        async for chunk in super().stream(*args, **kwargs):
            yield chunk

    async def embed(self, *args, **kwargs):  # type: ignore[override]
        await self._enforce()
        return await super().embed(*args, **kwargs)


# --------------------------------------------------------------------------- #
# Registry
# --------------------------------------------------------------------------- #


class ProviderRegistry:
    """
    Lazily-instantiated provider registry. The active provider is selected per
    request (so a user can route one query to local-Ollama and another to cloud
    without restarting). Defaults to `ollama`.
    """

    def __init__(self, settings: Settings) -> None:
        self.settings = settings
        self._instances: dict[str, ModelProvider] = {}

    def get(self, name: str | None = None) -> ModelProvider:
        name = (name or "ollama").lower()
        if name not in self._instances:
            self._instances[name] = self._build(name)
        return self._instances[name]

    def _build(self, name: str) -> ModelProvider:
        if name == "ollama":
            return OllamaProvider(self.settings)
        if name == "lmstudio":
            return LMStudioProvider(self.settings)
        if name == "cloud":
            return CloudProvider(self.settings)
        raise ModelProviderError(f"Unknown model provider: {name}")

    async def aclose(self) -> None:
        for p in self._instances.values():
            close = getattr(p, "aclose", None)
            if close:
                await close()
        self._instances.clear()

    def invalidate(self, name: str) -> None:
        """Drop a cached provider instance so the next .get() rebuilds it
        from current settings - needed after a runtime credential change."""
        self._instances.pop(name, None)
