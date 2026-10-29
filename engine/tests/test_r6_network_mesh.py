"""v1.2.14-6 regression tests — the collocation-network 504 fix.

The r4 field report: on a large Arabic corpus, POST /collocations/network
returned HTTP 504 ("exceeded the 30s deadline") while a concurrent GET
/corpora/{id} failed at the transport level. Three engine changes fix it,
and this module proves each one:

1. The depth-2 mesh ran one full compute_collocations() scan per pivot
   (14 window scans per build at the shipped top_n). The new
   stats.service.compute_collocation_mesh() answers every pivot×known
   pair with ONE self-join + ONE counting sweep. Tests 1-4 prove it is
   semantically identical to the per-pivot scans: same candidate sets,
   same O/fx/fy/N, same measures, same folding, same min_freq cut, and
   it can never attach a collocate outside `known`.
2. compute_collocations ran its Python window sweep on the event loop,
   stalling every concurrent request (and the shell's health probe) for
   the sweep's duration. The sweep now runs in a worker thread — with
   unchanged behaviour (the equivalence tests assert the same measures
   the flat table always produced).
3. Same-params re-queries re-paid the full scan. A bounded LRU result
   cache now serves them (test 5).

Token rows are seeded directly via session_scope (no NLP pipeline, no
CAMeL data pack) — the same in-memory DB the service functions read.
"""
from __future__ import annotations

import os
from collections.abc import AsyncIterator, Iterator

import pytest
from httpx import ASGITransport, AsyncClient

os.environ["CORPUSMIND_DB_URL"] = "sqlite+aiosqlite:///:memory:"
os.environ["CORPUSMIND_DATA_DIR"] = "/tmp/cm-test-mesh"
from app.settings import get_settings

get_settings.cache_clear()


EN_SENTENCES = [
    ["the", "deep", "ocean", "is", "blue"],
    ["the", "deep", "ocean", "is", "cold"],
    ["the", "blue", "ocean", "is", "vast"],
    ["the", "ocean", "is", "deep"],
    ["the", "ocean", "is", "blue"],
    ["the", "deep", "blue", "ocean", "is", "calm"],
]

# Diacritic vs plain spellings of the same words — the fold rule
# (_ar_fold / SQL arnorm under normalize_arabic=True) must collapse them
# exactly like the per-pivot scans do.
AR_SENTENCES = [
    ["قرأتُ", "الكِتابَ", "الجديدَ", "في", "المكتبةِ"],
    ["الكتاب", "الجديد", "على", "الطاولة"],
    ["الكِتاب", "مفيدٌ", "وجديد"],
    ["الكتاب", "في", "المكتبة"],
]

_MEASURE_KEYS = (
    "O", "fx", "fy", "N", "mi", "t_score", "log_likelihood",
    "dice", "log_dice", "chi_square", "delta_p_y_given_x",
    "delta_p_x_given_y", "fisher",
)


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
                    pos="" if text in {"the", "is", "في", "على"} else "NOUN",
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


# --------------------------------------------------------------------------- #
# 1. Mesh ≡ per-pivot scans (English, word level)
# --------------------------------------------------------------------------- #


async def test_mesh_matches_per_pivot_scans_english() -> None:
    from stats.service import compute_collocation_mesh, compute_collocations
    from storage.session import session_scope

    cid = await _seed_tokens(EN_SENTENCES, "en")

    async with session_scope() as session:
        center = await compute_collocations(session, cid, "ocean", min_freq=1, limit=200)
        assert center.rows, "ocean must have collocates"
        pivots = [r["collocate"] for r in center.rows]
        known = [*pivots, "ocean"]
        mesh = await compute_collocation_mesh(session, cid, pivots, known, min_freq=1)

        # Every pivot's mesh rows must match a fresh per-pivot scan,
        # restricted to the known set, on every count and measure.
        known_set = set(known)
        for pivot in pivots:
            per = await compute_collocations(session, cid, pivot, min_freq=1, limit=200)
            per_known = {
                r["collocate"]: r for r in per.rows
                if r["collocate"] in known_set and r["collocate"] != pivot
            }
            mesh_rows = {
                r["collocate"]: r for r in mesh.get(pivot, [])
                if r["collocate"] != pivot
            }
            assert set(per_known) == set(mesh_rows), (
                f"candidate set mismatch for pivot {pivot!r}: "
                f"scan-only={sorted(set(per_known) - set(mesh_rows))} "
                f"mesh-only={sorted(set(mesh_rows) - set(per_known))}"
            )
            for colloc, prow in per_known.items():
                mrow = mesh_rows[colloc]
                for k in _MEASURE_KEYS:
                    assert mrow[k] == pytest.approx(prow[k]), (pivot, colloc, k)

        # Spot-check exact co-occurrence counts by hand from EN_SENTENCES:
        # O(deep→blue)=2 (sentences 1 and 6), O(deep→ocean)=4, O(blue→ocean)=4.
        deep_rows = {r["collocate"]: r for r in mesh["deep"]}
        assert deep_rows["blue"]["O"] == 2
        assert deep_rows["ocean"]["O"] == 4
        blue_rows = {r["collocate"]: r for r in mesh["blue"]}
        assert blue_rows["ocean"]["O"] == 4
        assert blue_rows["deep"]["O"] == 2


# --------------------------------------------------------------------------- #
# 2. min_freq cut + known-set containment
# --------------------------------------------------------------------------- #


async def test_mesh_respects_min_freq() -> None:
    from stats.service import compute_collocation_mesh
    from storage.session import session_scope

    cid = await _seed_tokens(EN_SENTENCES, "en")

    async with session_scope() as session:
        mesh = await compute_collocation_mesh(
            session, cid, ["deep", "blue"], ["ocean", "deep", "blue"], min_freq=3,
        )
        deep_rows = {r["collocate"]: r for r in mesh["deep"]}
        assert "ocean" in deep_rows and deep_rows["ocean"]["O"] == 4
        # O(deep→blue)=2 < min_freq=3 — must be cut.
        assert "blue" not in deep_rows
        blue_rows = {r["collocate"]: r for r in mesh["blue"]}
        # O(blue→deep)=2 < 3, O(blue→ocean)=4 ≥ 3.
        assert "deep" not in blue_rows
        assert blue_rows["ocean"]["O"] == 4


async def test_mesh_never_adds_unknown_collocates() -> None:
    from stats.service import compute_collocation_mesh
    from storage.session import session_scope

    cid = await _seed_tokens(EN_SENTENCES, "en")

    async with session_scope() as session:
        # known = the center node only — every mesh row must attach there.
        mesh = await compute_collocation_mesh(
            session, cid, ["deep", "blue"], ["ocean"], min_freq=1,
        )
        for pivot, rows in mesh.items():
            for r in rows:
                assert r["collocate"] == "ocean", (pivot, r["collocate"])


# --------------------------------------------------------------------------- #
# 3. Arabic folding parity (normalize_arabic=True → SQL arnorm + _ar_fold)
# --------------------------------------------------------------------------- #


async def test_mesh_matches_per_pivot_scans_arabic_normalized() -> None:
    from stats.service import compute_collocation_mesh, compute_collocations
    from storage.session import session_scope

    cid = await _seed_tokens(AR_SENTENCES, "ar")

    async with session_scope() as session:
        center = await compute_collocations(
            session, cid, "الكتاب", min_freq=1, limit=200, normalize_arabic=True,
        )
        assert center.rows, "الكتاب must have collocates"
        # The node's corpus frequency must fold the diacritic spellings in:
        # الكِتابَ / الكِتاب / الكتاب appear in all four sentences.
        assert center.rows[0]["fx"] == 4

        pivots = [r["collocate"] for r in center.rows]
        known = [*pivots, "الكتاب"]
        mesh = await compute_collocation_mesh(
            session, cid, pivots, known, min_freq=1, normalize_arabic=True,
        )

        # Compare by FOLDED key, not display: a pivot scan's display for a
        # fold-key can carry harakat (surface ties resolve to the first
        # surface seen) while the graph node is the plain spelling. The
        # OLD per-pivot mesh dropped those edges ("other not in G.nodes");
        # the one-pass mesh attaches by folded key and names the edge with
        # the known display — a deliberate improvement the O-values below
        # assert.
        from stats.service import _ar_fold

        known_set = set(known)
        for pivot in pivots:
            per = await compute_collocations(
                session, cid, pivot, min_freq=1, limit=200, normalize_arabic=True,
            )
            per_known = {
                r["collocate"]: r for r in per.rows
                if r["collocate"] in known_set and r["collocate"] != pivot
            }
            mesh_rows = {
                r["collocate"]: r for r in mesh.get(pivot, [])
                if r["collocate"] != pivot
            }
            per_by_fold = {_ar_fold(c): r for c, r in per_known.items()}
            mesh_by_fold = {_ar_fold(c): r for c, r in mesh_rows.items()}
            assert set(per_by_fold) <= set(mesh_by_fold), (
                f"mesh lost folded pairs for pivot {pivot!r}: "
                f"{sorted(set(per_by_fold) - set(mesh_by_fold))}"
            )
            for kf, prow in per_by_fold.items():
                mrow = mesh_by_fold[kf]
                for k in _MEASURE_KEYS:
                    assert mrow[k] == pytest.approx(prow[k]), (pivot, kf, k)

        # O(الجديد → الكتاب) == 2 — the pivot display carries harakat but
        # the folded match must still land on the plain node form, and the
        # row display must be the known (graph-node) string.
        jd_key = next(p for p in pivots if "الجديد" in p)
        jd_rows = {r["collocate"]: r for r in mesh[jd_key]}
        assert jd_rows["الكتاب"]["O"] == 2
        assert jd_rows["الكتاب"]["collocate"] == "الكتاب"


# --------------------------------------------------------------------------- #
# 4. Edge cases
# --------------------------------------------------------------------------- #


async def test_mesh_empty_inputs_return_empty() -> None:
    from stats.service import compute_collocation_mesh
    from storage.session import session_scope

    cid = await _seed_tokens(EN_SENTENCES, "en")

    async with session_scope() as session:
        assert await compute_collocation_mesh(session, cid, [], ["ocean"]) == {}
        assert await compute_collocation_mesh(session, cid, ["deep"], []) == {}
        # Unknown corpus / unknown pivots → no rows, no error.
        assert await compute_collocation_mesh(session, cid, ["zzz"], ["ocean"]) == {}
        assert await compute_collocation_mesh(session, "nope", ["deep"], ["ocean"]) == {}


# --------------------------------------------------------------------------- #
# 5. Collocation result cache
# --------------------------------------------------------------------------- #


async def test_colloc_cache_hits_and_param_changes() -> None:
    from stats.service import (
        _COLLOC_CACHE,
        clear_colloc_cache,
        compute_collocations,
    )
    from storage.session import session_scope

    cid = await _seed_tokens(EN_SENTENCES, "en")

    async with session_scope() as session:
        clear_colloc_cache()
        r1 = await compute_collocations(session, cid, "ocean", min_freq=1, limit=50)
        assert len(_COLLOC_CACHE) == 1, "first call must populate exactly one entry"

        r2 = await compute_collocations(session, cid, "ocean", min_freq=1, limit=50)
        assert len(_COLLOC_CACHE) == 1, "same-params call must be served from cache"
        assert [dict(x) for x in r2.rows] == [dict(x) for x in r1.rows]
        assert r2.warnings == r1.warnings

        # Different window → different key, cache grows.
        await compute_collocations(session, cid, "ocean", min_freq=1, limit=50, window=2)
        assert len(_COLLOC_CACHE) == 2

        # Different limit slices the SAME cached candidates — no new entry.
        r4 = await compute_collocations(session, cid, "ocean", min_freq=1, limit=1)
        assert len(_COLLOC_CACHE) == 2
        assert len(r4.rows) == 1
        assert len(r1.rows) > 1

        clear_colloc_cache()
        assert len(_COLLOC_CACHE) == 0


# --------------------------------------------------------------------------- #
# 6. Endpoint-level: the mesh edges land in the served graph
# --------------------------------------------------------------------------- #


async def test_network_endpoint_mesh_edges(client: AsyncClient) -> None:
    cid = await _seed_tokens(EN_SENTENCES, "en")

    r = await client.post(
        f"/api/v1/corpora/{cid}/collocations/network",
        json={"node": "ocean", "level": "word", "window": 5, "min_freq": 1,
              "measure": "mi", "top_n": 14, "depth": 2, "max_nodes": 60},
    )
    assert r.status_code == 200, r.text
    body = r.json()

    node_ids = {n["id"] for n in body["nodes"]}
    assert {"ocean", "deep", "blue"} <= node_ids
    pairs = {frozenset((e["source"], e["target"])) for e in body["edges"]}
    # Spokes from the center scan…
    assert frozenset(("ocean", "deep")) in pairs
    assert frozenset(("ocean", "blue")) in pairs
    # …and the depth-2 mesh edge between the collocates themselves.
    assert frozenset(("deep", "blue")) in pairs
    # Every edge echoes ALL measures so the frontend can re-weight.
    for e in body["edges"]:
        for k in ("mi", "t_score", "log_likelihood", "dice", "log_dice",
                  "chi_square", "delta_p", "fisher", "weight"):
            assert k in e, (e["source"], e["target"], k)
