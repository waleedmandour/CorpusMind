"""v1.2.8 (review #5) — functional audit of the grammar pattern detectors.

Review finding: the grammar panel shipped with three light tests (passive,
modal, negation) and no guard against a *silent no-op* — a detector that
always returns zero because its dependency label never matches the model's
output. This suite runs one crafted case per rule category through the REAL
annotation pipeline (spaCy en_core_web_sm parses, not fixtures), asserts
every detector fires on a sentence containing all six patterns, checks
negative controls, and pins the example-field contract the web UI renders
(GrammarPanel reads verb/modal/negator/head/modifiers/evidence_id).
"""
from __future__ import annotations

import io
import os

import pytest
from httpx import ASGITransport, AsyncClient

os.environ["CORPUSMIND_DB_URL"] = "sqlite+aiosqlite:///:memory:"
os.environ["CORPUSMIND_DATA_DIR"] = "/tmp/cm-test-grammar-audit"


@pytest.fixture
async def client():
    from app.settings import get_settings

    get_settings.cache_clear()
    from app.main import app
    from storage.session import dispose_db

    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as ac:
        async with app.router.lifespan_context(app):
            yield ac
    await dispose_db()


async def _grammar_counts(client: AsyncClient, content: bytes, name: str):
    r = await client.post("/api/v1/projects", json={"name": f"P-{name}", "language": "en"})
    pid = r.json()["id"]
    r = await client.post(f"/api/v1/projects/{pid}/corpora", json={"name": name, "language": "en"})
    cid = r.json()["id"]
    await client.post(
        f"/api/v1/corpora/{cid}/documents",
        files={"files": ("audit.txt", io.BytesIO(content), "text/plain")},
    )
    r = await client.post(
        f"/api/v1/corpora/{cid}/grammar",
        json={"patterns": ["passive_voice", "modal", "negation", "relative_clause", "complex_np", "tense"], "limit": 50},
    )
    assert r.status_code == 200, r.text
    return r.json()


# --------------------------------------------------------------------------- #
# One crafted case per rule category (6 of 6)
# --------------------------------------------------------------------------- #


async def test_audit_passive_voice(client):
    data = await _grammar_counts(client, b"The manuscript was reviewed by two editors.", "G1")
    assert data["counts"]["passive_voice"] >= 1, data["counts"]
    ex = data["patterns"]["passive_voice"][0]
    assert ex["verb"] == "reviewed"
    assert ex["aux"].lower() in ("was", "were", "is", "are", "been", "be", "get", "got")
    assert ex["evidence_id"]


async def test_audit_modal(client):
    data = await _grammar_counts(client, b"Researchers must document their methods.", "G2")
    assert data["counts"]["modal"] >= 1, data["counts"]
    ex = data["patterns"]["modal"][0]
    assert ex["modal"].lower() == "must"
    assert ex["verb_lemma"] == "document"
    assert ex["evidence_id"]


async def test_audit_negation(client):
    data = await _grammar_counts(client, b"The results did not replicate.", "G3")
    assert data["counts"]["negation"] >= 1, data["counts"]
    ex = data["patterns"]["negation"][0]
    assert ex["negator"].lower() in ("not", "n't", "never")
    assert ex["evidence_id"]


async def test_audit_relative_clause(client):
    data = await _grammar_counts(client, b"The tool that linguists prefer is free.", "G4")
    assert data["counts"]["relative_clause"] >= 1, data["counts"]
    ex = data["patterns"]["relative_clause"][0]
    assert ex["evidence_id"]
    assert "pattern" in ex


async def test_audit_complex_np(client):
    data = await _grammar_counts(
        client, b"The new environmental policy affects everyone.", "G5"
    )
    assert data["counts"]["complex_np"] >= 1, data["counts"]
    ex = data["patterns"]["complex_np"][0]
    assert ex["head"].lower() == "policy"
    mods = {m.lower() for m in ex["modifiers"]}
    assert {"new", "environmental"} <= mods
    assert ex["evidence_id"]


async def test_audit_tense(client):
    data = await _grammar_counts(client, b"The dog barked loudly. She walks to work every day.", "G6")
    assert data["counts"]["tense"] >= 2, data["counts"]
    tenses = {ex["pattern"] for ex in data["patterns"]["tense"]}
    assert "tense_past" in tenses
    assert "tense_present" in tenses


# --------------------------------------------------------------------------- #
# Anti-no-op meta-test: one rich sentence must fire ALL six detectors
# --------------------------------------------------------------------------- #


async def test_audit_no_silent_noop_all_patterns_fire(client):
    """If any detector returns zero on a sentence engineered to contain it,
    the detector is a silent no-op (wrong label set for the model) — fail."""
    content = (
        b"The manuscript was reviewed by two editors, and the authors must revise it. "
        b"The results did not replicate. "
        b"The tool that linguists prefer is free. "
        b"The new environmental policy failed. "
        b"The committee announced the decision yesterday."
    )
    data = await _grammar_counts(client, content, "G7")
    for pattern in ("passive_voice", "modal", "negation", "relative_clause", "complex_np", "tense"):
        assert data["counts"][pattern] >= 1, (
            f"silent no-op: detector {pattern!r} fired 0 times on a sentence containing it: {data['counts']}"
        )


# --------------------------------------------------------------------------- #
# Negative controls: a plain sentence must NOT fire the absent patterns
# --------------------------------------------------------------------------- #


async def test_audit_negative_controls(client):
    data = await _grammar_counts(client, b"The cat sleeps.", "G8")
    assert data["counts"]["passive_voice"] == 0
    assert data["counts"]["modal"] == 0
    assert data["counts"]["negation"] == 0
    assert data["counts"]["relative_clause"] == 0
    assert data["counts"]["complex_np"] == 0


# --------------------------------------------------------------------------- #
# UI contract: GrammarPanel renders exactly these fields from the response
# --------------------------------------------------------------------------- #


async def test_audit_example_fields_match_ui_contract(client):
    """GrammarPanel (AnalysisView.tsx) renders: evidence_id, verb, modal,
    negator, head + modifiers. Every pattern's examples must therefore carry
    the fields its renderer reads, and counts must not silently truncate."""
    content = (
        b"The manuscript was reviewed by two editors. The authors must revise it. "
        b"The results did not replicate. The tool that linguists prefer is free. "
        b"The new environmental policy failed."
    )
    data = await _grammar_counts(client, content, "G9")
    required = {
        "passive_voice": {"verb", "aux"},
        "modal": {"modal", "verb"},
        "negation": {"negator"},
        "relative_clause": {"marker"},
        "complex_np": {"head", "modifiers"},
        "tense": {"verb", "lemma"},
    }
    for pattern, fields in required.items():
        for ex in data["patterns"][pattern]:
            missing = fields - set(ex.keys())
            assert not missing, f"{pattern}: UI-rendered fields missing {missing}"
            assert ex["pattern"]
            assert ex["doc"]
            assert ex["evidence_id"].count(":") == 2
    # counts consistency at limit=50: nothing truncated, nothing fabricated
    for pattern, examples in data["patterns"].items():
        if data["counts"][pattern] <= 50:
            assert len(examples) == data["counts"][pattern]
