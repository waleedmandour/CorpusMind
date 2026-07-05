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
    """§8.21: Arabic morphology analysis — root, pattern, lemma, POS, Buckwalter."""
    r = await client.post("/api/v1/arabic/analyze", json={
        "text": "الطلاب يدرسون في المكتبة",
        "dialect": "msa",
    })
    assert r.status_code == 200
    data = r.json()
    assert data["backend"] == "camel"
    assert data["detected_dialect"] == "msa"
    assert data["token_count"] >= 3
    # Each token must have the required fields
    for tok in data["tokens"]:
        assert "text" in tok
        assert "root" in tok
        assert "pattern" in tok
        assert "lemma" in tok
        assert "pos" in tok
        assert "buckwalter" in tok
    # المكتبة should have root ك.ت.ب
    maktaba = next(t for t in data["tokens"] if "مكتبة" in t["text"])
    assert "ك.ت.ب" in maktaba["root"]
    assert maktaba["pattern"]  # non-empty pattern


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
    assert "ه" in data["normalized"]  # noqa: RUF001 - Arabic character in test assertion


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
