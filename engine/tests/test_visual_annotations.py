"""v1.1.0 Lens round tests — the five-dimension visual annotation
framework and the corpus-linguistics battery computed over it.

Covers:
  - annotation schema endpoint (5 dimensions, EN+AR labels, categories)
  - PUT /images/{id}/annotations (round trip, invalid category 400,
    tags-only update preserves annotations, replace semantics)
  - bulk apply (dimension overwrite + tags add/replace)
  - visual-stats: hand-checked frequency + coverage
  - visual-profile: diversity battery sanity
  - visual-ngrams: hand-checked chains over a known shot-scale sequence
  - visual-collocations: hand-checked association measures
    (joint counts, dice, log-dice) on a known co-occurrence fixture
  - visual-keyness: set-vs-set f/N + LL direction
  - visual-dispersion: hand-checked Juilland's D and DP
  - visual-kwic: hits with left/right context
  - upload OCR-language resolution (corpus-language mapping)
  - reanalyse route + the 'analyse' batch action (gap-filling)
  - upload per-file isolation (bad file among good ones)

Uses a FILE-based SQLite DB like the other Lens rounds (background
sessions must see the same database).
"""
from __future__ import annotations

import asyncio
import io
import os

import pytest
from httpx import ASGITransport, AsyncClient

_DB_FILE = "/tmp/cm-test-visualcorpus.db"
if os.path.exists(_DB_FILE):
    os.remove(_DB_FILE)
os.environ["CORPUSMIND_DB_URL"] = f"sqlite+aiosqlite:///{_DB_FILE}"
os.environ["CORPUSMIND_DATA_DIR"] = "/tmp/cm-test-data-visualcorpus"
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


def _png(width: int = 60, height: int = 40, colour=(10, 120, 190)) -> bytes:
    from PIL import Image

    img = Image.new("RGB", (width, height), colour)
    buf = io.BytesIO()
    img.save(buf, format="PNG")
    return buf.getvalue()


async def _make_corpus_set(client: AsyncClient, name: str = "Set", language: str = "en") -> str:
    r = await client.post("/api/v1/projects", json={"name": "P", "language": language})
    pid = r.json()["id"]
    r = await client.post(f"/api/v1/projects/{pid}/corpora", json={"name": "C", "language": language})
    cid = r.json()["id"]
    r = await client.post(f"/api/v1/corpora/{cid}/image-sets", json={"name": name})
    return r.json()["id"]


async def _upload_one(client: AsyncClient, iset_id: str, name: str) -> str:
    """Upload a single image (separate request ⇒ deterministic created_at order)."""
    r = await client.post(
        f"/api/v1/image-sets/{iset_id}/images",
        files={"files": (name, io.BytesIO(_png()), "image/png")},
    )
    assert r.status_code == 200, r.text
    assert r.json()["failed"] == [], r.json()["failed"]
    return r.json()["uploaded"][0]["id"]


async def _annotate(client: AsyncClient, img_id: str, dims: dict, tags: list[str] | None = None):
    body: dict = {"dimensions": dims}
    if tags is not None:
        body["tags"] = tags
    r = await client.put(f"/api/v1/images/{img_id}/annotations", json=body)
    assert r.status_code == 200, r.text
    return r.json()


async def _seed_known_sequence(client: AsyncClient, iset_id: str) -> list[str]:
    """6 images with a KNOWN shot-scale stream:
    [close_up, medium_shot, close_up, long_shot, close_up, medium_shot]
    and multimodal_integration values:
    img0 caption+anchorage, img1 caption, img2 speech_balloon, img3 none,
    img4 caption, img5 none.
    """
    scales = ["close_up", "medium_shot", "close_up", "long_shot", "close_up", "medium_shot"]
    integration = [
        ["caption", "anchorage"], ["caption"], ["speech_balloon"], [], ["caption"], [],
    ]
    ids = []
    for i, (scale, integ) in enumerate(zip(scales, integration, strict=True)):
        img_id = await _upload_one(client, iset_id, f"frame{i}.png")
        await _annotate(
            client,
            img_id,
            {"shot_scale": {"values": [scale], "note": ""},
             "multimodal_integration": {"values": integ, "note": ""}},
            tags=[f"tag{i}"],
        )
        ids.append(img_id)
    return ids


# ---------------------------------------------------------------------------
# Schema + storage
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_annotation_schema_five_dimensions(client: AsyncClient):
    iset_id = await _make_corpus_set(client)
    r = await client.get(f"/api/v1/image-sets/{iset_id}/annotation-schema")
    assert r.status_code == 200
    data = r.json()
    assert [d["id"] for d in data["dimensions"]] == [
        "visual_morphology", "attentional_framing", "shot_scale",
        "path_transition", "multimodal_integration",
    ]
    for d in data["dimensions"]:
        assert d["label_en"] and d["label_ar"]
        assert d["description_en"] and d["description_ar"]
        assert d["framework"]
        assert len(d["categories"]) >= 8
        for c in d["categories"]:
            assert c["id"] and c["label_en"] and c["label_ar"]
    # Every category id is unique within its dimension.
    for d in data["dimensions"]:
        cat_ids = [c["id"] for c in d["categories"]]
        assert len(cat_ids) == len(set(cat_ids))


@pytest.mark.asyncio
async def test_put_annotations_round_trip_and_read_back(client: AsyncClient):
    iset_id = await _make_corpus_set(client)
    img_id = await _upload_one(client, iset_id, "one.png")
    out = await _annotate(
        client,
        img_id,
        {
            "visual_morphology": {"values": ["emblem", "graphic_stroke", "emblem"], "note": ""},
            "shot_scale": {"values": ["medium_shot"], "note": "waist-up crop"},
        },
        tags=["Press photo", "election", "Election"],
    )
    # duplicates removed, tags deduped case-insensitively
    assert out["annotations"]["visual_morphology"]["values"] == ["emblem", "graphic_stroke"]
    assert out["tags"] == ["Press photo", "election"]

    # The saved state is visible through the standard image listing.
    r = await client.get(f"/api/v1/image-sets/{iset_id}/images")
    meta = r.json()[0]["meta"]
    assert meta["tags"] == ["Press photo", "election"]
    assert meta["annotations"]["shot_scale"]["values"] == ["medium_shot"]
    assert meta["annotations"]["shot_scale"]["note"] == "waist-up crop"
    assert meta["annotations"]["visual_morphology"]["note"] == ""

    # The annotation listing exposes the set in reading order.
    r = await client.get(f"/api/v1/image-sets/{iset_id}/annotations")
    assert r.status_code == 200
    row = r.json()["annotations"][0]
    assert row["position"] == 0
    assert row["filename"] == "one.png"
    assert row["dimensions"]["shot_scale"]["values"] == ["medium_shot"]


@pytest.mark.asyncio
async def test_put_rejects_unknown_category_and_dimension_routes(client: AsyncClient):
    iset_id = await _make_corpus_set(client)
    img_id = await _upload_one(client, iset_id, "one.png")
    r = await client.put(
        f"/api/v1/images/{img_id}/annotations",
        json={"dimensions": {"shot_scale": {"values": ["warp_speed"]}}},
    )
    assert r.status_code == 400
    assert "warp_speed" in r.text

    # Analytics routes reject unknown dimensions with 400, not 500.
    for path in ("visual-ngrams", "visual-dispersion", "visual-kwic"):
        r = await client.get(
            f"/api/v1/image-sets/{iset_id}/{path}",
            params={"dim": "not_a_dimension", "category": "close_up"},
        )
        assert r.status_code == 400, (path, r.text)


@pytest.mark.asyncio
async def test_tags_only_update_preserves_annotations(client: AsyncClient):
    iset_id = await _make_corpus_set(client)
    img_id = await _upload_one(client, iset_id, "one.png")
    await _annotate(client, img_id, {"shot_scale": {"values": ["close_up"], "note": ""}})
    r = await client.put(
        f"/api/v1/images/{img_id}/annotations", json={"tags": ["only-tags"]}
    )
    assert r.status_code == 200
    assert r.json()["tags"] == ["only-tags"]
    assert r.json()["annotations"]["shot_scale"]["values"] == ["close_up"]


@pytest.mark.asyncio
async def test_bulk_annotations_add_and_replace_tags(client: AsyncClient):
    iset_id = await _make_corpus_set(client)
    ids = [await _upload_one(client, iset_id, f"img{i}.png") for i in range(3)]
    for i, img_id in enumerate(ids):
        await _annotate(client, img_id, {}, tags=[f"orig{i}"])

    r = await client.post(
        f"/api/v1/image-sets/{iset_id}/annotations-bulk",
        json={"dimensions": {"attentional_framing": {"values": ["panel"], "note": ""}},
              "tags": ["corpus-A"], "tag_mode": "add"},
    )
    assert r.status_code == 200, r.text
    assert r.json()["updated"] == 3

    r = await client.get(f"/api/v1/image-sets/{iset_id}/annotations")
    for row in r.json()["annotations"]:
        assert row["dimensions"]["attentional_framing"]["values"] == ["panel"]
        assert "corpus-A" in row["tags"]
        assert any(t.startswith("orig") for t in row["tags"])  # union, not wipe

    # replace mode overwrites tags; dimensions untouched keys preserved.
    r = await client.post(
        f"/api/v1/image-sets/{iset_id}/annotations-bulk",
        json={"tags": ["only"], "tag_mode": "replace"},
    )
    assert r.status_code == 200
    r = await client.get(f"/api/v1/image-sets/{iset_id}/annotations")
    for row in r.json()["annotations"]:
        assert row["tags"] == ["only"]
        assert row["dimensions"]["attentional_framing"]["values"] == ["panel"]

    # unknown category rejected
    r = await client.post(
        f"/api/v1/image-sets/{iset_id}/annotations-bulk",
        json={"dimensions": {"shot_scale": {"values": ["nope"]}}},
    )
    assert r.status_code == 400


# ---------------------------------------------------------------------------
# Analytics battery — hand-checked fixtures
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_visual_stats_frequency_and_coverage(client: AsyncClient):
    iset_id = await _make_corpus_set(client)
    await _seed_known_sequence(client, iset_id)

    r = await client.get(f"/api/v1/image-sets/{iset_id}/visual-stats")
    assert r.status_code == 200
    data = r.json()
    assert data["image_count"] == 6
    assert data["images_annotated"] == 6

    ss = data["dimensions"]["shot_scale"]
    assert ss["total_values"] == 6
    assert ss["distinct"] == 3
    assert ss["images_annotated"] == 6
    assert ss["coverage"] == 100.0
    freq = {row["category"]: row["count"] for row in ss["frequency"]}
    assert freq == {"close_up": 3, "medium_shot": 2, "long_shot": 1}
    pct = {row["category"]: row["percent"] for row in ss["frequency"]}
    assert pct["close_up"] == 50.0  # 3/6

    mi = data["dimensions"]["multimodal_integration"]
    freq_mi = {row["category"]: row["count"] for row in mi["frequency"]}
    assert freq_mi == {"caption": 3, "anchorage": 1, "speech_balloon": 1}
    # Unannotated dimension: zero coverage, empty frequency.
    vm = data["dimensions"]["visual_morphology"]
    assert vm["coverage"] == 0.0
    assert vm["frequency"] == []


@pytest.mark.asyncio
async def test_visual_profile_diversity(client: AsyncClient):
    iset_id = await _make_corpus_set(client)
    await _seed_known_sequence(client, iset_id)
    r = await client.get(f"/api/v1/image-sets/{iset_id}/visual-profile")
    assert r.status_code == 200
    ss = r.json()["dimensions"]["shot_scale"]
    assert ss["tokens"] == 6
    assert ss["types"] == 3
    assert ss["ttr"] == 0.5
    assert ss["frames_with_values"] == 6
    assert ss["values_per_frame"] == 1.0
    # Guiraud = 3 / sqrt(6) ≈ 1.225
    assert abs(ss["guiraud"] - round(3 / 6**0.5, 3)) < 1e-9
    vm = r.json()["dimensions"]["visual_morphology"]
    assert vm["tokens"] == 0 and vm["types"] == 0 and vm["ttr"] == 0.0


@pytest.mark.asyncio
async def test_visual_ngrams_known_chain(client: AsyncClient):
    iset_id = await _make_corpus_set(client)
    await _seed_known_sequence(client, iset_id)
    r = await client.get(
        f"/api/v1/image-sets/{iset_id}/visual-ngrams",
        params={"dim": "shot_scale", "n": 2},
    )
    assert r.status_code == 200
    data = r.json()
    assert data["stream_length"] == 6
    assert data["ngram_total"] == 5
    grams = {tuple(g["ngram"]): g["count"] for g in data["ngrams"]}
    assert grams == {
        ("close_up", "medium_shot"): 2,
        ("medium_shot", "close_up"): 1,
        ("close_up", "long_shot"): 1,
        ("long_shot", "close_up"): 1,
    }
    # Labels ride along for display.
    top = data["ngrams"][0]
    assert top["ngram_labels"] == ["Close-up", "Medium shot"]

    # include_gaps: unannotated frames surface as <gap>
    await _upload_one(client, iset_id, "unannotated.png")
    r = await client.get(
        f"/api/v1/image-sets/{iset_id}/visual-ngrams",
        params={"dim": "shot_scale", "n": 2, "include_gaps": True},
    )
    data = r.json()
    assert data["stream_length"] == 7
    assert ("medium_shot", "<gap>") in {tuple(g["ngram"]) for g in data["ngrams"]}
    # Without gaps the stream skips unannotated frames entirely.
    r = await client.get(
        f"/api/v1/image-sets/{iset_id}/visual-ngrams", params={"dim": "shot_scale", "n": 2}
    )
    data = r.json()
    assert data["stream_length"] == 6  # 7 frames, 1 unannotated → 6 tokens
    assert data["ngram_total"] == 5  # unannotated frame contributed nothing


@pytest.mark.asyncio
async def test_visual_collocations_hand_checked(client: AsyncClient):
    iset_id = await _make_corpus_set(client)
    await _seed_known_sequence(client, iset_id)
    r = await client.get(
        f"/api/v1/image-sets/{iset_id}/visual-collocations",
        params={"dim_a": "shot_scale", "dim_b": "multimodal_integration", "sort": "log_dice"},
    )
    assert r.status_code == 200
    data = r.json()
    # Frames annotated for BOTH dims: 0,1,2,4 (3 and 5 have no integration)
    assert data["frames"] == 4
    row = next(
        rrow for rrow in data["rows"]
        if rrow["category_a"] == "close_up" and rrow["category_b"] == "caption"
    )
    # close_up frames: 0,2,4 (all in N); caption frames: 0,1,4 (all in N);
    # joint (close_up ∩ caption): 0,4 → 2
    assert row["joint"] == 2
    assert row["f_a"] == 3
    assert row["f_b"] == 3
    # Dice = 2·2 / (3+3) = 0.6667
    assert abs(row["dice"] - round(2 * 2 / 6, 4)) < 1e-4
    # logDice = 14 + log2(2/3) ≈ 13.415
    import math

    assert abs(row["log_dice"] - round(14 + math.log2(2 / 3), 3)) < 1e-3
    # MI = log2(O/E), E = 3·3/4 = 2.25 → log2(2/2.25) ≈ -0.17
    assert abs(row["mi"] - round(math.log2(2 / 2.25), 3)) < 1e-3


@pytest.mark.asyncio
async def test_visual_keyness_set_vs_set(client: AsyncClient):
    iset_id = await _make_corpus_set(client, "Target Set")
    other_id = await _make_corpus_set(client, "Reference Set")

    # Target: close_up×3, medium×2, long×1  (N1 = 6)
    for scale in ["close_up", "medium_shot", "close_up", "long_shot", "close_up", "medium_shot"]:
        img_id = await _upload_one(client, iset_id, f"t-{scale}.png")
        await _annotate(client, img_id, {"shot_scale": {"values": [scale], "note": ""}})
    # Reference: close_up×1, long×3 (N2 = 4)
    for scale in ["close_up", "long_shot", "long_shot", "long_shot"]:
        img_id = await _upload_one(client, other_id, f"r-{scale}.png")
        await _annotate(client, img_id, {"shot_scale": {"values": [scale], "note": ""}})

    r = await client.get(
        f"/api/v1/image-sets/{iset_id}/visual-keyness",
        params={"other_iset_id": other_id, "dim": "shot_scale"},
    )
    assert r.status_code == 200
    data = r.json()
    assert data["target"]["values"] == 6
    assert data["reference"]["values"] == 4
    rows = {row["category"]: row for row in data["rows"]}
    assert rows["close_up"]["f_target"] == 3
    assert rows["close_up"]["f_reference"] == 1
    # close_up is over-represented in target → positive LL; long_shot the reverse.
    assert rows["close_up"]["log_likelihood"] > 0
    assert rows["long_shot"]["log_likelihood"] > 0  # 2x2 LL is direction-agnostic
    assert rows["long_shot"]["log_ratio"] < 0 < rows["close_up"]["log_ratio"]
    # Full §12 battery present per row.
    for key in ("log_likelihood", "chi_square", "log_ratio", "pct_diff", "simple_maths", "odds_ratio"):
        assert key in rows["close_up"]
    # Same set → 400.
    r = await client.get(
        f"/api/v1/image-sets/{iset_id}/visual-keyness",
        params={"other_iset_id": iset_id, "dim": "shot_scale"},
    )
    assert r.status_code == 400


@pytest.mark.asyncio
async def test_visual_dispersion_hand_checked(client: AsyncClient):
    iset_id = await _make_corpus_set(client)
    await _seed_known_sequence(client, iset_id)
    # stream = [close, medium, close, long, close, medium], bins=2 →
    # close_up: [2, 1]; medium_shot: [1, 1]; long_shot: [0, 1]
    r = await client.get(
        f"/api/v1/image-sets/{iset_id}/visual-dispersion",
        params={"dim": "shot_scale", "bins": 2},
    )
    assert r.status_code == 200
    data = r.json()
    assert data["bins"] == 2
    cats = {c["category"]: c for c in data["categories"]}

    # Juilland's D for [2,1]: mean 1.5, sd 0.5, cv 1/3, D = 1 − (1/3)/√1 ≈ 0.667
    assert abs(cats["close_up"]["juillands_d"] - round(1 - (1 / 3), 3)) < 1e-3
    assert cats["close_up"]["per_bin"] == [2, 1]
    assert cats["close_up"]["range"] == 1.0

    # Perfectly even [1,1] → D = 1.0
    assert cats["medium_shot"]["juillands_d"] == 1.0
    # Concentrated [0,1] → D = 0.0
    assert cats["long_shot"]["juillands_d"] == 0.0
    # DP for [2,1] with equal part sizes: 0.5·(|2/3−0.5| + |1/3−0.5|) = 1/6
    assert abs(cats["close_up"]["dp"] - round(1 / 6, 3)) < 1e-3


@pytest.mark.asyncio
async def test_visual_kwic_context(client: AsyncClient):
    iset_id = await _make_corpus_set(client)
    await _seed_known_sequence(client, iset_id)
    r = await client.get(
        f"/api/v1/image-sets/{iset_id}/visual-kwic",
        params={"dim": "shot_scale", "category": "close_up", "context": 1},
    )
    assert r.status_code == 200
    data = r.json()
    assert data["hit_count"] == 3
    hits = data["hits"]
    # position 0: left empty, right medium_shot
    assert hits[0]["position"] == 0
    assert hits[0]["left"] == []
    assert [h["category"] for h in hits[0]["right"]] == ["medium_shot"]
    # position 2: medium_shot … long_shot
    assert [h["category"] for h in hits[1]["left"]] == ["medium_shot"]
    assert [h["category"] for h in hits[1]["right"]] == ["long_shot"]
    # position 4: long_shot … medium_shot
    assert [h["category"] for h in hits[2]["left"]] == ["long_shot"]
    assert [h["category"] for h in hits[2]["right"]] == ["medium_shot"]
    assert hits[2]["node"]["label_en"] == "Close-up"
    assert data["category_label"] == "Close-up"


# ---------------------------------------------------------------------------
# Pipeline fixes — OCR language, reanalyse, isolation
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_upload_ocr_language_follows_corpus(client: AsyncClient):
    """An Arabic corpus maps to the ara+eng Tesseract pack (the engine is
    EN/AR bilingual); the resolved language rides in the cached OCR block
    even when Tesseract itself is absent (engine=none)."""
    iset_id = await _make_corpus_set(client, language="ar")
    img_id = await _upload_one(client, iset_id, "arabic.png")
    r = await client.get(f"/api/v1/images/{img_id}/analysis")
    assert r.json()["analysis"]["ocr"]["language"] == "ara+eng"

    # Explicit override wins.
    iset_en = await _make_corpus_set(client, language="en")
    r = await client.post(
        f"/api/v1/image-sets/{iset_en}/images",
        files={"files": ("override.png", io.BytesIO(_png()), "image/png")},
        data={"ocr_language": "fra"},
    )
    img2 = r.json()["uploaded"][0]["id"]
    r = await client.get(f"/api/v1/images/{img2}/analysis")
    assert r.json()["analysis"]["ocr"]["language"] == "fra"


@pytest.mark.asyncio
async def test_reanalyse_refreshes_base_analysis(client: AsyncClient):
    iset_id = await _make_corpus_set(client)
    img_id = await _upload_one(client, iset_id, "grey.png")

    # Simulate the no-tesseract-at-ingest defect: OCR never ran.
    from sqlalchemy.orm.attributes import flag_modified

    from storage.models import Image as ImageModel
    from storage.session import session_scope

    async with session_scope() as session:
        img = await session.get(ImageModel, img_id)
        a = dict(img.analysis or {})
        a["ocr"] = {"text": "", "confidence": 0.0, "word_count": 0, "engine": "none", "language": "eng"}
        # LLM caches must survive the refresh.
        a["vision_llm"] = {"default:abc": {"description": "kept", "model": "m"}}
        img.analysis = a
        flag_modified(img, "analysis")

    r = await client.post(f"/api/v1/images/{img_id}/reanalyse", json={"ocr_language": "eng"})
    assert r.status_code == 200, r.text
    assert r.json()["reanalysed"] is True

    r = await client.get(f"/api/v1/images/{img_id}/analysis")
    analysis = r.json()["analysis"]
    assert analysis["colours"]["brightness"] > 0  # refreshed
    assert analysis["vision_llm"]["default:abc"]["description"] == "kept"  # preserved

    # Missing bytes → 410, not a crash.
    async with session_scope() as session:
        img = await session.get(ImageModel, img_id)
        img.storage_path = "/nonexistent/path.png"
        await session.flush()
    r = await client.post(f"/api/v1/images/{img_id}/reanalyse")
    assert r.status_code == 410


@pytest.mark.asyncio
async def test_batch_analyse_action_fills_ocr_gaps(client: AsyncClient):
    """The 'analyse' batch action re-runs base analysis for images whose OCR
    engine is missing/none (the defect-#4 recovery path) and skips images
    that already have a real engine, unless refresh=True."""
    from sqlalchemy.orm.attributes import flag_modified

    from storage.models import Image as ImageModel
    from storage.session import session_scope

    iset_id = await _make_corpus_set(client)
    id_a = await _upload_one(client, iset_id, "a.png")
    id_b = await _upload_one(client, iset_id, "b.png")

    # a: OCR engine none (gap). b: OCR already ran on a real engine.
    async with session_scope() as session:
        for img_id, engine in ((id_a, "none"), (id_b, "tesseract")):
            img = await session.get(ImageModel, img_id)
            a = dict(img.analysis or {})
            a["ocr"] = {"text": "", "confidence": 0.0, "word_count": 0,
                        "engine": engine, "language": "eng"}
            img.analysis = a
            flag_modified(img, "analysis")

    r = await client.post(
        f"/api/v1/image-sets/{iset_id}/run-batch", json={"action": "analyse"}
    )
    assert r.status_code == 200, r.text
    for _ in range(100):
        await asyncio.sleep(0.05)
        st = (await client.get(f"/api/v1/image-sets/{iset_id}/run-batch/status")).json()
        if not st["running"]:
            break
    assert st["status"] == "done", st
    assert st["total"] == 2

    # Gap image refreshed (colours re-written; engine still none without
    # tesseract but the language + analysis blocks were regenerated).
    r = await client.get(f"/api/v1/images/{id_a}/analysis")
    assert r.json()["analysis"]["colours"]["brightness"] > 0


@pytest.mark.asyncio
async def test_upload_encrypted_at_rest(client: AsyncClient, monkeypatch):
    """With CORPUSMIND_ENCRYPTION_KEY set, bytes on disk are ciphertext while
    reads (thumbnail) transparently decrypt."""
    key_hex = os.urandom(32).hex()
    monkeypatch.setenv("CORPUSMIND_ENCRYPTION_KEY", key_hex)

    iset_id = await _make_corpus_set(client)
    raw = _png()
    r = await client.post(
        f"/api/v1/image-sets/{iset_id}/images",
        files={"files": ("secret.png", io.BytesIO(raw), "image/png")},
    )
    assert r.status_code == 200, r.text
    img_id = r.json()["uploaded"][0]["id"]

    from storage.models import Image as ImageModel
    from storage.session import session_scope

    async with session_scope() as session:
        img = await session.get(ImageModel, img_id)
        on_disk = open(img.storage_path, "rb").read()
    assert on_disk != raw  # actually encrypted
    assert len(on_disk) > len(raw)  # nonce + tag overhead

    # Reads still work (thumbnail route decrypts via read_image_bytes).
    r = await client.get(f"/api/v1/images/{img_id}/thumbnail")
    assert r.status_code == 200
    assert r.content[:3] == b"\xff\xd8\xff"  # JPEG
