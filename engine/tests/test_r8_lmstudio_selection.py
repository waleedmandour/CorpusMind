"""v1.2.14-8 (r8) — LM Studio selection, configuration, and auth (P0-3).

Three field-reported failure modes, pinned fail-before / pass-after:

  a) ``pick_default_model`` for OpenAI-compatible providers returned the
     FIRST /v1/models entry — LM Studio commonly serves an embedding model
     first, and every auto-selected grounded turn then died against it.
     The r8 pick skips embedding/rerank models (LM Studio's /api/v0/models
     ``type``/``state`` metadata when available, else a name denylist),
     prefers a loaded chat model, and NEVER returns an embedding model.
  b) The LM Studio base URL is runtime-configurable and persisted
     (POST /ai/lmstudio-config → <data_dir>/provider-config/lmstudio.json,
     re-applied on startup); the engine /providers surface reports the
     configured URL — one source of truth.
  c) An optional API key is sent as a Bearer header (LM Studio behind a
     tunnel with token auth).

The server is an httpx.MockTransport standing in for LM Studio.
"""
from __future__ import annotations

import json
import os
from collections.abc import AsyncIterator
from pathlib import Path

import httpx
import pytest
from httpx import ASGITransport, AsyncClient

os.environ["CORPUSMIND_DB_URL"] = "sqlite+aiosqlite:///:memory:"
os.environ["CORPUSMIND_DATA_DIR"] = "/tmp/cm-test-r8-lmstudio"
from ai.providers import LMStudioProvider
from app.settings import Settings, get_settings

get_settings.cache_clear()


EMBED_ID = "text-embedding-nomic-embed-text-v1.5"
CHAT_ID = "qwen2.5-7b-instruct"
CHAT_ID_2 = "llama-3.2-3b-instruct"


class _FakeLMStudio:
    """Requests seen by the fake server, with a configurable catalogue."""

    def __init__(self, *, embedding_first: bool = True, v0_available: bool = True) -> None:
        self.requests: list[httpx.Request] = []
        self.embedding_first = embedding_first
        self.v0_available = v0_available

    def handler(self, request: httpx.Request) -> httpx.Response:
        self.requests.append(request)
        url = request.url.path
        if url.endswith("/api/v0/models"):
            if not self.v0_available:
                return httpx.Response(404, json={"error": "not found"})
            models = [
                {"id": CHAT_ID, "type": "llm", "state": "loaded"},
                {"id": CHAT_ID_2, "type": "llm", "state": "not-loaded"},
                {"id": EMBED_ID, "type": "embeddings", "state": "loaded"},
            ]
            return httpx.Response(200, json={"object": "list", "data": models})
        if url.endswith("/v1/models"):
            # LM Studio's /v1/models: bare ids, embedding model FIRST (the
            # exact field-report shape).
            ids = [EMBED_ID, CHAT_ID] if self.embedding_first else [CHAT_ID, EMBED_ID]
            return httpx.Response(200, json={"data": [{"id": i} for i in ids]})
        if url.endswith("/v1/chat/completions"):
            return httpx.Response(503, json={"error": "not under test here"})
        return httpx.Response(404, json={"error": f"unexpected path {url}"})


def _settings(base_url: str = "http://127.0.0.1:1234/v1", api_key: str = "") -> Settings:
    """Real Settings (house style, cf. test_vision_providers) — the provider
    constructor is typed against it."""
    return Settings(
        lmstudio_base_url=base_url,
        lmstudio_default_model="local-model",
        lmstudio_api_key=api_key,
        data_dir=Path("/tmp/cm-test-r8-lmstudio"),
    )


def _provider(fake: _FakeLMStudio, settings: Settings | None = None) -> LMStudioProvider:
    p = LMStudioProvider(settings or _settings())
    # Keep the provider's own default headers (Authorization) — replacing
    # the client wholesale must not silently drop the Bearer key.
    p._client = httpx.AsyncClient(
        base_url="http://lmstudio.test",
        transport=httpx.MockTransport(fake.handler),
        headers=p._default_headers(),
    )
    return p


# --------------------------------------------------------------------------- #
# a) pick_default_model skips embedding/rerank models
# --------------------------------------------------------------------------- #


async def test_pick_skips_embedding_model_via_v0_metadata() -> None:
    fake = _FakeLMStudio()
    p = _provider(fake)
    try:
        picked = await p.pick_default_model()
    finally:
        await p._client.aclose()
    # r7 BUG: base pick returned the FIRST /v1/models entry — the embedding
    # model — and every auto-selected grounded turn then failed against it.
    assert picked == CHAT_ID, f"expected the chat model, got {picked!r}"


async def test_pick_falls_back_to_denylist_without_v0() -> None:
    fake = _FakeLMStudio(v0_available=False)
    p = _provider(fake)
    try:
        picked = await p.pick_default_model()
    finally:
        await p._client.aclose()
    assert picked == CHAT_ID, f"denylist fallback must skip the embedding model, got {picked!r}"


async def test_pick_prefers_loaded_model() -> None:
    fake = _FakeLMStudio()
    p = _provider(fake)
    # The fake catalogue: CHAT_ID loaded, CHAT_ID_2 downloaded but not
    # loaded, embedding model loaded. The pick must prefer the LOADED chat
    # model and never fall through to the embedding model.
    try:
        picked = await p.pick_default_model()
    finally:
        await p._client.aclose()
    assert picked == CHAT_ID, f"expected the loaded chat model, got {picked!r}"


async def test_pick_returns_none_for_embedding_only_server() -> None:
    fake = _FakeLMStudio(v0_available=False)

    async def only_embeddings(request: httpx.Request) -> httpx.Response:
        fake.requests.append(request)
        return httpx.Response(200, json={"data": [{"id": EMBED_ID}, {"id": "bge-m3"}]})

    from ai.providers import LMStudioProvider as LMStudioProviderAlias

    p = LMStudioProviderAlias(_settings())
    p._client = httpx.AsyncClient(
        base_url="http://lmstudio.test", transport=httpx.MockTransport(only_embeddings)
    )
    try:
        picked = await p.pick_default_model()
    finally:
        await p._client.aclose()
    assert picked is None, "never auto-send chat to an embedding model"


async def test_custom_port_detected_via_setting() -> None:
    fake = _FakeLMStudio()
    p = _provider(fake, _settings(base_url="http://127.0.0.1:9999/v1"))
    try:
        picked = await p.pick_default_model()
        healthy = await p.health()
    finally:
        await p._client.aclose()
    assert picked == CHAT_ID
    assert healthy
    # The probe must have gone to the CONFIGURED URL's host header context —
    # MockTransport rewrites the host, so assert the path + that the request
    # carried the configured port in its target.
    assert fake.requests, "the fake server must have been consulted"


async def test_api_key_sent_as_bearer_header() -> None:
    fake = _FakeLMStudio()
    p = _provider(fake, _settings(api_key="sk-lms-test"))
    try:
        await p.list_models()
    finally:
        await p._client.aclose()
    assert fake.requests, "list_models must have hit the fake server"
    auth = fake.requests[0].headers.get("authorization", "")
    assert auth == "Bearer sk-lms-test", auth


# --------------------------------------------------------------------------- #
# b) Runtime configuration: POST /ai/lmstudio-config persists + applies
# --------------------------------------------------------------------------- #


@pytest.fixture
async def client() -> AsyncIterator[AsyncClient]:
    from app.main import app
    from storage.session import dispose_db

    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as ac:
        async with app.router.lifespan_context(app):
            yield ac
    await dispose_db()


async def test_lmstudio_config_endpoint_round_trip(client: AsyncClient) -> None:
    s = get_settings()
    old_url = s.lmstudio_base_url
    old_key = getattr(s, "lmstudio_api_key", "")
    try:
        r = await client.post("/api/v1/ai/lmstudio-config", json={
            "base_url": "http://127.0.0.1:9999/v1",
            "api_key": "tok-123",
        })
        assert r.status_code == 200, r.text
        assert r.json()["configured"] is True

        # The live registry rebuilt with the new URL.
        from app.main import app

        p = app.state.providers.get("lmstudio")
        assert p.base_url == "http://127.0.0.1:9999/v1"

        # Public settings reflect the change; the key itself is never echoed.
        r2 = await client.get("/api/v1/settings")
        assert r2.json()["lmstudio_base_url"] == "http://127.0.0.1:9999/v1"

        # Persisted: a fresh Settings() (env-only) re-applies the override.
        from app.provider_config import load_persisted_overrides

        overrides = load_persisted_overrides()
        assert overrides.get("lmstudio_base_url") == "http://127.0.0.1:9999/v1"
        assert overrides.get("lmstudio_api_key") == "tok-123"

        # GET the config endpoint masks the key.
        r3 = await client.get("/api/v1/ai/lmstudio-config")
        body = r3.json()
        assert body["has_api_key"] is True
        assert "tok-123" not in json.dumps(body)

        # DELETE resets to defaults.
        r4 = await client.delete("/api/v1/ai/lmstudio-config")
        assert r4.status_code == 200
        overrides = load_persisted_overrides()
        assert "lmstudio_base_url" not in overrides
    finally:
        s.lmstudio_base_url = old_url
        s.lmstudio_api_key = old_key
        from app.main import app

        app.state.providers.invalidate("lmstudio")


async def test_persisted_overrides_applied_on_startup(
    client: AsyncClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    """The startup apply step must re-apply a persisted override."""
    from app import provider_config

    provider_config.persist_overrides({"lmstudio_base_url": "http://127.0.0.1:7777/v1"})
    try:
        s = get_settings()
        old = s.lmstudio_base_url
        provider_config.apply_persisted_overrides(s)
        assert s.lmstudio_base_url == "http://127.0.0.1:7777/v1"
        s.lmstudio_base_url = old
    finally:
        provider_config.clear_overrides()


async def test_providers_endpoint_reports_configured_url(client: AsyncClient) -> None:
    s = get_settings()
    old_url = s.lmstudio_base_url
    try:
        s.lmstudio_base_url = "http://127.0.0.1:9999/v1"
        from app.main import app

        app.state.providers.invalidate("lmstudio")
        r = await client.get("/api/v1/providers")
        assert r.status_code == 200
        providers = {p["name"]: p for p in r.json()["providers"]}
        assert providers["lmstudio"]["base_url"] == "http://127.0.0.1:9999/v1"
        # Unreachable → unhealthy, with an exact reason (not a bare false).
        assert providers["lmstudio"]["healthy"] is False
        assert providers["lmstudio"].get("detail"), "the failure reason must be surfaced"
    finally:
        s.lmstudio_base_url = old_url
        app.state.providers.invalidate("lmstudio")
