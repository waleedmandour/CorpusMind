"""v1.2.14-9 (r9) regression tests — collocation-network normalization parity.

Field report: on an Arabic corpus, the collocation TABLE (which honors the
unification switch, normalize_arabic=True) showed results while the
collocation NETWORK rendered empty — the network request model carried no
normalization fields at all, so it always computed on RAW tokens. A pivot
picked from the normalized table (e.g. اخبار-style unified spelling) never
matched the decorated raw forms in the corpus, and the graph stayed empty.

Fixed by mirroring CollocationRequest's three normalization fields on
NetworkRequest (build + expand) and on the collocation / network-diagram /
keyness EXPORT requests, and passing them to compute_collocations /
compute_collocation_mesh / compute_keyness.

These tests seed tokens directly via session_scope (no NLP pipeline, no
CAMeL data pack) — the same in-memory DB the service functions read. The
corpus contains NO plain unified spelling of the pivot: every occurrence
carries hamza-alef and/or harakat, so only the folded match can succeed.
"""
from __future__ import annotations

import os
from collections.abc import AsyncIterator, Iterator

import pytest
from httpx import ASGITransport, AsyncClient

os.environ["CORPUSMIND_DB_URL"] = "sqlite+aiosqlite:///:memory:"
os.environ["CORPUSMIND_DATA_DIR"] = "/tmp/cm-test-r9-netnorm"
from app.settings import get_settings

get_settings.cache_clear()


# The pivot's unified spelling is deliberately absent in plain form: every token is
# decorated (hamza-alef أ, harakat). The unified spelling الاخبار exists
# ONLY after folding — exactly the situation after a user enables the
# unification switch and picks a node from the normalized table.
AR_SENTENCES = [
    ["الأخبارُ", "السَّريعةُ", "انتشرت", "في", "المدينةِ"],
    ["الأخبارُ", "السريعة", "هي", "مفيدةٌ"],
    ["الأخبارُ", "في", "الصحافة"],
    ["السَّريعةُ", "والدقيقةُ", "أهمّ"],
]

_STOPWORDS = {"في", "هي", "على"}


async def _seed_tokens(sentences: list[list[str]], language: str) -> str:
    """Seed project + corpus + annotation version + tokens; return cid."""
    from storage.models import AnnotationVersion, Corpus, Document, Project, Token
    from storage.session import init_db, session_scope

    await init_db()

    async with session_scope() as s:
        p = Project(name="P", language=language)
        s.add(p)
        await s.flush()
        c = Corpus(project_id=p.id, name="C", language=language)
        s.add(c)
        await s.flush()
        doc = Document(corpus_id=c.id, filename="doc0.txt", cleaned_text="seed")
        s.add(doc)
        await s.flush()
        v = AnnotationVersion(corpus_id=c.id, version_label="v1")
        s.add(v)
        await s.flush()
        for sent_idx, sent in enumerate(sentences):
            for tok_idx, text in enumerate(sent):
                s.add(Token(
                    version_id=v.id, document_id=doc.id,
                    sentence_idx=sent_idx, token_idx=tok_idx,
                    text=text, lemma=text,
                    pos="" if text in _STOPWORDS else "NOUN",
                ))
        await s.flush()
        return c.id


@pytest.fixture(autouse=True)
def _fresh_caches() -> Iterator[None]:
    """Isolate the memo caches around every test."""
    from stats.service import clear_colloc_cache, clear_vocab_cache

    clear_colloc_cache()
    clear_vocab_cache()
    yield
    clear_colloc_cache()
    clear_vocab_cache()


@pytest.fixture
async def client() -> AsyncIterator[AsyncClient]:
    from app.main import app
    from storage.session import dispose_db

    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as ac:
        async with app.router.lifespan_context(app):
            yield ac
    await dispose_db()


# The unification switch folds hamza-alef variants and strips harakat, so
# the surface forms above collapse to: الاخبار / السريعه (ة→ه) / المدينه…
PIVOT_UNIFIED = "الاخبار"     # plain spelling a user would type/pick
PIVOT_SURFACE = "الأخبارُ"    # the only spelling present in the corpus


# --------------------------------------------------------------------------- #
# 1. Network build honors normalize_arabic (the reported bug)
# --------------------------------------------------------------------------- #


async def test_network_build_honors_normalize_arabic(client: AsyncClient) -> None:
    from stats.service import _ar_fold

    cid = await _seed_tokens(AR_SENTENCES, "ar")

    # Folded pivot must match the decorated corpus under the switch…
    r = await client.post(
        f"/api/v1/corpora/{cid}/collocations/network",
        json={"node": PIVOT_UNIFIED, "level": "word", "window": 5, "min_freq": 1,
              "measure": "mi", "top_n": 14, "depth": 2, "max_nodes": 60,
              "normalize_arabic": True},
    )
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["params"]["normalize_arabic"] is True
    assert body["nodes"], "unified pivot must match decorated tokens under the switch"

    node_ids = {n["id"] for n in body["nodes"]}
    assert PIVOT_UNIFIED in node_ids                      # center echoes the request
    # rows carry SURFACE labels whose fold is the group key (same convention
    # as test_r6_network_mesh.py) — fold before comparing.
    folded_node_ids = {_ar_fold(n) for n in node_ids}
    folded_collocates = {_ar_fold(tok) for tok in ("السَّريعةُ", "المدينةِ", "الصحافة")}
    assert folded_collocates & folded_node_ids, (folded_collocates, folded_node_ids)
    # Center + at least two spokes (السريعه O=2, وفي/المدينه/الصحافه O=1).
    assert body["stats"]["edges"] >= 2
    center = next(n for n in body["nodes"] if n["id"] == PIVOT_UNIFIED)
    assert center["is_center"] is True and center["freq"] == 3


async def test_network_build_without_flag_stays_raw(client: AsyncClient) -> None:
    """Without the switch the network must keep matching RAW forms — the
    unified pivot is absent from this corpus, so the graph is empty (the
    pre-r9 behaviour is pinned here as the documented semantics, not
    silently 'fixed' by always normalizing)."""
    cid = await _seed_tokens(AR_SENTENCES, "ar")

    r = await client.post(
        f"/api/v1/corpora/{cid}/collocations/network",
        json={"node": PIVOT_UNIFIED, "level": "word", "window": 5, "min_freq": 1,
              "measure": "mi", "top_n": 14, "depth": 2, "max_nodes": 60},
    )
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["nodes"] == [] and body["edges"] == []

    # …while the DECORATED surface form still matches raw (regression guard:
    # the switch must be additive, never change the raw path).
    r2 = await client.post(
        f"/api/v1/corpora/{cid}/collocations/network",
        json={"node": PIVOT_SURFACE, "level": "word", "window": 5, "min_freq": 1,
              "measure": "mi", "top_n": 14, "depth": 2, "max_nodes": 60},
    )
    assert r2.status_code == 200, r2.text
    assert r2.json()["nodes"], "raw decorated pivot must still match without the switch"


async def test_network_expand_honors_normalize_arabic(client: AsyncClient) -> None:
    from stats.service import _ar_fold

    cid = await _seed_tokens(AR_SENTENCES, "ar")

    r = await client.post(
        f"/api/v1/corpora/{cid}/collocations/network/expand",
        json={"node": PIVOT_UNIFIED, "level": "word", "window": 5, "min_freq": 1,
              "measure": "mi", "top_n": 14, "depth": 2,
              "known_nodes": [PIVOT_UNIFIED], "normalize_arabic": True},
    )
    assert r.status_code == 200, r.text
    body = r.json()
    folded_collocates = {_ar_fold(tok) for tok in ("السَّريعةُ", "المدينةِ", "الصحافة")}
    folded_new = {_ar_fold(n) for n in body["new_nodes"]}
    assert folded_collocates & folded_new, body["new_nodes"]


# --------------------------------------------------------------------------- #
# 2. Exports must agree with the on-screen table (same switch)
# --------------------------------------------------------------------------- #


async def test_collocation_export_honors_normalize_arabic(client: AsyncClient) -> None:
    from stats.service import _ar_fold

    cid = await _seed_tokens(AR_SENTENCES, "ar")
    folded = _ar_fold("السَّريعةُ")

    r = await client.post(
        f"/api/v1/corpora/{cid}/export/collocations?fmt=csv",
        json={"node": PIVOT_UNIFIED, "level": "word", "window": 5, "min_freq": 1,
              "limit": 100, "normalize_arabic": True},
    )
    assert r.status_code == 200, r.text
    # CSV rows carry surface labels — fold the whole text before checking
    # (representative-surface choice inside a variant group is not fixed).
    assert folded in _ar_fold(r.text), "exported CSV must contain the folded collocate"

    # Without the switch the same export is empty (raw pivot absent) —
    # proving the flag actually reaches the computation.
    r2 = await client.post(
        f"/api/v1/corpora/{cid}/export/collocations?fmt=csv",
        json={"node": PIVOT_UNIFIED, "level": "word", "window": 5, "min_freq": 1,
              "limit": 100},
    )
    assert r2.status_code == 200, r2.text
    assert folded not in _ar_fold(r2.text)


async def test_network_svg_export_honors_normalize_arabic(client: AsyncClient) -> None:
    from stats.service import _ar_fold

    cid = await _seed_tokens(AR_SENTENCES, "ar")
    folded = _ar_fold("السَّريعةُ")

    r = await client.post(
        f"/api/v1/corpora/{cid}/export/collocations.network.svg",
        json={"node": PIVOT_UNIFIED, "level": "word", "window": 5, "min_freq": 1,
              "limit": 100, "normalize_arabic": True},
    )
    assert r.status_code == 200, r.text
    assert "image/svg" in r.headers["content-type"]
    assert "<svg" in r.text
    assert folded in _ar_fold(r.text), "network diagram must be built from the folded rows"


async def test_keyness_export_honors_normalize_arabic(client: AsyncClient) -> None:
    """The keyness EXPORT must honor the same switch as the keyness table.

    Target corpus = decorated Arabic sentences; reference = a tiny English
    corpus. The unified term الاخبار can only rank if the target-side vocab
    is folded — i.e. if the export passed the switch through to
    compute_keyness."""
    from storage.models import AnnotationVersion, Corpus, Document, Project, Token
    from storage.session import init_db, session_scope

    await init_db()
    ref_sents = [["the", "news", "is", "good"], ["the", "news", "is", "brief"]]

    async with session_scope() as s:
        p = Project(name="P", language="ar")
        s.add(p)
        await s.flush()
        c = Corpus(project_id=p.id, name="T", language="ar")
        s.add(c)
        await s.flush()
        d = Document(corpus_id=c.id, filename="t.txt", cleaned_text="seed")
        s.add(d)
        await s.flush()
        v = AnnotationVersion(corpus_id=c.id, version_label="v1")
        s.add(v)
        await s.flush()
        for i, sent in enumerate(AR_SENTENCES):
            for j, text in enumerate(sent):
                s.add(Token(version_id=v.id, document_id=d.id, sentence_idx=i,
                            token_idx=j, text=text, lemma=text,
                            pos="" if text in _STOPWORDS else "NOUN"))
        pr = Project(name="R", language="en")
        s.add(pr)
        await s.flush()
        cr = Corpus(project_id=pr.id, name="R", language="en")
        s.add(cr)
        await s.flush()
        dr = Document(corpus_id=cr.id, filename="r.txt", cleaned_text="seed")
        s.add(dr)
        await s.flush()
        vr = AnnotationVersion(corpus_id=cr.id, version_label="v1")
        s.add(vr)
        await s.flush()
        for i, sent in enumerate(ref_sents):
            for j, text in enumerate(sent):
                s.add(Token(version_id=vr.id, document_id=dr.id, sentence_idx=i,
                            token_idx=j, text=text, lemma=text, pos="NOUN"))
        target_cid, ref_cid = c.id, cr.id

    folded = "الاخبار"  # _ar_fold of both the unified and decorated pivot
    r = await client.post(
        f"/api/v1/corpora/{target_cid}/export/keyness?fmt=csv",
        json={"reference_corpus_id": ref_cid, "min_freq": 1, "limit": 100,
              "normalize_arabic": True},
    )
    assert r.status_code == 200, r.text
    assert folded in r.text, "keyness export must rank folded forms under the switch"
