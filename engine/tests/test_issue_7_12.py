"""Regression tests for provider hardening (Issues 7 & 12).

Issue 7: httpx CONCATENATES the client base path with the request path, so
CloudProvider's base "https://api.openai.com/v1" plus a "/v1/chat/completions"
request path produced https://api.openai.com/v1/v1/chat/completions — a
guaranteed 404 for BOTH cloud providers. Verified empirically with
httpx.AsyncClient.build_request before the fix.

Issue 12: the Gemini API key travelled as a URL query parameter (leaking into
proxy/HTTP logs) and the raw upstream error body was echoed to clients; also
enabling Gemini required no data-leaves-device acknowledgment unlike every
other cloud path.
"""
from __future__ import annotations

import pytest
from httpx import ASGITransport, AsyncClient


@pytest.fixture
async def client():
    import os
    os.environ["CORPUSMIND_DB_URL"] = "sqlite+aiosqlite:///:memory:"
    os.environ["CORPUSMIND_DATA_DIR"] = "/tmp/cm-test-data"

    from app.settings import get_settings
    get_settings.cache_clear()
    from storage.session import _engine, dispose_db
    _engine.clear() if hasattr(_engine, "clear") else None

    from app.main import app
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as ac:
        async with app.router.lifespan_context(app):
            yield ac
    await dispose_db()


# --------------------------------------------------------------------------- #
# Issue 7 — cloud providers hit the right URLs
# --------------------------------------------------------------------------- #


def _make_cloud_provider(provider: str, base_url_override: str | None = None):
    import os

    old = {k: os.environ.get(k) for k in
           ("CORPUSMIND_CLOUD_PROVIDER", "CORPUSMIND_CLOUD_API_KEY", "CORPUSMIND_CLOUD_BASE_URL")}
    os.environ["CORPUSMIND_CLOUD_PROVIDER"] = provider
    os.environ["CORPUSMIND_CLOUD_API_KEY"] = "sk-test-key"
    if base_url_override:
        os.environ["CORPUSMIND_CLOUD_BASE_URL"] = base_url_override
    elif "CORPUSMIND_CLOUD_BASE_URL" in os.environ:
        del os.environ["CORPUSMIND_CLOUD_BASE_URL"]
    try:
        from app.settings import get_settings
        get_settings.cache_clear()
        from ai.providers import CloudProvider
        return CloudProvider(get_settings())
    finally:
        for k, v in old.items():
            if v is None:
                os.environ.pop(k, None)
            else:
                os.environ[k] = v
        from app.settings import get_settings as _gs
        _gs.cache_clear()


@pytest.mark.parametrize("provider,expected", [
    ("openai", "https://api.openai.com/v1/chat/completions"),
    ("anthropic", "https://api.anthropic.com/v1/chat/completions"),
])
def test_issue7_cloud_chat_url_has_single_v1(provider, expected):
    p = _make_cloud_provider(provider)
    req = p._client.build_request("POST", "/v1/chat/completions", json={})
    assert str(req.url) == expected, (
        f"{provider} chat URL wrong — the httpx base-path concatenation bug is back"
    )


def test_issue7_anthropic_sends_version_header():
    p = _make_cloud_provider("anthropic")
    assert p._client.headers.get("anthropic-version") == "2023-06-01"


def test_issue7_custom_base_url_with_v1_suffix_still_works():
    """LM Studio / OpenRouter style overrides ending in /v1 must not double up."""
    p = _make_cloud_provider("openai", base_url_override="https://openrouter.ai/api/v1")
    req = p._client.build_request("POST", "/v1/chat/completions", json={})
    assert str(req.url) == "https://openrouter.ai/api/v1/chat/completions"


# --------------------------------------------------------------------------- #
# Issue 12 — Gemini key handling
# --------------------------------------------------------------------------- #


@pytest.mark.asyncio
async def test_issue12_gemini_key_requires_acknowledgment(client):
    r = await client.post(
        "/api/v1/troubleshoot/gemini-key",
        json={"api_key": "AIzaTest", "acknowledge_data_leaves_device": False},
    )
    assert r.status_code == 422
    assert "data leaves" in r.json()["detail"].lower()

    r2 = await client.post(
        "/api/v1/troubleshoot/gemini-key",
        json={"api_key": "AIzaTest", "acknowledge_data_leaves_device": True},
    )
    assert r2.status_code == 200
    assert r2.json()["ok"] is True


def test_issue12_gemini_request_sends_key_in_header_not_url():
    """The interpret route must use x-goog-api-key, never params={'key': ...}."""
    import inspect

    from api import troubleshoot

    src = inspect.getsource(troubleshoot)
    assert 'params={"key"' not in src, "Gemini key still sent as URL query parameter"
    assert '"x-goog-api-key"' in src
    # No raw upstream body echo
    assert "r.text[:200]" not in src
