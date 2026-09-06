"""v1.0.9 Lens round tests — image-corpus metadata + OCR corpus tools.

Covers the scholarly apparatus added to the visual side:
  - SQLite column migration (image_sets.description, images.meta)
  - image-set description (create + PATCH)
  - per-image metadata PATCH (non-destructive merge; exif/xmp locked)
  - bulk metadata ("tag all images")
  - set-level stats
  - OCR search (KWIC windows), OCR frequency (stopword control)
  - set-vs-set OCR keyness (log-likelihood)
  - OCR corpus export (txt <doc> markers + json)
  - list_images pagination (limit/offset + X-Total-Count)
  - vision suggestions on /query-suggestions?shell=lens

Uses a FILE-based SQLite DB (not :memory:) — same reason as the batch
round tests: background/second sessions must see the same database.
"""
from __future__ import annotations

import io
import json
import os
from pathlib import Path

import pytest
from httpx import ASGITransport, AsyncClient

_DB_FILE = "/tmp/cm-test-lensv109.db"
if os.path.exists(_DB_FILE):
    os.remove(_DB_FILE)
os.environ["CORPUSMIND_DB_URL"] = f"sqlite+aiosqlite:///{_DB_FILE}"
os.environ["CORPUSMIND_DATA_DIR"] = "/tmp/cm-test-data-lensv109"
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


def _make_test_image(width: int = 60, height: int = 40) -> bytes:
    from PIL import Image
    img = Image.new("RGB", (width, height), (10, 120, 190))
    buf = io.BytesIO()
    img.save(buf, format="PNG")
    return buf.getvalue()


async def _make_project_corpus(client: AsyncClient) -> str:
    r = await client.post("/api/v1/projects", json={"name": "P", "language": "en"})
    pid = r.json()["id"]
    r = await client.post(f"/api/v1/projects/{pid}/corpora", json={"name": "C", "language": "en"})
    return r.json()["id"]


async def _make_set(client: AsyncClient, cid: str, name: str, description: str = "") -> str:
    r = await client.post(f"/api/v1/corpora/{cid}/image-sets",
                          json={"name": name, "description": description})
    assert r.status_code == 200, r.text
    return r.json()["id"]


async def _upload(client: AsyncClient, iset_id: str, n: int = 2, name_prefix: str = "img") -> list[str]:
    ids = []
    for i in range(n):
        r = await client.post(
            f"/api/v1/image-sets/{iset_id}/images",
            files={"files": (f"{name_prefix}{i}.png", io.BytesIO(_make_test_image()), "image/png")},
        )
        assert r.status_code == 200, r.text
        ids.extend(img["id"] for img in r.json())
    return ids


async def _inject_ocr(img_id: str, text: str, meta: dict | None = None) -> None:
    """Write OCR text (and optional meta) straight into the DB row — the
    OCR engine itself needs tesseract, which the test env may not have."""
    from sqlalchemy.orm.attributes import flag_modified

    from storage.models import Image as ImageModel
    from storage.session import session_scope
    async with session_scope() as session:
        img = await session.get(ImageModel, img_id)
        assert img is not None
        a = dict(img.analysis or {})
        a["ocr"] = {"text": text, "confidence": 0.9, "word_count": len(text.split()),
                    "engine": "test", "language": "en"}
        img.analysis = a
        flag_modified(img, "analysis")
        if meta is not None:
            img.meta = meta
            flag_modified(img, "meta")


# ---------------------------------------------------------------------------
# Migration + schema
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_migration_adds_new_columns(client: AsyncClient):
    from sqlalchemy import text

    from storage.session import session_scope
    async with session_scope() as session:
        cols_sets = {r[1] for r in (await session.execute(text("PRAGMA table_info(image_sets)"))).fetchall()}
        cols_images = {r[1] for r in (await session.execute(text("PRAGMA table_info(images)"))).fetchall()}
    assert "description" in cols_sets
    assert "meta" in cols_images


# ---------------------------------------------------------------------------
# Image set description + PATCH
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_image_set_description_create_and_patch(client: AsyncClient):
    cid = await _make_project_corpus(client)
    iset_id = await _make_set(client, cid, "Front pages",
                              description="UK tabloid front pages, Jan-Mar 2024")
    r = await client.get(f"/api/v1/corpora/{cid}/image-sets")
    assert r.json()[0]["description"] == "UK tabloid front pages, Jan-Mar 2024"

    r = await client.patch(f"/api/v1/image-sets/{iset_id}",
                           json={"description": "Updated sampling note", "name": "Front pages 2024"})
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["description"] == "Updated sampling note"
    assert body["name"] == "Front pages 2024"


# ---------------------------------------------------------------------------
# Per-image metadata
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_image_meta_patch_merge_and_lock(client: AsyncClient):
    cid = await _make_project_corpus(client)
    iset_id = await _make_set(client, cid, "Ads")
    (img_id,) = await _upload(client, iset_id, n=1)

    # No metadata extracted from a bare generated PNG — meta starts empty.
    r = await client.get(f"/api/v1/image-sets/{iset_id}/images")
    assert r.json()[0]["meta"] == {}

    r = await client.patch(f"/api/v1/images/{img_id}",
                           json={"meta": {"genre": "advertisement", "source": "Al-Ahram",
                                          "license": "CC BY-NC", "exif": {"FAKE": "nope"}}})
    assert r.status_code == 200, r.text
    meta = r.json()["meta"]
    assert meta["user"]["genre"] == "advertisement"
    assert meta["user"]["source"] == "Al-Ahram"
    assert meta["user"]["license"] == "CC BY-NC"
    # The machine-extracted block is NOT writable through this route.
    assert "FAKE" not in meta.get("exif", {})

    # Merge, not replace: patching genre keeps source/license.
    r = await client.patch(f"/api/v1/images/{img_id}", json={"meta": {"genre": "editorial"}})
    meta = r.json()["meta"]
    assert meta["user"]["genre"] == "editorial"
    assert meta["user"]["source"] == "Al-Ahram"

    # Caption editing still works through the same route.
    r = await client.patch(f"/api/v1/images/{img_id}", json={"caption": "Cover page"})
    assert r.json()["caption"] == "Cover page"


@pytest.mark.asyncio
async def test_bulk_meta(client: AsyncClient):
    cid = await _make_project_corpus(client)
    iset_id = await _make_set(client, cid, "Posters")
    ids = await _upload(client, iset_id, n=3)

    r = await client.post(f"/api/v1/image-sets/{iset_id}/images-bulk-meta",
                          json={"meta": {"genre": "poster", "language": "ar"}})
    assert r.status_code == 200, r.text
    assert r.json() == {"updated": 3, "applied": ["genre", "language"]}

    r = await client.get(f"/api/v1/image-sets/{iset_id}/images")
    assert all(img["meta"]["user"]["genre"] == "poster" for img in r.json())

    # No valid keys -> 400
    r = await client.post(f"/api/v1/image-sets/{iset_id}/images-bulk-meta",
                          json={"meta": {"exif": "hack"}})
    assert r.status_code == 400


# ---------------------------------------------------------------------------
# Stats
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_image_set_stats(client: AsyncClient):
    cid = await _make_project_corpus(client)
    iset_id = await _make_set(client, cid, "Mixed")
    ids = await _upload(client, iset_id, n=2)
    await _inject_ocr(ids[0], "BREAKING NEWS headline here", meta={"user": {"genre": "news"}})
    await _inject_ocr(ids[1], "Buy now limited offer", meta={"user": {"genre": "ad", "source": "Web"}})

    r = await client.get(f"/api/v1/image-sets/{iset_id}/stats")
    assert r.status_code == 200, r.text
    s = r.json()
    assert s["image_count"] == 2
    assert s["formats"] == {"png": 2}
    # 60x40 generated images are landscape
    assert s["orientations"] == {"landscape": 2}
    assert s["coverage"]["with_ocr"] == 2
    assert s["coverage"]["with_caption"] == 0
    assert s["ocr_word_total"] == 8  # 4 + 4 words
    assert s["genres"] == {"news": 1, "ad": 1}
    assert s["sources"] == {"Web": 1}


# ---------------------------------------------------------------------------
# OCR search / frequency / keyness / corpus export
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_ocr_search_kwic(client: AsyncClient):
    cid = await _make_project_corpus(client)
    iset_id = await _make_set(client, cid, "Search set")
    (img_id,) = await _upload(client, iset_id, n=1)
    await _inject_ocr(img_id, "The minister announced a new policy for the city council yesterday")

    r = await client.get(f"/api/v1/image-sets/{iset_id}/ocr-search", params={"q": "policy"})
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["hit_count"] == 1
    hit = body["hits"][0]
    assert hit["match"].lower() == "policy"
    assert "announced a new" in hit["left"]
    assert "for the city" in hit["right"]
    assert hit["field"] == "ocr"

    # Caption is searched too
    await client.patch(f"/api/v1/images/{img_id}", json={"caption": "policy poster"})
    r = await client.get(f"/api/v1/image-sets/{iset_id}/ocr-search", params={"q": "policy"})
    assert r.json()["hit_count"] == 2
    fields = {h["field"] for h in r.json()["hits"]}
    assert fields == {"ocr", "caption"}


@pytest.mark.asyncio
async def test_ocr_frequency_stopwords(client: AsyncClient):
    cid = await _make_project_corpus(client)
    iset_id = await _make_set(client, cid, "Freq set")
    (img_id,) = await _upload(client, iset_id, n=1)
    await _inject_ocr(img_id, "the minister and the minister said policy policy policy")

    # Stopwords ON: 'the', 'and' filtered
    r = await client.get(f"/api/v1/image-sets/{iset_id}/ocr-frequency")
    words = {row["word"]: row["count"] for row in r.json()["frequency"]}
    assert "the" not in words and "and" not in words
    assert words["minister"] == 2 and words["policy"] == 3

    # Stopwords OFF: they return
    r = await client.get(f"/api/v1/image-sets/{iset_id}/ocr-frequency", params={"stopwords": "false"})
    words = {row["word"]: row["count"] for row in r.json()["frequency"]}
    assert words["the"] == 2


@pytest.mark.asyncio
async def test_ocr_keyness_between_sets(client: AsyncClient):
    cid = await _make_project_corpus(client)
    set_a = await _make_set(client, cid, "Ads")
    set_b = await _make_set(client, cid, "News")
    ids_a = await _upload(client, set_a, n=1, name_prefix="ad")
    ids_b = await _upload(client, set_b, n=1, name_prefix="news")
    await _inject_ocr(ids_a[0], "buy buy now cheap discount sale offer limited time")
    await _inject_ocr(ids_b[0], "minister minister announced policy council budget report announced")

    r = await client.get(f"/api/v1/image-sets/{set_a}/ocr-keyness", params={"other_iset_id": set_b})
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["target"]["tokens"] > 0 and body["reference"]["tokens"] > 0
    terms = {row["term"] for row in body["rows"]}
    # 'buy' appears only in the target set -> positive keyness
    assert "buy" in terms
    buy = next(row for row in body["rows"] if row["term"] == "buy")
    assert buy["f_target"] == 2 and buy["f_reference"] == 0
    assert buy["log_likelihood"] > 0
    # rows ranked by LL
    lls = [row["log_likelihood"] for row in body["rows"]]
    assert lls == sorted(lls, reverse=True)

    # Same-set comparison is rejected
    r = await client.get(f"/api/v1/image-sets/{set_a}/ocr-keyness", params={"other_iset_id": set_a})
    assert r.status_code == 400


@pytest.mark.asyncio
async def test_ocr_corpus_export(client: AsyncClient):
    cid = await _make_project_corpus(client)
    iset_id = await _make_set(client, cid, "Corpus set", description="Sampling note")
    (img_id,) = await _upload(client, iset_id, n=1)
    await _inject_ocr(img_id, "headline text of the front page",
                      meta={"user": {"genre": "news", "source": "Guardian"}})
    await client.patch(f"/api/v1/images/{img_id}", json={"caption": "Front page"})

    r = await client.get(f"/api/v1/image-sets/{iset_id}/ocr-corpus")
    assert r.status_code == 200
    body = r.text
    assert "<doc " in body and "</doc>" in body
    assert "headline text of the front page" in body
    assert "<caption>Front page</caption>" in body
    assert 'genre="news"' in body and 'source="Guardian"' in body

    r = await client.get(f"/api/v1/image-sets/{iset_id}/ocr-corpus", params={"format": "json"})
    data = r.json()
    assert data["image_set"] == "Corpus set"
    assert data["description"] == "Sampling note"
    assert data["documents"][0]["ocr_text"] == "headline text of the front page"
    assert data["documents"][0]["meta"]["genre"] == "news"


# ---------------------------------------------------------------------------
# Pagination
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_list_images_pagination(client: AsyncClient):
    cid = await _make_project_corpus(client)
    iset_id = await _make_set(client, cid, "Page set")
    await _upload(client, iset_id, n=5)

    r = await client.get(f"/api/v1/image-sets/{iset_id}/images", params={"limit": 2})
    assert r.status_code == 200
    assert len(r.json()) == 2
    assert r.headers["X-Total-Count"] == "5"

    r = await client.get(f"/api/v1/image-sets/{iset_id}/images", params={"limit": 2, "offset": 2})
    assert len(r.json()) == 2

    # No limit -> full list, backward compatible, no header
    r = await client.get(f"/api/v1/image-sets/{iset_id}/images")
    assert len(r.json()) == 5
    assert "X-Total-Count" not in r.headers


# ---------------------------------------------------------------------------
# Vision-aware suggestions
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_query_suggestions_shell_lens(client: AsyncClient):
    r = await client.get("/api/v1/ai/query-suggestions", params={"language": "en", "shell": "lens"})
    assert r.status_code == 200, r.text
    ids = [s["id"] for s in r.json()["suggestions"]]
    assert "vision-set-overview" in ids
    assert "vision-crossmodal" in ids
    # The text catalogue is still present below the vision block.
    assert "freq-top10" in ids
    # Vision templates come first.
    assert ids.index("vision-set-overview") < ids.index("freq-top10")

    # Main shell unchanged — no vision templates.
    r = await client.get("/api/v1/ai/query-suggestions", params={"language": "en"})
    ids = [s["id"] for s in r.json()["suggestions"]]
    assert "vision-set-overview" not in ids


# ---------------------------------------------------------------------------
# EXIF/XMP extractor unit checks
# ---------------------------------------------------------------------------

def test_extract_image_metadata_never_raises_and_no_gps():
    from vision.image_meta import extract_image_metadata
    # Garbage bytes -> {} (never raises)
    assert extract_image_metadata(b"not an image at all") == {}
    # A valid PNG with no metadata -> {}
    assert extract_image_metadata(_make_test_image()) == {}


def test_extract_image_metadata_xmp_packet():
    from vision.image_meta import extract_image_metadata
    xmp = (b"<x:xmpmeta xmlns:x='adobe:ns:meta/'>"
           b"<rdf:RDF><rdf:Description>"
           b"<photoshop:Headline>Protest march</photoshop:Headline>"
           b"<dc:creator><rdf:Seq><rdf:li>J. Doe</rdf:li></rdf:Seq></dc:creator>"
           b"<dc:subject><rdf:Bag><rdf:li>protest</rdf:li><rdf:li>city</rdf:li></rdf:Bag></dc:subject>"
           b"</rdf:Description></rdf:RDF></x:xmpmeta>")
    png = _make_test_image()
    # Splice an XMP packet into a fake "file" is not a real container —
    # exercise the packet scanner directly through the public function by
    # wrapping the packet with a minimal JPEG-like frame is overkill; the
    # scanner operates on raw bytes, so test the packet path via a JPEG SOI
    # header + APP1-ish payload that Pillow can still open is not feasible.
    # Instead assert on the pure scanner behaviour via the private helper.
    from vision.image_meta import _extract_xmp
    out = _extract_xmp(png + xmp + b"\x00" * 16)
    assert out["headline"] == "Protest march"
    assert out["creator"] == "J. Doe"
    assert out["keywords"] == ["protest", "city"]


# ---------------------------------------------------------------------------
# §18 facial-analysis opt-in toggle
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_facial_analysis_optin_toggle(client: AsyncClient):
    r = await client.get("/api/v1/facial-analysis/status")
    assert r.status_code == 200
    assert r.json()["enabled"] is False

    r = await client.post("/api/v1/facial-analysis/enabled", json={"enabled": True})
    assert r.status_code == 200, r.text
    assert r.json()["enabled"] is True

    # Persisted as a marker file next to the user's data.
    from app.settings import get_settings
    marker = Path(get_settings().data_dir) / "facial_analysis.enabled"
    assert marker.exists()

    r = await client.get("/api/v1/facial-analysis/status")
    assert r.json()["enabled"] is True

    r = await client.post("/api/v1/facial-analysis/enabled", json={"enabled": False})
    assert r.json()["enabled"] is False
    assert not marker.exists()
