"""v1.2.15 — runtime engine attachment: CORS + preflight behaviour.

Covers the engine-side changes that let a hosted PWA attach an engine at
runtime (docs/BUILD_GUIDE.md §5.8):

  1. the hosted PWA origin ships in the default CORS allow-list;
  2. CORPUSMIND_CORS_ORIGINS accepts a comma-separated list (not only JSON);
  3. CORS preflights (OPTIONS) pass through the shared-bearer-token
     middleware instead of being rejected with 401 — while the actual
     request is still token-checked.
"""
from __future__ import annotations

import pytest
from httpx import ASGITransport, AsyncClient

HOSTED_PWA_ORIGIN = "https://corpus-mind-web.vercel.app"


def _fresh_cors_origins() -> list[str]:
    """Build a Settings with the CURRENT env, without leaving cache residue."""
    from app.settings import get_settings

    get_settings.cache_clear()
    try:
        return get_settings().cors_origins
    finally:
        get_settings.cache_clear()


def test_default_cors_includes_hosted_pwa(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("CORPUSMIND_CORS_ORIGINS", raising=False)
    assert HOSTED_PWA_ORIGIN in _fresh_cors_origins()


def test_cors_env_comma_separated(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("CORPUSMIND_CORS_ORIGINS", "https://a.example, https://b.example ,,")
    assert _fresh_cors_origins() == ["https://a.example", "https://b.example"]


def test_cors_env_json_still_works(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("CORPUSMIND_CORS_ORIGINS", '["https://c.example"]')
    assert _fresh_cors_origins() == ["https://c.example"]


@pytest.mark.asyncio
async def test_preflight_passes_token_middleware(monkeypatch: pytest.MonkeyPatch) -> None:
    """A token-protected remote engine must answer its own preflight.

    Browsers never send Authorization on an OPTIONS preflight (the Fetch
    spec forbids it), so the token middleware used to 401 it and the
    browser surfaced a CORS error instead of an auth challenge.
    """
    monkeypatch.setenv("CORPUSMIND_AUTH_TOKEN", "secret-token")
    monkeypatch.setenv("CORPUSMIND_HOST", "0.0.0.0")  # non-loopback → token required
    monkeypatch.setenv("CORPUSMIND_DB_URL", "sqlite+aiosqlite:///:memory:")
    monkeypatch.setenv("CORPUSMIND_DATA_DIR", "/tmp/cm-test-cors")
    monkeypatch.delenv("CORPUSMIND_CORS_ORIGINS", raising=False)

    from app.settings import get_settings

    get_settings.cache_clear()
    from storage.session import _engine, dispose_db

    _engine.clear() if hasattr(_engine, "clear") else None

    from app.main import app

    try:
        async with AsyncClient(
            transport=ASGITransport(app=app), base_url="http://engine.example"
        ) as ac:
            async with app.router.lifespan_context(app):
                # Preflight: no Authorization header — must be answered by
                # CORSMiddleware (200 + allow-origin), not 401'd.
                r = await ac.options(
                    "/api/v1/health",
                    headers={
                        "Origin": HOSTED_PWA_ORIGIN,
                        "Access-Control-Request-Method": "GET",
                    },
                )
                assert r.status_code == 200
                assert r.headers.get("access-control-allow-origin") == HOSTED_PWA_ORIGIN

                # The ACTUAL request is still token-checked: without the
                # bearer → 401; with it → through.
                r2 = await ac.get("/api/v1/projects")
                assert r2.status_code == 401
                r3 = await ac.get(
                    "/api/v1/projects", headers={"Authorization": "Bearer secret-token"}
                )
                assert r3.status_code == 200
    finally:
        await dispose_db()
        get_settings.cache_clear()
