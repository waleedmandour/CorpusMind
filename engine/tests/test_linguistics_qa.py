"""v1.0.1 linguistics-QA round — tests for every fix and new feature.

Covers: size-weighted DP + DP-norm, Fisher's exact, Haldane-corrected odds
ratio, MATTR/MTLD/Guiraud, readability (Flesch/LIX/RIX), regex + phrase +
KWIC-sort concordance, root/pattern frequency levels, frequency range +
diversity battery, folded collocate aggregation, asymmetric spans, POS and
stopword collocate filters, χ² Cochran diagnostic, keyness-bridge f2=0
exclusion, stopword-list CRUD, document stats, metadata-group pivot, and
the Arabic sentence segmenter.
"""
from __future__ import annotations

import io
import math

import pytest
from httpx import ASGITransport, AsyncClient

from stats.measures import (
    chi2_min_expected,
    fisher_exact_2x2,
    gries_dp,
    gries_dp_norm,
    guiraud,
    mattr,
    mtld,
    odds_ratio_haldane,
)
from stats.readability import (
    count_syllables_en,
    flesch_kincaid_grade,
    flesch_reading_ease,
    lix,
    rix,
)

# --------------------------------------------------------------------------- #
# Unit tests — pure statistics
# --------------------------------------------------------------------------- #


def test_gries_dp_size_weighted():
    # 10 tokens all in a 10-token doc, zero in a 90-token doc: expected
    # proportions 0.1/0.9 vs observed 1.0/0.0 → DP = 0.5·1.8 = 0.9
    assert math.isclose(gries_dp([10, 0], sizes=[10, 90]), 0.9)
    # uniform sizes fall back to the classic behaviour
    assert math.isclose(gries_dp([10, 0]), 0.5)
    # perfectly proportional distribution → DP 0 regardless of sizes
    assert math.isclose(gries_dp([10, 90], sizes=[10, 90]), 0.0, abs_tol=1e-9)


def test_gries_dp_norm_scaling():
    dp = gries_dp([10, 0])
    assert math.isclose(gries_dp_norm([10, 0]), dp * 2 / 1)


def test_fisher_exact_known_tables():
    # classic 2×2 (Fisher's tea-tasting style): p = 0.4857
    assert math.isclose(fisher_exact_2x2(3, 1, 1, 3), 0.4857, abs_tol=1e-3)
    # perfectly associated table
    assert fisher_exact_2x2(10, 0, 0, 10) < 1e-4
    # independent-ish table → large p
    assert fisher_exact_2x2(5, 5, 5, 5) > 0.9


def test_odds_ratio_haldane():
    # no zero cells → identical to raw OR
    assert math.isclose(odds_ratio_haldane(10, 100, 1000, 10000), 1.0, rel_tol=1e-6)
    # zero cell → finite Haldane value instead of inf
    v = odds_ratio_haldane(0, 100, 1000, 10000)
    assert math.isfinite(v) and v > 0


def test_chi2_min_expected():
    # cells (2,98,3,97): min expected = (r·c)/n = 5·100/200 = 2.5
    assert math.isclose(chi2_min_expected(2, 98, 3, 97), 2.5)


def test_mattr_perfectly_uniform():
    toks = list("abcdefghij" * 30)
    # every 10-token window has 10 types → MATTR = 1.0
    assert math.isclose(mattr(toks, window=10), 1.0)


def test_mtld_high_for_repetitive_cycling_text():
    toks = list("abcdefghij" * 30)
    assert mtld(toks) > 10  # many factor resets per 100 tokens


def test_guiraud_root_ttr():
    toks = ["a", "b", "a", "b", "a"]
    assert math.isclose(guiraud(toks), 2 / math.sqrt(5))


def test_flesch_worked_example():
    # ASL=20, ASW=1.5 → FRE = 206.835 - 20.3 - 126.9 = 59.635
    assert math.isclose(flesch_reading_ease(20, 1.5), 59.635, abs_tol=1e-3)
    # FKGL = 0.39·20 + 11.8·1.5 - 15.59 = 9.91
    assert math.isclose(flesch_kincaid_grade(20, 1.5), 9.91, abs_tol=1e-3)


def test_lix_rix():
    # 100 words, 5 sentences, 20 long words → LIX = 20 + 20 = 40
    assert math.isclose(lix(100, 5, 20), 40.0)
    assert math.isclose(rix(20, 5), 4.0)
    assert lix(0, 0, 0) == 0.0


def test_syllable_counter_basics():
    assert count_syllables_en("cat") == 1
    assert count_syllables_en("table") == 2     # syllabic consonant+le
    assert count_syllables_en("name") == 1      # silent -e
    assert count_syllables_en("wanted") == 2    # -ed after t adds a syllable
    assert count_syllables_en("walked") == 1    # silent -ed
    assert count_syllables_en("computer") == 3
    assert count_syllables_en("") == 0


# --------------------------------------------------------------------------- #
# Arabic segmenter (pure function — no CAMeL dependency)
# --------------------------------------------------------------------------- #


def test_arabic_sentencizer_splits_on_terminals():
    from nlp.arabic.pipeline import split_arabic_sentences

    text = "اللغة العربية جميلة. هل هذا صحيح؟ نعم، بالتأكيد!"
    parts = split_arabic_sentences(text)
    assert len(parts) == 3
    assert parts[0].endswith(".")
    assert parts[1].endswith("؟")


def test_arabic_sentencizer_protects_decimals():
    from nlp.arabic.pipeline import split_arabic_sentences

    parts = split_arabic_sentences("ارتفع المؤشر 3.4 في المئة. ثم انخفض.")
    assert len(parts) == 2
    assert "3.4" in parts[0]


def test_arabic_sentencizer_handles_newlines():
    from nlp.arabic.pipeline import split_arabic_sentences

    parts = split_arabic_sentences("سطر أول\nسطر ثان\n")
    assert len(parts) == 2


def test_arabic_stopword_checker():
    from nlp.stopwords import is_arabic_stopword

    assert is_arabic_stopword("من")
    assert is_arabic_stopword("في")
    assert not is_arabic_stopword("كتاب")


# --------------------------------------------------------------------------- #
# Reference-data sanity (the "404: Not Found" regression guard)
# --------------------------------------------------------------------------- #


def test_camel_arabic_reference_file_is_real_data():
    from pathlib import Path

    path = Path(__file__).resolve().parents[2] / "reference-data" / "reference-corpora" / "ar" / "camel-arabic-top1000.tsv"
    lines = path.read_text(encoding="utf-8").splitlines()
    data = [ln for ln in lines if ln.strip() and not ln.startswith("#")]
    assert len(data) >= 900, f"expected >= 900 entries, got {len(data)}"
    for ln in data[:50]:
        w, _, freq = ln.partition("\t")
        assert freq.strip().isdigit(), f"bad row: {ln!r}"
        assert w, f"empty word in row: {ln!r}"
        assert "404" not in ln


def test_awl_wordlist_present_and_shaped():
    from pathlib import Path

    path = Path(__file__).resolve().parents[2] / "reference-data" / "wordlists" / "awl-sublists.tsv"
    lines = [ln for ln in path.read_text(encoding="utf-8").splitlines() if ln.strip() and not ln.startswith("#")]
    assert len(lines) >= 500, f"AWL should have ~570 families, got {len(lines)}"
    head, _, subs = lines[0].partition("\t")
    assert head and subs  # headword<TAB>sublist(s)


# --------------------------------------------------------------------------- #
# API integration tests
# --------------------------------------------------------------------------- #


@pytest.fixture
async def client():
    import os

    os.environ["CORPUSMIND_DB_URL"] = "sqlite+aiosqlite:///:memory:"
    os.environ["CORPUSMIND_DATA_DIR"] = "/tmp/cm-test-data-v101"

    from app.settings import get_settings

    get_settings.cache_clear()
    from storage.session import _engine

    _engine.clear() if hasattr(_engine, "clear") else None

    from app.main import app

    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as ac:
        async with app.router.lifespan_context(app):
            yield ac
    from storage.session import dispose_db

    await dispose_db()


async def _make_corpus(client, text: bytes, name: str = "test.txt") -> str:
    r = await client.post("/api/v1/projects", json={"name": "T", "language": "en"})
    pid = r.json()["id"]
    r = await client.post(f"/api/v1/projects/{pid}/corpora", json={"name": "C", "language": "en"})
    cid = r.json()["id"]
    r = await client.post(
        f"/api/v1/corpora/{cid}/documents",
        files={"files": (name, io.BytesIO(text), "text/plain")},
    )
    assert r.status_code == 200
    return cid


@pytest.mark.asyncio
async def test_regex_concordance(client):
    cid = await _make_corpus(client, b"The cat sat. The cab arrived. The dog ran.")
    r = await client.post(
        f"/api/v1/corpora/{cid}/concordance",
        json={"query": "ca[bt]", "regex": True, "level": "word"},
    )
    assert r.status_code == 200
    data = r.json()
    assert data["total"] == 2
    nodes = {ln["node"].lower() for ln in data["lines"]}
    assert nodes == {"cat", "cab"}


@pytest.mark.asyncio
async def test_phrase_concordance(client):
    cid = await _make_corpus(client, b"The cat sat on the mat. The cat napped. A cat sat quietly.")
    r = await client.post(
        f"/api/v1/corpora/{cid}/concordance",
        json={"query": "cat sat", "level": "word", "window": 3},
    )
    assert r.status_code == 200
    data = r.json()
    assert data["total"] == 2
    for ln in data["lines"]:
        assert ln["node"].lower() == "cat sat"


@pytest.mark.asyncio
async def test_kwic_sort_by_left_token(client):
    cid = await _make_corpus(client, b"The dog ran. A dog barked. The dog slept.")
    r = await client.post(
        f"/api/v1/corpora/{cid}/concordance",
        json={"query": "dog", "level": "word",
              "sort": [{"side": "left", "offset": 1}]},
    )
    assert r.status_code == 200
    lines = r.json()["lines"]
    assert len(lines) == 3
    lefts = [ln["left"].split()[-1].lower() if ln["left"].split() else "" for ln in lines]
    assert lefts == sorted(lefts)
    assert lefts[0] == "a" and lefts[-1] == "the"


@pytest.mark.asyncio
async def test_frequency_range_and_diversity(client):
    cid = await _make_corpus(client, b"The cat sat. The dog ran. The bird flew.")
    r = await client.post(f"/api/v1/corpora/{cid}/frequency", json={"unit": "word"})
    assert r.status_code == 200
    data = r.json()
    the_row = next(row for row in data["rows"] if row["item"].lower() == "the")
    assert the_row["range"] == 1  # single document
    assert 0 < the_row["range_percent"] <= 100
    div = data["lexical_diversity"]
    assert set(div.keys()) == {"ttr", "sttr", "mattr", "mtld", "guiraud"}
    assert div["ttr"] > 0


@pytest.mark.asyncio
async def test_frequency_stopword_filter(client):
    cid = await _make_corpus(client, b"The cat sat. The dog ran.")
    r = await client.post(
        f"/api/v1/corpora/{cid}/frequency",
        json={"unit": "word", "stopword_list_id": "builtin:en"},
    )
    assert r.status_code == 200
    data = r.json()
    items = {row["item"].lower() for row in data["rows"]}
    assert "the" not in items
    assert "cat" in items


@pytest.mark.asyncio
async def test_collocation_folded_and_filtered(client):
    text = b"The researchers analyzed the data. The researchers published the results. Many researchers analyzed data sets."
    cid = await _make_corpus(client, text)
    r = await client.post(
        f"/api/v1/corpora/{cid}/collocations",
        json={"node": "the", "level": "word", "min_freq": 1, "measures": ["mi", "fisher", "chi_square", "delta_p"]},
    )
    assert r.status_code == 200
    data = r.json()
    # folded aggregation: 'researchers' appears once per sentence — single row
    researchers = [row for row in data["rows"] if row["collocate"].lower() == "researchers"]
    assert len(researchers) == 1
    row = researchers[0]
    assert "fisher" in row and 0.0 <= row["fisher"] <= 1.0
    assert "chi2_min_expected" in row
    assert data["warnings"] == [] or isinstance(data["warnings"], list)
    # corpus-wide marginals: N must exceed node-sentence token count
    assert row["N"] > row["fx"]


@pytest.mark.asyncio
async def test_collocation_asymmetric_span_and_pos_filter(client):
    cid = await _make_corpus(client, b"The quick brown fox jumps. The lazy brown dog sleeps.")
    # Right-only span: 'brown' should collocate with 'jumps'/'sleeps' via R1
    r = await client.post(
        f"/api/v1/corpora/{cid}/collocations",
        json={"node": "brown", "span_left": 0, "span_right": 2, "min_freq": 1, "measures": ["mi"]},
    )
    assert r.status_code == 200
    data = r.json()
    assert data["span_left"] == 0 and data["span_right"] == 2
    # POS exclude DET: no 'the' row
    r2 = await client.post(
        f"/api/v1/corpora/{cid}/collocations",
        json={"node": "quick", "min_freq": 1, "measures": ["mi"], "pos_exclude": ["DET"]},
    )
    assert r2.status_code == 200
    items2 = {row["collocate"].lower() for row in r2.json()["rows"]}
    assert "the" not in items2


@pytest.mark.asyncio
async def test_dispersion_size_weighted(client):
    r = await client.post("/api/v1/projects", json={"name": "T", "language": "en"})
    pid = r.json()["id"]
    r = await client.post(f"/api/v1/projects/{pid}/corpora", json={"name": "C", "language": "en"})
    cid = r.json()["id"]
    await client.post(
        f"/api/v1/corpora/{cid}/documents",
        files={"files": ("a.txt", io.BytesIO(b"The cat sat. The cat ran. The cat slept here."), "text/plain")},
    )
    await client.post(
        f"/api/v1/corpora/{cid}/documents",
        files={"files": ("b.txt", io.BytesIO(b"Dogs bark all night long outside."), "text/plain")},
    )
    r = await client.post(f"/api/v1/corpora/{cid}/dispersion", json={"term": "cat"})
    assert r.status_code == 200
    data = r.json()
    assert "gries_dp_norm" in data
    assert data["range"] == 1  # cat occurs only in doc a
    assert len(data["part_sizes"]) == 2
    # all 'cat' tokens in the first document → DP > 0 (size-weighted)
    assert data["gries_dp"] > 0


@pytest.mark.asyncio
async def test_keyness_stopwords_via_api(client):
    cid = await _make_corpus(client, b"The cat sat. The cat ran. Dogs bark loudly outside.")
    # use the same corpus as reference — degenerate but exercises the path
    r = await client.post(
        f"/api/v1/corpora/{cid}/keyness",
        json={"reference_corpus_id": cid, "stopword_list_id": "builtin:en"},
    )
    assert r.status_code == 200
    data = r.json()
    assert isinstance(data.get("warnings"), list)
    terms = {kw["term"] for kw in data["positive_keywords"]} | {kw["term"] for kw in data["negative_keywords"]}
    assert "the" not in terms


@pytest.mark.asyncio
async def test_keyness_bridge_excludes_f2_zero(monkeypatch):
    # The top-N list trap: target words absent from the reference list must
    # be EXCLUDED (previously they produced infinite Log Ratio / %DIFF).
    from reference_corpus import keyness_bridge

    async def _fake_bridge():
        pass

    # Build a minimal fake session/corpus by monkeypatching the two DB helpers
    async def _fake_latest(session, corpus_id):
        return "vid"

    async def _fake_size(session, vid):
        return 1000

    monkeypatch.setattr(keyness_bridge, "_latest_version_id", _fake_latest)
    monkeypatch.setattr(keyness_bridge, "_corpus_size", _fake_size)

    class _FakeSession:  # enough of a duck for the patched path
        pass

    monkeypatch.setattr(
        keyness_bridge,
        "load_frequency_list",
        lambda name: {"alpha": 50, "beta": 30},
    )

    # One row per token occurrence in the (faked) target corpus:
    # alpha×100, beta×10, gamma×80
    class _FakeResult:
        def all(self):
            return [("alpha",)] * 100 + [("beta",)] * 10 + [("gamma",)] * 80

    async def _exec(stmt):
        return _FakeResult()

    fake_session = _FakeSession()
    fake_session.execute = _exec

    result = await keyness_bridge.compute_keyness_with_reference_list(
        fake_session, "corpus-x", "be06-top1000"
    )
    terms = {kw["term"] for kw in result.positive_keywords} | {
        kw["term"] for kw in result.negative_keywords
    }
    assert "gamma" not in terms  # absent from reference list → excluded
    assert "alpha" in terms
    assert result.warnings  # top-N methodology warning present
    for kw in result.positive_keywords + result.negative_keywords:
        assert math.isfinite(kw["log_ratio"]) or kw["f2"] > 0


@pytest.mark.asyncio
async def test_stopword_list_crud(client):
    r = await client.get("/api/v1/stopword-lists")
    assert r.status_code == 200
    items = r.json()["items"]
    ids = {item["id"] for item in items}
    assert "builtin:en" in ids and "builtin:ar" in ids

    r = await client.post(
        "/api/v1/stopword-lists",
        json={"name": "My list", "language": "en", "words": ["Foo", "bar ", "foo"]},
    )
    assert r.status_code == 200
    created = r.json()
    assert created["words"] == ["bar", "foo"]  # deduped, stripped, lowered

    r = await client.delete(f"/api/v1/stopword-lists/{created['id']}")
    assert r.status_code == 200
    r = await client.delete("/api/v1/stopword-lists/builtin:en")
    assert r.status_code == 400


@pytest.mark.asyncio
async def test_document_stats_endpoint(client):
    cid = await _make_corpus(client, b"The cat sat on the mat. The dog barked loudly at night.")
    r = await client.get(f"/api/v1/corpora/{cid}/documents/stats")
    assert r.status_code == 200
    items = r.json()["items"]
    assert len(items) == 1
    row = items[0]
    assert row["tokens"] > 0
    assert row["sentences"] == 2
    assert 0 < row["ttr"] <= 1.0
    assert row["lix"] > 0


@pytest.mark.asyncio
async def test_readability_endpoint(client):
    cid = await _make_corpus(client, b"The cat sat. The dog ran fast. Birds fly high above trees.")
    r = await client.get(f"/api/v1/corpora/{cid}/readability")
    assert r.status_code == 200
    data = r.json()
    assert data["words"] > 0
    assert data["lix"] > 0
    # English corpus → Flesch panel present
    assert data["flesch_reading_ease"] is not None
    assert data["flesch_kincaid_grade"] is not None


@pytest.mark.asyncio
async def test_group_frequency_pivot(client):
    r = await client.post("/api/v1/projects", json={"name": "T", "language": "en"})
    pid = r.json()["id"]
    r = await client.post(f"/api/v1/projects/{pid}/corpora", json={"name": "C", "language": "en"})
    cid = r.json()["id"]

    r = await client.post(
        f"/api/v1/corpora/{cid}/documents",
        files={"files": ("a.txt", io.BytesIO(b"Cats love fish. Cats love naps."), "text/plain")},
    )
    doc_a = r.json()[0]["id"]
    r = await client.post(
        f"/api/v1/corpora/{cid}/documents",
        files={"files": ("b.txt", io.BytesIO(b"Dogs love walks. Dogs love balls."), "text/plain")},
    )
    doc_b = r.json()[0]["id"]

    r = await client.patch(
        f"/api/v1/corpora/{cid}/documents/{doc_a}/meta", json={"meta": {"genre": "cats"}}
    )
    assert r.status_code in (200, 204)
    r = await client.patch(
        f"/api/v1/corpora/{cid}/documents/{doc_b}/meta", json={"meta": {"genre": "dogs"}}
    )
    assert r.status_code in (200, 204)

    r = await client.post(
        f"/api/v1/corpora/{cid}/groups/frequency",
        json={"meta_field": "genre", "unit": "word", "min_freq": 1},
    )
    assert r.status_code == 200
    data = r.json()
    group_names = {g["name"] for g in data["groups"]}
    assert {"cats", "dogs"} <= group_names
    love = next(row for row in data["rows"] if row["item"].lower() == "love")
    assert love["groups"]["cats"]["freq"] == 2
    assert love["groups"]["dogs"]["freq"] == 2
    # per-million present for each group
    assert "per_million" in love["groups"]["cats"]
