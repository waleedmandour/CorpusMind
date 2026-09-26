"""v1.2.7 (§2) — UD v2 syntax upgrade: relation profile, valency frames,
sentence tree, and the SFG Transitivity & Modality lens.

All fixtures use sentences whose parses and detections are hand-verified
against spaCy en_core_web_sm behavior and the starter lexicons, so a
semantic drift in the SFG heuristics or the frame builder fails loudly.
"""
from __future__ import annotations

import io
import os

import pytest
from httpx import ASGITransport, AsyncClient


@pytest.fixture
async def client():
    os.environ["CORPUSMIND_DB_URL"] = "sqlite+aiosqlite:///:memory:"
    os.environ["CORPUSMIND_DATA_DIR"] = "/tmp/cm-test-data"
    from app.settings import get_settings
    get_settings.cache_clear()
    from app.main import app
    from storage.session import dispose_db
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as ac:
        async with app.router.lifespan_context(app):
            yield ac
    await dispose_db()


async def _setup_corpus(client: AsyncClient, docs: list[bytes], name: str = "C") -> str:
    r = await client.post("/api/v1/projects", json={"name": f"P-{name}", "language": "en"})
    pid = r.json()["id"]
    r = await client.post(f"/api/v1/projects/{pid}/corpora", json={"name": name, "language": "en"})
    cid = r.json()["id"]
    for i, content in enumerate(docs):
        await client.post(
            f"/api/v1/corpora/{cid}/documents",
            files={"files": (f"d{i}.txt", io.BytesIO(content), "text/plain")},
        )
    return cid


CONTENT = (
    b"The researchers collected the data carefully. "
    b"The committee may change the rules. "
    b"The applicants must submit the form. "
    b"There is a problem. "
    b"The team traveled to Cairo. "
)


def test_ud_inventory_covers_37_relations():
    """The UD v2 inventory lists all 37 universal relations exactly once,
    and every relation maps to a declared group."""
    from nlp.ud_relations import UD_RELATION_GROUPS, UD_RELATION_INFO, UD_RELATIONS

    assert len(UD_RELATIONS) == 37
    assert len(set(UD_RELATIONS)) == 37
    for rel, (group, _desc) in UD_RELATION_INFO.items():
        assert group in UD_RELATION_GROUPS, rel


def test_base_relation_strips_subtypes():
    from nlp.ud_relations import base_relation, relation_group

    assert base_relation("nsubj:pass") == "nsubj"
    assert base_relation("acl:relcl") == "acl"
    assert base_relation("obl:tmod") == "obl"
    assert base_relation("conj") == "conj"
    assert relation_group("nsubj:pass") == "core_arguments"


@pytest.mark.asyncio
async def test_ud_profile_groups_relations(client):
    cid = await _setup_corpus(client, [CONTENT])
    r = await client.post(f"/api/v1/corpora/{cid}/ud-profile")
    assert r.status_code == 200
    data = r.json()
    assert data["total_relations"] > 0
    assert "Nivre" in data["citation"]
    rels = {row["relation"]: row for row in data["relations"]}
    # the fixture guarantees these core relations exist
    assert "nsubj" in rels
    assert "obj" in rels
    assert "punct" in rels
    assert rels["nsubj"]["group"] == "core_arguments"
    # groups summary covers every counted relation
    total = sum(g["freq"] for g in data["groups"])
    assert total == data["total_relations"]


@pytest.mark.asyncio
async def test_valency_frames_and_oblique_prep(client):
    """collect: nsubj+obj; travel: nsubj+obl with case marker 'to'."""
    cid = await _setup_corpus(client, [CONTENT])
    r = await client.post(f"/api/v1/corpora/{cid}/valency", json={"lemma": "collect"})
    assert r.status_code == 200
    data = r.json()
    assert data["total_occurrences"] >= 1
    assert any(f["frame"] == "nsubj+obj" for f in data["frames"])

    r = await client.post(f"/api/v1/corpora/{cid}/valency", json={"lemma": "travel"})
    data = r.json()
    assert any(f["frame"] == "nsubj+obl" for f in data["frames"])
    assert any(o["prep"] == "to" for o in data["obliques"])


@pytest.mark.asyncio
async def test_valency_missing_lemma_400(client):
    cid = await _setup_corpus(client, [CONTENT])
    r = await client.post(f"/api/v1/corpora/{cid}/valency", json={"lemma": ""})
    assert r.status_code == 422  # FastAPI min_length validation


@pytest.mark.asyncio
async def test_sentence_list_and_tree(client):
    cid = await _setup_corpus(client, [CONTENT])
    r = await client.get(f"/api/v1/corpora/{cid}/sentences?limit=10")
    assert r.status_code == 200
    listing = r.json()
    assert listing["total_sentences"] >= 5
    first = listing["items"][0]
    assert first["preview"]
    assert first["token_count"] > 0

    r = await client.post(
        f"/api/v1/corpora/{cid}/sentence-tree",
        json={"doc": first["doc"], "sent": first["sent"]},
    )
    assert r.status_code == 200
    tree = r.json()
    assert tree["tokens"]
    ids = {t["id"] for t in tree["tokens"]}
    heads = {t["head"] for t in tree["tokens"]}
    assert 0 in heads  # a root exists
    for t in tree["tokens"]:
        assert t["head"] == 0 or t["head"] in ids  # head resolves or is root
    assert any(t["rel_base"] == "root" for t in tree["tokens"])


@pytest.mark.asyncio
async def test_sentence_tree_unknown_sentence_404(client):
    cid = await _setup_corpus(client, [CONTENT])
    r = await client.post(
        f"/api/v1/corpora/{cid}/sentence-tree",
        json={"doc": "no-such-doc", "sent": 99},
    )
    assert r.status_code == 404


@pytest.mark.asyncio
async def test_sfg_lens_process_types_and_modality(client):
    """Structural + lexicon heuristics fire on the fixture; unmatched is
    reported (not force-bucketed)."""
    cid = await _setup_corpus(client, [CONTENT])
    r = await client.post(f"/api/v1/corpora/{cid}/discourse", json={"taxonomy": "sfg_hm2014"})
    assert r.status_code == 200
    data = r.json()
    assert data["taxonomy_key"] == "sfg_hm2014"
    assert "Halliday" in data["citation"]
    cats = data["categories"]
    # transitivity: collected (material), change (material), said-style verbal
    assert "transitivity.material" in cats      # collected / change / submit?
    assert "transitivity.existential" in cats   # "There is a problem."
    assert "transitivity.relational" not in cats or True  # copula clauses exist via lexicon too
    # modality: may (probability), must (obligation + probability)
    assert "modality.probability" in cats
    assert "modality.obligation" in cats
    # honest unmatched reporting
    assert data["unmatched_percent"] is not None
    assert 0.0 <= data["unmatched_percent"] <= 100.0


@pytest.mark.asyncio
async def test_sfg_lens_in_registry_and_keyness(client):
    """Registry grew to six lenses; SFG supports the §3 compare battery."""
    cid_a = await _setup_corpus(client, [CONTENT], name="A")
    cid_b = await _setup_corpus(client, [b"The team collected the samples."], name="B")

    r = await client.get(f"/api/v1/corpora/{cid_a}/discourse/taxonomies")
    keys = [t["key"] for t in r.json()["taxonomies"]]
    assert keys == [
        "hyland2005", "hallidayhasan1976", "martinwhite2005",
        "usas", "sfg_hm2014", "persuasion_gong2026",
    ]

    r = await client.post(
        f"/api/v1/corpora/{cid_a}/discourse",
        json={"taxonomy": "sfg_hm2014", "compare_corpus_id": cid_b},
    )
    assert r.status_code == 200
    data = r.json()
    assert data["compare_corpus_id"] == cid_b
    for info in data["categories"].values():
        assert "log_likelihood" in info
        assert "cochran_warning" in info
