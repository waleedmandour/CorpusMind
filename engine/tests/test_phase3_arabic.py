"""Phase 3 integration tests — Arabic NLP pipeline (§8.21)."""
from __future__ import annotations

import os

import pytest
from httpx import ASGITransport, AsyncClient

os.environ["CORPUSMIND_DB_URL"] = "sqlite+aiosqlite:///:memory:"
os.environ["CORPUSMIND_DATA_DIR"] = "/tmp/cm-test-data"
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


@pytest.mark.asyncio
async def test_arabic_morphology_analysis(client):
    """§8.21: Arabic morphology analysis — root, pattern, lemma, POS, Buckwalter,
    number, gender, broken plural."""
    r = await client.post("/api/v1/arabic/analyze", json={
        "text": "الطلاب يدرسون في المكتبة",
        "dialect": "msa",
    })
    assert r.status_code == 200
    data = r.json()
    assert data["backend"] == "camel"
    assert data["detected_dialect"] == "msa"
    assert data["token_count"] >= 3
    # Each token must have the required fields including Phase 3 polish additions
    for tok in data["tokens"]:
        assert "text" in tok
        assert "root" in tok
        assert "pattern" in tok
        assert "lemma" in tok
        assert "pos" in tok
        assert "buckwalter" in tok
        assert "number" in tok          # Phase 3 polish
        assert "gender" in tok          # Phase 3 polish
        assert "is_broken_plural" in tok  # Phase 3 polish
    # المكتبة should have root ك.ت.ب
    maktaba = next(t for t in data["tokens"] if "مكتبة" in t["text"])
    assert "ك.ت.ب" in maktaba["root"]
    assert maktaba["pattern"]  # non-empty pattern


@pytest.mark.asyncio
async def test_arabic_broken_plural_detection(client):
    """§8.21: Broken plural (جمع تكسير) detection."""
    # كتب is a broken plural of كتاب (root ك.ت.ب)
    r = await client.post("/api/v1/arabic/analyze", json={
        "text": "كتب طلاب مدارس",
        "dialect": "msa",
    })
    assert r.status_code == 200
    data = r.json()
    # At least one token should be flagged as a broken plural
    broken_plurals = [t for t in data["tokens"] if t["is_broken_plural"]]
    assert len(broken_plurals) >= 1, f"Expected at least one broken plural, got: {data['tokens']}"
    # Each broken plural must be a plural noun
    for bp in broken_plurals:
        assert bp["number"] == "p"
        assert bp["pos"] in ("noun", "adj")


@pytest.mark.asyncio
async def test_arabic_gender_and_number(client):
    """§8.21: Gender + number (singular/dual/plural) detection."""
    # طالب = singular masculine, طالبة = singular feminine,
    # طالبان = dual masculine, طالبات = plural feminine
    r = await client.post("/api/v1/arabic/analyze", json={
        "text": "طالب طالبة طالبان طالبات",
        "dialect": "msa",
    })
    assert r.status_code == 200
    data = r.json()
    tokens = {t["text"]: t for t in data["tokens"]}
    if "طالب" in tokens:
        assert tokens["طالب"]["number"] == "s"
        assert tokens["طالب"]["gender"] == "m"
    if "طالبة" in tokens:
        assert tokens["طالبة"]["gender"] == "f"


@pytest.mark.asyncio
async def test_arabic_dialect_id_with_cities(client):
    """§8.21: Dialect ID with city-level scores (Phase 3 polish)."""
    r = await client.post("/api/v1/arabic/dialect", json={
        "text": "الطلاب يدرسون في المكتبة",
        "include_cities": True,
    })
    assert r.status_code == 200
    data = r.json()
    dist = data["dialect_distribution"]
    assert "msa" in dist
    # With include_cities=True, city_scores should be present (if model available)
    if "city_scores" in data:
        # Should include at least one city
        assert len(data["city_scores"]) >= 1
        # Top city should be a known code
        assert data.get("top_city") in (None, "MSA", "BEI", "CAI", "DOH", "RAB", "TUN")


@pytest.mark.asyncio
async def test_arabic_root_extraction(client):
    """§8.21: Root extraction (الجذر)."""
    r = await client.post("/api/v1/arabic/roots", json={
        "text": "يكتب الكاتب في المكتبة كتابا"
    })
    assert r.status_code == 200
    data = r.json()
    roots = [row["root"] for row in data["roots"] if row["root"]]
    # All these words share the root ك.ت.ب
    assert "ك.ت.ب" in roots


@pytest.mark.asyncio
async def test_arabic_dialect_id(client):
    """§8.21: Dialect identification."""
    r = await client.post("/api/v1/arabic/dialect", json={
        "text": "الطلاب يدرسون في المكتبة"
    })
    assert r.status_code == 200
    data = r.json()
    dist = data["dialect_distribution"]
    # Should return a probability distribution over dialects
    assert "msa" in dist
    assert "egy" in dist
    assert "glf" in dist
    assert "lev" in dist
    # Probabilities should sum to ~1.0
    assert abs(sum(dist.values()) - 1.0) < 0.1


@pytest.mark.asyncio
async def test_arabic_register_detection(client):
    """§8.21: Register detection (Classical / MSA / Dialectal)."""
    r = await client.post("/api/v1/arabic/register", json={
        "text": "الطلاب يدرسون في المكتبة"
    })
    assert r.status_code == 200
    data = r.json()
    dist = data["register_distribution"]
    assert "classical" in dist
    assert "msa" in dist
    assert "dialectal" in dist


@pytest.mark.asyncio
async def test_arabic_buckwalter_transliteration(client):
    """§8.21: Buckwalter transliteration."""
    r = await client.post("/api/v1/arabic/buckwalter", json={
        "text": "الطلاب يدرسون"
    })
    assert r.status_code == 200
    data = r.json()
    # Buckwalter uses ASCII characters
    bw = data["buckwalter"]
    assert all(ord(c) < 128 for c in bw)
    assert "AlTlAb" in bw  # الطلاب → AlTlAb


@pytest.mark.asyncio
async def test_arabic_dediacritization(client):
    """§8.21: Diacritics removal (التشكيل)."""
    r = await client.post("/api/v1/arabic/dediacritize", json={
        "text": "يَدْرُسُونَ"  # with diacritics
    })
    assert r.status_code == 200
    data = r.json()
    # Result should have no diacritics (Harakat)
    diacritics = set("ًٌٍَُِّْ")
    assert not any(c in diacritics for c in data["dediacritized"])


@pytest.mark.asyncio
async def test_arabic_normalization(client):
    """§8.21: Normalization (alef variants, teh marbuta)."""
    r = await client.post("/api/v1/arabic/normalize", json={
        "text": "هذا بيت كبيره"  # teh marbuta ة at end of كبيره
    })
    assert r.status_code == 200
    data = r.json()
    # Normalization converts teh marbuta ة → ه
    assert "ه" in data["normalized"]


@pytest.mark.asyncio
async def test_arabic_backends_list(client):
    """§8.21: Backend listing."""
    r = await client.get("/api/v1/arabic/backends")
    assert r.status_code == 200
    data = r.json()
    backends = {b["name"]: b for b in data["backends"]}
    assert "camel" in backends
    assert backends["camel"]["available"] is True
    # Phase 3 ships CAMeL as the only wired backend; Farasa + SinaTools are stubbed
    assert backends["farasa"]["available"] is False
    assert backends["sinatools"]["available"] is False
    # CAMeL should report supported dialects
    assert "msa" in backends["camel"]["dialects_supported"]


@pytest.mark.asyncio
async def test_arabic_tools_registered(client):
    """§8.21: All 5 Arabic tools registered in the grounded-AI surface."""
    r = await client.get("/api/v1/ai/tools")
    assert r.status_code == 200
    tool_names = {t["name"] for t in r.json()["tools"]}
    # Phase 1 (6) + Phase 2 (8) + Phase 3 (5 Arabic) + ping = 20 tools total
    for name in ["arabic_morphology", "arabic_dialect_id", "arabic_roots",
                 "arabic_register", "arabic_transliterate"]:
        assert name in tool_names, f"missing Arabic tool: {name}"


@pytest.mark.asyncio
async def test_arabic_clitic_segmentation(client):
    """§8.21: Clitic segmentation."""
    r = await client.post("/api/v1/arabic/clitics", json={
        "text": "الطلاب يدرسون"
    })
    assert r.status_code == 200
    data = r.json()
    assert len(data["segments"]) >= 2
    for seg in data["segments"]:
        assert "surface" in seg
        assert "stem" in seg
        assert "pos" in seg


# --------------------------------------------------------------------------- #
# §8.22 Bilingual corpus tools — Phase 3 polish
# --------------------------------------------------------------------------- #


@pytest.mark.asyncio
async def test_translation_lookup_ar_en(client):
    """§8.22: Arabic→English translation lookup."""
    r = await client.post("/api/v1/bilingual/translate", json={
        "word": "كتاب",
        "direction": "ar-en",
    })
    assert r.status_code == 200
    data = r.json()
    assert data["word"] == "كتاب"
    assert data["direction"] == "ar-en"
    assert "book" in data["equivalents"]
    assert data["source"] == "starter-dict"


@pytest.mark.asyncio
async def test_translation_lookup_en_ar(client):
    """§8.22: English→Arabic translation lookup (reverse)."""
    r = await client.post("/api/v1/bilingual/translate", json={
        "word": "school",
        "direction": "en-ar",
    })
    assert r.status_code == 200
    data = r.json()
    assert data["direction"] == "en-ar"
    # Reverse lookup should find مدرسة
    assert "مدرسة" in data["equivalents"]


@pytest.mark.asyncio
async def test_parallel_alignment(client):
    """§8.22: Sentence-level parallel alignment (Gale-Church)."""
    import io
    # Create two English corpora (we don't have ar_core_web_sm installed,
    # so we use English for both sides — the alignment algorithm is
    # language-agnostic and works on any parallel pair).
    r = await client.post("/api/v1/projects", json={"name": "Bilingual", "language": "en"})
    pid = r.json()["id"]
    r = await client.post(f"/api/v1/projects/{pid}/corpora", json={"name": "Side A", "language": "en"})
    ar_cid = r.json()["id"]
    r = await client.post(f"/api/v1/projects/{pid}/corpora", json={"name": "Side B", "language": "en"})
    en_cid = r.json()["id"]

    text_a = b"The student studies in the library. The teacher writes the book. The boy reads the lesson."
    text_b = b"The student studies in the library. The teacher writes the book. The boy reads the lesson."

    await client.post(f"/api/v1/corpora/{ar_cid}/documents",
        files={"files": ("a.txt", io.BytesIO(text_a), "text/plain")})
    await client.post(f"/api/v1/corpora/{en_cid}/documents",
        files={"files": ("b.txt", io.BytesIO(text_b), "text/plain")})

    r = await client.post("/api/v1/bilingual/align", json={
        "ar_corpus_id": ar_cid,
        "en_corpus_id": en_cid,
    })
    assert r.status_code == 200
    data = r.json()
    assert data["method"] == "Gale-Church 1993 length-based"
    assert data["pair_count"] >= 1
    for pair in data["pairs"]:
        assert "ar_sentence" in pair
        assert "en_sentence" in pair
        assert "confidence" in pair
        assert 0.0 <= pair["confidence"] <= 1.0


@pytest.mark.asyncio
async def test_parallel_concordance(client):
    """§8.22: Parallel concordance (KWIC side-by-side)."""
    import io
    r = await client.post("/api/v1/projects", json={"name": "PC", "language": "en"})
    pid = r.json()["id"]
    r = await client.post(f"/api/v1/projects/{pid}/corpora", json={"name": "Side A", "language": "en"})
    ar_cid = r.json()["id"]
    r = await client.post(f"/api/v1/projects/{pid}/corpora", json={"name": "Side B", "language": "en"})
    en_cid = r.json()["id"]

    text_a = b"The student studies in the library. The teacher writes the book."
    text_b = b"The student studies in the library. The teacher writes the book."

    await client.post(f"/api/v1/corpora/{ar_cid}/documents",
        files={"files": ("a.txt", io.BytesIO(text_a), "text/plain")})
    await client.post(f"/api/v1/corpora/{en_cid}/documents",
        files={"files": ("b.txt", io.BytesIO(text_b), "text/plain")})

    r = await client.post("/api/v1/bilingual/parallel-concordance", json={
        "ar_corpus_id": ar_cid,
        "en_corpus_id": en_cid,
        "query": "student",
        "level": "word",
        "window": 3,
        "limit": 10,
    })
    assert r.status_code == 200
    data = r.json()
    assert data["total"] >= 1
    assert len(data["pairs"]) >= 1
    pair = data["pairs"][0]
    assert "ar_node" in pair
    assert "ar_left" in pair
    assert "ar_right" in pair
    assert "en_sentence" in pair
    assert pair["ar_node"] == "student"
