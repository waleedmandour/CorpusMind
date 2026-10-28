"""v1.2.0 Lens round tests — batch runner, deletion, export, frameworks.

Uses a FILE-based SQLite DB (not :memory:) because the batch runner runs
in a background task with its own session — an in-memory DB would be a
different, empty database from that connection.
"""
from __future__ import annotations

import asyncio
import io
import json
import os
from unittest.mock import AsyncMock, MagicMock

import pytest
from httpx import ASGITransport, AsyncClient

_DB_FILE = "/tmp/cm-test-batchround.db"
if os.path.exists(_DB_FILE):
    os.remove(_DB_FILE)
os.environ["CORPUSMIND_DB_URL"] = f"sqlite+aiosqlite:///{_DB_FILE}"
os.environ["CORPUSMIND_DATA_DIR"] = "/tmp/cm-test-data-batchround"
from app.settings import get_settings  # noqa: E402 — env must be set first

get_settings.cache_clear()


@pytest.fixture
async def client():
    from app.main import app
    from storage.session import dispose_db

    if os.path.exists(_DB_FILE):
        os.remove(_DB_FILE)
    get_settings.cache_clear()
    await dispose_db()
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as ac:
        async with app.router.lifespan_context(app):
            yield ac
    await dispose_db()
    if os.path.exists(_DB_FILE):
        os.remove(_DB_FILE)


def _make_test_image(width: int = 60, height: int = 60) -> bytes:
    from PIL import Image
    img = Image.new("RGB", (width, height), (10, 120, 190))
    buf = io.BytesIO()
    img.save(buf, format="PNG")
    return buf.getvalue()


async def _setup_image_set(client: AsyncClient, n_images: int = 1) -> tuple[str, str]:
    r = await client.post("/api/v1/projects", json={"name": "P", "language": "en"})
    pid = r.json()["id"]
    r = await client.post(f"/api/v1/projects/{pid}/corpora", json={"name": "C", "language": "en"})
    cid = r.json()["id"]
    r = await client.post(f"/api/v1/corpora/{cid}/image-sets", json={"name": "Set A"})
    iset_id = r.json()["id"]
    for i in range(n_images):
        r = await client.post(
            f"/api/v1/image-sets/{iset_id}/images",
            files={"files": (f"img{i}.png", io.BytesIO(_make_test_image()), "image/png")},
        )
        assert r.status_code == 200, r.text
    return cid, iset_id


def _inject_mock_provider(client: AsyncClient) -> MagicMock:
    from ai.providers import ChatResponse
    from app.main import app

    mock = MagicMock()
    mock.name = "ollama"
    mock.default_model = "qwen3-vl:2b"
    mock.health = AsyncMock(return_value=True)
    mock.chat = AsyncMock(return_value=ChatResponse(
        content=json.dumps({
            "claims": [{"framework": "Kress & van Leeuwen (2006)", "category": "representational",
                        "claim": "Under a heuristic reading, the image may depict a scene.",
                        "evidence": [], "confidence": 0.4}],
            "summary": "A test summary.",
        }),
        model="qwen3-vl:2b",
        provider="ollama",
        raw={},
    ))
    mock.list_models = AsyncMock(return_value=["qwen3-vl:2b"])
    mock.aclose = AsyncMock()
    app.state.providers._instances["ollama"] = mock
    return mock


async def _wait_batch_done(client: AsyncClient, iset_id: str, timeout: float = 15.0) -> dict:
    deadline = asyncio.get_event_loop().time() + timeout
    last: dict = {}
    while asyncio.get_event_loop().time() < deadline:
        r = await client.get(f"/api/v1/image-sets/{iset_id}/run-batch/status")
        if r.status_code == 200:
            last = r.json()
            if last.get("running") is False:
                return last
        await asyncio.sleep(0.05)
    return last


# ---------------------------------------------------------------------------
# Batch runner
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_batch_status_404_before_any_run(client):
    _, iset_id = await _setup_image_set(client)
    r = await client.get(f"/api/v1/image-sets/{iset_id}/run-batch/status")
    assert r.status_code == 404


@pytest.mark.asyncio
async def test_batch_describe_run_completes(client):
    _, iset_id = await _setup_image_set(client, n_images=2)
    _inject_mock_provider(client)
    r = await client.post(f"/api/v1/image-sets/{iset_id}/run-batch", json={"action": "describe"})
    assert r.status_code == 200, r.text
    assert r.json()["status"] == "running"

    state = await _wait_batch_done(client, iset_id)
    assert state.get("status") == "done", state
    assert state.get("total") == 2
    assert state.get("done") == 2
    assert state.get("errors") == []

    # Descriptions are now cached — batch view sees them.
    r = await client.get(f"/api/v1/image-sets/{iset_id}/batch-analysis")
    assert r.status_code == 200
    assert r.json()["images_with_vlm"] == 2


@pytest.mark.asyncio
async def test_batch_describe_skips_cached(client):
    _, iset_id = await _setup_image_set(client, n_images=1)
    mock = _inject_mock_provider(client)

    r = await client.post(f"/api/v1/image-sets/{iset_id}/run-batch", json={"action": "describe"})
    assert r.status_code == 200
    await _wait_batch_done(client, iset_id)
    assert mock.chat.await_count == 1

    # Second run — cached → no additional model calls.
    r = await client.post(f"/api/v1/image-sets/{iset_id}/run-batch", json={"action": "describe"})
    assert r.status_code == 200
    await _wait_batch_done(client, iset_id)
    assert mock.chat.await_count == 1  # unchanged


@pytest.mark.asyncio
async def test_batch_all_runs_describe_and_lenses(client):
    _, iset_id = await _setup_image_set(client, n_images=1)
    mock = _inject_mock_provider(client)
    r = await client.post(f"/api/v1/image-sets/{iset_id}/run-batch", json={"action": "all"})
    assert r.status_code == 200, r.text
    state = await _wait_batch_done(client, iset_id)
    assert state.get("status") == "done", state
    assert state.get("errors") == []
    # describe + 8 lenses = 9 model calls for 1 image
    assert mock.chat.await_count == 9, mock.chat.await_count


@pytest.mark.asyncio
async def test_batch_second_run_conflict(client):
    _, iset_id = await _setup_image_set(client, n_images=1)
    _inject_mock_provider(client)
    r = await client.post(f"/api/v1/image-sets/{iset_id}/run-batch", json={"action": "describe"})
    assert r.status_code == 200
    # Immediately POST again — either 409 (still running) or 200 (finished fast).
    r2 = await client.post(f"/api/v1/image-sets/{iset_id}/run-batch", json={"action": "describe"})
    assert r2.status_code in (200, 409)
    await _wait_batch_done(client, iset_id)


# ---------------------------------------------------------------------------
# Deletion
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_delete_image(client):
    _, iset_id = await _setup_image_set(client, n_images=2)
    r = await client.get(f"/api/v1/image-sets/{iset_id}/images")
    img_id = r.json()[0]["id"]

    r = await client.delete(f"/api/v1/images/{img_id}")
    assert r.status_code == 200
    assert r.json()["deleted"] is True

    r = await client.get(f"/api/v1/image-sets/{iset_id}/images")
    assert len(r.json()) == 2 - 1
    # Deleted image is gone entirely.
    r = await client.get(f"/api/v1/images/{img_id}/analysis")
    assert r.status_code == 404


@pytest.mark.asyncio
async def test_delete_image_removes_file(client):
    _, iset_id = await _setup_image_set(client, n_images=1)
    r = await client.get(f"/api/v1/image-sets/{iset_id}/images")
    img_id = r.json()[0]["id"]

    from app.settings import get_settings
    storage_dir = get_settings().data_dir / "images"
    files_before = list(storage_dir.glob("*.png")) + list(storage_dir.glob("*.jpg"))
    assert files_before, "expected at least one stored image file"

    r = await client.delete(f"/api/v1/images/{img_id}")
    assert r.status_code == 200
    files_after = list(storage_dir.glob("*.png")) + list(storage_dir.glob("*.jpg"))
    assert len(files_after) == len(files_before) - 1


@pytest.mark.asyncio
async def test_delete_image_set_cascades(client):
    from app.settings import get_settings
    storage_dir = get_settings().data_dir / "images"
    before = {p.name for p in storage_dir.glob("*") if p.is_file()}

    _, iset_id = await _setup_image_set(client, n_images=3)
    r = await client.delete(f"/api/v1/image-sets/{iset_id}")
    assert r.status_code == 200
    assert r.json()["images_removed"] == 3

    r = await client.get(f"/api/v1/image-sets/{iset_id}/images")
    assert r.status_code == 200
    assert r.json() == []  # set gone → no images

    after = {p.name for p in storage_dir.glob("*") if p.is_file()}
    assert after == before, "the set's 3 image files should be removed from disk"


# ---------------------------------------------------------------------------
# Export
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_export_csv_and_json(client):
    _, iset_id = await _setup_image_set(client, n_images=2)
    r = await client.get(f"/api/v1/image-sets/{iset_id}/export?format=csv")
    assert r.status_code == 200
    assert "text/csv" in r.headers["content-type"]
    body = r.content.decode("utf-8-sig")
    assert "filename" in body
    assert "img0.png" in body

    r = await client.get(f"/api/v1/image-sets/{iset_id}/export?format=json")
    assert r.status_code == 200
    data = json.loads(r.content)
    assert len(data) == 2
    assert data[0]["filename"] == "img0.png"
    assert "ocr_text" in data[0]

    r = await client.get(f"/api/v1/image-sets/{iset_id}/export?format=xlsx")
    assert r.status_code == 200
    assert r.content[:2] == b"PK"  # xlsx = zip


@pytest.mark.asyncio
async def test_export_404_unknown_set(client):
    r = await client.get("/api/v1/image-sets/nope/export?format=csv")
    assert r.status_code == 404


# ---------------------------------------------------------------------------
# Frameworks catalogue
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_frameworks_endpoint_lists_yaml_catalogue(client):
    r = await client.get("/api/v1/frameworks")
    assert r.status_code == 200, r.text
    data = r.json()
    assert len(data["frameworks"]) >= 12
    keys = {f["key"] for f in data["frameworks"]}
    assert "kress-van-leeuwen" in keys
    kv = next(f for f in data["frameworks"] if f["key"] == "kress-van-leeuwen")
    assert kv["full_name"].startswith("Kress")
    assert {c["id"] for c in kv["categories"]} >= {"representational", "interactive", "compositional"}
