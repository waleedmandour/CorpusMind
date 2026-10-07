"""Phase 3 integration tests — Arabic NLP pipeline (§8.21)."""
from __future__ import annotations

import os

import pytest
from httpx import ASGITransport, AsyncClient

os.environ["CORPUSMIND_DB_URL"] = "sqlite+aiosqlite:///:memory:"
os.environ["CORPUSMIND_DATA_DIR"] = "/tmp/cm-test-data"
from app.settings import get_settings

get_settings.cache_clear()


# ---------------------------------------------------------------------------
# camel_tools gate.
#
# The 9 tests marked @_needs_camel below exercise Arabic morphology,
# normalization, or backend loading. All of them require BOTH:
#   (a) the camel_tools Python package to be importable, AND
#   (b) the morphology database (calima-msa-r13) + dialect-ID model
#       (model6) to be downloaded via `camel_data -i` and stored under
#       ~/.camel_tools.
#
# A naive `find_spec("camel_tools")` check would only verify (a) and would
# let the tests run when (b) is missing, producing confusing FileNotFoundError
# / "assert 500 == 200" failures instead of clean skips. This deeper check
# actually attempts to instantiate the MorphologyDB, which is the cheapest
# operation that fails fast if either the package OR its data is missing.
#
# The other 8 tests in this file (dialect ID by length heuristics, register
# detection, AI tool registration, translation lookup, parallel alignment,
# parallel concordance) have no camel_tools dependency and run unconditionally
# — they were previously excluded from CI along with everything else in this
# file by the file-level `--ignore` flag in ci.yml, which silently dropped
# 8 perfectly runnable tests.
# ---------------------------------------------------------------------------
def _camel_is_usable() -> bool:
    """Return True only if camel_tools is importable AND its morphology
    database can actually be loaded. Used by the @_needs_camel skipif
    marker so we skip cleanly when EITHER the package OR its data is
    missing — not just the package."""
    try:
        import camel_tools  # noqa: F401
        from camel_tools.morphology.database import MorphologyDB
        # This will raise if the calima-msa-r13 database isn't downloaded.
        # v1.2.11: this line read `MorphologyDB.built_db(...)` - a method
        # that does not exist (the real name is `builtin_db`). The guard
        # therefore ALWAYS raised AttributeError and returned False, so all
        # 9 @_needs_camel tests silently skipped even on machines (incl. CI)
        # where camel_tools AND its data were fully installed. That is how
        # the Arabic Tools "spins forever" hang survived unnoticed.
        MorphologyDB.builtin_db("calima-msa-r13")
        return True
    except Exception:
        return False


_CAMEL_AVAILABLE = _camel_is_usable()
_needs_camel = pytest.mark.skipif(
    not _CAMEL_AVAILABLE,
    reason="camel_tools not installed or its morphology DB not downloaded "
           "(run `camel_data -i morphology-db-msa-r13` to install)",
)


@pytest.fixture
async def client():
    from app.main import app
    from storage.session import dispose_db
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as ac:
        async with app.router.lifespan_context(app):
            yield ac
    await dispose_db()


@_needs_camel
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


@_needs_camel
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


@_needs_camel
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


@_needs_camel
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


@_needs_camel
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


@_needs_camel
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


@_needs_camel
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


@_needs_camel
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


@_needs_camel
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


# ---------------------------------------------------------------------------
# v1.2.11 regression tests - the "Arabic Tools Analysis spins forever" bug.
#
# Root cause chain (all three layers had to be fixed):
#   1. camel_tools, on a machine without its provisioned data, attempts a
#      BLOCKING, TIMEOUT-LESS HTTPS download of its catalogue on first use
#      (Catalogue.update_catalogue -> requests.get with no timeout). On an
#      offline/firewalled machine that never returns.
#   2. The /arabic/* routes ran that synchronous pipeline inline in async
#      handlers, so the hang (or any slow first load) froze the WHOLE
#      engine: /health included.
#   3. The frontend had no request deadline and no cancel, so the panel
#      spun forever.
# The guard typo fixed above kept every @_needs_camel test skipping, so
# none of this was ever exercised.
# ---------------------------------------------------------------------------


@pytest.fixture
def _reset_camel_backend_cache():
    """Isolate tests that fiddle with data resolution: drop the lru_cached
    backend singleton and the lru_cached data-dir resolver, restore after."""
    from nlp.arabic.pipeline import get_arabic_backend

    get_arabic_backend.cache_clear()
    yield
    get_arabic_backend.cache_clear()


@pytest.mark.asyncio
async def test_camel_skip_guard_integrity():
    """Typo canary for _camel_is_usable (v1.2.11).

    This test ALWAYS runs. If camel_tools is importable AND its data is
    provisioned on this machine, the guard MUST report available - a future
    typo in the guard (e.g. the v1.2.x `built_db` typo that disabled the
    whole Arabic suite, including in CI) fails HERE, loudly, instead of
    silently skipping 9 tests forever.
    """
    import importlib.util

    from app.resource_paths import camel_tools_data_dir

    if importlib.util.find_spec("camel_tools") is None:
        pytest.skip("camel_tools not installed on this machine at all")
    # The API camel_tools actually exposes (would have caught built_db):
    from camel_tools.morphology.database import MorphologyDB

    assert hasattr(MorphologyDB, "builtin_db"), (
        "camel_tools API changed: MorphologyDB.builtin_db is gone - "
        "update _camel_is_usable() in this file"
    )
    if camel_tools_data_dir() is None:
        pytest.skip(
            "camel_tools installed but no provisioned data pack "
            "(run: camel_data -i morphology-db-msa-r13)"
        )
    assert _CAMEL_AVAILABLE, (
        "camel_tools IS installed AND its data IS provisioned, but "
        "_camel_is_usable() returned False - the guard is broken again "
        "(this is how the v1.2.x built_db typo hid the Arabic hang)"
    )


@pytest.mark.asyncio
async def test_health_resources_reports_camel_tools(client):
    """GET /health/resources must report CAMeL provisioning (v1.2.11).

    Filesystem checks only - this endpoint must never import or load
    camel_tools, and must never be able to trigger its download path.
    """
    from pathlib import Path

    r = await client.get("/api/v1/health/resources")
    assert r.status_code == 200
    body = r.json()
    camel = body["languages"]["camel_tools"]
    assert set(camel) >= {"installed", "data_dir", "morphology_db_msa", "dialectid_model6"}
    assert isinstance(camel["installed"], bool)
    if camel["installed"]:
        assert camel["data_dir"]
        # The catalogue marker the resolver keys on must exist in data_dir
        assert (Path(camel["data_dir"]) / "catalogue.json").is_file()


@pytest.mark.asyncio
@pytest.mark.usefixtures("_reset_camel_backend_cache")
async def test_arabic_data_missing_returns_503_fast(client, monkeypatch):
    """Unprovisioned machine: Arabic analysis must fail FAST with HTTP 503
    and an actionable hint - never attempt the timeout-less download that
    caused the indefinite hang (v1.2.11)."""
    import time as _time

    from app import resource_paths

    # Save the REAL resolver reference first: after monkeypatch replaces the
    # module attribute, only this saved object still has .cache_clear().
    from app.resource_paths import camel_tools_data_dir as _ct_resolver

    monkeypatch.delenv("CAMELTOOLS_DATA", raising=False)
    monkeypatch.setattr(resource_paths, "camel_tools_data_dir", lambda: None)
    _ct_resolver.cache_clear()
    try:
        t0 = _time.perf_counter()
        r = await client.post(
            "/api/v1/arabic/analyze",
            json={"text": "الطلاب يدرسون في المكتبة", "dialect": "msa"},
        )
        elapsed = _time.perf_counter() - t0
        assert r.status_code == 503
        detail = r.json()["detail"]
        assert "camel_data -i" in detail
        assert "never downloads data at request time" in detail
        # "Fast" must mean fast: the pre-flight is a filesystem check, not a
        # network attempt. Generous ceiling so slow CI runners stay green.
        assert elapsed < 10, f"503 took {elapsed:.1f}s - pre-flight is no longer fast"
    finally:
        _ct_resolver.cache_clear()


@pytest.mark.asyncio
async def test_arabic_timeout_returns_504(client, monkeypatch):
    """A stuck analysis must hit the hard deadline and return HTTP 504 with
    a hint (v1.2.11). The event loop stays free throughout - that property
    is asserted separately by the /health responsiveness test."""
    import time as _time

    from api import arabic as arabic_routes

    def _slow_analysis(*args, **kwargs):
        # Sync CPU-bound stub, slightly longer than the test deadline; the
        # abandoned worker thread simply drains on its own after the 504.
        _time.sleep(1.0)
        return None

    monkeypatch.setattr(arabic_routes, "analyze_arabic", _slow_analysis)
    monkeypatch.setattr(arabic_routes, "ARABIC_TIMEOUT_S", 0.3)
    t0 = _time.perf_counter()
    r = await client.post(
        "/api/v1/arabic/analyze",
        json={"text": "الطلاب يدرسون في المكتبة", "dialect": "msa"},
    )
    elapsed = _time.perf_counter() - t0
    assert r.status_code == 504
    detail = r.json()["detail"]
    assert "did not finish within" in detail
    assert "shorter text" in detail or "try again" in detail
    # 504 must come from the deadline, not after the work completed
    assert elapsed < 0.9


@_needs_camel
@pytest.mark.asyncio
async def test_health_stays_responsive_during_analysis(client):
    """While a REAL Arabic analysis runs (CAMeL loaded), /health must still
    answer promptly (v1.2.11). Before the fix the analysis ran ON the event
    loop and /health latency equalled the analysis duration.

    This test must NOT be skipped where camel_tools + data exist - the
    skipif guard above only skips genuinely unprovisioned machines.
    """
    import asyncio as _asyncio
    import time as _time

    if not _CAMEL_AVAILABLE:
        pytest.fail(
            "camel_tools + data are expected on this machine but the guard "
            "says otherwise; refusing to run this regression test as a "
            "no-op. Install: camel_data -i morphology-db-msa-r13"
        )
    # ~64k tokens: even on a warm cache this takes seconds, guaranteeing the
    # health probe overlaps a still-running analysis.
    big_text = " ".join(["الطلاب يدرسون في المكتبة الكبيرة ويقرأون الكتب"] * 8000)
    analyze_task = _asyncio.create_task(
        client.post("/api/v1/arabic/analyze", json={"text": big_text, "dialect": "msa"})
    )
    # Let the analysis request reach the engine and start hogging time
    await _asyncio.sleep(0.2)
    t0 = _time.perf_counter()
    health = await client.get("/api/v1/health")
    health_s = _time.perf_counter() - t0
    assert health.status_code == 200
    # Remaining analysis time AFTER the health probe completed: if the loop
    # were blocked by the analysis, the probe could only return once the
    # analysis was already done, leaving ~0s here.
    analysis_r = await analyze_task
    analysis_s = _time.perf_counter() - t0 - health_s
    assert analysis_r.status_code == 200
    # The overlap must be real, otherwise the assertion below is vacuous.
    assert analysis_s > 0.3, (
        f"analysis had only {analysis_s:.2f}s of work left after the health "
        f"probe returned ({health_s:.2f}s); enlarge the text"
    )
    # The loop must never be blocked for the whole analysis any more.
    assert health_s < 1.5, (
        f"/health took {health_s:.2f}s while analysis ran for "
        f"{analysis_s:.2f}s - CPU-bound work is back on the event loop"
    )
