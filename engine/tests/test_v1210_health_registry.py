"""Pin the v1.2.10 /health/resources registry contract.

/health/resources is the SINGLE asserted registry for the release smoke
gates (ci_smoke_engine.sh/.ps1) and the Docker CI job. These tests lock
the response shape and the dev-layout values so the gates and the endpoint
can never drift apart silently.
"""

from __future__ import annotations

import os
from collections.abc import AsyncIterator

import pytest
from httpx import ASGITransport, AsyncClient

EXPECTED_REFERENCE_CORPORA = {
    "be06_top1000",
    "leipzig_news_top100",
    "ellipse_learner_top1000",
    "pd_persuasive_top1000",
    "camel_arabic_top1000",
    "quranic_arabic_freq",
    "dialectal_tweets_top1000",
}


@pytest.fixture
async def client() -> AsyncIterator[AsyncClient]:
    os.environ["CORPUSMIND_DB_URL"] = "sqlite+aiosqlite:///:memory:"
    os.environ["CORPUSMIND_DATA_DIR"] = "/tmp/cm-test-data"
    from app.main import app
    from storage.session import dispose_db

    async with AsyncClient(
        transport=ASGITransport(app=app), base_url="http://test"
    ) as ac:
        async with app.router.lifespan_context(app):
            yield ac
    await dispose_db()


@pytest.mark.asyncio
async def test_resources_registry_full_payload(client: AsyncClient) -> None:
    """In a dev checkout every bundled resource must report true."""
    r = await client.get("/api/v1/health/resources")
    assert r.status_code == 200
    d = r.json()

    # Bundled contract — asserted by the smoke gates on every platform.
    assert d["usas"] == {"en": True, "ar": True}
    assert d["wordlists"] == {"awl": True, "k1_top200": True}
    assert set(d["reference_corpora"]) == EXPECTED_REFERENCE_CORPORA
    assert all(d["reference_corpora"].values())
    assert d["frameworks"]["count"] >= 12
    assert d["reference_data_dir"] is not None
    assert isinstance(d["reference_data_dir"], str)

    # Report-only keys exist with the right shape (values are
    # environment-dependent and never asserted by gates).
    assert isinstance(d["spacy_model"], dict) and "en_core_web_sm" in d["spacy_model"]
    assert isinstance(d["wordfreq"], dict) and "installed" in d["wordfreq"]
    assert isinstance(d["sentiment"], dict) and "nrc_configured" in d["sentiment"]


@pytest.mark.asyncio
async def test_resources_registry_report_only_keys_are_honest(
    client: AsyncClient,
) -> None:
    """User-supplied resources must be honest flags, never fake trues."""
    d = (await client.get("/api/v1/health/resources")).json()
    # NRC EmoLex is license-restricted and never bundled: the report only
    # says whether the operator configured it, never that it "shipped".
    assert isinstance(d["sentiment"]["nrc_configured"], bool)
