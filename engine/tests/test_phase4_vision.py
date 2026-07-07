"""Phase 4 integration tests — Vision suite (§9.1–9.10)."""
from __future__ import annotations

import io
import os

import pytest
from httpx import ASGITransport, AsyncClient

os.environ["CORPUSMIND_DB_URL"] = "sqlite+aiosqlite:///:memory:"
os.environ["CORPUSMIND_DATA_DIR"] = "/tmp/cm-test-data-vision"
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
    """Generate a small PNG image of a solid color."""
    from PIL import Image
    img = Image.new("RGB", (width, height), color)
    buf = io.BytesIO()
    img.save(buf, format="PNG")
    return buf.getvalue()


async def _setup_corpus_with_image_set(client: AsyncClient) -> tuple[str, str]:
    """Create a project + corpus + image set. Returns (corpus_id, image_set_id)."""
    r = await client.post("/api/v1/projects", json={"name": "Vision Test", "language": "en"})
    pid = r.json()["id"]
    r = await client.post(f"/api/v1/projects/{pid}/corpora", json={"name": "Images", "language": "en"})
    cid = r.json()["id"]
    r = await client.post(f"/api/v1/corpora/{cid}/image-sets", json={"name": "Test Set"})
    iset_id = r.json()["id"]
    return cid, iset_id


@pytest.mark.asyncio
async def test_create_image_set(client):
    """§9.1: Image set creation."""
    r = await client.post("/api/v1/projects", json={"name": "T", "language": "en"})
    pid = r.json()["id"]
    r = await client.post(f"/api/v1/projects/{pid}/corpora", json={"name": "C", "language": "en"})
    cid = r.json()["id"]
    r = await client.post(f"/api/v1/corpora/{cid}/image-sets", json={"name": "My Images"})
    assert r.status_code == 200
    data = r.json()
    assert data["name"] == "My Images"
    assert data["corpus_id"] == cid
    assert data["image_count"] == 0


@pytest.mark.asyncio
async def test_image_upload_and_analysis(client):
    """§9.2 + §9.4: Image upload triggers full analysis (colour, composition, OCR)."""
    _, iset_id = await _setup_corpus_with_image_set(client)
    img_bytes = _make_test_image(200, 150, (220, 50, 50))  # red image
    r = await client.post(
        f"/api/v1/image-sets/{iset_id}/images",
        files={"files": ("test.png", io.BytesIO(img_bytes), "image/png")},
    )
    assert r.status_code == 200
    data = r.json()
    assert len(data) == 1
    img = data[0]
    assert img["filename"] == "test.png"
    assert img["format"] == "png"
    assert img["width"] == 200
    assert img["height"] == 150
    assert img["size_bytes"] > 0

    # Retrieve the cached analysis
    img_id = img["id"]
    r = await client.get(f"/api/v1/images/{img_id}/analysis")
    assert r.status_code == 200
    analysis = r.json()
    assert analysis["filename"] == "test.png"
    assert "colours" in analysis["analysis"]
    assert "composition" in analysis["analysis"]
    assert "ocr" in analysis["analysis"]
    # The dominant colour should be red-ish
    dom = analysis["analysis"]["colours"]["dominant_colours"][0]
    assert dom["rgb"][0] > 150  # high R
    assert dom["rgb"][1] < 100  # low G
    assert dom["rgb"][2] < 100  # low B


@pytest.mark.asyncio
async def test_visual_grammar_analysis(client):
    """§9.10: Visual Grammar (Kress & van Leeuwen) analysis."""
    _, iset_id = await _setup_corpus_with_image_set(client)
    img_bytes = _make_test_image(200, 200, (50, 50, 220))  # blue image
    r = await client.post(
        f"/api/v1/image-sets/{iset_id}/images",
        files={"files": ("blue.png", io.BytesIO(img_bytes), "image/png")},
    )
    img_id = r.json()[0]["id"]

    r = await client.post(f"/api/v1/images/{img_id}/visual-grammar")
    assert r.status_code == 200
    data = r.json()
    assert data["framework"] == "Kress & van Leeuwen (2006)"
    assert "claims" in data
    assert "scores" in data
    # Every claim must be framework-attributed (§4 Principle 5)
    for claim in data["claims"]:
        assert "metafunction" in claim
        assert "category" in claim
        assert "claim" in claim
        assert "evidence" in claim
        assert "confidence" in claim
        # The claim text should reference Kress & van Leeuwen
        assert "Kress & van Leeuwen" in claim["claim"]
    # Should have at least one compositional claim
    metafunctions = {c["metafunction"] for c in data["claims"]}
    assert "compositional" in metafunctions


@pytest.mark.asyncio
async def test_image_text_alignment(client):
    """§9.8: Multimodal image-text alignment (flagship feature)."""
    _, iset_id = await _setup_corpus_with_image_set(client)
    # Upload a red image
    img_bytes = _make_test_image(200, 200, (220, 50, 50))
    r = await client.post(
        f"/api/v1/image-sets/{iset_id}/images",
        files={"files": ("red.png", io.BytesIO(img_bytes), "image/png")},
    )
    img_id = r.json()[0]["id"]

    # Align with a caption mentioning "red"
    r = await client.post(f"/api/v1/images/{img_id}/align", json={
        "text": "A red square on the left side of the image",
    })
    assert r.status_code == 200
    data = r.json()
    assert data["method"] == "heuristic-colour-positional"
    assert "regions" in data
    assert "spans" in data
    assert "alignments" in data
    # Should have 9 regions (3x3 grid)
    assert len(data["regions"]) == 9
    # Should have extracted text spans including "red" (colour term)
    span_texts = [s["text"].lower() for s in data["spans"]]
    assert "red" in span_texts
    # Should have at least one alignment
    assert len(data["alignments"]) >= 1
    # Each alignment must have confidence + match_reason + region/span refs
    for a in data["alignments"]:
        assert "region_id" in a
        assert "span_id" in a
        assert "confidence" in a
        assert "match_reason" in a
        assert 0.0 <= a["confidence"] <= 1.0
    # Cross-modal relations should be present (§9.9)
    assert "cross_modal_relations" in data


@pytest.mark.asyncio
async def test_cross_modal_relations(client):
    """§9.9: Cross-modal meaning detection (reinforcement, complementarity, etc.)."""
    _, iset_id = await _setup_corpus_with_image_set(client)
    img_bytes = _make_test_image(200, 200, (50, 180, 50))  # green
    r = await client.post(
        f"/api/v1/image-sets/{iset_id}/images",
        files={"files": ("green.png", io.BytesIO(img_bytes), "image/png")},
    )
    img_id = r.json()[0]["id"]

    # Align with text that mentions "green" — should produce high-confidence matches
    r = await client.post(f"/api/v1/images/{img_id}/align", json={
        "text": "The green colour dominates this image",
    })
    assert r.status_code == 200
    data = r.json()
    relations = data["cross_modal_relations"]
    assert len(relations) >= 1
    # Each relation must have a type + alignment references
    for rel in relations:
        assert "relation_type" in rel
        assert "alignment_refs" in rel
        assert "description" in rel
        assert "confidence" in rel


@pytest.mark.asyncio
async def test_image_upload_with_caption(client):
    """§9.2: Image upload with co-occurring caption text."""
    _, iset_id = await _setup_corpus_with_image_set(client)
    img_bytes = _make_test_image(100, 100, (128, 128, 128))
    r = await client.post(
        f"/api/v1/image-sets/{iset_id}/images",
        files={"files": ("grey.png", io.BytesIO(img_bytes), "image/png")},
        data={"captions": "A neutral grey square"},
    )
    assert r.status_code == 200
    img = r.json()[0]
    assert img["caption"] == "A neutral grey square"


@pytest.mark.asyncio
async def test_list_image_sets(client):
    """§9.1: List image sets in a corpus."""
    cid, _ = await _setup_corpus_with_image_set(client)
    # Create a second image set
    await client.post(f"/api/v1/corpora/{cid}/image-sets", json={"name": "Second Set"})
    r = await client.get(f"/api/v1/corpora/{cid}/image-sets")
    assert r.status_code == 200
    data = r.json()
    assert len(data) >= 2


@pytest.mark.asyncio
async def test_list_images_in_set(client):
    """§9.2: List images in an image set."""
    _, iset_id = await _setup_corpus_with_image_set(client)
    # Upload two images
    for color in [(220, 50, 50), (50, 50, 220)]:
        img_bytes = _make_test_image(100, 100, color)
        await client.post(
            f"/api/v1/image-sets/{iset_id}/images",
            files={"files": ("img.png", io.BytesIO(img_bytes), "image/png")},
        )
    r = await client.get(f"/api/v1/image-sets/{iset_id}/images")
    assert r.status_code == 200
    data = r.json()
    assert len(data) == 2
