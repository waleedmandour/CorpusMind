"""Regression: collocations must survive nodes in >1000 sentences (v1.2.10).

The Student Mode soak test (scripts/soak_student_load.py) hit a hard 500 on
a ~100K-token corpus with the node "time" in ~4.5K sentences:

    sqlite3.OperationalError: Expression tree is too large (maximum depth 1000)

The old step-3 query built one OR branch per node sentence. This test seeds
1,500 node sentences — past SQLite's expression depth — and pins the
self-join rewrite that replaced the or_-chain. Tokens are inserted directly
(no spaCy annotation) so the test stays fast and deterministic.
"""

from __future__ import annotations

import os
from collections.abc import AsyncIterator

import pytest


@pytest.fixture
async def db_env() -> AsyncIterator[None]:
    os.environ["CORPUSMIND_DB_URL"] = "sqlite+aiosqlite:///:memory:"
    os.environ["CORPUSMIND_DATA_DIR"] = "/tmp/cm-test-data"
    from app.settings import get_settings

    get_settings.cache_clear()
    from app.main import app  # noqa: F401  (import AFTER env is pinned)
    from storage.session import dispose_db

    yield
    await dispose_db()


@pytest.mark.asyncio
async def test_collocations_beyond_sqlite_expression_depth(db_env: None) -> None:
    import storage.session as _ss
    from app.main import app
    from stats.service import compute_collocations
    from storage.models import AnnotationVersion, Corpus, Document, Project, Token

    async with app.router.lifespan_context(app):
        sm = _ss._sessionmaker
        assert sm is not None
        async with sm() as s:
            p = Project(name="P", language="en")
            s.add(p)
            await s.flush()
            c = Corpus(project_id=p.id, name="Node-heavy corpus", language="en")
            s.add(c)
            await s.flush()
            v = AnnotationVersion(corpus_id=c.id, version_label="v1", model_name="test")
            s.add(v)
            await s.flush()

            d = Document(corpus_id=c.id, filename="heavy.txt", cleaned_text="seed")
            s.add(d)
            await s.flush()

            # 1,500 sentences sharing the node 'time' — one OR branch per
            # sentence under the old query, past SQLite's depth limit.
            for sent_idx in range(1500):
                toks = ["time", "data", f"w{sent_idx % 10}", "end"]
                for tok_idx, tok in enumerate(toks):
                    s.add(Token(
                        version_id=v.id,
                        document_id=d.id,
                        sentence_idx=sent_idx,
                        token_idx=tok_idx,
                        text=tok,
                        lemma=tok,
                        pos="NOUN" if tok in ("time", "data") else "WORD",
                        dep_rel="dep",
                    ))
            await s.commit()
            cid = c.id

        sm = _ss._sessionmaker
        assert sm is not None
        async with sm() as session:
            result = await compute_collocations(session, cid, "time", min_freq=2)

    collocates = {r["collocate"] for r in result.rows}
    # 'data' and 'end' sit next to the node in all 1,500 sentences; the
    # rotating fillers w0..w9 appear 150x each — all above min_freq=2.
    assert "data" in collocates, f"'data' must collocate with 'time': got {sorted(collocates)}"
    assert "end" in collocates
    assert "w0" in collocates


# --------------------------------------------------------------------------- #
# v1.2.10 review follow-up: the self-join must not only not crash, it must
# produce the SAME NUMBERS as the or_-chain it replaced. A silent fan-out
# (each node token joining against itself twice) or a silently dropped
# sentence would publish wrong association scores — worse than the crash.
#
# Strategy: seed a small corpus (small enough that the or_-chain still runs),
# rebuild the OLD step-1 + step-2 + step-3 queries verbatim from the
# pre-fba3119 code, derive the expected O / fx / fy / N from those old rows
# with an independent window scan, then assert compute_collocations (new
# self-join) returns exactly those numbers, including the published scores.
# Sentence s1/s4/s5 put the node twice in one sentence — the classic
# self-join fan-out trap: without the DISTINCT, counts would double.
# --------------------------------------------------------------------------- #
import math  # noqa: E402
from collections import Counter, defaultdict  # noqa: E402

from sqlalchemy import func, select  # noqa: E402
from sqlalchemy import or_ as _or  # noqa: E402

from stats.measures import log_likelihood_2x2, mutual_information  # noqa: E402
from stats.service import (  # noqa: E402
    _fold,
    _is_real_token,
)
from storage.models import Token  # noqa: E402

_EQ_WINDOW = 1
_EQ_MIN_FREQ = 2
# (sentence_idx, [(text, pos, is_punct), ...]) — single doc keeps it simple.
_EQ_SENTENCES: list[tuple[int, list[tuple[str, str, bool]]]] = [
    (0, [("time", "NOUN", False), ("data", "NOUN", False),
         (" ", "SPACE", False), ("w0", "WORD", False), ("end", "WORD", False)]),
    (1, [("time", "NOUN", False), ("time", "NOUN", False),
         ("data", "NOUN", False), ("end", "WORD", False)]),
    (2, [("the", "WORD", False), ("time", "NOUN", False),
         ("Data", "NOUN", False), ("w1", "WORD", False), ("end", "WORD", False)]),
    (3, [("calm", "WORD", False), ("quiet", "WORD", False), ("still", "WORD", False)]),
    (4, [("time", "NOUN", False), ("end", "WORD", False),
         (",", "PUNCT", True), ("time", "NOUN", False), ("w2", "WORD", False)]),
    (5, [("data", "NOUN", False), ("time", "NOUN", False), ("data", "NOUN", False)]),
]


@pytest.mark.asyncio
async def test_collocations_selfjoin_matches_or_chain_numbers(db_env: None) -> None:
    import storage.session as _ss
    from app.main import app
    from stats.service import compute_collocations
    from storage.models import AnnotationVersion, Corpus, Document, Project

    async with app.router.lifespan_context(app):
        sm = _ss._sessionmaker
        assert sm is not None
        async with sm() as s:
            p = Project(name="P", language="en")
            s.add(p)
            await s.flush()
            c = Corpus(project_id=p.id, name="Equivalence corpus", language="en")
            s.add(c)
            await s.flush()
            v = AnnotationVersion(corpus_id=c.id, version_label="v1", model_name="test")
            s.add(v)
            await s.flush()
            d = Document(corpus_id=c.id, filename="eq.txt", cleaned_text="seed")
            s.add(d)
            await s.flush()
            for sent_idx, toks in _EQ_SENTENCES:
                for tok_idx, (text, pos, is_punct) in enumerate(toks):
                    s.add(Token(
                        version_id=v.id, document_id=d.id,
                        sentence_idx=sent_idx, token_idx=tok_idx,
                        text=text, lemma=text.lower(), pos=pos, is_punct=is_punct,
                    ))
            await s.commit()
            cid, vid = c.id, v.id

        sm = _ss._sessionmaker
        assert sm is not None
        async with sm() as session:
            # --- step 1 + 2 + 3 replicas of the OLD (pre-self-join) code ---
            col = Token.text
            node_lower, node_folded = "time", _fold("time")
            node_cond = (
                (func.lower(col) == node_lower) | (func.lower(col) == node_folded)
            ) & _is_real_token()
            node_sentences = {
                (r[0], r[1])
                for r in (
                    await session.execute(
                        select(Token.document_id, Token.sentence_idx)
                        .where(Token.version_id == vid, node_cond)
                        .distinct()
                    )
                ).all()
            }
            sent_filter = _or(*[
                (Token.document_id == doc_id) & (Token.sentence_idx == sent_idx)
                for doc_id, sent_idx in node_sentences
            ])
            old_rows = (
                await session.execute(
                    select(
                        Token.document_id, Token.sentence_idx, Token.token_idx,
                        col.label("text"), Token.is_punct, Token.pos,
                    )
                    .where(Token.version_id == vid, sent_filter)
                    .order_by(Token.document_id, Token.sentence_idx, Token.token_idx)
                )
            ).all()
            vocab_rows = (
                await session.execute(
                    select(col, func.count(Token.id))
                    .where(Token.version_id == vid, _is_real_token())
                    .group_by(col)
                )
            ).all()

            folded_counts: Counter[str] = Counter()
            for text, cnt in vocab_rows:
                if text and not text.isspace():
                    folded_counts[_fold(text)] += cnt
            N = sum(folded_counts.values())
            fx = folded_counts[node_folded]

            # Independent window scan over the OLD rows (the oracle).
            sentences: dict[tuple[str, int], list[tuple[int, str, str]]] = defaultdict(list)
            for doc_id, sent_idx, tok_idx, text, is_punct, pos in old_rows:
                if is_punct or pos == "SPACE" or (text and text.isspace()):
                    continue
                sentences[(doc_id, sent_idx)].append((tok_idx, text, pos or ""))
            O: Counter[str] = Counter()
            surfaces: dict[str, Counter[str]] = defaultdict(Counter)
            for row_toks in sentences.values():
                for i, (_idx, text, _pos) in enumerate(row_toks):
                    if _fold(text) != node_folded:
                        continue
                    for j in range(max(0, i - _EQ_WINDOW), min(len(row_toks), i + _EQ_WINDOW + 1)):
                        if j == i:
                            continue
                        key = _fold(row_toks[j][1])
                        O[key] += 1
                        surfaces[key][row_toks[j][1]] += 1

            expected: dict[str, int] = {
                k: o for k, o in O.items()
                if o >= _EQ_MIN_FREQ and folded_counts.get(k, 0) > 0
            }
            # Hand-computed cross-check of the oracle itself (fan-out trap
            # sentences s1/s4/s5 included): data 5, time 2 (self-pairs in s1),
            # end 2. If this ever drifts, the oracle — not the service — broke.
            assert expected == {"data": 5, "time": 2, "end": 2}, expected

            # --- the NEW path: aliased self-join inside compute_collocations ---
            result = await compute_collocations(
                session, cid, "time", window=_EQ_WINDOW, min_freq=_EQ_MIN_FREQ,
            )

            got = {_fold(r["collocate"]): r for r in result.rows}
            assert set(got) == set(expected), (sorted(got), sorted(expected))
            for key, o in expected.items():
                row = got[key]
                fy = folded_counts[key]
                # Counts and marginals identical, not merely "close":
                assert row["O"] == o, (key, row["O"], o)
                assert row["fx"] == fx
                assert row["fy"] == fy
                assert row["N"] == N
                # Published association scores equal the same deterministic
                # functions of (O, fx, fy, N) — a fan-out/duplication anywhere
                # upstream would shift O and every score below.
                a = min(o, fx, fy)
                b = fx - a
                c_ = fy - a
                d_cell = N - fx - fy + a
                assert row["log_likelihood"] == round(log_likelihood_2x2(a, b, c_, d_cell), 4)
                assert row["mi"] == round(mutual_information(O=o, R=fx, C=fy, N=N), 4)
                assert math.isfinite(row["log_likelihood"])
            # Display surface: 'Data' (s2) folds into 'data' (4x 'data', 1x
            # 'Data') — the most-common surface must win the display name.
            assert got["data"]["collocate"] == "data"
