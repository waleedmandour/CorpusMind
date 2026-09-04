"""Regression tests for security hardening (Issues 8 & 9).

Issue 8: the engine had no authentication anywhere, while docker-compose
documents a shared-lab deployment on a LAN. A shared bearer token
(CORPUSMIND_AUTH_TOKEN) is now enforced whenever the engine binds a
non-loopback host; loopback and unset-token keep the local-first no-auth
behavior. /api/v1/health stays open for the Docker healthcheck.

Issue 9: reference-corpus archives were extracted with bare extractall() —
zip-slip/tar-slip could write outside the temp dir.
"""
from __future__ import annotations

import io
import tarfile
import zipfile

import pytest
from httpx import ASGITransport, AsyncClient


def _make_client_fixture(env: dict[str, str], unset: tuple[str, ...] = ()):
    async def client():
        import os
        for k in unset:
            os.environ.pop(k, None)
        for k, v in env.items():
            os.environ[k] = v
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
    return pytest.fixture(client)


auth_client = _make_client_fixture({
    "CORPUSMIND_HOST": "0.0.0.0",
    "CORPUSMIND_AUTH_TOKEN": "secret-lab-token-123",
})
plain_client = _make_client_fixture(
    {"CORPUSMIND_HOST": "127.0.0.1"},
    unset=("CORPUSMIND_AUTH_TOKEN",),
)


# --------------------------------------------------------------------------- #
# Issue 8 — shared bearer token on non-loopback bindings
# --------------------------------------------------------------------------- #


@pytest.mark.asyncio
async def test_issue8_health_stays_open_without_token(auth_client):
    r = await auth_client.get("/api/v1/health")
    assert r.status_code == 200  # healthcheck cannot present credentials


@pytest.mark.asyncio
async def test_issue8_api_rejects_missing_or_wrong_token(auth_client):
    r = await auth_client.get("/api/v1/projects")
    assert r.status_code == 401

    r = await auth_client.get(
        "/api/v1/projects", headers={"Authorization": "Bearer wrong"}
    )
    assert r.status_code == 401


@pytest.mark.asyncio
async def test_issue8_api_accepts_correct_token(auth_client):
    r = await auth_client.get("/api/v1/projects", headers={"Authorization": "Bearer secret-lab-token-123"})
    assert r.status_code == 200


@pytest.mark.asyncio
async def test_issue8_loopback_default_keeps_no_auth(plain_client):
    """Default local-first behavior is unchanged: no token configured, no auth."""
    r = await plain_client.get("/api/v1/projects")
    assert r.status_code == 200


# --------------------------------------------------------------------------- #
# Issue 9 — archive extraction cannot escape the temp dir
# --------------------------------------------------------------------------- #


def _build_evil_zip(member: str) -> bytes:
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w") as zf:
        zf.writestr(member, "evil")
    return buf.getvalue()


def _build_evil_targz(member: str) -> bytes:
    buf = io.BytesIO()
    with tarfile.open(fileobj=buf, mode="w:gz") as tar:
        data = b"evil"
        info = tarfile.TarInfo(name=member)
        info.size = len(data)
        tar.addfile(info, io.BytesIO(data))
    return buf.getvalue()


@pytest.mark.parametrize("evil_member", [
    "../../escape.txt",
    "/abs/escape.txt",
    "a/../../escape.txt",
])
def test_issue9_validate_zip_members_rejects_traversal(evil_member, tmp_path):
    from api.reference_corpus import _validate_zip_members

    zf = zipfile.ZipFile(io.BytesIO(_build_evil_zip(evil_member)))
    with pytest.raises(ValueError, match=r"[Uu]nsafe archive member"):
        _validate_zip_members(zf, str(tmp_path))


@pytest.mark.asyncio
async def test_issue9_zip_slip_via_download_endpoint_is_rejected(plain_client, monkeypatch):
    """End-to-end: a hostile archive served by a (compromised) mirror must be
    refused — the download job reports failure instead of writing files."""
    from tests.test_reference_corpus_archive import _patch_download, _wait_for_job

    evil = _build_evil_zip("../../evil-poc.txt")
    _patch_download(monkeypatch, evil)

    r = await plain_client.post("/api/v1/reference-corpora/bnc-baby/download-full")
    assert r.status_code == 200  # job accepted

    job = await _wait_for_job(plain_client, "bnc-baby")
    assert job["status"] == "failed", f"Expected failed, got: {job!r}"
    assert "Unsafe archive member" in (job.get("error") or job.get("message") or "")
    # and nothing escaped the temp dir
    assert not (tmp_project_root() / "evil-poc.txt").exists()


def tmp_project_root():
    from pathlib import Path

    return Path.cwd()
