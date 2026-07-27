"""Tests for GET /image-sets/{iset_id}/batch-analysis (build step 7).

The batch view aggregates cached vision-LM analysis across all images
in a set. It's a READ-ONLY endpoint — it doesn't call any model, just
surfaces what's already cached in img.analysis.

Coverage:
  - Empty set (no images): returns zeros + empty lists.
  - Set with images but no cached VLM analysis: returns zeros + note.
  - Set with cached VLM descriptions: aggregates them.
  - Set with cached discourse analysis: surfaces recurring themes.
  - OCR frequency: Python-side Counter over OCR text across images.
  - 404 for nonexistent image set.
"""
from __future__ import annotations

import io
import os

import pytest
from httpx import ASGITransport, AsyncClient

os.environ["CORPUSMIND_DB_URL"] = "sqlite+aiosqlite:///:memory:"
os.environ["CORPUSMIND_DATA_DIR"] = "/tmp/cm-test-batch-view"
os.environ.pop("CORPUSMIND_FACIAL_ANALYSIS_ENABLED", None)
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


def _make_test_image(width: int = 100, height: int = 100, color: tuple = (220, 50, 50)) -> bytes:
    from PIL import Image
    img = Image.new("RGB", (width, height), color)
    buf = io.BytesIO()
    img.save(buf, format="PNG")
    return buf.getvalue()


async def _setup_image_set_with_images(client: AsyncClient, count: int = 3) -> tuple[str, list[str]]:
    """Create a project + corpus + image set + N images. Returns (iset_id, [img_ids])."""
    r = await client.post("/api/v1/projects", json={"name": "T", "language": "en"})
    pid = r.json()["id"]
    r = await client.post(f"/api/v1/projects/{pid}/corpora", json={"name": "C", "language": "en"})
    cid = r.json()["id"]
    r = await client.post(f"/api/v1/corpora/{cid}/image-sets", json={"name": "S"})
    iset_id = r.json()["id"]

    img_ids = []
    for i in range(count):
        img_bytes = _make_test_image(100, 100, (220 - i * 30, 50, 50))
        r = await client.post(
            f"/api/v1/image-sets/{iset_id}/images",
            files={"files": (f"img{i}.png", io.BytesIO(img_bytes), "image/png")},
        )
        assert r.status_code == 200, r.text
        img_ids.append(r.json()[0]["id"])
    return iset_id, img_ids


async def _inject_vlm_cache(client: AsyncClient, img_id: str, description: str, model: str = "moondream"):
    """Inject a cached vision-LM description directly into the image's analysis."""
    from storage.models import Image as ImageModel
    from storage.session import session_scope
    async with session_scope() as session:
        img = await session.get(ImageModel, img_id)
        new_analysis = dict(img.analysis or {})
        vlm = dict(new_analysis.get("vision_llm", {}))
        vlm[f"{model}:abc123"] = {
            "description": description,
            "model": model,
            "provider": "ollama",
            "prompt": "Describe this image.",
            "prompt_hash": "abc123",
            "timestamp": "2026-01-01T00:00:00Z",
        }
        new_analysis["vision_llm"] = vlm
        img.analysis = new_analysis
        await session.commit()


async def _inject_discourse_cache(
    client: AsyncClient,
    img_id: str,
    framework_key: str,
    framework_name: str,
    claims: list[dict],
    model: str = "moondream",
):
    """Inject cached discourse analysis directly into the image's analysis."""
    from storage.models import Image as ImageModel
    from storage.session import session_scope
    async with session_scope() as session:
        img = await session.get(ImageModel, img_id)
        new_analysis = dict(img.analysis or {})
        discourse = dict(new_analysis.get("vision_llm_discourse", {}))
        discourse[f"{framework_key}:{model}:def456"] = {
            "analysis_type": framework_key,
            "framework": framework_name,
            "claims": claims,
            "summary": f"{framework_name} analysis.",
            "provenance": {
                "mode": "llm",
                "model": model,
                "provider": "ollama",
                "prompt_hash": "def456",
                "timestamp": "2026-01-01T00:00:00Z",
            },
        }
        new_analysis["vision_llm_discourse"] = discourse
        img.analysis = new_analysis
        await session.commit()


async def _inject_ocr(client: AsyncClient, img_id: str, ocr_text: str):
    """Inject OCR text directly into the image's analysis."""
    from storage.models import Image as ImageModel
    from storage.session import session_scope
    async with session_scope() as session:
        img = await session.get(ImageModel, img_id)
        new_analysis = dict(img.analysis or {})
        new_analysis["ocr"] = {
            "text": ocr_text,
            "confidence": 0.9,
            "word_count": len(ocr_text.split()),
            "engine": "tesseract",
            "language": "auto",
        }
        img.analysis = new_analysis
        await session.commit()


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_batch_analysis_empty_set(client):
    """An image set with no images returns zeros + empty lists."""
    r = await client.post("/api/v1/projects", json={"name": "T", "language": "en"})
    pid = r.json()["id"]
    r = await client.post(f"/api/v1/projects/{pid}/corpora", json={"name": "C", "language": "en"})
    cid = r.json()["id"]
    r = await client.post(f"/api/v1/corpora/{cid}/image-sets", json={"name": "Empty"})
    iset_id = r.json()["id"]

    r = await client.get(f"/api/v1/image-sets/{iset_id}/batch-analysis")
    assert r.status_code == 200
    data = r.json()
    assert data["image_count"] == 0
    assert data["images_with_vlm"] == 0
    assert data["images_with_discourse"] == 0
    assert data["recurring_themes"] == []
    assert data["ocr_frequency"] == []
    assert data["descriptions"] == []


@pytest.mark.asyncio
async def test_batch_analysis_no_cached_vlm(client):
    """Set with images but no cached VLM analysis: returns zeros + note."""
    iset_id, _ = await _setup_image_set_with_images(client, count=3)

    r = await client.get(f"/api/v1/image-sets/{iset_id}/batch-analysis")
    assert r.status_code == 200
    data = r.json()
    assert data["image_count"] == 3
    assert data["images_with_vlm"] == 0
    assert data["images_with_discourse"] == 0
    assert data["recurring_themes"] == []
    assert "note" in data
    assert "Run /describe" in data["note"]


@pytest.mark.asyncio
async def test_batch_analysis_aggregates_vlm_descriptions(client):
    """Set with cached VLM descriptions: aggregates them."""
    iset_id, img_ids = await _setup_image_set_with_images(client, count=3)

    await _inject_vlm_cache(client, img_ids[0], "A red square.")
    await _inject_vlm_cache(client, img_ids[1], "A blue circle.")
    # img_ids[2] has no VLM cache

    r = await client.get(f"/api/v1/image-sets/{iset_id}/batch-analysis")
    assert r.status_code == 200
    data = r.json()
    assert data["image_count"] == 3
    assert data["images_with_vlm"] == 2
    assert len(data["descriptions"]) == 2
    descs = {d["description"] for d in data["descriptions"]}
    assert "A red square." in descs
    assert "A blue circle." in descs


@pytest.mark.asyncio
async def test_batch_analysis_recurring_themes(client):
    """Set with cached discourse analysis: surfaces recurring themes."""
    iset_id, img_ids = await _setup_image_set_with_images(client, count=3)

    # All 3 images have social_semiotic analysis with the same category
    for i, img_id in enumerate(img_ids):
        await _inject_discourse_cache(
            client, img_id, "social_semiotic", "Kress & van Leeuwen (Social Semiotics 2006)",
            [
                {"framework": "Kress & van Leeuwen", "category": "representational",
                 "claim": f"Claim {i}", "evidence": [], "confidence": 0.6},
                {"framework": "Kress & van Leeuwen", "category": "interactive",
                 "claim": f"Interactive claim {i}", "evidence": [], "confidence": 0.5},
            ],
        )

    r = await client.get(f"/api/v1/image-sets/{iset_id}/batch-analysis")
    assert r.status_code == 200
    data = r.json()
    assert data["images_with_discourse"] == 3
    assert len(data["recurring_themes"]) == 1  # one framework
    theme = data["recurring_themes"][0]
    assert "Kress & van Leeuwen" in theme["framework"]
    assert theme["total_claims"] == 6  # 3 images × 2 claims each

    # Categories should be counted: representational=3, interactive=3
    cats = {c["category"]: c["count"] for c in theme["categories"]}
    assert cats["representational"] == 3
    assert cats["interactive"] == 3

    # An example claim should be attached
    assert any(c["example_claim"] for c in theme["categories"])


@pytest.mark.asyncio
async def test_batch_analysis_multiple_frameworks(client):
    """Multiple frameworks each get their own entry in recurring_themes."""
    iset_id, img_ids = await _setup_image_set_with_images(client, count=2)

    await _inject_discourse_cache(
        client, img_ids[0], "social_semiotic", "Kress & van Leeuwen",
        [{"framework": "K&vL", "category": "representational", "claim": "r", "evidence": [], "confidence": 0.5}],
    )
    await _inject_discourse_cache(
        client, img_ids[1], "framing", "Entman (1993) Framing Theory",
        [{"framework": "Entman", "category": "selection", "claim": "s", "evidence": [], "confidence": 0.5}],
    )

    r = await client.get(f"/api/v1/image-sets/{iset_id}/batch-analysis")
    assert r.status_code == 200
    data = r.json()
    assert len(data["recurring_themes"]) == 2
    frameworks = {t["framework"] for t in data["recurring_themes"]}
    assert "Kress & van Leeuwen" in frameworks
    assert "Entman (1993) Framing Theory" in frameworks


@pytest.mark.asyncio
async def test_batch_analysis_ocr_frequency(client):
    """OCR text across images is aggregated into a frequency list."""
    iset_id, img_ids = await _setup_image_set_with_images(client, count=3)

    # Each image has some OCR text with overlapping words
    await _inject_ocr(client, img_ids[0], "STOP sign ahead")
    await _inject_ocr(client, img_ids[1], "STOP here now")
    await _inject_ocr(client, img_ids[2], "YIELD sign ahead")

    r = await client.get(f"/api/v1/image-sets/{iset_id}/batch-analysis")
    assert r.status_code == 200
    data = r.json()
    # "stop" appears in 2 images, "sign" in 2, "ahead" in 2
    freq = {f["word"]: f["count"] for f in data["ocr_frequency"]}
    assert freq["stop"] == 2
    assert freq["sign"] == 2
    assert freq["ahead"] == 2
    assert freq["yield"] == 1
    assert freq["here"] == 1


@pytest.mark.asyncio
async def test_batch_analysis_404_nonexistent_set(client):
    """404 for an image set that doesn't exist."""
    r = await client.get("/api/v1/image-sets/nonexistent/batch-analysis")
    assert r.status_code == 404


@pytest.mark.asyncio
async def test_batch_analysis_mixed_data(client):
    """A set with some images having VLM, some having discourse, some
    having OCR, some having nothing — all aggregated correctly."""
    iset_id, img_ids = await _setup_image_set_with_images(client, count=4)

    # img 0: VLM + OCR
    await _inject_vlm_cache(client, img_ids[0], "A red square.")
    await _inject_ocr(client, img_ids[0], "red square")

    # img 1: discourse only
    await _inject_discourse_cache(
        client, img_ids[1], "framing", "Entman",
        [{"framework": "Entman", "category": "selection", "claim": "test", "evidence": [], "confidence": 0.5}],
    )

    # img 2: OCR only
    await _inject_ocr(client, img_ids[2], "blue circle")

    # img 3: nothing

    r = await client.get(f"/api/v1/image-sets/{iset_id}/batch-analysis")
    assert r.status_code == 200
    data = r.json()
    assert data["image_count"] == 4
    assert data["images_with_vlm"] == 1
    assert data["images_with_discourse"] == 1
    assert len(data["descriptions"]) == 1
    assert len(data["recurring_themes"]) == 1
    assert len(data["ocr_frequency"]) > 0
    # No note because some analysis exists
    assert data["note"] == ""
