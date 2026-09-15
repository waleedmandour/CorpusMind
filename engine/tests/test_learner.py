"""Learner Research tests (v1.2.0 item 5).

Covers, in order:
  * pure-stat sanity for the reused HD-D measure (stats.measures);
  * compute_caf on toy English sentences with fake dependency labels —
    clause counting, sentence-length stats, and the heuristic accuracy
    proxy (no DB);
  * the EN/AR error-candidate seed rules as pure functions (no DB — the AR
    rules never touch the pipeline, so camel-tools is NOT required);
  * the API surface over an in-memory DB with minimal-but-real seeding
    (Project → Corpus(l1/proficiency) → Documents → AnnotationVersion →
    Tokens, mirroring the test_ai_chat_endpoint_e2e.py seeding pattern).

NOTE on hd_d: the implementation returns the RAW McCarthy–Jarvis sum; for
texts longer than the 42-token sample window that sum can exceed 1 (it equals
≈42 for 100 all-distinct tokens). For texts ≤ 42 tokens it falls back to
plain TTR, which is why the (0, 1] assertions below use short texts — the
behaviour is documented, not a bug this module may "fix" silently.
"""
from __future__ import annotations

import os
import uuid

import pytest
from httpx import ASGITransport, AsyncClient

from learner.caf import caf_delta, compute_caf
from learner.errors import flag_sentence_tokens
from stats.measures import hd_d


def _has_en_model() -> bool:
    """Is the full en_core_web_sm model installed in THIS environment?

    Without it get_pipeline falls back to a tokenizer-only blank model, so
    dependency-derived clause indices legitimately come out None. The API
    test below branches on this instead of asserting one environment's
    behaviour everywhere.
    """
    try:
        import spacy

        return spacy.util.is_package("en_core_web_sm")
    except Exception:
        return False


HAS_EN_MODEL = _has_en_model()


# --------------------------------------------------------------------------- #
# Unit — HD-D sanity (reused §12 measure)
# --------------------------------------------------------------------------- #


def test_hd_d_sanity():
    # Short texts (n ≤ 42): HD-D falls back to TTR, so it is in (0, 1].
    distinct = [f"w{i}" for i in range(30)]                # 30 all-distinct types
    repeated = ["a"] * 15 + [f"o{i}" for i in range(15)]   # 1 type repeated + 15 types
    d_distinct, d_repeated = hd_d(distinct), hd_d(repeated)
    assert 0 < d_repeated < d_distinct <= 1.0
    assert d_distinct == pytest.approx(1.0)   # all-distinct short text → TTR = 1

    # Longer texts: the ordering property still holds (repetition lowers HD-D
    # drastically), even though the raw sum exceeds 1 there. (A text made of a
    # single repeated type yields exactly 0 — avoided here to keep the > 0
    # assertion meaningful.)
    long_distinct = hd_d([f"t{i}" for i in range(100)])
    long_repeated = hd_d(["a"] * 50 + [f"o{i}" for i in range(50)])
    assert 0 < long_repeated < long_distinct


# --------------------------------------------------------------------------- #
# Unit — compute_caf on toy sentences (fake dep labels, no DB)
# --------------------------------------------------------------------------- #


def _tok(text: str, pos: str = "NOUN", rel: str = "dep", idx: int = 1) -> dict:
    return {
        "text": text, "lemma": text.lower(), "pos": pos, "morph": "",
        "dep_rel": rel, "token_idx": idx,
    }


def test_compute_caf_en_clause_counting_and_lengths():
    # S1 has TWO clause heads (left=ccomp VERB, stayed=conj VERB) plus the
    # "they is" agreement error; S2 has ONE (was=advcl AUX). 13 tokens, 2
    # sentences → clauses_per_sentence = 3/2 = 1.5, mean_sentence_length = 6.5.
    s1 = [
        _tok("They", "PRON", "nsubj", 1),
        _tok("is", "AUX", "ROOT", 2),
        _tok("he", "PRON", "nsubj", 3),
        _tok("left", "VERB", "ccomp", 4),
        _tok("and", "CCONJ", "cc", 5),
        _tok("they", "PRON", "nsubj", 6),
        _tok("stayed", "VERB", "conj", 7),
    ]
    s2 = [
        _tok("Because", "SCONJ", "mark", 1),
        _tok("he", "PRON", "nsubj", 2),
        _tok("was", "AUX", "advcl", 3),
        _tok("tired", "ADJ", "acomp", 4),
        _tok("he", "PRON", "nsubj", 5),
        _tok("slept", "VERB", "ROOT", 6),
    ]
    caf = compute_caf([s1, s2])
    assert caf.tokens == 13
    assert caf.sentences == 2
    assert caf.mean_sentence_length == pytest.approx(6.5)
    assert caf.clauses_per_sentence == pytest.approx(1.5)       # 3 clause heads / 2 sents
    assert caf.mean_clause_length == pytest.approx(round(13 / 3, 4))  # 13 tokens / 3 heads
    # 7-token and 6-token sentences both land in the 6-10 bucket.
    assert caf.sentence_length_histogram == {"1-5": 0, "6-10": 2, "11-15": 0, "16-20": 0, "21+": 0}
    # Lexical diversity on lowercased stream: types = they,is,he,left,and,
    # stayed,because,was,tired,slept = 10 / 13 tokens.
    assert caf.ttr == pytest.approx(round(10 / 13, 4))
    assert 0 < caf.ttr <= 1.0
    # Accuracy proxy: S1 fires (they is), S2 clean → 1/2 error-free.
    assert caf.error_free_sentence_ratio == pytest.approx(0.5)
    assert caf.error_candidates_per_100 == pytest.approx(round(1 / 13 * 100, 4))
    # No morph layer on these tokens → root_type_ratio is None (not 0).
    assert caf.root_type_ratio is None
    # Honesty disclaimers are always attached.
    assert any("HEURISTIC PROXIES" in n for n in caf.notes)
    assert any("Lu 2010/2012" in n for n in caf.notes)


def test_compute_caf_without_parse_omits_clause_indices():
    # Blank-pipeline / Arabic-placeholder tokens: every dep_rel is "dep" →
    # clause fields must be None + an explanatory note (not fabricated zeros).
    s = [
        _tok("الطلاب", "NOUN", "dep", 1),
        _tok("اخذ", "VERB", "dep", 2),   # hamza candidate (seed rule key)
        _tok("الكتاب", "NOUN", "dep", 3),
    ]
    caf = compute_caf([s])
    assert caf.clauses_per_sentence is None
    assert caf.mean_clause_length is None
    assert any("Dependency parsing unavailable" in n for n in caf.notes)
    # Language auto-detected from Arabic script → AR rules apply to the
    # accuracy proxy (اخذ is a hamza candidate).
    assert caf.error_free_sentence_ratio == pytest.approx(0.0)


def test_caf_delta_subtracts_and_propagates_none():
    s_clean = [_tok("The", "DET", "det", 1), _tok("cat", "NOUN", "nsubj", 2), _tok("sat", "VERB", "ROOT", 3)]
    s_err = [_tok("They", "PRON", "nsubj", 1), _tok("is", "AUX", "ROOT", 2)]
    target = compute_caf([s_err])
    baseline = compute_caf([s_clean])
    delta = caf_delta(target, baseline)
    assert delta["tokens"] == -1
    assert delta["ttr"] == pytest.approx(round(target.ttr - baseline.ttr, 4))
    # Either side None (no parse here → clause fields None) → None, not a number.
    assert delta["mean_clause_length"] is None
    # notes/histogram are not diffed.
    assert "notes" not in delta and "sentence_length_histogram" not in delta


# --------------------------------------------------------------------------- #
# Unit — seed error rules (pure functions; AR needs no camel-tools)
# --------------------------------------------------------------------------- #


def test_en_error_rules_fire():
    assert flag_sentence_tokens(
        [{"text": "They", "token_idx": 1}, {"text": "is", "token_idx": 2}], "en"
    ) is True
    assert flag_sentence_tokens(
        [{"text": "a", "token_idx": 1}, {"text": "apple", "token_idx": 2}], "en"
    ) is True
    assert flag_sentence_tokens([{"text": "recieve", "token_idx": 1}], "en") is True
    # Case-insensitive matching.
    assert flag_sentence_tokens([{"text": "Recieve", "token_idx": 1}], "en") is True
    # Clean sentence → no firing.
    assert flag_sentence_tokens(
        [{"text": "They", "token_idx": 1}, {"text": "are", "token_idx": 2},
         {"text": "happy", "token_idx": 3}], "en"
    ) is False


def test_ar_error_rules_fire():
    # Hamza omission.
    assert flag_sentence_tokens([{"text": "اخذ", "token_idx": 1}], "ar") is True
    # Ta marbuta written as ه.
    assert flag_sentence_tokens([{"text": "مدرسه", "token_idx": 1}], "ar") is True
    # Alef maksura confusion.
    assert flag_sentence_tokens([{"text": "فى", "token_idx": 1}], "ar") is True
    # Correct forms → clean.
    assert flag_sentence_tokens([{"text": "كتاب", "token_idx": 1}], "ar") is False
    assert flag_sentence_tokens([{"text": "أخذ", "token_idx": 1}], "ar") is False


# --------------------------------------------------------------------------- #
# API — in-memory DB client fixture (canonical pattern from test_api.py)
# --------------------------------------------------------------------------- #


@pytest.fixture
async def client():
    """Spawn the FastAPI app with a fresh in-memory DB per test."""
    os.environ["CORPUSMIND_DB_URL"] = "sqlite+aiosqlite:///:memory:"
    os.environ["CORPUSMIND_DATA_DIR"] = "/tmp/cm-test-data"

    from app.settings import get_settings

    get_settings.cache_clear()
    from storage.session import _engine, dispose_db

    _engine.clear() if hasattr(_engine, "clear") else None

    from app.main import app

    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as ac:
        async with app.router.lifespan_context(app):
            yield ac
    await dispose_db()


async def _seed_learner_corpus() -> str:
    """Minimal-but-real learner corpus: 2 docs, 1 annotation version, tokens
    including a "they is" bigram. Returns the corpus id.

    doc1 carries meta {"proficiency": "B2"} so the group_by=proficiency test
    exercises the meta-overrides-corpus-default convention (corpus says B1).
    """
    from storage.models import AnnotationVersion, Corpus, Document, Project, Token
    from storage.session import session_scope

    pid, cid = uuid.uuid4().hex[:16], uuid.uuid4().hex[:16]
    vid = uuid.uuid4().hex[:16]
    doc1, doc2 = uuid.uuid4().hex[:16], uuid.uuid4().hex[:16]

    async with session_scope() as s:
        s.add(Project(id=pid, name="Learner test project", language="en"))
        s.add(Corpus(id=cid, project_id=pid, name="Learner corpus EN",
                     language="en", l1="Arabic", proficiency="B1"))
        s.add(Document(id=doc1, corpus_id=cid, filename="essay1.txt",
                       meta={"proficiency": "B2"}))
        s.add(Document(id=doc2, corpus_id=cid, filename="essay2.txt", meta={}))
        s.add(AnnotationVersion(id=vid, corpus_id=cid, token_count=11,
                                type_count=10, sentence_count=3))

        def tok(doc_id: str, sent: int, idx: int, text: str, pos: str, rel: str) -> Token:
            return Token(version_id=vid, document_id=doc_id, sentence_idx=sent,
                         token_idx=idx, text=text, lemma=text.lower(), pos=pos,
                         dep_head=0, dep_rel=rel, is_punct=(pos == "PUNCT"))

        # doc1 s0: "They is happy ."        (en_agreement bigram)
        # doc1 s1: "I recieve a apple ."    (en_spelling + en_article)
        for t in (
            tok(doc1, 0, 1, "They", "PRON", "nsubj"),
            tok(doc1, 0, 2, "is", "AUX", "ROOT"),
            tok(doc1, 0, 3, "happy", "ADJ", "acomp"),
            tok(doc1, 0, 4, ".", "PUNCT", "punct"),
            tok(doc1, 1, 1, "I", "PRON", "nsubj"),
            tok(doc1, 1, 2, "recieve", "VERB", "ROOT"),
            tok(doc1, 1, 3, "a", "DET", "det"),
            tok(doc1, 1, 4, "apple", "NOUN", "obj"),
            tok(doc1, 1, 5, ".", "PUNCT", "punct"),
            # doc2 s0: "The book is good ."
            tok(doc2, 0, 1, "The", "DET", "det"),
            tok(doc2, 0, 2, "book", "NOUN", "nsubj"),
            tok(doc2, 0, 3, "is", "AUX", "ROOT"),
            tok(doc2, 0, 4, "good", "ADJ", "acomp"),
            tok(doc2, 0, 5, ".", "PUNCT", "punct"),
        ):
            s.add(t)
    return cid


async def test_learner_caf_endpoint(client):
    cid = await _seed_learner_corpus()
    r = await client.post(f"/api/v1/corpora/{cid}/learner/caf", json={})
    assert r.status_code == 200, r.text
    data = r.json()
    assert data["corpus"]["l1"] == "Arabic"
    assert data["corpus"]["proficiency"] == "B1"
    overall = data["overall"]
    assert overall["tokens"] > 0
    assert 0 < overall["caf"]["ttr"] <= 1.0
    assert overall["caf"]["error_free_sentence_ratio"] is not None
    assert "formulas" in data and "ttr" in data["formulas"]
    assert any("Housen" in c for c in data["citations"])

    # group_by=proficiency: doc1 meta B2 overrides the corpus default B1.
    r2 = await client.post(
        f"/api/v1/corpora/{cid}/learner/caf", json={"group_by": "proficiency"}
    )
    assert r2.status_code == 200
    names = {g["name"] for g in r2.json()["groups"]}
    assert names == {"B1", "B2"}


async def test_learner_caf_endpoint_404(client):
    r = await client.post("/api/v1/corpora/doesnotexist/learner/caf", json={})
    assert r.status_code == 404


async def test_learner_errors_endpoint(client):
    cid = await _seed_learner_corpus()
    r = await client.post(f"/api/v1/corpora/{cid}/learner/errors", json={})
    assert r.status_code == 200, r.text
    data = r.json()
    assert data["verified_count"] == 0
    assert data["language"] == "en"
    assert data["total_tokens"] == 11  # 14 seeded tokens − 3 punctuation
    rule_ids = {c["rule_id"] for c in data["candidates"]}
    assert "en_agreement" in rule_ids          # "they is"
    assert "en_spelling" in rule_ids           # "recieve"
    assert "en_article" in rule_ids            # "a apple" (orthographic heuristic)
    agreement = next(c for c in data["candidates"] if c["rule_id"] == "en_agreement")
    assert agreement["word"] == "is"
    # line_ref format: {document_id}:{sentence_idx}:{token_idx}
    assert agreement["line_ref"] == (
        f"{agreement['document_id']}:{agreement['sentence_idx']}:{agreement['token_idx']}"
    )
    # Sentence text is reconstructed from the scanned (non-punct) tokens.
    assert agreement["sentence"] == "They is happy"
    assert "candidate" in agreement["reason"].lower()
    # counts are per emitted rule
    assert data["counts"]["en_agreement"] >= 1

    # Unknown rule id → 422 with the valid ids listed.
    r2 = await client.post(
        f"/api/v1/corpora/{cid}/learner/errors", json={"rule_ids": ["nope"]}
    )
    assert r2.status_code == 422


async def test_learner_cia_endpoint_no_arms(client):
    """CIA with no reference/compare arms: CAF target block + warnings only."""
    cid = await _seed_learner_corpus()
    r = await client.post(f"/api/v1/corpora/{cid}/learner/cia", json={})
    assert r.status_code == 200, r.text
    data = r.json()
    assert data["target"]["corpus"]["id"] == cid
    assert data["target"]["caf"]["tokens"] > 0
    assert data["reference"] is None and data["compare"] is None
    assert data["keyness"] is None
    assert data["deltas"] == {}
    assert any("CIA" in c or "Granger" in c for c in data["citations"])
    assert any("No keyness arm" in w for w in data["warnings"])


async def test_learner_cia_endpoint_compare_corpus(client):
    """The learner-vs-learner CIA arm: compare corpus CAF delta."""
    cid = await _seed_learner_corpus()
    # A second learner corpus sharing the same annotation content shape.
    from storage.models import AnnotationVersion, Corpus, Document, Project, Token
    from storage.session import session_scope

    pid, cid2 = uuid.uuid4().hex[:16], uuid.uuid4().hex[:16]
    vid = uuid.uuid4().hex[:16]
    doc = uuid.uuid4().hex[:16]
    async with session_scope() as s:
        s.add(Project(id=pid, name="Second learner project", language="en"))
        s.add(Corpus(id=cid2, project_id=pid, name="Learner corpus 2",
                     language="en", l1="Chinese", proficiency="B2"))
        s.add(Document(id=doc, corpus_id=cid2, filename="c2.txt"))
        s.add(AnnotationVersion(id=vid, corpus_id=cid2))
        for i, (text, pos) in enumerate(
            [("The", "DET"), ("cat", "NOUN"), ("sat", "VERB")], start=1
        ):
            s.add(Token(version_id=vid, document_id=doc, sentence_idx=0,
                        token_idx=i, text=text, lemma=text.lower(), pos=pos,
                        dep_head=0, dep_rel="dep"))

    r = await client.post(
        f"/api/v1/corpora/{cid}/learner/cia",
        json={"compare_corpus_id": cid2},
    )
    assert r.status_code == 200, r.text
    data = r.json()
    assert data["compare"]["corpus"]["id"] == cid2
    assert data["compare"]["caf"]["tokens"] == 3
    delta = data["deltas"]["compare_vs_target"]
    assert delta["tokens"] == 3 - data["target"]["caf"]["tokens"]

    # Missing compare corpus → 404.
    r2 = await client.post(
        f"/api/v1/corpora/{cid}/learner/cia", json={"compare_corpus_id": "nope"}
    )
    assert r2.status_code == 404


async def test_learner_caf_text_endpoint(client):
    cid = await _seed_learner_corpus()
    r = await client.post(
        "/api/v1/learner/caf-text",
        json={"text": "They is happy. I recieve a apple.", "language": "en",
              "corpus_id": cid},
    )
    assert r.status_code == 200, r.text
    data = r.json()
    assert data["text_caf"]["tokens"] > 0
    assert data["text_caf"]["sentences"] == 2
    assert data["text_caf"]["error_free_sentence_ratio"] is not None
    # Clause fields depend on whether the full spaCy model is installed:
    # blank fallback → None + explanatory note; full model → numeric value.
    if HAS_EN_MODEL:
        assert isinstance(data["text_caf"]["clauses_per_sentence"], (int, float))
    else:
        assert data["text_caf"]["clauses_per_sentence"] is None
        assert any("Dependency parsing unavailable" in n for n in data["text_caf"]["notes"])
    # Corpus arm: CAF + text-vs-corpus deltas.
    assert data["corpus_caf"] is not None
    assert data["corpus_caf"]["tokens"] == 11
    assert data["deltas"] is not None and "ttr" in data["deltas"]
    assert any("Parsed with" in n for n in data["notes"])

    # Without a corpus_id → corpus_caf/deltas None, still 200.
    r2 = await client.post(
        "/api/v1/learner/caf-text",
        json={"text": "They is happy.", "language": "en"},
    )
    assert r2.status_code == 200
    assert r2.json()["corpus_caf"] is None
    assert r2.json()["deltas"] is None

    # Unknown corpus_id → 404.
    r3 = await client.post(
        "/api/v1/learner/caf-text",
        json={"text": "Hello.", "language": "en", "corpus_id": "nope"},
    )
    assert r3.status_code == 404

    # Empty text → 422 (pydantic min_length).
    r4 = await client.post("/api/v1/learner/caf-text", json={"text": ""})
    assert r4.status_code == 422
