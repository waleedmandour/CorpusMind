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
import json
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
    ) -> ChatResponse: ...

    async def chat_json(
        self,
        messages: list[Message],
        *,
        model: str | None = None,
        temperature: float = 0.1,
        timeout: float | None = 60.0,
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
        return await self.chat(messages, model=model, temperature=temperature, timeout=timeout, json_mode=True)

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

    @abc.abstractmethod
    async def health(self) -> bool:
        """Return True iff the provider responds to a lightweight probe."""


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
        "Okay, let's", "Let me", "The user wants", "I need to",
        "First, let's", "Alright,", "So,", "Now,", "Hmm,",
        "I should", "Let's think", "To answer",
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
                if any(w in stripped.lower() for w in ["let's", "should", "need to", "going to", "first", "now i"]):
                    continue
            # This line doesn't look like thinking
            in_thinking = False
        result_lines.append(line)

    result = "\n".join(result_lines).strip()
    return result if result else trimmed


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
        self._client = httpx.AsyncClient(
            base_url=self.base_url.rstrip("/"),
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
    ) -> ChatResponse:
        payload: dict[str, Any] = {
            "model": model or self.default_model,
            "messages": [{"role": m.role, "content": m.content, **({"name": m.name} if m.name else {})} for m in messages],
            "temperature": temperature,
            "stream": False,
        }
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
            raise ModelProviderError(f"[{self.name}] unexpected response shape: {data}") from e
        return ChatResponse(content=content, model=data.get("model", payload["model"]), provider=self.name, raw=data)

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
            "messages": [{"role": m.role, "content": m.content} for m in messages],
            "temperature": temperature,
            "stream": True,
        }
        try:
            async with self._client.stream("POST", "/v1/chat/completions", json=payload, timeout=timeout) as r:
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
        return EmbeddingResponse(vector=vec, model=data.get("model", payload["model"]), provider=self.name)

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
    ) -> ChatResponse:
        model_name = model or self.default_model
        is_qwen3 = self._is_qwen3(model_name)

        # Build /api/chat request body
        payload: dict[str, Any] = {
            "model": model_name,
            "messages": [
                {"role": m.role, "content": m.content, **({"name": m.name} if m.name else {})}
                for m in messages
            ],
            "stream": False,
            "think": False,  # Disable thinking for ALL models (harmless for non-Qwen3)
            "options": {
                "temperature": temperature,
                "num_predict": 1024 if is_qwen3 else 512,  # More tokens for Qwen3
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
            return await self._chat_openai_compat(messages, model=model_name,
                                                   temperature=temperature, tools=tools, timeout=timeout)

        log.info("ollama_chat_request", model=model_name, messages=len(messages), qwen3=is_qwen3, json_mode=json_mode)

        try:
            r = await self._client.post("/api/chat", json=payload, timeout=timeout)
            r.raise_for_status()
        except httpx.HTTPError as e:
            raise ModelProviderError(f"[ollama] chat request failed: {e}") from e

        # Capture raw response text BEFORE parsing (for debugging)
        raw_text = r.text
        log.debug("ollama_raw_response", length=len(raw_text), preview=raw_text[:500])

        try:
            data = json.loads(raw_text)
        except json.JSONDecodeError as e:
            raise ModelProviderError(
                f"[ollama] failed to parse response: {e}. Raw (first 200 chars): {raw_text[:200]}"
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
                f"[ollama] empty translation. Model: {model_name}. "
                f"Raw response (first 300 chars): {raw_text[:300]}"
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
    ) -> ChatResponse:
        """Fallback to /v1/chat/completions for tool-calling (Ollama supports both)."""
        payload: dict[str, Any] = {
            "model": model,
            "messages": [{"role": m.role, "content": m.content} for m in messages],
            "temperature": temperature,
            "stream": False,
        }
        if tools:
            payload["tools"] = tools

        try:
            r = await self._client.post("/v1/chat/completions", json=payload, timeout=timeout)
            r.raise_for_status()
        except httpx.HTTPError as e:
            raise ModelProviderError(f"[ollama] tool-call request failed: {e}") from e

        data = r.json()
        try:
            content = data["choices"][0]["message"]["content"]
        except (KeyError, IndexError) as e:
            raise ModelProviderError(f"[ollama] unexpected tool-call response: {data}") from e
        return ChatResponse(content=content, model=data.get("model", model), provider=self.name, raw=data)

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
            "messages": [{"role": m.role, "content": m.content} for m in messages],
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
        return EmbeddingResponse(vector=vec, model=data.get("model", payload["model"]), provider=self.name)

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
            raise CloudDisabledError("Cloud provider is hard-disabled in settings (CORPUSMIND_CLOUD_DISABLED_HARD=1).")

        if not settings.cloud_api_key:
            raise CloudDisabledError("Cloud provider selected but CORPUSMIND_CLOUD_API_KEY is empty.")

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
