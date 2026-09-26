"""v1.2.7 (§3) — Discourse statistics DataTable: dispersion + keyness wiring.

Every value asserted here is hand-computed against the measures library
formulas on a deterministic fixture, so a silent change in detection
semantics or a formula regression fails loudly:

  corpus A (2 documents)             corpus B (1 document)
    d1: "However, the results were clear."    "Perhaps the weather was bad."
    d2: "However, the data differ clearly."

Non-punct token counts: A = 5 + 5 = 10, B = 5.

Hyland lens on A:  transitions/however freq 2 (per_million 200000);
                   boosters/clearly   freq 1, only in d2.
DP (Gries, size-weighted, sizes [5,5] → expected 0.5 each):
    however  observed [1,1]  → DP = 0.0
    clearly  observed [0,1]  → DP = 0.5
Keyness A vs B for however: f1=2 N1=10 f2=1 N2=5 → the 2x2 table has a
perfectly uniform expected matrix (E = 2/8/1/4), so LL = 0.0 exactly,
Log Ratio = log2((2/10)/(1/5)) = 0.0 exactly, and the smallest expected
cell is 1 < 5 → Cochran warning MUST fire.
hedges/perhaps: freq 0 in A, 1 in B → union row with freq 0, Log Ratio
None (undefined, JSON null), Cochran warning True, LL > 0.
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


async def _setup_corpus(
    client: AsyncClient,
    docs: list[bytes],
    name: str = "C",
    language: str = "en",
) -> str:
    """Create project + corpus + upload documents. Returns corpus_id."""
    r = await client.post("/api/v1/projects", json={"name": f"P-{name}", "language": language})
    pid = r.json()["id"]
    r = await client.post(f"/api/v1/projects/{pid}/corpora", json={"name": name, "language": language})
    cid = r.json()["id"]
    for i, content in enumerate(docs):
        await client.post(
            f"/api/v1/corpora/{cid}/documents",
            files={"files": (f"doc{i}.txt", io.BytesIO(content), "text/plain")},
        )
    return cid


DOC_A1 = b"However, the results were clear."
DOC_A2 = b"However, the data differ clearly."
# B contains "however" (also in A) → however's 2x2 table has a perfectly
# uniform expected matrix (E = 2/8/1/4), so LL = 0.0 exactly, Log Ratio =
# log2((2/10)/(1/5)) = 0.0 exactly, and the smallest expected cell is 1 < 5
# → Cochran warning MUST fire.
DOC_B1 = b"However, the weather was bad."
# C contains "perhaps" (hedges) which A lacks → union row with freq 0,
# Log Ratio None (undefined, JSON null), Cochran warning True.
DOC_C1 = b"Perhaps the weather was bad."


@pytest.mark.asyncio
async def test_discourse_dp_dispersion(client):
    """Gries' DP is size-weighted across documents and deterministic."""
    cid = await _setup_corpus(client, [DOC_A1, DOC_A2])
    r = await client.post(f"/api/v1/corpora/{cid}/discourse", json={"taxonomy": "hyland2005"})
    assert r.status_code == 200
    cats = r.json()["categories"]
    assert cats["interactive.transitions"]["freq"] == 2
    assert cats["interactive.transitions"]["per_million"] == 200000.0
    assert cats["interactive.transitions"]["dp"] == 0.0  # even: [1,1] over [5,5]
    assert cats["interactional.boosters"]["freq"] == 1
    assert cats["interactional.boosters"]["dp"] == 0.5  # concentrated: [0,1]


@pytest.mark.asyncio
async def test_discourse_keyness_against_compare_corpus(client):
    """Per-category keyness battery against a second corpus (§3)."""
    cid_a = await _setup_corpus(client, [DOC_A1, DOC_A2], name="A")
    cid_b = await _setup_corpus(client, [DOC_B1], name="B")
    r = await client.post(
        f"/api/v1/corpora/{cid_a}/discourse",
        json={"taxonomy": "hyland2005", "compare_corpus_id": cid_b},
    )
    assert r.status_code == 200
    data = r.json()
    assert data["compare_corpus_id"] == cid_b
    assert data["compare_total_tokens"] == 5
    cats = data["categories"]

    however = cats["interactive.transitions"]
    # uniform expected table → LL exactly 0; effect size exactly 0
    assert however["log_likelihood"] == 0.0
    assert however["log_ratio"] == 0.0
    assert however["pct_diff"] == 0.0
    assert however["simple_maths"] == 1.0
    # smallest expected cell = 1 < 5 → Cochran low-power warning
    assert however["cochran_warning"] is True

    # "clearly" present in A (1/10), absent from B → Log Ratio undefined
    boosters = cats["interactional.boosters"]
    assert boosters["freq"] == 1
    assert boosters["log_ratio"] is None
    assert boosters["pct_diff"] is None
    assert boosters["log_likelihood"] == 0.85  # pin: keyness_ll(1, 0, 10, 5)
    assert boosters["cochran_warning"] is True

    # B has no "perhaps" → no freq-0 union row when comparing with B
    assert "interactional.hedges" not in cats


@pytest.mark.asyncio
async def test_discourse_keyness_union_row_freq_zero(client):
    """Compare corpus contains a category the target lacks → freq-0 row."""
    cid_a = await _setup_corpus(client, [DOC_A1, DOC_A2], name="A")
    cid_c = await _setup_corpus(client, [DOC_C1], name="C")
    r = await client.post(
        f"/api/v1/corpora/{cid_a}/discourse",
        json={"taxonomy": "hyland2005", "compare_corpus_id": cid_c},
    )
    assert r.status_code == 200
    data = r.json()
    assert data["compare_total_tokens"] == 5
    hedges = data["categories"]["interactional.hedges"]
    assert hedges["freq"] == 0
    assert hedges["log_ratio"] is None  # undefined — JSON null, not ±inf
    assert hedges["pct_diff"] is None
    assert hedges["log_likelihood"] == 2.34  # pin: keyness_ll(0, 1, 10, 5)
    assert hedges["cochran_warning"] is True


@pytest.mark.asyncio
async def test_discourse_backward_compat_without_compare(client):
    """No compare_corpus_id → v1.2.6 response shape (no keyness keys)."""
    cid = await _setup_corpus(client, [DOC_A1, DOC_A2])
    r = await client.post(f"/api/v1/corpora/{cid}/discourse", json={"taxonomy": "hyland2005"})
    data = r.json()
    assert data["compare_corpus_id"] is None
    assert data["compare_total_tokens"] is None
    for info in data["categories"].values():
        assert "dp" in info
        assert "log_likelihood" not in info
        assert "cochran_warning" not in info


@pytest.mark.asyncio
async def test_discourse_compare_unknown_corpus_404(client):
    cid = await _setup_corpus(client, [DOC_A1])
    r = await client.post(
        f"/api/v1/corpora/{cid}/discourse",
        json={"taxonomy": "hyland2005", "compare_corpus_id": "does-not-exist"},
    )
    assert r.status_code == 404


@pytest.mark.asyncio
async def test_discourse_compare_empty_corpus_no_keyness(client):
    """A comparison corpus with no processed version degrades gracefully."""
    cid_a = await _setup_corpus(client, [DOC_A1, DOC_A2], name="A")
    cid_c = await _setup_corpus(client, [], name="C")
    r = await client.post(
        f"/api/v1/corpora/{cid_a}/discourse",
        json={"taxonomy": "hyland2005", "compare_corpus_id": cid_c},
    )
    assert r.status_code == 200
    data = r.json()
    assert data["compare_corpus_id"] is None
    assert data["compare_total_tokens"] is None
    for info in data["categories"].values():
        assert "log_likelihood" not in info


@pytest.mark.asyncio
async def test_discourse_usas_dp_and_compare(client):
    """The USAS lens carries the same dp + keyness wiring."""
    cid_a = await _setup_corpus(client, [DOC_A1, DOC_A2], name="A")
    cid_b = await _setup_corpus(client, [DOC_B1], name="B")
    r = await client.post(
        f"/api/v1/corpora/{cid_a}/discourse",
        json={"taxonomy": "usas", "compare_corpus_id": cid_b},
    )
    assert r.status_code == 200
    data = r.json()
    assert data["taxonomy_key"] == "usas"
    cats = data["categories"]
    assert len(cats) > 0
    for info in cats.values():
        assert "dp" in info
        assert "log_likelihood" in info
        assert "cochran_warning" in info


@pytest.mark.asyncio
async def test_discourse_halliday_dp_includes_lexical_repetition(client):
    """lexical.repetition (computed, not cue-listed) also gets a DP value."""
    cid = await _setup_corpus(
        client,
        [b"The researchers collected the data. The researchers repeated it."],
    )
    r = await client.post(f"/api/v1/corpora/{cid}/discourse", json={"taxonomy": "hallidayhasan1976"})
    assert r.status_code == 200
    cats = r.json()["categories"]
    assert "lexical.repetition" in cats
    assert cats["lexical.repetition"]["freq"] >= 1
    assert "dp" in cats["lexical.repetition"]
