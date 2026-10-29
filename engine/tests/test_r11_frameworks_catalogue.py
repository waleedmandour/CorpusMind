"""r11 — the theoretical-frameworks catalogue is research-grounded AND visible.

Field report (v1.2.14-10): the 12 YAML framework lenses shipped with only
{name, full_name, version, family, categories} and the /api/v1/frameworks
catalogue had NO consumer in the UI — so the CDA frameworks (Fairclough,
van Dijk, Wodak) were effectively invisible in the Discourse window, even
though the assistant system prompt and the visual-corpus CDA routes apply
them at the interpretive layer.

Fix (two halves, both pinned here and in the web test):
  1. Every framework YAML now carries research-grounding metadata:
     `description` (scholarly definition), `core_concepts`,
     `references` (canonical citations). The catalogue endpoint serves
     them additively.
  2. The web Discourse panel renders the catalogue (CDA family first),
     so the frameworks are finally visible where analysts look for them.

Engine-side pins: the catalogue lists all 12 lenses; the classic CDA trio
plus Machin & Mayr MCDA are present with their canonical citations; every
framework carries non-empty research metadata; and the existing catalogue
contract (kress-van-leeuwen categories) still holds.
"""

from __future__ import annotations

import os
import shutil
import tempfile
from collections.abc import AsyncIterator
from pathlib import Path

import pytest
from httpx import ASGITransport, AsyncClient

os.environ["CORPUSMIND_DB_URL"] = "sqlite+aiosqlite:///file::memory:?cache=shared&uri=true"
os.environ["CORPUSMIND_DATA_DIR"] = tempfile.mkdtemp(prefix="cm-test-r11-fw-")
from app.settings import get_settings  # env must be set before import

get_settings.cache_clear()


@pytest.fixture
async def client() -> AsyncIterator[AsyncClient]:
    from app.main import app
    from storage.session import dispose_db

    get_settings.cache_clear()
    await dispose_db()
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as ac:
        async with app.router.lifespan_context(app):
            yield ac
    await dispose_db()


def _teardown_function() -> None:
    data_dir = os.environ["CORPUSMIND_DATA_DIR"]
    shutil.rmtree(data_dir, ignore_errors=True)
    os.environ["CORPUSMIND_DATA_DIR"] = tempfile.mkdtemp(prefix="cm-test-r11-fw-")


# --------------------------------------------------------------------------- #
# YAML source-of-truth pins (no HTTP needed)
# --------------------------------------------------------------------------- #


def _repo_frameworks_dir() -> Path:
    # engine/tests/x.py -> repo root
    return Path(__file__).resolve().parent.parent.parent / "reference-data" / "frameworks"


def test_twelve_yaml_lenses_with_research_metadata() -> None:
    yaml = pytest.importorskip("yaml")
    d = _repo_frameworks_dir()
    files = sorted(d.glob("*.yaml"))
    assert len(files) == 12, f"expected 12 lens templates, found {len(files)}"
    for f in files:
        data = yaml.safe_load(f.read_text(encoding="utf-8")) or {}
        stem = f.stem
        # r11 research grounding: each lens defines itself out of its own literature.
        assert str(data.get("description", "")).strip(), f"{stem}: missing description"
        assert data.get("core_concepts"), f"{stem}: missing core_concepts"
        assert data.get("references"), f"{stem}: missing references"
        assert data.get("framework_family"), f"{stem}: missing framework_family"


def test_cda_family_keys_and_canonical_citations() -> None:
    yaml = pytest.importorskip("yaml")
    d = _repo_frameworks_dir()
    data = {f.stem: yaml.safe_load(f.read_text(encoding="utf-8")) for f in d.glob("*.yaml")}

    # The classic CDA trio the analyst expects to find, by name.
    trio = {
        "fairclough-cda": "Fairclough",
        "van-dijk-sca": "van Dijk",
        "wodak-dha": "Wodak",
    }
    for key, author in trio.items():
        fw = data[key]
        assert author in fw["full_name"], f"{key}: full_name must cite {author}"
        assert fw["framework_family"] == "cda", f"{key}: expected cda family"
        refs = " ".join(fw["references"])
        # Canonical sources: Fairclough 1989/1995, van Dijk 1998/2008,
        # Wodak (Reisigl & Wodak 2001 / Wodak & Meyer 2001/2009).
        if key == "fairclough-cda":
            assert "1989" in refs and "1995" in refs
        elif key == "van-dijk-sca":
            assert "1998" in refs and "2008" in refs
        else:
            assert "Reisigl" in refs and "2001" in refs

    # The 4th critical lens: Machin & Mayr's multimodal CDA (family mcda).
    mm = data["machin-mayr-mcda"]
    assert mm["framework_family"] == "mcda"
    assert "Machin" in mm["full_name"] and "2012" in " ".join(mm["references"])


# --------------------------------------------------------------------------- #
# Endpoint contract (additive fields served to the UI)
# --------------------------------------------------------------------------- #


@pytest.mark.asyncio
async def test_frameworks_endpoint_serves_research_metadata(client: AsyncClient) -> None:
    r = await client.get("/api/v1/frameworks")
    assert r.status_code == 200, r.text
    data = r.json()
    fws = data["frameworks"]
    assert len(fws) >= 12
    by_key = {f["key"]: f for f in fws}

    # The catalogue is the single source of truth the Discourse panel renders.
    for key in ("fairclough-cda", "van-dijk-sca", "wodak-dha", "machin-mayr-mcda"):
        fw = by_key[key]
        assert fw["description"].strip(), f"{key}: endpoint must serve description"
        assert fw["core_concepts"], f"{key}: endpoint must serve core_concepts"
        assert fw["references"], f"{key}: endpoint must serve references"

    # Research grounding actually names the literature, not placeholders.
    fairclough = by_key["fairclough-cda"]
    assert "1989" in " ".join(fairclough["references"])
    assert "description" in fairclough["description"].lower() or "three-dimensional" in fairclough["description"].lower()

    # Existing contract from the v1.2.0 Lens round still holds.
    kv = by_key["kress-van-leeuwen"]
    assert kv["full_name"].startswith("Kress")
    assert {c["id"] for c in kv["categories"]} >= {"representational", "interactive", "compositional"}
