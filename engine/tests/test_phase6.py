"""Phase 6 integration tests — research workflow (§8.23) + collaboration (§10.2) + encryption (§13.2)."""
from __future__ import annotations

import os

import pytest
from httpx import ASGITransport, AsyncClient

os.environ["CORPUSMIND_DB_URL"] = "sqlite+aiosqlite:///:memory:"
os.environ["CORPUSMIND_DATA_DIR"] = "/tmp/cm-test-data-phase6"
from app.settings import get_settings

get_settings.cache_clear()


@pytest.fixture
async def client():
    from app.main import app
    from storage.session import dispose_db
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as ac:
        async with app.router.lifespan_context(app):
            yield ac
    await dispose_db()


async def _setup_project(client: AsyncClient) -> str:
    r = await client.post("/api/v1/projects", json={"name": "P6", "language": "en"})
    return r.json()["id"]


# --------------------------------------------------------------------------- #
# §8.23 Saved searches
# --------------------------------------------------------------------------- #


@pytest.mark.asyncio
async def test_saved_search_crud(client):
    """§8.23: Create, list, and delete saved searches."""
    pid = await _setup_project(client)

    # Create
    r = await client.post(f"/api/v1/projects/{pid}/saved-searches", json={
        "name": "My search",
        "query": "fox",
        "search_type": "concordance",
        "parameters": {"window": 5, "level": "lemma"},
    })
    assert r.status_code == 200
    sid = r.json()["id"]
    assert r.json()["name"] == "My search"
    assert r.json()["query"] == "fox"

    # List
    r = await client.get(f"/api/v1/projects/{pid}/saved-searches")
    assert r.status_code == 200
    assert len(r.json()) == 1
    assert r.json()[0]["id"] == sid

    # Delete
    r = await client.delete(f"/api/v1/saved-searches/{sid}")
    assert r.status_code == 200
    assert r.json()["deleted"] == sid

    # Verify deleted
    r = await client.get(f"/api/v1/projects/{pid}/saved-searches")
    assert len(r.json()) == 0


# --------------------------------------------------------------------------- #
# §8.23 Bookmarks
# --------------------------------------------------------------------------- #


@pytest.mark.asyncio
async def test_bookmark_crud(client):
    """§8.23: Create, list, and delete bookmarks."""
    pid = await _setup_project(client)
    # Create a corpus to bookmark against
    r = await client.post(f"/api/v1/projects/{pid}/corpora", json={"name": "C", "language": "en"})
    cid = r.json()["id"]

    # Create
    r = await client.post(f"/api/v1/projects/{pid}/bookmarks", json={
        "corpus_id": cid,
        "reference_type": "concordance_line",
        "reference_id": "doc:0:3",
        "label": "Interesting fox usage",
        "note": "Check this for metaphor analysis",
    })
    assert r.status_code == 200
    bid = r.json()["id"]
    assert r.json()["label"] == "Interesting fox usage"

    # List
    r = await client.get(f"/api/v1/projects/{pid}/bookmarks")
    assert r.status_code == 200
    assert len(r.json()) == 1

    # Delete
    r = await client.delete(f"/api/v1/bookmarks/{bid}")
    assert r.status_code == 200


# --------------------------------------------------------------------------- #
# §8.23 Favorites
# --------------------------------------------------------------------------- #


@pytest.mark.asyncio
async def test_favorite_crud(client):
    """§8.23: Create, list, and delete favorites."""
    pid = await _setup_project(client)

    # Create
    r = await client.post(f"/api/v1/projects/{pid}/favorites", json={
        "item_type": "corpus",
        "item_id": "abc123",
    })
    assert r.status_code == 200
    fid = r.json()["id"]

    # List
    r = await client.get(f"/api/v1/projects/{pid}/favorites")
    assert r.status_code == 200
    assert len(r.json()) == 1

    # Delete
    r = await client.delete(f"/api/v1/favorites/{fid}")
    assert r.status_code == 200


# --------------------------------------------------------------------------- #
# §10.2 Project sharing
# --------------------------------------------------------------------------- #


@pytest.mark.asyncio
async def test_project_sharing(client):
    """§10.2: Share a project (private + public)."""
    pid = await _setup_project(client)

    # Share as private
    r = await client.post(f"/api/v1/projects/{pid}/share", json={"visibility": "private"})
    assert r.status_code == 200
    data = r.json()
    assert data["visibility"] == "private"
    assert data["share_token"]  # non-empty token
    assert data["sync_enabled"] is True

    # Get share info
    r = await client.get(f"/api/v1/projects/{pid}/share")
    assert r.status_code == 200
    assert r.json()["share_token"] == data["share_token"]

    # Unshare
    r = await client.delete(f"/api/v1/projects/{pid}/share")
    assert r.status_code == 200
    assert r.json()["unshared"] == pid

    # Verify unshared
    r = await client.get(f"/api/v1/projects/{pid}/share")
    assert r.status_code == 404


@pytest.mark.asyncio
async def test_project_sharing_public(client):
    """§10.2: Share a project as public."""
    pid = await _setup_project(client)
    r = await client.post(f"/api/v1/projects/{pid}/share", json={"visibility": "public"})
    assert r.status_code == 200
    assert r.json()["visibility"] == "public"


# --------------------------------------------------------------------------- #
# §7.4 Sync events
# --------------------------------------------------------------------------- #


@pytest.mark.asyncio
async def test_sync_events(client):
    """§7.4: Log + list sync events (save-and-sync audit trail)."""
    pid = await _setup_project(client)

    # Log a sync event
    r = await client.post(f"/api/v1/projects/{pid}/sync", json={
        "event_type": "push",
        "summary": "Pushed 3 new documents",
    })
    assert r.status_code == 200
    assert r.json()["event_type"] == "push"

    # List sync events
    r = await client.get(f"/api/v1/projects/{pid}/sync-events")
    assert r.status_code == 200
    assert len(r.json()) == 1
    assert r.json()[0]["summary"] == "Pushed 3 new documents"


# --------------------------------------------------------------------------- #
# §13.2 Encryption status
# --------------------------------------------------------------------------- #


@pytest.mark.asyncio
async def test_encryption_status(client):
    """§13.2: Encryption status endpoint (transparency)."""
    r = await client.get("/api/v1/encryption/status")
    assert r.status_code == 200
    data = r.json()
    assert "enabled" in data
    assert "method" in data
    assert "notice" in data
    # By default, encryption is OFF
    assert data["enabled"] is False
    assert "OFF" in data["notice"] or "off" in data["notice"].lower()


# --------------------------------------------------------------------------- #
# Unit tests for encryption module
# --------------------------------------------------------------------------- #


def test_encryption_key_generation():
    """§13.2: Encryption key generation produces a valid 32-byte hex string."""
    from storage.encryption import generate_encryption_key
    key = generate_encryption_key()
    assert len(key) == 64  # 32 bytes = 64 hex chars
    assert all(c in "0123456789abcdef" for c in key)


def test_encryption_disabled_by_default():
    """§13.2: Encryption is OFF by default."""
    from storage.encryption import is_encryption_enabled
    # Clear any env var that might be set
    old = os.environ.pop("CORPUSMIND_ENCRYPTION_KEY", None)
    assert is_encryption_enabled() is False
    if old:
        os.environ["CORPUSMIND_ENCRYPTION_KEY"] = old


def test_encrypt_decrypt_roundtrip():
    """§13.2: Encrypt → decrypt produces the original data."""
    from storage.encryption import decrypt_file, encrypt_file, generate_encryption_key
    key = bytes.fromhex(generate_encryption_key())
    original = b"This is a secret research corpus."
    encrypted = encrypt_file(original, key)
    assert encrypted != original  # actually encrypted
    decrypted = decrypt_file(encrypted, key)
    assert decrypted == original  # roundtrip works


def test_encrypt_passthrough_when_disabled():
    """§13.2: When encryption is disabled, data passes through unchanged."""
    from storage.encryption import decrypt_file, encrypt_file
    old = os.environ.pop("CORPUSMIND_ENCRYPTION_KEY", None)
    data = b"unencrypted data"
    assert encrypt_file(data) == data  # passthrough
    assert decrypt_file(data) == data  # passthrough
    if old:
        os.environ["CORPUSMIND_ENCRYPTION_KEY"] = old
