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

import pytest


@pytest.fixture
async def db_env():
    os.environ["CORPUSMIND_DB_URL"] = "sqlite+aiosqlite:///:memory:"
    os.environ["CORPUSMIND_DATA_DIR"] = "/tmp/cm-test-data"
    from app.settings import get_settings

    get_settings.cache_clear()
    from app.main import app  # noqa: F401  (import AFTER env is pinned)
    from storage.session import dispose_db

    yield
    await dispose_db()


@pytest.mark.asyncio
async def test_collocations_beyond_sqlite_expression_depth(db_env) -> None:
    import storage.session as _ss
    from app.main import app
    from stats.service import compute_collocations
    from storage.models import AnnotationVersion, Corpus, Document, Project, Token

    async with app.router.lifespan_context(app):
        async with _ss._sessionmaker() as s:
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

        async with _ss._sessionmaker() as session:
            result = await compute_collocations(session, cid, "time", min_freq=2)

    collocates = {r["collocate"] for r in result.rows}
    # 'data' and 'end' sit next to the node in all 1,500 sentences; the
    # rotating fillers w0..w9 appear 150x each — all above min_freq=2.
    assert "data" in collocates, f"'data' must collocate with 'time': got {sorted(collocates)}"
    assert "end" in collocates
    assert "w0" in collocates
