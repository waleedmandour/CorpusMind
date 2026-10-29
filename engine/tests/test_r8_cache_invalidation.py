"""v1.2.14-8 (r8) — stale collocation/vocab caches after corpus mutations.

P0-1 field report: delete a document, re-run the analysis, and the numbers
DO NOT CHANGE. ``stats.service._VOCAB_CACHE`` (and the v1.2.14-6 collocation
RESULT cache) are keyed by ``version_id`` — and a document delete (or an
add into an existing corpus) keeps the SAME annotation version, so the
cache key is identical and the stale Counter is served forever.
``clear_vocab_cache()`` / ``clear_colloc_cache()`` had no production caller.

The r8 contract pinned here (fail-before / pass-after):

  1. Deleting a document via the API updates the folded vocab (N and the
     per-type counts) for the SAME version id.
  2. Adding a document into the SAME (reused) annotation version — the
     ingestion/service.py reuse path — updates the folded vocab too.
  3. The collocation RESULT cache reflects both mutations (a deleted
     document's collocates disappear instead of being served from the LRU).
  4. Every mutating endpoint bumps the global data epoch — the mechanism
     that keys both caches. Pinned white-box so the wiring cannot rot.

Token rows are seeded directly via session_scope (no NLP pipeline) — the
same in-memory DB the service functions read, exactly like
test_r6_network_mesh.py.
"""
from __future__ import annotations

import os
from collections.abc import AsyncIterator, Iterator

import pytest
from httpx import ASGITransport, AsyncClient

os.environ["CORPUSMIND_DB_URL"] = "sqlite+aiosqlite:///:memory:"
os.environ["CORPUSMIND_DATA_DIR"] = "/tmp/cm-test-r8-cache"
from app.settings import get_settings

get_settings.cache_clear()


DOC0_SENTENCES = [
    ["the", "deep", "ocean", "is", "blue"],
    ["the", "deep", "ocean", "is", "cold"],
    ["the", "blue", "ocean", "is", "vast"],
]
DOC1_SENTENCES = [
    ["mountain", "streams", "run", "fast"],
    ["mountain", "air", "is", "crisp"],
]


@pytest.fixture(autouse=True)
def _fresh_caches_and_epoch() -> Iterator[None]:
    """Isolate the memo caches AND the data epoch around every test."""
    from stats.service import clear_colloc_cache, clear_vocab_cache

    clear_colloc_cache()
    clear_vocab_cache()
    try:
        from stats.service import reset_data_epoch

        reset_data_epoch()
    except ImportError:
        pass  # r7: no data epoch yet (fail-before)
    yield
    clear_colloc_cache()
    clear_vocab_cache()
    try:
        from stats.service import reset_data_epoch

        reset_data_epoch()
    except ImportError:
        pass


@pytest.fixture
async def client() -> AsyncIterator[AsyncClient]:
    from app.main import app
    from storage.session import dispose_db

    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as ac:
        async with app.router.lifespan_context(app):
            yield ac
    await dispose_db()


async def _seed_corpus(per_doc_sentences: list[list[list[str]]]) -> tuple[str, str, list[str]]:
    """Seed project + corpus + ONE annotation version + one document per
    sentence block. Returns (cid, version_id, document_ids)."""
    from storage.models import AnnotationVersion, Corpus, Document, Project, Token
    from storage.session import init_db, session_scope

    await init_db()

    async with session_scope() as s:
        p = Project(name="P-r8", language="en")
        s.add(p)
        await s.flush()
        c = Corpus(project_id=p.id, name="C-r8", language="en")
        s.add(c)
        await s.flush()
        v = AnnotationVersion(
            corpus_id=c.id, version_label="v1",
            # Matches _FakePipeline's label in the add-path test so that test
            # exercises the version REUSE path (not a fresh version).
            model_name="spacy:en_core_web_sm", model_version="0.0.0",
        )
        s.add(v)
        await s.flush()
        doc_ids: list[str] = []
        for doc_idx, sentences in enumerate(per_doc_sentences):
            d = Document(corpus_id=c.id, filename=f"doc{doc_idx}.txt", cleaned_text="seed")
            s.add(d)
            await s.flush()
            doc_ids.append(d.id)
            for sent_idx, sent in enumerate(sentences):
                for tok_idx, text in enumerate(sent):
                    s.add(Token(
                        version_id=v.id, document_id=d.id,
                        sentence_idx=sent_idx, token_idx=tok_idx,
                        text=text, lemma=text,
                        pos="" if text in {"the", "is"} else "NOUN",
                    ))
        await s.flush()
        return c.id, v.id, doc_ids


def _expected_tokens(sentences: list[list[list[str]]]) -> int:
    return sum(len(s) for block in sentences for s in block)


# --------------------------------------------------------------------------- #
# 1. Document DELETE via the API must update the folded vocab
# --------------------------------------------------------------------------- #


async def test_document_delete_updates_folded_vocab(client: AsyncClient) -> None:
    from stats.service import _get_folded_vocab, _Norm
    from storage.session import session_scope

    cid, vid, doc_ids = await _seed_corpus([DOC0_SENTENCES, DOC1_SENTENCES])

    async with session_scope() as session:
        norm = _Norm(False, "en")
        counter, n = await _get_folded_vocab(session, vid, "word", norm, None)
        assert n == _expected_tokens([DOC0_SENTENCES, DOC1_SENTENCES])
        assert counter["ocean"] == 3

    # Field-report path: delete the ocean document through the real API.
    r = await client.delete(f"/api/v1/corpora/{cid}/documents/{doc_ids[0]}")
    assert r.status_code == 200, r.text

    async with session_scope() as session:
        norm = _Norm(False, "en")
        counter, n = await _get_folded_vocab(session, vid, "word", norm, None)
        # r7 BUG: same (version_id, level, norm, doc_ids=None) key → stale
        # Counter served; ocean stayed at 3 and N never dropped.
        assert n == _expected_tokens([DOC1_SENTENCES]), (
            "folded vocab must reflect the document deletion immediately"
        )
        assert "ocean" not in counter


# --------------------------------------------------------------------------- #
# 2. Document ADD into the reused version must update the folded vocab
# --------------------------------------------------------------------------- #


class _FakePipelineInfo:
    backend = "spacy"
    model_name = "en_core_web_sm"
    model_version = "0.0.0"
    spacy_version = "test"
    language = "en"
    degraded = False


class _FakeToken:
    def __init__(self, text: str) -> None:
        self.text = text
        self.lemma = text
        self.pos = "NOUN" if text not in {"the", "is"} else ""
        self.pos_fine = ""
        self.morph = ""
        self.dep_head = 0
        self.dep_rel = "dep"
        self.is_punct = False
        self.is_stop = False


class _FakeSentence:
    def __init__(self, words: list[str]) -> None:
        self.tokens = [_FakeToken(w) for w in words]


class _FakeParsed:
    def __init__(self, sentences: list[list[str]]) -> None:
        self.sentences = [_FakeSentence(s) for s in sentences]
        self.token_count = sum(len(s) for s in sentences)
        self.type_count = len({w for s in sentences for w in s})


class _FakePipeline:
    """Deterministic tokenizer-only pipeline (no spaCy model needed)."""

    def __init__(self) -> None:
        self.info_value = _FakePipelineInfo()

    def info(self) -> _FakePipelineInfo:
        return self.info_value

    def parse_document(self, text: str) -> _FakeParsed:
        return _FakeParsed([text.split()])


async def test_document_add_into_reused_version_updates_folded_vocab(
    client: AsyncClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    from sqlalchemy import select

    from stats.service import _get_folded_vocab, _Norm
    from storage.session import session_scope

    cid, vid, _doc_ids = await _seed_corpus([DOC1_SENTENCES])

    async with session_scope() as session:
        norm = _Norm(False, "en")
        counter, n = await _get_folded_vocab(session, vid, "word", norm, None)
        assert n == _expected_tokens([DOC1_SENTENCES])

    # Production add path: upload endpoint → ingestion.service.ingest_document.
    # The pipeline model label is unchanged, so the annotation version is
    # REUSED (ingestion/service.py:89-117) — the exact staleness scenario.
    from ingestion import service as ingest_service

    monkeypatch.setattr(
        ingest_service, "get_pipeline", lambda **_kw: _FakePipeline()
    )
    r = await client.post(
        f"/api/v1/corpora/{cid}/documents",
        files={"files": ("ocean.txt", b"the deep ocean is blue", "text/plain")},
    )
    assert r.status_code == 200, r.text

    async with session_scope() as session:
        from storage.models import AnnotationVersion

        versions = (await session.execute(
            select(AnnotationVersion).where(AnnotationVersion.corpus_id == cid)
        )).scalars().all()
        assert len(versions) == 1, "the pipeline label matched — the version must be REUSED"
        assert versions[0].id == vid
        norm = _Norm(False, "en")
        counter, n = await _get_folded_vocab(session, vid, "word", norm, None)
        assert n == _expected_tokens([DOC1_SENTENCES]) + 5, (
            "folded vocab must include tokens added under the SAME version id"
        )
        assert counter["ocean"] == 1


# --------------------------------------------------------------------------- #
# 3. The collocation RESULT cache must reflect the deletion
# --------------------------------------------------------------------------- #


async def test_collocation_result_cache_invalidated_on_delete(client: AsyncClient) -> None:
    from stats.service import compute_collocations
    from storage.session import session_scope

    cid, _vid, doc_ids = await _seed_corpus([DOC0_SENTENCES, DOC1_SENTENCES])

    async with session_scope() as session:
        r1 = await compute_collocations(session, cid, "ocean", min_freq=1, limit=50)
        assert r1.rows, "ocean must have collocates before the delete"

    r = await client.delete(f"/api/v1/corpora/{cid}/documents/{doc_ids[0]}")
    assert r.status_code == 200, r.text

    async with session_scope() as session:
        r2 = await compute_collocations(session, cid, "ocean", min_freq=1, limit=50)
        # r7 BUG: the (version, node, window, ...) result key is unchanged →
        # the pre-delete rows came back from the LRU.
        assert r2.rows == [], (
            "a deleted document's collocates must not be served from cache"
        )


# --------------------------------------------------------------------------- #
# 4. Mutating endpoints bump the data epoch (the mechanism)
# --------------------------------------------------------------------------- #


async def test_mutating_endpoints_bump_data_epoch(client: AsyncClient) -> None:
    from stats.service import current_data_epoch

    cid, _vid, doc_ids = await _seed_corpus([DOC0_SENTENCES, DOC1_SENTENCES])
    e0 = current_data_epoch()

    r = await client.delete(f"/api/v1/corpora/{cid}/documents/{doc_ids[1]}")
    assert r.status_code == 200, r.text
    assert current_data_epoch() > e0, "document delete must bump the data epoch"

    e1 = current_data_epoch()
    r = await client.post(
        f"/api/v1/corpora/{cid}/documents",
        files={"files": ("more.txt", b"extra words here now", "text/plain")},
    )
    assert r.status_code == 200, r.text
    assert current_data_epoch() > e1, "document add must bump the data epoch"

    e2 = current_data_epoch()
    r = await client.delete(f"/api/v1/corpora/{cid}")
    assert r.status_code == 200, r.text
    assert current_data_epoch() > e2, "corpus delete must bump the data epoch"
