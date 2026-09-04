"""Regression tests for post-v1.0.0 Priority-0 Issues 5 & 6.

Issue 5: the chat contract never delivered the persisted assistant turn's DB
id, so the frontend's Accept/Reject/Edit verification buttons could never
render and /research/verify-turn was unreachable end-to-end.

Issue 6: /images/{id}/analysis and /image-sets/{id}/batch-analysis served the
RAW cached VLM descriptions verbatim (only /describe filtered), so the §18
consent gate could be bypassed by any client that could reach the API.
"""
from __future__ import annotations

import io

import pytest
from httpx import ASGITransport, AsyncClient

from tests.test_vision_describe import _inject_mock_provider, _setup_corpus_with_image

RAW_PERSON_DESCRIPTION = "A smiling woman in a red dress stands by the door."


@pytest.fixture
async def client():
    """Spawn the FastAPI app with a fresh in-memory DB per test."""
    import os
    os.environ["CORPUSMIND_DB_URL"] = "sqlite+aiosqlite:///:memory:"
    os.environ["CORPUSMIND_DATA_DIR"] = "/tmp/cm-test-data"

    from app.settings import get_settings
    get_settings.cache_clear()
    from storage.session import _engine, dispose_db
    _engine.clear() if hasattr(_engine, "clear") else None

    from app.main import app
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as ac:
        async with app.router.lifespan_context(app):
            yield ac
    await dispose_db()


# --------------------------------------------------------------------------- #
# Issue 6 — consent gate holds on every read path, not just /describe
# --------------------------------------------------------------------------- #


async def _cache_raw_description(client, img_id: str) -> None:
    """Run /describe once with a mock provider so the RAW description is
    stored in img.analysis['vision_llm'] (the cache holds unfiltered output)."""
    _inject_mock_provider(client, chat_content=RAW_PERSON_DESCRIPTION)
    r = await client.post(f"/api/v1/images/{img_id}/describe")
    assert r.status_code == 200, r.text
    data = r.json()
    # Sanity: the describe route itself must have been filtered (gate closed)
    assert "woman" not in data["description"]
    assert "person-descriptive" in data["description"]


@pytest.mark.asyncio
async def test_issue6_analysis_read_redacts_cached_descriptions(client):
    img_id, _iset = await _setup_corpus_with_image(client)
    await _cache_raw_description(client, img_id)

    r = await client.get(f"/api/v1/images/{img_id}/analysis")
    assert r.status_code == 200, r.text
    analysis = r.json()["analysis"]
    vlm = (analysis or {}).get("vision_llm", {})
    assert vlm, "test setup failed — no cached vision_llm"
    for cached in vlm.values():
        desc = cached.get("description", "")
        assert "woman" not in desc
        assert "smiling" not in desc
        assert "person-descriptive" in desc  # redaction marker present


@pytest.mark.asyncio
async def test_issue6_batch_analysis_redacts_cached_descriptions(client):
    img_id, iset_id = await _setup_corpus_with_image(client)
    await _cache_raw_description(client, img_id)

    r = await client.get(f"/api/v1/image-sets/{iset_id}/batch-analysis")
    assert r.status_code == 200, r.text
    descriptions = r.json().get("descriptions", [])
    assert descriptions, "test setup failed — no descriptions in batch view"
    for d in descriptions:
        assert "woman" not in d["description"]
        assert "person-descriptive" in d["description"]


@pytest.mark.asyncio
async def test_issue6_discourse_claims_summary_is_filtered(client):
    """filter_discourse_claims' docstring always claimed `summary` is filtered
    independently — the code only filtered `claim`. Pin the fixed behavior."""
    from vision.consent_gate import filter_discourse_claims

    claims = [{
        "framework": "representation",
        "category": "social_semiotics",
        "claim": "The image foregrounds institutional power structures.",
        "summary": "A smiling woman gazes at the viewer, inviting identification.",
    }]
    out = filter_discourse_claims(claims)
    assert out["person_descriptive_redacted"] is True
    fixed = out["claims"][0]
    assert "woman" not in fixed["claim"] or "person-descriptive" in fixed["claim"]
    assert "woman" not in fixed["summary"]
    assert "person-descriptive" in fixed["summary"]


# --------------------------------------------------------------------------- #
# Issue 5 — turn_id flows through the chat contract
# --------------------------------------------------------------------------- #


@pytest.mark.asyncio
async def test_issue5_chatresponse_schema_carries_turn_id(client):
    from ai.assistant import AssistantTurn
    from api.ai import ChatResponse

    assert "turn_id" in ChatResponse.model_fields
    assert "turn_id" in AssistantTurn.__dataclass_fields__


@pytest.mark.asyncio
async def test_issue5_chat_returns_persisted_turn_id(client):
    """End-to-end: POST /ai/chat with a mocked provider → response carries the
    DB id of the persisted assistant turn, and GET /ai/conversations/{id}
    shows the same turn row."""
    img_id, _ = await _setup_corpus_with_image(client)  # corpus for context
    mock = _inject_mock_provider(client, provider_name="ollama", chat_content="Grounded answer.")

    r = await client.post("/api/v1/ai/chat", json={
        "message": "What is in the corpus?",
        "provider": "ollama",
        "model": "moondream",
    })
    assert r.status_code == 200, r.text
    data = r.json()
    assert data["content"] == "Grounded answer."
    # THE fix: turn_id must be present and be the persisted row id
    assert data["turn_id"] is not None
    assert isinstance(data["turn_id"], int)

    # The id must match a real persisted assistant turn
    r2 = await client.get(f"/api/v1/ai/conversations/{data['conversation_id']}")
    assert r2.status_code == 200, r2.text
    turns = r2.json()["turns"]
    assistant_turns = [t for t in turns if t["role"] == "assistant"]
    assert any(t.get("id") == data["turn_id"] for t in assistant_turns), (
        "turn_id from /ai/chat does not match any persisted assistant turn"
    )
