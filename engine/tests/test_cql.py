"""CQL-lite (Phase 1) — parser, matcher, and endpoint tests.

Parser tests need no DB. Matcher/endpoint tests seed a small deterministic
corpus directly through the ORM (no spaCy annotation) so attribute values
are exact, following the test_v1210_collocation_tree.py precedent.

Fixture corpus (English, cid):
  doc1 s0: The/DT the|quick/JJ quick|brown/JJ brown|fox/NN fox|jumps/VBZ jump|
           over/IN over|the/DT the|lazy/JJ lazy|dog/NN dog|/PUNCT .
  doc1 s1: The/DT the|dog/NN dog|barked/VBZ bark|/PUNCT .
  doc2 s0: A/DT a|fox/NN fox|sleeps/VBZ sleep|/PUNCT .
  doc2 s1: Dogs/NNS dog|are/VBP be|loyal/JJ loyal|/PUNCT .
Arabic corpus (ar_cid) — morph strings use the REAL CAMeL calima-msa-r13
format (verified against the official morphology.db, see
test_cql_hardening.py::test_arabic_root_format_matches_real_camel_data):
root = DOTTED and undiacritised (ك.ت.ب); pattern = the calima template with
digit radical slots, e.g. كَتَبَ (PV) → 1َ2َ3, كُتُب (N) → 1ُ2ُ3:
  s0: أحمد/NOUN | كتب/VERB (root=ك.ت.ب|pattern=1َ2َ3) | كتابا/NOUN (root=ك.ت.ب|pattern=1ُ2ُ3) | ./PUNCT
  s1: إحمد/NOUN | نام/VERB | ./PUNCT
"""

from __future__ import annotations

import os
from collections.abc import AsyncIterator

import pytest

from stats.cql import (
    CqlSyntaxError,
    AnyUnit,
    WordUnit,
    ast_to_str,
    parse_cql,
)


# --------------------------------------------------------------------------- #
# Parser (no DB)
# --------------------------------------------------------------------------- #


def test_parser_accepts_core_forms() -> None:
    forms = [
        '"fox"',
        '"Fox" %c',
        "[]",
        '"very"? "quick"',
        '"quick" "brown"',
        '"said" []* "news"',
        '"a"{2,4} "b"',
        '[lemma="take"] []{0,3} "risk" within sentence',
        '[pos="DET" | pos="ADJ"]',
        '[lemma="book" & pos="N.*"]',
        '[pos!="DET"]+ "barked"',
        '("dog" | "fox") "barked"',
        "[word=/fox|dog/ %c]",
        "[word=/fox|dog/] %c",
        '[root="ك ت ب"]',
        '"x" within document',
        # v1.2.13-2: CQP-style scope aliases + merged flag spellings
        '"x" within s',
        '"x" within doc',
        '"a" %c%d',
        '"a" %cd',
        '"a" %c %d',
    ]
    for q in forms:
        assert ast_to_str(parse_cql(q)), q


def test_parser_rejects_malformed() -> None:
    bad = [
        '"fox',
        '[lemma="x"',
        '[bogus="x"]',
        '"a"{5,2}',
        '"a"{0}',
        "[] %c",
        '"a" within paragraph',
        "[lemma=/x(/]",
        "{}",
        '("a" | ',
        "",
        "   ",
        "bare_word",
        '[lemma="x" & ]',
        # v1.2.13-2: catastrophic regexes are rejected at parse time
        "[word=/(a+)+$/]",
        "[word=/((a+)+b)+$/]",
    ]
    for q in bad:
        with pytest.raises(CqlSyntaxError):
            parse_cql(q)


def test_parser_within_aliases() -> None:
    assert parse_cql('"x" within s').within == "sentence"
    assert parse_cql('"x" within sentence').within == "sentence"
    assert parse_cql('"x" within doc').within == "document"
    assert parse_cql('"x" within document').within == "document"


def test_parser_merged_flags() -> None:
    el = parse_cql('"a" %c%d').sequence[0]
    assert el.flags.ignore_case and el.flags.fold_diacritics
    el = parse_cql('"a" %cd').sequence[0]
    assert el.flags.ignore_case and el.flags.fold_diacritics


def test_parser_rejects_catastrophic_regex() -> None:
    # ReDoS guard: nested quantifiers over quantified groups are rejected
    # at parse time with an actionable message.
    for q in ['"a" [word=/(a+)+$/]', '[lemma=/(x*|y*)*$/]']:
        with pytest.raises(CqlSyntaxError, match="catastrophically"):
            parse_cql(q)
    # bounded, non-nested forms are fine
    assert parse_cql('[word=/(ab)+/]').sequence[0].unit.dnf[0][0].regex


def test_parser_cqp_compat_quoted_are_anchored_regex() -> None:
    q = parse_cql('"cat.*"', cqp_compat=True)
    el = q.sequence[0]
    # Compat mode: the quoted token becomes an anchored regex test on word.
    t = el.unit.dnf[0][0]
    assert t.regex and t.value == "^(?:cat.*)$"
    # Round-trips through the canonical rendering.
    once = ast_to_str(q)
    assert ast_to_str(parse_cql(once)) == once
    # Non-compat: wildcard literal (no regex).
    q2 = parse_cql('"cat.*"')
    assert isinstance(q2.sequence[0].unit, WordUnit)
    assert q2.sequence[0].unit.value == "cat.*"
    # Spec values convert too.
    q3 = parse_cql('[lemma="tak.*"]', cqp_compat=True)
    t3 = q3.sequence[0].unit.dnf[0][0]
    assert t3.regex and t3.value == "^(?:tak.*)$"


def test_parser_canonical_round_trip() -> None:
    # the canonical form re-parses to itself (idempotence)
    q = '[lemma="take"] []{0,3} "risk" within sentence'
    once = ast_to_str(parse_cql(q))
    assert ast_to_str(parse_cql(once)) == once


def test_parser_quantifier_forms() -> None:
    for suffix, (qmin, qmax) in {
        "?": (0, 1),
        "*": (0, None),
        "+": (1, None),
        "{3}": (3, 3),
        "{2,5}": (2, 5),
        "{2,}": (2, None),
        "{,3}": (0, 3),
    }.items():
        el = parse_cql(f'"a"{suffix} "b"').sequence[0]
        assert (el.qmin, el.qmax) == (qmin, qmax), suffix


# --------------------------------------------------------------------------- #
# Matcher / service (seeded ORM corpus)
# --------------------------------------------------------------------------- #


@pytest.fixture
async def corpus_env() -> AsyncIterator[tuple[str, str]]:
    """Fresh app + seeded English and Arabic corpora; yields (cid, ar_cid)."""
    os.environ["CORPUSMIND_DB_URL"] = "sqlite+aiosqlite:///:memory:"
    os.environ["CORPUSMIND_DATA_DIR"] = "/tmp/cm-test-data"
    from app.settings import get_settings

    get_settings.cache_clear()
    from app.main import app  # noqa: F401  (import AFTER env is pinned)
    from storage.session import dispose_db

    async with app.router.lifespan_context(app):
        import storage.session as _ss
        from storage.models import AnnotationVersion, Corpus, Document, Project, Token

        sm = _ss._sessionmaker
        assert sm is not None
        async with sm() as s:
            p = Project(name="CQL", language="en")
            s.add(p)
            await s.flush()
            c = Corpus(project_id=p.id, name="CQL corpus", language="en")
            s.add(c)
            await s.flush()
            v = AnnotationVersion(corpus_id=c.id, version_label="v1", model_name="test")
            s.add(v)
            await s.flush()

            # (text, lemma, pos, xpos, rel, is_punct)
            S0 = [
                ("The", "the", "DET", "DT", "det", False),
                ("quick", "quick", "ADJ", "JJ", "amod", False),
                ("brown", "brown", "ADJ", "JJ", "amod", False),
                ("fox", "fox", "NOUN", "NN", "nsubj", False),
                ("jumps", "jump", "VERB", "VBZ", "root", False),
                ("over", "over", "ADP", "IN", "case", False),
                ("the", "the", "DET", "DT", "det", False),
                ("lazy", "lazy", "ADJ", "JJ", "amod", False),
                ("dog", "dog", "NOUN", "NN", "obj", False),
                (".", ".", "PUNCT", ".", "punct", True),
            ]
            S1 = [
                ("The", "the", "DET", "DT", "det", False),
                ("dog", "dog", "NOUN", "NN", "nsubj", False),
                ("barked", "bark", "VERB", "VBZ", "root", False),
                (".", ".", "PUNCT", ".", "punct", True),
            ]

            async def add_doc(doc_name: str, sentences: list[list[tuple[str, str, str, str, str, bool]]]) -> str:
                d = Document(corpus_id=c.id, filename=doc_name, cleaned_text="seed")
                s.add(d)
                await s.flush()
                for sent_idx, sent in enumerate(sentences):
                    for tok_idx, (text, lemma, pos, xpos, rel, isp) in enumerate(sent):
                        s.add(
                            Token(
                                version_id=v.id,
                                document_id=d.id,
                                sentence_idx=sent_idx,
                                token_idx=tok_idx,
                                text=text,
                                lemma=lemma,
                                pos=pos,
                                pos_fine=xpos,
                                dep_rel=rel,
                                is_punct=isp,
                            )
                        )
                await s.flush()
                return d.id

            await add_doc("one.txt", [S0, S1])

            d2 = Document(corpus_id=c.id, filename="two.txt", cleaned_text="seed")
            s.add(d2)
            await s.flush()
            S2 = [
                ("A", "a", "DET", "DT", "det", False),
                ("fox", "fox", "NOUN", "NN", "nsubj", False),
                ("sleeps", "sleep", "VERB", "VBZ", "root", False),
                (".", ".", "PUNCT", ".", "punct", True),
            ]
            S3 = [
                ("Dogs", "dog", "NOUN", "NNS", "nsubj", False),
                ("are", "be", "AUX", "VBP", "cop", False),
                ("loyal", "loyal", "ADJ", "JJ", "root", False),
                (".", ".", "PUNCT", ".", "punct", True),
            ]
            for sent_idx, sent in enumerate([S2, S3]):
                for tok_idx, (text, lemma, pos, xpos, rel, isp) in enumerate(sent):
                    s.add(
                        Token(
                            version_id=v.id,
                            document_id=d2.id,
                            sentence_idx=sent_idx,
                            token_idx=tok_idx,
                            text=text,
                            lemma=lemma,
                            pos=pos,
                            pos_fine=xpos,
                            dep_rel=rel,
                            is_punct=isp,
                        )
                    )
            await s.commit()
            cid = c.id

        # Arabic corpus with morph layer + orthographic variants
        pa = Project(name="CQL-AR", language="ar")
        s.add(pa)
        await s.flush()
        ca = Corpus(project_id=pa.id, name="CQL AR", language="ar")
        s.add(ca)
        await s.flush()
        va = AnnotationVersion(corpus_id=ca.id, version_label="v1", model_name="test")
        s.add(va)
        await s.flush()
        da = Document(corpus_id=ca.id, filename="ar.txt", cleaned_text="seed")
        s.add(da)
        await s.flush()
        AR0 = [
            ("أحمد", "أحمد", "NOUN", "", "nsubj", False, ""),
            ("كتب", "كتب", "VERB", "", "root", False, "root=ك.ت.ب|pattern=1َ2َ3"),
            ("كتابا", "كتابا", "NOUN", "", "obj", False, "root=ك.ت.ب|pattern=1ُ2ُ3"),
            (".", ".", "PUNCT", "", "punct", True, ""),
        ]
        AR1 = [
            ("إحمد", "إحمد", "NOUN", "", "nsubj", False, ""),
            ("نام", "نام", "VERB", "", "root", False, ""),
            (".", ".", "PUNCT", "", "punct", True, ""),
        ]
        for sent_idx, sent in enumerate([AR0, AR1]):
            for tok_idx, (text, lemma, pos, xpos, rel, isp, morph) in enumerate(sent):
                s.add(
                    Token(
                        version_id=va.id,
                        document_id=da.id,
                        sentence_idx=sent_idx,
                        token_idx=tok_idx,
                        text=text,
                        lemma=lemma,
                        pos=pos,
                        pos_fine=xpos,
                        dep_rel=rel,
                        is_punct=isp,
                        morph=morph,
                    )
                )
        await s.commit()
        ar_cid = ca.id

        yield cid, ar_cid
    await dispose_db()


async def _run_cql(cid: str, query: str, **kw):
    from stats.cql import search_concordance_cql

    import storage.session as _ss

    sm = _ss._sessionmaker
    assert sm is not None
    async with sm() as session:
        return await search_concordance_cql(session, cid, query, **kw)


@pytest.mark.asyncio
async def test_single_word_token(corpus_env) -> None:
    cid, _ = corpus_env
    r = await _run_cql(cid, '"fox"')
    assert r.total == 2
    assert all(l.node == "fox" for l in r.lines)
    assert {l.document_filename for l in r.lines} == {"one.txt", "two.txt"}
    assert r.query["mode"] == "cql"


@pytest.mark.asyncio
async def test_case_sensitivity_and_flag(corpus_env) -> None:
    cid, _ = corpus_env
    assert (await _run_cql(cid, '"the"')).total == 1  # only d1 s0 t6
    assert (await _run_cql(cid, '"the" %c')).total == 3  # + The x2
    assert (await _run_cql(cid, '"The"')).total == 2


@pytest.mark.asyncio
async def test_wildcards(corpus_env) -> None:
    cid, _ = corpus_env
    assert (await _run_cql(cid, '"dog*"')).total == 2  # dog x2; Dogs excluded (case)
    assert (await _run_cql(cid, '"d?g"')).total == 2
    r = await _run_cql(cid, '"d*g" %c')
    assert r.total == 2  # 'Dogs' does not END in g — only the two 'dog' tokens


@pytest.mark.asyncio
async def test_attribute_specs(corpus_env) -> None:
    cid, _ = corpus_env
    assert (await _run_cql(cid, '[lemma="jump" & pos="VERB"]')).total == 1
    assert (await _run_cql(cid, '[xpos="DT"]')).total == 4
    assert (await _run_cql(cid, '[rel="nsubj"]')).total == 4
    assert (await _run_cql(cid, '[pos="AUX" | pos="VERB"]')).total == 4
    assert (await _run_cql(cid, "[word=/fox|dog/]")).total == 4
    assert (await _run_cql(cid, '[pos!="PUNCT"]')).total == 18


@pytest.mark.asyncio
async def test_sequences_and_gaps(corpus_env) -> None:
    cid, _ = corpus_env
    r = await _run_cql(cid, '"quick" "brown"')
    assert r.total == 1 and r.lines[0].node == "quick brown"

    r = await _run_cql(cid, '"quick" []{1} "fox"')
    assert r.total == 1 and r.lines[0].node == "quick brown fox"

    assert (await _run_cql(cid, '"quick" []{2} "fox"')).total == 0

    # ambiguity: []{1,2} has two spans from the same start -> shortest kept
    r = await _run_cql(cid, '"quick" []{1,2} "fox"')
    assert r.total == 1 and r.lines[0].node == "quick brown fox"

    # punctuation is a stream token: 'dog . The' bridges the s0/s1 boundary
    r = await _run_cql(cid, '"dog" "." "The"')
    assert r.total == 1 and r.lines[0].node == "dog . The"


@pytest.mark.asyncio
async def test_quantifiers(corpus_env) -> None:
    cid, _ = corpus_env
    r = await _run_cql(cid, '"lazy"? "dog"')
    nodes = sorted(l.node for l in r.lines)
    assert r.total == 3 and nodes == ["dog", "dog", "lazy dog"]

    r = await _run_cql(cid, '[pos="ADJ"]{2}')
    assert r.total == 1 and r.lines[0].node == "quick brown"


@pytest.mark.asyncio
async def test_groups_and_cross_sentence_scope(corpus_env) -> None:
    cid, _ = corpus_env
    r = await _run_cql(cid, '("dog" | "fox") "barked"')
    assert r.total == 1 and r.lines[0].node == "dog barked"

    # document scope (default): the match crosses the s0/s1 boundary in doc1
    r = await _run_cql(cid, '"jumps" []* "barked"')
    assert r.total == 1
    assert r.query["within"] == "document"

    # within sentence excludes it
    r = await _run_cql(cid, '"jumps" []* "barked" within sentence')
    assert r.total == 0

    r = await _run_cql(cid, '"dog" "barked" within sentence')
    assert r.total == 1 and r.lines[0].node == "dog barked"


@pytest.mark.asyncio
async def test_pagination_sort_sample(corpus_env) -> None:
    cid, _ = corpus_env
    r = await _run_cql(cid, '"the" %c')
    assert r.total == 3
    paged = await _run_cql(cid, '"the" %c', limit=2, offset=1)
    assert paged.total == 3 and len(paged.lines) == 2

    srt = await _run_cql(cid, '"the" %c', sort=[{"side": "right", "offset": 1}])
    rights = [l.right.split()[0] for l in srt.lines if l.right]
    assert rights == sorted(rights)

    a = await _run_cql(cid, '"the" %c', random_sample=2, sample_seed=42)
    b = await _run_cql(cid, '"the" %c', random_sample=2, sample_seed=42)
    assert len(a.lines) == 2 and [l.line_id for l in a.lines] == [l.line_id for l in b.lines]


@pytest.mark.asyncio
async def test_no_match_and_meta(corpus_env) -> None:
    cid, _ = corpus_env
    r = await _run_cql(cid, '"zebra"')
    assert r.total == 0 and r.lines == []
    assert r.query["parsed"] == '"zebra"'


@pytest.mark.asyncio
async def test_arabic_morph_layer_and_normalization(corpus_env) -> None:
    _, ar_cid = corpus_env
    # REAL CAMeL calima-msa-r13 format: dotted root (ك.ت.ب), template
    # pattern with digit radical slots (1َ2َ3 = PV كَتَبَ; 1ُ2ُ3 = N كُتُب).
    r = await _run_cql(ar_cid, '[root="ك.ت.ب"]')
    assert r.total == 2 and {l.lemma for l in r.lines} == {"كتب", "كتابا"}

    r = await _run_cql(ar_cid, '[pattern="1ُ2ُ3"]')
    assert r.total == 1 and r.lines[0].lemma == "كتابا"

    # wildcard substring over the morph layer (documented *…* style)
    r = await _run_cql(ar_cid, '[morph="*root=ك.ت.ب*"]')
    assert r.total == 2

    # normalization folds أ/إ → ا on both sides
    assert (await _run_cql(ar_cid, '"احمد"')).total == 0
    r = await _run_cql(ar_cid, '"احمد"', normalize=True)
    assert r.total == 2
    assert r.query["normalize"] is True
    assert "Arabic normalization" in r.query["normalization"]


@pytest.mark.asyncio
async def test_fetch_cap_marks_total_capped(corpus_env, monkeypatch) -> None:
    cid, _ = corpus_env
    import stats.cql as cql_mod

    monkeypatch.setattr(cql_mod, "_CONCORDANCE_FETCH_CAP", 2)
    r = await _run_cql(cid, '"the" %c')
    assert r.query["total_capped"] is True
    assert r.query["total_lower_bound"] == r.total


# --------------------------------------------------------------------------- #
# Endpoint (E2E)
# --------------------------------------------------------------------------- #


@pytest.mark.asyncio
async def test_endpoint_happy_path(corpus_env) -> None:
    from httpx import ASGITransport, AsyncClient

    from app.main import app

    cid, _ = corpus_env
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as ac:
        r = await ac.post(
            f"/api/v1/corpora/{cid}/concordance/cql",
            json={"query": '[lemma="jump" & pos="VERB"] []{0,4} "dog"', "window": 5},
        )
        assert r.status_code == 200
        data = r.json()
        assert data["total"] == 1
        assert data["lines"][0]["node"] == "jumps over the lazy dog"
        assert data["query"]["mode"] == "cql"
        assert "parsed" in data["query"]


@pytest.mark.asyncio
async def test_endpoint_syntax_error_422(corpus_env) -> None:
    from httpx import ASGITransport, AsyncClient

    from app.main import app

    cid, _ = corpus_env
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as ac:
        r = await ac.post(f"/api/v1/corpora/{cid}/concordance/cql", json={"query": '[lemma="x"'})
        assert r.status_code == 422
        assert "Invalid CQL query" in r.json()["detail"]


@pytest.mark.asyncio
async def test_endpoint_unknown_corpus_404(corpus_env) -> None:
    from httpx import ASGITransport, AsyncClient

    from app.main import app

    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as ac:
        r = await ac.post("/api/v1/corpora/nonexistent/concordance/cql", json={"query": '"a"'})
        assert r.status_code == 404


@pytest.mark.asyncio
async def test_endpoint_sort_and_sample(corpus_env) -> None:
    from httpx import ASGITransport, AsyncClient

    from app.main import app

    cid, _ = corpus_env
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as ac:
        r = await ac.post(
            f"/api/v1/corpora/{cid}/concordance/cql",
            json={
                "query": '"the" %c',
                "sort": [{"side": "right", "offset": 1}],
                "random_sample": 2,
                "sample_seed": 7,
            },
        )
        assert r.status_code == 200
        data = r.json()
        assert len(data["lines"]) == 2
        assert data["query"]["sort"] == [{"side": "right", "offset": 1}]
