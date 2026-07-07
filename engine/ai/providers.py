"""
ModelProvider abstraction (§11.4).

Three concrete implementations share one interface:
  - OllamaProvider   → http://localhost:11434  (native + OpenAI-compatible /v1)
  - LMStudioProvider → http://localhost:1234/v1 (OpenAI-compatible)
  - CloudProvider    → user-supplied API key, opt-in, OFF by default

Because Ollama and LM Studio both speak the OpenAI chat-completions schema,
one thin client drives both — only base URL and model name differ.
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
    ) -> ChatResponse: ...

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
# OpenAI-compatible base (drives both Ollama /v1 and LM Studio)
# --------------------------------------------------------------------------- #


class _OpenAICompatibleProvider(ModelProvider):
    """
    Shared implementation for anything that speaks OpenAI's /v1 schema.
    Concrete subclasses set `name`, `base_url`, and a default model.
    """

    name: str = "openai-compatible"
    base_url: str = ""
    default_model: str = ""
    # Ollama's /api/tags is non-OpenAI; subclasses can override.
    tags_path: str = "/v1/models"
    # Some providers (Ollama native) want Bearer omitted when no key is set.
    auth_header: str | None = None

    def __init__(self, settings: Settings) -> None:
        self.settings = settings
        self._client = httpx.AsyncClient(
            base_url=self.base_url.rstrip("/"),
            timeout=httpx.Timeout(60.0, connect=5.0),
            headers=self._default_headers(),
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
    ) -> ChatResponse:
        payload: dict[str, Any] = {
            "model": model or self.default_model,
            "messages": [{"role": m.role, "content": m.content, **({"name": m.name} if m.name else {})} for m in messages],
            "temperature": temperature,
            "stream": False,
        }
        if tools:
            payload["tools"] = tools

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
                        # forward but never crash the stream
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
        # Both Ollama /api/tags and OpenAI /v1/models expose a list under `data` or `models`
        items = data.get("data") or data.get("models") or []
        return [m.get("id") or m.get("name") for m in items if isinstance(m, dict)]

    # --- health ---
    async def health(self) -> bool:
        try:
            r = await self._client.get(self.tags_path, timeout=3.0)
            return r.status_code == 200
        except httpx.HTTPError:
            return False


# --------------------------------------------------------------------------- #
# Concrete providers
# --------------------------------------------------------------------------- #


class OllamaProvider(_OpenAICompatibleProvider):
    name = "ollama"
    tags_path = "/api/tags"  # native Ollama endpoint; /v1/models also works but /api/tags is canonical

    def __init__(self, settings: Settings) -> None:
        self.base_url = settings.ollama_base_url
        self.default_model = settings.ollama_default_model
        super().__init__(settings)


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
            # still construct so the registry can hold it, but every call will fail-fast.
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
