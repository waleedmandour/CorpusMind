"""v1.2.13-2 CQL hardening — regression tests for the review findings.

Every P0 item has a test that FAILS on the v1.2.13-1 code and PASSES here:
  * P0-1 matcher cost: 50K-token test with budget/memory assertions
        (v1.2.13-1: 20K = 23 s / 1.4 GB, 50K OOM-killed; probes file
        tests/cql_probes_v1.2.13-1.py holds the reproduction probes).
  * P0-2 %c non-ASCII: French / German / Turkish / Greek / Cyrillic matrix
        plus Arabic %d, each also asserting the SQL-prefilter superset
        property (prefilter ON == prefilter OFF).
  * P0-3 student mode: allowlist boundary + stricter student budget.
  * P0-4 truth: real CAMeL root/pattern format, morph whole-string
        semantics, no Sketch-Engine-compat claim (docstring, enforced by
        review), differences documented.
Plus P1: wildcard helper consistency, page-first context + span cache,
server-side CQL export, cqp_compat, and the P2 consumers (find_cql_spans,
frequency/collocations/dispersion/n-grams over a CQL node, subcorpus-by-CQL,
saved queries, AI search_cql tool).
"""

from __future__ import annotations

import os
import time
from collections.abc import AsyncIterator

import pytest

from stats.cql import (
    CqlDeadlineExceeded,
    CqlSyntaxError,
    CqlTooExpensive,
    MatchLimits,
    STUDENT_MATCH_LIMITS,
    ast_to_str,
    parse_cql,
)


# --------------------------------------------------------------------------- #
# Fixture: same seeded corpora as test_cql.py, plus a Unicode doc
# --------------------------------------------------------------------------- #


@pytest.fixture
async def hard_env() -> AsyncIterator[tuple[str, str]]:
    """Fresh app + seeded English/Arabic corpora; yields (cid, ar_cid)."""
    os.environ["CORPUSMIND_DB_URL"] = "sqlite+aiosqlite:///:memory:"
    os.environ["CORPUSMIND_DATA_DIR"] = "/tmp/cm-test-data"
    from app.settings import get_settings

    get_settings.cache_clear()
    from app.main import app  # noqa: F401

    from storage.session import dispose_db

    async with app.router.lifespan_context(app):
        import storage.session as _ss
        from storage.models import AnnotationVersion, Corpus, Document, Project, Token

        sm = _ss._sessionmaker
        assert sm is not None
        async with sm() as s:
            p = Project(name="CQLH", language="en")
            s.add(p)
            await s.flush()
            c = Corpus(project_id=p.id, name="CQLH corpus", language="en")
            s.add(c)
            await s.flush()
            v = AnnotationVersion(corpus_id=c.id, version_label="v1", model_name="test")
            s.add(v)
            await s.flush()

            EN = [
                [("The", "the", "DET"), ("quick", "quick", "ADJ"), ("fox", "fox", "NOUN")],
                [("A", "a", "DET"), ("lazy", "lazy", "ADJ"), ("dog", "dog", "NOUN")],
            ]
            d = Document(corpus_id=c.id, filename="en.txt", cleaned_text="seed")
            s.add(d)
            await s.flush()
            for si, sent in enumerate(EN):
                for ti, (text, lemma, pos) in enumerate(sent):
                    s.add(Token(version_id=v.id, document_id=d.id, sentence_idx=si,
                                token_idx=ti, text=text, lemma=lemma, pos=pos))
            # Unicode doc (one token per "sentence" keeps positions simple)
            d2 = Document(corpus_id=c.id, filename="unicode.txt", cleaned_text="seed")
            s.add(d2)
            await s.flush()
            words = ["école", "École", "ÉCOLE", "москва", "МОСКВА",
                     "straße", "STRASSE", "Straße", "İstanbul", "İSTANBUL",
                     "ΑΒΣ", "ΑΒς", "αβς", "Οδός", "ΟΔΟΣ", "οδος"]
            for i, w in enumerate(words):
                s.add(Token(version_id=v.id, document_id=d2.id, sentence_idx=i,
                            token_idx=0, text=w, lemma=w.lower(), pos="NOUN"))
            await s.commit()
            cid = c.id

            # Arabic corpus with REAL-format morph layer
            pa = Project(name="CQLH-AR", language="ar")
            s.add(pa)
            await s.flush()
            ca = Corpus(project_id=pa.id, name="CQLH AR", language="ar")
            s.add(ca)
            await s.flush()
            va = AnnotationVersion(corpus_id=ca.id, version_label="v1", model_name="test")
            s.add(va)
            await s.flush()
            da = Document(corpus_id=ca.id, filename="ar.txt", cleaned_text="seed")
            s.add(da)
            await s.flush()
            AR = [
                ("كتب", "كتب", "VERB", "root=ك.ت.ب|pattern=1َ2َ3"),
                ("كتابا", "كتابا", "NOUN", "root=ك.ت.ب|pattern=1ُ2ُ3"),
                ("مدرسة", "مدرسة", "NOUN", ""),
            ]
            for ti, (text, lemma, pos, morph) in enumerate(AR):
                s.add(Token(version_id=va.id, document_id=da.id, sentence_idx=0,
                            token_idx=ti, text=text, lemma=lemma, pos=pos, morph=morph))
            await s.commit()
            ar_cid = ca.id

        yield cid, ar_cid
    await dispose_db()


async def _run(cid: str, query: str, **kw):
    from stats.cql import search_concordance_cql

    import storage.session as _ss

    sm = _ss._sessionmaker
    async with sm() as session:
        return await search_concordance_cql(session, cid, query, **kw)


# --------------------------------------------------------------------------- #
# P0-2: Unicode %c matrix + superset property
# --------------------------------------------------------------------------- #


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "query,expected,label",
    [
        ('"école" %c', 3, "FR é/É"),
        ('"москва" %c', 2, "RU Cyrillic"),
        ('"straße" %c', 3, "DE ß/SS casefold"),
        ('"αβς" %c', 3, "EL final sigma ς/Σ/σ"),
        ('"Οδος" %c', 2, "EL accents NOT folded by %c alone"),
        ('"οδος" %c%d', 3, "EL %c%d accent+case"),
        ('"ecole" %c', 0, "no fold-collapse of é→e under %c"),
        ('"İstanbul" %c', 2, "TR İ self-consistent"),
    ],
)
async def test_unicode_case_matrix(hard_env, query, expected, label) -> None:
    cid, _ = hard_env
    r = await _run(cid, query)
    assert r.total == expected, f"{label}: {query} -> {r.total}, expected {expected}"

    # Superset property: the SQL prefilter (ON) must yield exactly the same
    # result as a full scan (prefilter OFF). Any drift = silent under-match.
    import stats.cql as cql_mod

    original = cql_mod._anchor_condition

    async def _run_no_prefilter():
        # run the same query with the anchor condition disabled
        from stats.cql import search_concordance_cql
        import storage.session as _ss

        sm = _ss._sessionmaker
        async with sm() as session:
            saved = cql_mod._anchor_condition
            try:
                cql_mod._anchor_condition = lambda el, norm: None
                return await search_concordance_cql(session, cid, query)
            finally:
                cql_mod._anchor_condition = saved

    r2 = await _run_no_prefilter()
    assert r.total == r2.total, f"{label}: prefilter drift {r.total} != {r2.total}"
    assert [l.line_id for l in r.lines] == [l.line_id for l in r2.lines]


@pytest.mark.asyncio
async def test_arabic_diacritic_fold_falls_back_to_scan(hard_env) -> None:
    _, ar_cid = hard_env
    # %d has no SQL counterpart — the prefilter drops the condition (scan)
    # and the Python matcher folds harakat. (No harakat in the fixture; the
    # fold identity still must hold: %d on plain text matches plain text.)
    r = await _run(ar_cid, '"كتب" %d')
    assert r.total == 1


@pytest.mark.asyncio
async def test_wildcard_helper_consistent_across_layers(hard_env) -> None:
    """P1-5: one wildcard->regex helper; [..] is LITERAL, not a class."""
    cid, _ = hard_env
    # 'A[BC]*' must match the literal string 'A[BC]'-prefixed tokens only.
    # In the fixture, "A" (DET) exists: "A[BC]*" as a WILDCARD pattern
    # matches 'A' followed by nothing?? No — [BC] is literal, so it matches
    # only tokens spelled 'A[BC]...'; fixture has none -> 0 matches, and the
    # prefilter (LIKE path) must also over-match safely to the same set.
    r = await _run(cid, '"A[BC]*"')
    assert r.total == 0
    # fnmatch (removed) would have treated [BC] as a class and matched 'A'!
    r2 = await _run(cid, '"A"')
    assert r2.total == 1  # sanity: 'A' matches exactly one token


# --------------------------------------------------------------------------- #
# P0-1: budget, deadline, span bound, sentence-bounded scans
# --------------------------------------------------------------------------- #


@pytest.mark.asyncio
async def test_budget_raises_cql_too_expensive(hard_env, monkeypatch) -> None:
    cid, _ = hard_env
    tiny = MatchLimits(max_steps=2, max_span=100, deadline_s=10.0)
    with pytest.raises(CqlTooExpensive, match="work budget"):
        await _run(cid, '"quick"', limits=tiny)


@pytest.mark.asyncio
async def test_budget_422_actionable_endpoint(hard_env) -> None:
    from httpx import ASGITransport, AsyncClient

    from app.main import app

    cid, _ = hard_env
    import stats.cql as cql_mod

    # Make the default limits tiny via monkeypatched class default
    original = cql_mod.MatchLimits

    class TinyLimits(original):
        def __init__(self, *a, **kw):
            super().__init__(*a, **kw)
            object.__setattr__(self, "max_steps", 2)

    monkey = pytest.MonkeyPatch()
    monkey.setattr(cql_mod, "MatchLimits", TinyLimits)
    # the route resolved MatchLimits into its own namespace at import time
    import api.analysis as analysis_mod

    monkey.setattr(analysis_mod, "MatchLimits", TinyLimits)
    try:
        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as ac:
            r = await ac.post(
                f"/api/v1/corpora/{cid}/concordance/cql", json={"query": '"quick"'}
            )
        assert r.status_code == 422
        assert "too expensive" in r.json()["detail"].lower()
        assert "narrow" in r.json()["detail"].lower()  # actionable hint
    finally:
        monkey.undo()


@pytest.mark.asyncio
async def test_deadline_raises_and_maps_to_504(hard_env) -> None:
    cid, _ = hard_env
    import stats.cql as cql_mod

    limits = MatchLimits(max_steps=10_000_000, max_span=100, deadline_s=-1.0)
    with pytest.raises(CqlDeadlineExceeded, match="deadline"):
        await _run(cid, '"quick"', limits=limits)

    from httpx import ASGITransport, AsyncClient

    from app.main import app

    original = cql_mod.MatchLimits

    class PastDeadline(original):
        def __init__(self, *a, **kw):
            super().__init__(*a, **kw)
            object.__setattr__(self, "deadline_s", -1.0)

    monkey = pytest.MonkeyPatch()
    monkey.setattr(cql_mod, "MatchLimits", PastDeadline)
    import api.analysis as analysis_mod2

    monkey.setattr(analysis_mod2, "MatchLimits", PastDeadline)
    try:
        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as ac:
            r = await ac.post(
                f"/api/v1/corpora/{cid}/concordance/cql", json={"query": '"quick"'}
            )
        assert r.status_code == 504
    finally:
        monkey.undo()


@pytest.mark.asyncio
async def test_max_span_bound(hard_env) -> None:
    cid, _ = hard_env
    # A gap wider than max_span cannot match.
    limits = MatchLimits(max_steps=100_000, max_span=2, deadline_s=20.0)
    r = await _run(cid, '"quick" []{2} "fox"', limits=limits)
    assert r.total == 0  # gap of 2 needs a span of 4 > max_span 2
    r2 = await _run(cid, '"quick" "fox"', limits=limits)
    assert r2.total == 1  # span of 2 is within the bound


@pytest.mark.asyncio
async def test_within_sentence_never_scans_beyond(hard_env) -> None:
    cid, _ = hard_env
    # Two one-token "sentences": DET ADJ | DET ADJ — cross-sentence
    # "quick fox"?? quick is s0 t1, fox s0 t2 — same sentence. Build the
    # cross-boundary probe from the sentence split: "quick" is the LAST
    # token of s0 and "A" the FIRST of s1; a document-scope gap may bridge
    # them, a sentence-scope one may not.
    r_doc = await _run(cid, '"quick" []* "dog"')
    assert r_doc.total == 1  # crosses the s0/s1 boundary (document scope)
    r_sent = await _run(cid, '"quick" []* "dog" within s')
    assert r_sent.total == 0  # sentence bound forbids the crossing


# --------------------------------------------------------------------------- #
# P0-1: matcher cost regression — 50K tokens under budget/memory assertions
# (budget-based, not machine-timing-based). v1.2.13-1 measured 23 s / 1.4 GB
# at 20K and was OOM-killed at 50K (see tests/cql_probes_v1.2.13-1.py).
# --------------------------------------------------------------------------- #


@pytest.mark.asyncio
async def test_matcher_cost_50k_tokens_memory_bounded() -> None:
    import tracemalloc

    os.environ["CORPUSMIND_DB_URL"] = "sqlite+aiosqlite:///:memory:"
    os.environ["CORPUSMIND_DATA_DIR"] = "/tmp/cm-test-data"
    from app.settings import get_settings

    get_settings.cache_clear()
    from app.main import app  # noqa: F401

    from storage.session import dispose_db

    async with app.router.lifespan_context(app):
        import storage.session as _ss
        from storage.models import AnnotationVersion, Corpus, Document, Project, Token

        sm = _ss._sessionmaker
        async with sm() as s:
            p = Project(name="Perf", language="en")
            s.add(p)
            await s.flush()
            c = Corpus(project_id=p.id, name="Perf", language="en")
            s.add(c)
            await s.flush()
            v = AnnotationVersion(corpus_id=c.id, version_label="v1", model_name="test")
            s.add(v)
            await s.flush()
            d = Document(corpus_id=c.id, filename="perf.txt", cleaned_text="seed")
            s.add(d)
            await s.flush()
            # one 'sentence' so the document-scope gap path is exercised
            N = 50_000
            rows = []
            i = 0
            pos_i = 0
            while len(rows) < N:
                rows.append(("the", "the", "DET"))
                for k in range(48):
                    if len(rows) >= N:
                        break
                    rows.append((f"w{pos_i}_{k}", f"w{pos_i}_{k}", "NOUN"))
                rows.append(("of", "of", "ADP"))
                for k in range(48):
                    if len(rows) >= N:
                        break
                    rows.append((f"v{pos_i}_{k}", f"v{pos_i}_{k}", "NOUN"))
                pos_i += 1
            for idx, (text, lemma, pos) in enumerate(rows[:N]):
                s.add(Token(version_id=v.id, document_id=d.id, sentence_idx=0,
                            token_idx=idx, text=text, lemma=lemma, pos=pos))
            await s.commit()
            cid = c.id

        from stats.cql import search_concordance_cql

        async with sm() as session:
            tracemalloc.start()
            r = await search_concordance_cql(
                session, cid, '"the" []* "of"',
                limits=MatchLimits(max_steps=10_000_000, max_span=5_000, deadline_s=60.0),
            )
            _cur, peak = tracemalloc.get_traced_memory()
            tracemalloc.stop()
        # each 98-token cycle (the + 48 fillers + of + 48 fillers) yields
        # exactly one "the ... of" match
        expected = N // 98
        assert abs(r.total - expected) <= 1, f"{r.total} vs ~{expected}"
        # Memory assertion (budget-based, machine-independent): the v1.2.13-1
        # matcher peaked at 1.4 GB for 20K tokens; 50K must stay well bounded.
        assert peak < 250 * 1024 * 1024, f"peak matcher memory {peak/1e6:.0f} MB >= 250 MB"

    await dispose_db()


@pytest.mark.asyncio
async def test_health_stays_fast_during_heavy_cql(hard_env) -> None:
    """P0-1: matching runs in a worker thread — /health never blocks."""
    from httpx import ASGITransport, AsyncClient

    from app.main import app

    cid, _ = hard_env
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as ac:
        # a modestly heavy query: gap matching over the seeded corpus
        async def heavy() -> None:
            r = await ac.post(
                f"/api/v1/corpora/{cid}/concordance/cql",
                json={"query": '"quick" []* "dog"', "window": 5},
            )
            assert r.status_code == 200

        task = None
        import asyncio

        task = asyncio.create_task(heavy())
        latencies: list[float] = []
        for _ in range(5):
            t0 = time.perf_counter()
            h = await ac.get("/api/v1/health")
            dt = time.perf_counter() - t0
            assert h.status_code == 200
            latencies.append(dt)
            await asyncio.sleep(0.02)
        await task
        assert max(latencies) < 0.5, f"/health latency {max(latencies):.3f}s >= 0.5s"


# --------------------------------------------------------------------------- #
# P0-4: documentation truth — real CAMeL format, morph semantics
# --------------------------------------------------------------------------- #


def test_arabic_root_format_matches_real_camel_data() -> None:
    """P0-4c: verify the dotted-root claim against the REAL calima-msa-r13
    morphology.db (official CAMeL release), not a hand-seeded string.

    Skips LOUDLY (visible reason) when the data pack is not installed —
    CI and dev machines without the pack still see why.
    """
    from pathlib import Path

    candidates = [
        # the camel_data-managed layout (~/.camel_tools/data/morphology_db/…)
        Path.home() / ".camel_tools" / "data" / "morphology_db" / "calima-msa-r13" / "morphology.db",
        Path("/tmp/cm-probe-data/.camel_tools/data/morphology_db/calima-msa-r13/morphology.db"),
        # legacy flat layout tolerated for older sandboxes
        Path.home() / ".camel_tools" / "data" / "morphology-db-msa-r13" / "morphology.db",
    ]
    db = next((p for p in candidates if p.is_file()), None)
    if db is None:
        pytest.skip(
            "REAL-DATA CHECK SKIPPED: calima-msa-r13 morphology.db not found "
            f"(looked in {[str(p) for p in candidates]}). Install the Arabic data "
            "pack (Settings > Arabic data pack, or: curl -L -o msa.zip "
            "https://github.com/CAMeL-Lab/camel-tools-data/releases/download/"
            "2022.03.21/morphology_db_calima-msa-r13-0.4.0.zip) and re-run to "
            "verify the dotted-root format against the real CAMeL release."
        )
    found = False
    dotted = 0
    with open(db, encoding="utf-8") as f:
        for line in f:
            if line.startswith(("###", "DEFINE", "DEFAULT")):
                continue
            if "\t" not in line or "root:" not in line:
                continue
            word = line.split("\t", 1)[0]
            if word != "كتب":
                continue
            idx = line.find("root:")
            root_val = line[idx + 5 :].split(" ", 1)[0].strip()
            if root_val == "ك.ت.ب":
                found = True
            if "." in root_val:
                dotted += 1
            if found and dotted >= 5:
                break
    assert found, (
        "The real calima-msa-r13 DB does NOT contain root ك.ت.ب for كتب — "
        "the documented dotted-root format claim is wrong; fix the docs/tests."
    )
    assert dotted >= 5, "expected multiple dotted analyses of كتب in the real DB"


@pytest.mark.asyncio
async def test_morph_is_whole_string_wildcards_for_substring(hard_env) -> None:
    """P0-4b: morph matches the WHOLE Feats string; *…* for substring."""
    _, ar_cid = hard_env
    # Whole-string semantics: an unanchored value does NOT match.
    assert (await _run(ar_cid, '[morph="ك.ت.ب"]')).total == 0
    assert (await _run(ar_cid, '[morph="root=ك.ت.ب|pattern=1َ2َ3"]')).total == 1
    # Documented substring style via wildcards:
    assert (await _run(ar_cid, '[morph="*root=ك.ت.ب*"]')).total == 2


# --------------------------------------------------------------------------- #
# P0-1/P1: ReDoS guard on the SIMPLE concordance regex level
# --------------------------------------------------------------------------- #


@pytest.mark.asyncio
async def test_simple_regex_redos_guard(hard_env) -> None:
    from httpx import ASGITransport, AsyncClient

    from app.main import app

    cid, _ = hard_env
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as ac:
        r = await ac.post(
            f"/api/v1/corpora/{cid}/concordance",
            json={"query": "(a+)+$", "regex": True},
        )
        assert r.status_code == 422
        assert "catastrophically" in r.json()["detail"]


@pytest.mark.asyncio
async def test_cql_regex_budget_counts_steps(hard_env) -> None:
    cid, _ = hard_env
    tiny = MatchLimits(max_steps=2, max_span=100, deadline_s=10.0)
    with pytest.raises(CqlTooExpensive):
        await _run(cid, "[word=/fox|dog/]", limits=tiny)


# --------------------------------------------------------------------------- #
# P1-7: paging — slice first, context per page, span cache
# --------------------------------------------------------------------------- #


@pytest.mark.asyncio
async def test_paging_fetches_context_for_page_only(hard_env, monkeypatch) -> None:
    from stats import cql as cql_mod

    calls: list[int] = []
    original = cql_mod._fetch_sentences

    async def spy(session, version_id, needed):
        calls.append(len(needed))
        return await original(session, version_id, needed)

    monkeypatch.setattr(cql_mod, "_fetch_sentences", spy)
    monkeypatch.setattr(cql_mod, "_span_cache_clear", lambda: cql_mod._SPAN_CACHE.clear())
    cql_mod._SPAN_CACHE.clear()

    cid, _ = hard_env
    # Small corpus: 6 tokens, all 6 positions match '[]' -> build a query
    # with several matches: [pos="DET"] matches 2; add gaps to make more.
    r_page0 = await _run(cid, '[pos="NOUN"]', limit=1, offset=0)
    r_page1 = await _run(cid, '[pos="NOUN"]', limit=1, offset=1)
    # 2 fixture NOUNs + 16 unicode NOUNs = 18
    assert r_page0.total == 18
    # context fetch happened once per request, bounded by the page size
    assert calls, "context fetch never ran"
    for n in calls:
        assert n <= 4, f"context fetched for {n} sentences — page-first slicing broken"


@pytest.mark.asyncio
async def test_span_cache_skips_rematching(hard_env, monkeypatch) -> None:
    from stats import cql as cql_mod

    cql_mod._SPAN_CACHE.clear()
    counter = {"n": 0}
    original = cql_mod._match_all

    def spy(*a, **kw):
        counter["n"] += 1
        return original(*a, **kw)

    monkeypatch.setattr(cql_mod, "_match_all", spy)
    cid, _ = hard_env
    await _run(cid, '"quick"', limit=10, offset=0)
    n1 = counter["n"]
    assert n1 == 1
    # second page of the SAME query must reuse the cached spans
    await _run(cid, '"quick"', limit=10, offset=0)
    assert counter["n"] == 1, "span cache miss on identical (corpus, query, version)"
    # a DIFFERENT query re-matches
    await _run(cid, '"fox"')
    assert counter["n"] == 2


@pytest.mark.asyncio
async def test_paged_results_match_full_results(hard_env) -> None:
    cid, _ = hard_env
    full = await _run(cid, '[pos="NOUN"]', limit=1000, offset=0)
    p0 = await _run(cid, '[pos="NOUN"]', limit=5, offset=0)
    p1 = await _run(cid, '[pos="NOUN"]', limit=5, offset=5)
    ids = [l.line_id for l in p0.lines] + [l.line_id for l in p1.lines]
    assert ids == [l.line_id for l in full.lines[:10]]
    assert p0.total == full.total


# --------------------------------------------------------------------------- #
# P1-8: server-side CQL export
# --------------------------------------------------------------------------- #


@pytest.mark.asyncio
async def test_cql_export_all_formats(hard_env) -> None:
    from httpx import ASGITransport, AsyncClient

    from app.main import app

    cid, _ = hard_env
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as ac:
        # A CQL pattern a SIMPLE query cannot express: ADJ followed by NOUN.
        for fmt, marker in [("csv", b"quick fox"), ("json", b"quick fox"),
                            ("txt", b"quick fox"), ("tsv", b"quick fox")]:
            r = await ac.post(
                f"/api/v1/corpora/{cid}/export/concordance/cql?fmt={fmt}",
                json={"query": '[pos="ADJ"] "fox"', "window": 3},
            )
            assert r.status_code == 200, (fmt, r.text)
            assert marker in r.content, f"{fmt} export missing CQL-specific row"
            assert "attachment" in r.headers.get("content-disposition", "")
        # xlsx round-trips as a zip
        r = await ac.post(
            f"/api/v1/corpora/{cid}/export/concordance/cql?fmt=xlsx",
            json={"query": '[pos="ADJ"] "fox"'},
        )
        assert r.status_code == 200 and r.content[:2] == b"PK"
        # invalid query -> 422
        r = await ac.post(
            f"/api/v1/corpora/{cid}/export/concordance/cql?fmt=csv",
            json={"query": '[lemma="x"'},
        )
        assert r.status_code == 422


# --------------------------------------------------------------------------- #
# cqp_compat
# --------------------------------------------------------------------------- #


@pytest.mark.asyncio
async def test_cqp_compat_anchored_regex_semantics(hard_env) -> None:
    cid, _ = hard_env
    # Non-compat: quoted values are WILDCARD literals — 'École' matches the
    # one literal École token (case-sensitive).
    assert (await _run(cid, '"École"')).total == 1
    # compat: quoted values are ANCHORED regexes — 'É.ol+' matches École?
    # 'École' =~ ^(É.ol+)$? 'É','c'... no: É.ol+ expects É then any char
    # then 'ol+' -> 'Écol' + ... 'École': É c o l e — É.ol+ = É + c + ol+ →
    # 'É' 'c' 'ol' then l+ needs at least one more l — no. Use a clean one:
    r_compat = await _run(cid, '"Écol.*"', cqp_compat=True)
    assert r_compat.total == 1  # École (case-SENSITIVE anchored regex)
    r_noncompat = await _run(cid, '"Écol.*"')
    assert r_noncompat.total == 0  # wildcard literal has no dot-star power
    # anchoring: 'col' (unanchored regex would match inside École)
    r_anch = await _run(cid, '"col"', cqp_compat=True)
    assert r_anch.total == 0  # anchored to the whole token — no token 'col'


# --------------------------------------------------------------------------- #
# P2: find_cql_spans service + consumers
# --------------------------------------------------------------------------- #


@pytest.mark.asyncio
async def test_find_cql_spans_service(hard_env) -> None:
    from stats.cql import find_cql_spans
    import storage.session as _ss

    cid, _ = hard_env
    sm = _ss._sessionmaker
    async with sm() as session:
        ms = await find_cql_spans(session, cid, '[pos="ADJ"] "fox"')
        assert len(ms.spans) == 1
        d, s, e = ms.spans[0]
        assert e - s == 1
        node = " ".join(v.text for v in ms.streams[d][s : e + 1])
        assert node == "quick fox"
        assert ms.per_document()[d] == 1


@pytest.mark.asyncio
async def test_consumer_cql_frequency(hard_env) -> None:
    cid, _ = hard_env
    r = await _run_freq(cid, '[pos="ADJ"] "fox"')
    assert r["total_tokens"] == 1
    assert r["rows"][0]["item"] == "quick" and r["rows"][0]["freq"] == 1
    assert r["cql_query"] == '[pos="ADJ"] "fox"'


async def _run_freq(cid: str, query: str, **kw) -> dict:
    from stats.cql_stats import compute_cql_frequency
    import storage.session as _ss

    sm = _ss._sessionmaker
    async with sm() as session:
        return await compute_cql_frequency(session, cid, query, **kw)


@pytest.mark.asyncio
async def test_consumer_cql_collocations(hard_env) -> None:
    from stats.cql_stats import compute_cql_collocations
    import storage.session as _ss

    cid, _ = hard_env
    sm = _ss._sessionmaker
    async with sm() as session:
        r = await compute_cql_collocations(
            session, cid, '[pos="DET"]', window=2, min_freq=1
        )
    # DET matches 'The' and 'A'; collocates around them carry measures
    assert r["is_cql"] is True
    assert r["rows"], "expected at least one collocate row"
    collocates = {row["collocate"] for row in r["rows"]}
    assert "quick" in collocates or "lazy" in collocates
    for row in r["rows"]:
        assert {"O", "fx", "fy", "N", "mi", "log_likelihood"} <= set(row)
        assert row["fx"] == 2  # two DET match spans


@pytest.mark.asyncio
async def test_consumer_cql_dispersion(hard_env) -> None:
    from stats.cql_stats import compute_cql_dispersion
    import storage.session as _ss

    cid, _ = hard_env
    sm = _ss._sessionmaker
    async with sm() as session:
        r = await compute_cql_dispersion(session, cid, '"fox"')
    assert r.per_part_freqs.count(0) >= 0  # shape sanity
    assert sum(r.per_part_freqs) == 1  # en.txt has one 'fox'; unicode doc none
    assert r.term == '"fox"'


@pytest.mark.asyncio
async def test_consumer_cql_ngrams(hard_env) -> None:
    from stats.cql_stats import compute_cql_ngrams
    import storage.session as _ss

    cid, _ = hard_env
    sm = _ss._sessionmaker
    async with sm() as session:
        r = await compute_cql_ngrams(session, cid, '[pos="DET"]', n=2, min_freq=1)
    bundles = {row["ngram"] for row in r.rows}
    assert "The quick" in bundles and "A lazy" in bundles


@pytest.mark.asyncio
async def test_consumer_ngrams_endpoint(hard_env) -> None:
    from httpx import ASGITransport, AsyncClient

    from app.main import app

    cid, _ = hard_env
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as ac:
        r = await ac.post(
            f"/api/v1/corpora/{cid}/ngrams",
            json={"n": 2, "min_freq": 1, "cql_query": '[pos="DET"]'},
        )
        assert r.status_code == 200
        bundles = {row["ngram"] for row in r.json()["rows"]}
        assert "The quick" in bundles


@pytest.mark.asyncio
async def test_consumer_frequency_endpoint(hard_env) -> None:
    from httpx import ASGITransport, AsyncClient

    from app.main import app

    cid, _ = hard_env
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as ac:
        r = await ac.post(
            f"/api/v1/corpora/{cid}/frequency",
            json={"unit": "word", "cql_query": '[pos="ADJ"] "fox"'},
        )
        assert r.status_code == 200
        data = r.json()
        assert data["rows"][0]["item"] == "quick"


@pytest.mark.asyncio
async def test_subcorpus_from_cql(hard_env) -> None:
    from httpx import ASGITransport, AsyncClient

    from app.main import app

    cid, _ = hard_env
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as ac:
        r = await ac.post(
            f"/api/v1/corpora/{cid}/subcorpora/from-cql",
            json={"name": "Fox contexts", "query": '("fox" | "dog")'},
        )
        assert r.status_code == 200, r.text
        sid = r.json()["id"]
        assert r.json()["filter_criteria"]["kind"] == "cql"
        # The subcorpus restricts a concordance to its member documents:
        r2 = await ac.post(
            f"/api/v1/corpora/{cid}/concordance/cql",
            json={"query": '"fox"', "subcorpus_id": sid},
        )
        assert r2.status_code == 200
        assert r2.json()["total"] == 1
        # invalid query -> 422 at creation
        r3 = await ac.post(
            f"/api/v1/corpora/{cid}/subcorpora/from-cql",
            json={"name": "bad", "query": '[lemma="x"'},
        )
        assert r3.status_code == 422


@pytest.mark.asyncio
async def test_saved_queries_crud(hard_env) -> None:
    from httpx import ASGITransport, AsyncClient

    from app.main import app

    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as ac:
        # create a project
        r = await ac.post("/api/v1/projects", json={"name": "SavedQ", "language": "en"})
        pid = r.json()["id"]
        _, ar_cid = hard_env
        r = await ac.post(
            f"/api/v1/projects/{pid}/saved-queries",
            json={"project_id": pid, "name": "adj-noun", "query": '[pos="ADJ"] "fox"', "mode": "cql"},
        )
        assert r.status_code == 200, r.text
        qid = r.json()["id"]
        assert r.json()["parsed"] == '[pos="ADJ"] "fox"'
        # invalid CQL is rejected at save time
        r2 = await ac.post(
            f"/api/v1/projects/{pid}/saved-queries",
            json={"project_id": pid, "name": "bad", "query": '"unterminated', "mode": "cql"},
        )
        assert r2.status_code == 422
        # list + delete
        r3 = await ac.get(f"/api/v1/projects/{pid}/saved-queries")
        assert r3.status_code == 200 and len(r3.json()) == 1
        r4 = await ac.delete(f"/api/v1/projects/{pid}/saved-queries/{qid}")
        assert r4.status_code == 200
        r5 = await ac.get(f"/api/v1/projects/{pid}/saved-queries")
        assert r5.json() == []


@pytest.mark.asyncio
async def test_ai_tool_search_cql(hard_env) -> None:
    cid, _ = hard_env
    from ai.tools import execute_tool

    out = await execute_tool("search_cql", {"corpus_id": cid, "query": '[pos="ADJ"] "fox"'})
    assert out["mode"] == "cql" and out["total"] == 1
    line = out["lines"][0]
    assert line["node"] == "quick fox" and ":" in line["line_id"]  # grounded id


# --------------------------------------------------------------------------- #
# P0-3: student allowlist boundary + stricter student budget
# --------------------------------------------------------------------------- #


def test_student_allowlist_cql_boundary() -> None:
    from app.server_mode import student_route_allowed

    # ON (deliberate, guarded):
    assert student_route_allowed("POST", "/api/v1/corpora/abc/concordance/cql")
    assert student_route_allowed("POST", "/api/v1/corpora/abc/export/concordance/cql")
    # still allowed (existing surface):
    assert student_route_allowed("POST", "/api/v1/corpora/abc/concordance")
    # OFF (deliberate):
    assert not student_route_allowed("POST", "/api/v1/corpora/abc/subcorpora/from-cql")
    assert not student_route_allowed("POST", "/api/v1/projects/p/saved-queries")
    assert not student_route_allowed("GET", "/api/v1/projects/p/saved-queries")
    assert not student_route_allowed("DELETE", "/api/v1/projects/p/saved-queries/q")


@pytest.mark.asyncio
async def test_student_request_uses_stricter_budget(hard_env) -> None:
    from types import SimpleNamespace

    from api.analysis import CqlRequest, concordance_cql
    from stats.cql import MatchLimits, STUDENT_MATCH_LIMITS
    import storage.session as _ss
    from storage.models import Corpus

    cid, _ = hard_env
    sm = _ss._sessionmaker
    captured: dict = {}

    async def fake_search(session, corpus_id, query, **kw):
        captured["limits"] = kw.get("limits")
        from stats.cql import search_concordance_cql as _real

        return await _real(session, corpus_id, query, **kw)

    import api.analysis as analysis_mod

    original = analysis_mod.search_concordance_cql
    analysis_mod.search_concordance_cql = fake_search
    try:
        async with sm() as session:
            assert await session.get(Corpus, cid)
            body = CqlRequest(query='"quick"')
            # teacher (no role set — direct loopback desktop app)
            req = SimpleNamespace(state=SimpleNamespace())
            await concordance_cql(cid, body, req, session)
            assert captured["limits"] == MatchLimits()
            # student (role set by the classroom auth middleware)
            req2 = SimpleNamespace(state=SimpleNamespace(role="student"))
            await concordance_cql(cid, body, req2, session)
            assert captured["limits"] == STUDENT_MATCH_LIMITS
            assert STUDENT_MATCH_LIMITS.max_steps < MatchLimits().max_steps
            assert STUDENT_MATCH_LIMITS.deadline_s < MatchLimits().deadline_s
    finally:
        analysis_mod.search_concordance_cql = original


# --------------------------------------------------------------------------- #
# Real-pipeline tests (spaCy English; CAMeL Arabic when available)
# --------------------------------------------------------------------------- #


def _camel_msa_data_available() -> bool:
    from pathlib import Path

    home = Path.home() / ".camel_tools"
    if (home / "catalogue.json").is_file():
        return (home / "data" / "morphology_db" / "calima-msa-r13").is_dir()
    return False


@pytest.mark.asyncio
async def test_real_camel_arabic_pipeline_cql_root(hard_env) -> None:
    """P0-4c ground truth: ingest REAL Arabic text through the REAL CAMeL
    backend (calima-msa-r13) and query it with the documented dotted-root
    CQL. The stored morph format this test pins —
    ``root=ك.ت.ب|stem=كُتُب|pattern=1ُ2ُ3`` — was verified live against the
    real backend (scripts/probe_camel_morph.py output, v1.2.13-2 worklog).

    Skips LOUDLY (explicit reason + install instructions) when the data pack
    is not provisioned — never a silent pass.
    """
    if not _camel_msa_data_available():
        pytest.skip(
            "REAL-CAMeL TEST SKIPPED: calima-msa-r13 not provisioned "
            "(~/.camel_tools/data/morphology_db/calima-msa-r13 missing). "
            "Install via Settings > Arabic data pack > Install (or camel_data "
            "-i morphology-db-msa-r13) and re-run to verify the dotted-root "
            "format through the real ingestion pipeline."
        )
    from httpx import ASGITransport, AsyncClient

    from app.main import app

    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as ac:
        r = await ac.post("/api/v1/projects", json={"name": "RealAR", "language": "ar"})
        pid = r.json()["id"]
        r = await ac.post(f"/api/v1/projects/{pid}/corpora", json={"name": "C", "language": "ar"})
        cid = r.json()["id"]
        text = "كتب الطالب الكتاب في المكتبة."
        r = await ac.post(
            f"/api/v1/corpora/{cid}/documents",
            files={"files": ("ar_real.txt", text.encode("utf-8"), "text/plain")},
        )
        assert r.status_code == 200, r.text
        # Dotted root over REAL ingestion: كتب / الكتاب / المكتبة share ك.ت.ب
        r = await ac.post(
            f"/api/v1/corpora/{cid}/concordance/cql",
            json={"query": '[root="ك.ت.ب"]', "window": 2},
        )
        assert r.status_code == 200, r.text
        data = r.json()
        assert data["total"] == 3, f"expected 3 ك.ت.ب roots, got {data['total']}"
        nodes = {l["node"] for l in data["lines"]}
        assert {"كتب", "الكتاب", "المكتبة"} <= nodes
        # template pattern from the real backend (كُتُب 'books' = 1ُ2ُ3)
        r2 = await ac.post(
            f"/api/v1/corpora/{cid}/concordance/cql",
            json={"query": '[pattern="1ُ2ُ3"]'},
        )
        assert r2.status_code == 200, r2.text
        assert r2.json()["total"] == 1
        assert r2.json()["lines"][0]["node"] == "كتب"


@pytest.mark.asyncio
async def test_real_spacy_pipeline_cql_sequences(hard_env) -> None:
    """CQL over REALLY annotated tokens (spaCy en_core_web_sm), not seeds.

    The hard_env fixture provides the initialised app/database; the model
    check below fails loudly if en_core_web_sm is missing — CI installs it;
    a silent skip would hide regressions in the real ingestion → CQL path.
    """
    try:
        import spacy

        spacy.load("en_core_web_sm")
    except Exception as e:  # pragma: no cover - env guard
        raise AssertionError(
            "spaCy en_core_web_sm is REQUIRED for the real-pipeline CQL test "
            "(install: python -m spacy download en_core_web_sm) — a silent "
            "skip would hide real-annotation regressions"
        ) from e

    from httpx import ASGITransport, AsyncClient

    from app.main import app

    cid, _ = hard_env
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as ac:
        r = await ac.post("/api/v1/projects", json={"name": "RealEN", "language": "en"})
        pid = r.json()["id"]
        r = await ac.post(f"/api/v1/projects/{pid}/corpora", json={"name": "C", "language": "en"})
        cid = r.json()["id"]
        text = (
            "The quick fox jumps over the lazy dog. A scientist writes careful "
            "reports. The tired student reads long articles."
        )
        r = await ac.post(
            f"/api/v1/corpora/{cid}/documents",
            files={"files": ("real.txt", text.encode(), "text/plain")},
        )
        assert r.status_code == 200, r.text
        r = await ac.post(
            f"/api/v1/corpora/{cid}/concordance/cql",
            json={"query": '[pos="ADJ"] []{0,1} [pos="NOUN"]', "window": 3},
        )
        assert r.status_code == 200, r.text
        nodes = [l["node"] for l in r.json()["lines"]]
        assert "quick fox" in nodes
        assert "lazy dog" in nodes
        assert "careful reports" in nodes
        assert "tired student" in nodes
        # POS gaps over real annotation
        r2 = await ac.post(
            f"/api/v1/corpora/{cid}/concordance/cql",
            json={"query": '[pos="DET"] [pos="ADJ"] [pos="NOUN"]'},
        )
        nodes2 = [l["node"] for l in r2.json()["lines"]]
        assert "The quick fox" in nodes2 and "The tired student" in nodes2, f"got: {nodes2}"
