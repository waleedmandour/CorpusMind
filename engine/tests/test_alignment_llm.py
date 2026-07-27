"""Tests for the ?mode=llm alignment route (CorpusMind Lens build step 6).

Tests the vision-LM-backed alignment path on POST /images/{img_id}/align.
Uses a mock provider so tests run without any real Ollama instance.

Coverage:
  - LLM mode produces alignments with provenance metadata.
  - Heuristic mode (default) unchanged — backward compat.
  - Fallback: when mode=llm but no provider available, falls back to
    heuristic with fallback_reason.
  - Consent gate: person-descriptive content in region descriptors is
    redacted when the gate is closed.
  - JSON parsing fallback: non-JSON output produces empty alignments,
    not a 500.
"""
from __future__ import annotations

import io
import os
from unittest.mock import AsyncMock, MagicMock

import pytest
from httpx import ASGITransport, AsyncClient

os.environ["CORPUSMIND_DB_URL"] = "sqlite+aiosqlite:///:memory:"
os.environ["CORPUSMIND_DATA_DIR"] = "/tmp/cm-test-align-llm"
os.environ.pop("CORPUSMIND_FACIAL_ANALYSIS_ENABLED", None)
from app.settings import get_settings

get_settings.cache_clear()


@pytest.fixture
async def client():
    from app.main import app
    from storage.session import dispose_db
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as ac:
        async with app.router.lifespan_context(app):
            yield ac
    await dispose_db()


def _make_test_image(width: int = 100, height: int = 100, color: tuple = (220, 50, 50)) -> bytes:
    from PIL import Image
    img = Image.new("RGB", (width, height), color)
    buf = io.BytesIO()
    img.save(buf, format="PNG")
    return buf.getvalue()


async def _setup_corpus_with_image(client: AsyncClient) -> str:
    r = await client.post("/api/v1/projects", json={"name": "T", "language": "en"})
    pid = r.json()["id"]
    r = await client.post(f"/api/v1/projects/{pid}/corpora", json={"name": "C", "language": "en"})
    cid = r.json()["id"]
    r = await client.post(f"/api/v1/corpora/{cid}/image-sets", json={"name": "S"})
    iset_id = r.json()["id"]
    img_bytes = _make_test_image()
    r = await client.post(
        f"/api/v1/image-sets/{iset_id}/images",
        files={"files": ("test.png", io.BytesIO(img_bytes), "image/png")},
    )
    assert r.status_code == 200, r.text
    return r.json()[0]["id"]


def _inject_mock_provider(
    client: AsyncClient,
    provider_name: str = "ollama",
    *,
    health_ok: bool = True,
    chat_content: str = '{"alignments": []}',
    chat_model: str = "moondream",
    raise_on_chat: Exception | None = None,
) -> MagicMock:
    from ai.providers import ChatResponse
    from app.main import app
    registry = app.state.providers
    mock = MagicMock()
    mock.name = provider_name
    mock.default_model = chat_model
    mock.health = AsyncMock(return_value=health_ok)
    if raise_on_chat:
        mock.chat = AsyncMock(side_effect=raise_on_chat)
    else:
        mock.chat = AsyncMock(return_value=ChatResponse(
            content=chat_content,
            model=chat_model,
            provider=provider_name,
            raw={},
        ))
    mock.list_models = AsyncMock(return_value=[chat_model])
    mock.aclose = AsyncMock()
    registry._instances[provider_name] = mock
    return mock


_LLM_ALIGN_RESPONSE = """{
  "alignments": [
    {
      "span_text": "red square",
      "region_descriptor": "the central red area",
      "confidence": 0.8,
      "match_reason": "The text 'red square' refers to the dominant red shape in the centre of the image."
    },
    {
      "span_text": "background",
      "region_descriptor": "the surrounding area",
      "confidence": 0.6,
      "match_reason": "The text 'background' refers to the area around the central shape."
    }
  ]
}"""


# ---------------------------------------------------------------------------
# LLM mode happy path
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_align_llm_mode_produces_alignments(client):
    """LLM mode produces alignments with provenance metadata."""
    img_id = await _setup_corpus_with_image(client)
    mock = _inject_mock_provider(client, chat_content=_LLM_ALIGN_RESPONSE)

    r = await client.post(
        f"/api/v1/images/{img_id}/align?mode=llm&model=moondream",
        json={"text": "A red square on a background."},
    )
    assert r.status_code == 200, r.text
    data = r.json()
    assert data["method"] == "vision-llm"
    assert data["provenance"]["mode"] == "llm"
    assert data["provenance"]["model"] == "moondream"
    assert data["provenance"]["provider"] == "ollama"
    assert len(data["alignments"]) == 2
    assert data["alignments"][0]["span_text"] == "red square"
    assert data["alignments"][0]["region_descriptor"] == "the central red area"
    assert data["alignments"][0]["confidence"] == 0.8
    assert "red square" in data["alignments"][0]["match_reason"]

    # The provider was actually called with image bytes attached.
    mock.chat.assert_called_once()
    messages = mock.chat.call_args.args[0]
    assert len(messages) == 2  # system + user
    assert messages[0].role == "system"
    assert messages[1].role == "user"
    assert len(messages[1].images) == 1  # image bytes attached
    assert isinstance(messages[1].images[0], bytes)
    # The text is included in the user prompt
    assert "red square on a background" in messages[1].content


@pytest.mark.asyncio
async def test_align_llm_mode_includes_consent_gate_field(client):
    """The response includes person_descriptive_redacted (step 5 gate)."""
    img_id = await _setup_corpus_with_image(client)
    _inject_mock_provider(client, chat_content=_LLM_ALIGN_RESPONSE)

    r = await client.post(
        f"/api/v1/images/{img_id}/align?mode=llm&model=moondream",
        json={"text": "A red square."},
    )
    assert r.status_code == 200
    assert "person_descriptive_redacted" in r.json()
    assert r.json()["person_descriptive_redacted"] is False  # no person content


# ---------------------------------------------------------------------------
# Backward compat: heuristic mode unchanged
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_align_heuristic_mode_default(client):
    """Calling /align without ?mode= runs the heuristic path — backward
    compat for existing callers."""
    img_id = await _setup_corpus_with_image(client)

    r = await client.post(
        f"/api/v1/images/{img_id}/align",
        json={"text": "A red square on a blue background."},
    )
    assert r.status_code == 200
    data = r.json()
    assert data["method"] == "heuristic-colour-positional"
    assert data["provenance"]["mode"] == "heuristic"
    assert "fallback_reason" not in data
    # Heuristic mode produces regions + spans
    assert len(data["regions"]) > 0
    assert len(data["spans"]) > 0


@pytest.mark.asyncio
async def test_align_heuristic_mode_explicit(client):
    """?mode=heuristic explicitly runs the heuristic path even if a
    provider is available."""
    img_id = await _setup_corpus_with_image(client)
    _inject_mock_provider(client, chat_content='{"alignments": []}')

    r = await client.post(
        f"/api/v1/images/{img_id}/align?mode=heuristic",
        json={"text": "A red square."},
    )
    assert r.status_code == 200
    data = r.json()
    assert data["provenance"]["mode"] == "heuristic"


# ---------------------------------------------------------------------------
# Fallback
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_align_llm_falls_back_when_provider_unhealthy(client):
    """When mode=llm but provider is unhealthy, falls back to heuristic
    with fallback_reason — never an error."""
    img_id = await _setup_corpus_with_image(client)
    _inject_mock_provider(client, health_ok=False)

    r = await client.post(
        f"/api/v1/images/{img_id}/align?mode=llm",
        json={"text": "A red square."},
    )
    assert r.status_code == 200
    data = r.json()
    assert data["provenance"]["mode"] == "heuristic"
    assert "fallback_reason" in data
    assert "LLM" in data["fallback_reason"]


@pytest.mark.asyncio
async def test_align_llm_falls_back_when_provider_call_fails(client):
    """When the provider call itself fails, fall back to heuristic."""
    from ai.providers import ModelProviderError
    img_id = await _setup_corpus_with_image(client)
    _inject_mock_provider(client, raise_on_chat=ModelProviderError("model crashed"))

    r = await client.post(
        f"/api/v1/images/{img_id}/align?mode=llm",
        json={"text": "A red square."},
    )
    assert r.status_code == 200
    data = r.json()
    assert data["provenance"]["mode"] == "heuristic"
    assert "fallback_reason" in data


# ---------------------------------------------------------------------------
# Consent gate
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_align_llm_redacts_person_descriptive(client, monkeypatch):
    """When the gate is closed and the vision-LM's region descriptor
    contains person-descriptive content, it's redacted."""
    monkeypatch.delenv("CORPUSMIND_FACIAL_ANALYSIS_ENABLED", raising=False)
    img_id = await _setup_corpus_with_image(client)
    _inject_mock_provider(
        client,
        chat_content='{"alignments": [{"span_text": "the person", "region_descriptor": "a young woman smiling", "confidence": 0.7, "match_reason": "The woman is the central subject."}]}',
    )

    r = await client.post(
        f"/api/v1/images/{img_id}/align?mode=llm&model=moondream",
        json={"text": "The person is central."},
    )
    assert r.status_code == 200
    data = r.json()
    assert data["person_descriptive_redacted"] is True
    desc = data["alignments"][0]["region_descriptor"].lower()
    assert "young woman" not in desc
    assert "redacted" in desc


@pytest.mark.asyncio
async def test_align_llm_passes_through_when_gate_open(client, monkeypatch):
    """When the gate is open, person-descriptive content passes through."""
    monkeypatch.setenv("CORPUSMIND_FACIAL_ANALYSIS_ENABLED", "1")
    img_id = await _setup_corpus_with_image(client)
    _inject_mock_provider(
        client,
        chat_content='{"alignments": [{"span_text": "the person", "region_descriptor": "a young woman smiling", "confidence": 0.7, "match_reason": "The woman is central."}]}',
    )

    r = await client.post(
        f"/api/v1/images/{img_id}/align?mode=llm&model=moondream",
        json={"text": "The person is central."},
    )
    assert r.status_code == 200
    data = r.json()
    assert data["person_descriptive_redacted"] is False
    assert "young woman" in data["alignments"][0]["region_descriptor"].lower()


# ---------------------------------------------------------------------------
# JSON parsing fallback
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_align_llm_handles_non_json_output(client):
    """When the model returns non-JSON, the route returns empty alignments
    instead of 500-ing."""
    img_id = await _setup_corpus_with_image(client)
    _inject_mock_provider(
        client,
        chat_content="This is not JSON. The image shows a red square.",
    )

    r = await client.post(
        f"/api/v1/images/{img_id}/align?mode=llm&model=moondream",
        json={"text": "A red square."},
    )
    assert r.status_code == 200
    data = r.json()
    assert data["provenance"]["mode"] == "llm"
    assert data["alignments"] == []  # empty, not an error


@pytest.mark.asyncio
async def test_align_llm_handles_json_with_code_fences(client):
    """When the model wraps JSON in code fences, the route strips them."""
    img_id = await _setup_corpus_with_image(client)
    _inject_mock_provider(
        client,
        chat_content='```json\n{"alignments": [{"span_text": "red", "region_descriptor": "centre", "confidence": 0.7, "match_reason": "colour match"}]}\n```',
    )

    r = await client.post(
        f"/api/v1/images/{img_id}/align?mode=llm&model=moondream",
        json={"text": "red"},
    )
    assert r.status_code == 200
    data = r.json()
    assert len(data["alignments"]) == 1
    assert data["alignments"][0]["span_text"] == "red"
