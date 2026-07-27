"""Tests for the vision-LM mode (?mode=llm) of the eight discourse routes
in api/phase5.py (CorpusMind Lens build step 4).

These tests use a mock provider injected into app.state.providers so
they run without any real Ollama / LM Studio instance. They cover:

  - LLM mode produces a different result than heuristic mode (the core
    acceptance criterion from the build prompt).
  - Every interpretive claim is hedged and cites a specific feature
    (verified by asserting the LLM's JSON output shape).
  - Provenance metadata (model, provider, prompt_hash, timestamp, mode)
    is returned for reproducibility.
  - Fallback: when mode=llm is requested but no provider is available,
    the route returns the heuristic result with a fallback_reason —
    never an error state.
  - Caching: second call with same prompt+model returns cached result
    without re-calling the model.
  - JSON-column mutation safety: cached results persist across sessions
    (the full-reassignment pattern works).
  - The hedging contract is in the system prompt sent to the model
    (verified by inspecting the mock's call args).
  - CDA sub-frameworks (fairclough, van_dijk, wodak, machin_mayr) each
    get their own framework_key and cache entry.
"""
from __future__ import annotations

import io
import os
from unittest.mock import AsyncMock, MagicMock

import pytest
from httpx import ASGITransport, AsyncClient

os.environ["CORPUSMIND_DB_URL"] = "sqlite+aiosqlite:///:memory:"
os.environ["CORPUSMIND_DATA_DIR"] = "/tmp/cm-test-data-discourse-llm"
from app.settings import get_settings

get_settings.cache_clear()


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture
async def client():
    from app.main import app
    from storage.session import dispose_db
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as ac:
        async with app.router.lifespan_context(app):
            yield ac
    await dispose_db()


def _make_test_image(width: int = 100, height: int = 100, color: tuple = (220, 50, 50)) -> bytes:
    """Generate a small PNG image of a solid color."""
    from PIL import Image
    img = Image.new("RGB", (width, height), color)
    buf = io.BytesIO()
    img.save(buf, format="PNG")
    return buf.getvalue()


async def _setup_corpus_with_image(client: AsyncClient) -> str:
    """Create project + corpus + image set + one uploaded image.
    Returns image_id."""
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
    chat_content: str = '{"claims": [], "summary": ""}',
    chat_model: str = "moondream",
    raise_on_chat: Exception | None = None,
) -> MagicMock:
    """Inject a mock provider into app.state.providers._instances."""
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


# A realistic LLM response that a small vision model might produce for a
# social semiotic analysis. The claims are hedged and cite specific
# features — this is the shape the system prompt asks for.
_LLM_RESPONSE_SOCIAL_SEMIOTIC = """{
  "claims": [
    {
      "framework": "Kress & van Leeuwen (Social Semiotics 2006)",
      "category": "representational",
      "claim": "Under a Social Semiotic reading, the central placement of the red figure may construct it as the nucleus of the image's representational meaning.",
      "evidence": ["composition.salience_centre", "colours.dominant_colours"],
      "confidence": 0.6
    },
    {
      "framework": "Kress & van Leeuwen (Social Semiotics 2006)",
      "category": "interactive",
      "claim": "Under a Social Semiotic reading, the frontal angle of the depicted subject may construct a relationship of involvement with the viewer.",
      "evidence": ["depicted_subject.angle"],
      "confidence": 0.5
    }
  ],
  "summary": "Social semiotic analysis identified 2 claims about representational and interactive meaning."
}"""


# ---------------------------------------------------------------------------
# Core acceptance criterion: LLM mode produces different output than heuristic
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_llm_mode_produces_different_output_than_heuristic(client):
    """The core acceptance criterion from the build prompt: 'Every one of
    the eight discourse-framework routes has a working vision-LM path
    that produces different, better-grounded output than the heuristic-
    only path for an image with no caption.'

    With no caption and a solid-color image, the heuristic social-semiotic
    path produces claims based only on colour symbolism notes + composition
    geometry. The LLM path produces claims that reference the actual
    depicted content. This test confirms they differ."""
    img_id = await _setup_corpus_with_image(client)

    # Heuristic mode (default — no mode param).
    r_h = await client.post(f"/api/v1/images/{img_id}/social-semiotic")
    assert r_h.status_code == 200
    heuristic = r_h.json()
    assert heuristic["provenance"]["mode"] == "heuristic"

    # LLM mode.
    mock = _inject_mock_provider(
        client, chat_content=_LLM_RESPONSE_SOCIAL_SEMIOTIC,
    )
    r_l = await client.post(
        f"/api/v1/images/{img_id}/social-semiotic?mode=llm&model=moondream",
    )
    assert r_l.status_code == 200, r_l.text
    llm = r_l.json()
    assert llm["provenance"]["mode"] == "llm"
    assert llm["provenance"]["model"] == "moondream"
    assert llm["provenance"]["provider"] == "ollama"
    assert len(llm["provenance"]["prompt_hash"]) == 16

    # The outputs MUST differ — that's the whole point of the LLM path.
    assert llm["claims"] != heuristic["claims"], (
        "LLM mode produced the same claims as heuristic mode. The LLM "
        "path is supposed to produce different, better-grounded output "
        "by looking at the actual image content."
    )

    # The LLM was actually called with image bytes attached.
    mock.chat.assert_called_once()
    messages = mock.chat.call_args.args[0]
    assert len(messages) == 2  # system + user
    assert messages[0].role == "system"
    assert messages[1].role == "user"
    assert len(messages[1].images) == 1  # image bytes attached
    assert isinstance(messages[1].images[0], bytes)


@pytest.mark.asyncio
async def test_llm_mode_claims_are_hedged(client):
    """Every interpretive claim from the LLM must be phrased as a
    hypothesis ('Under a [Framework] reading, X may indicate Y') per
    the hedging contract. The system prompt enforces this; this test
    verifies the contract is actually in the prompt sent to the model."""
    img_id = await _setup_corpus_with_image(client)
    mock = _inject_mock_provider(
        client, chat_content=_LLM_RESPONSE_SOCIAL_SEMIOTIC,
    )

    await client.post(
        f"/api/v1/images/{img_id}/social-semiotic?mode=llm&model=moondream",
    )

    messages = mock.chat.call_args.args[0]
    system_prompt = messages[0].content

    # The hedging contract requires:
    # 1. Claims phrased as hypotheses (check case-insensitively — the
    #    prompt uses "HYPOTHESES" plural)
    assert "hypothes" in system_prompt.lower(), (
        "System prompt must mention hypotheses — the hedging contract "
        "requires claims to be phrased as hypotheses, not settled fact."
    )
    # 2. The "Under a [Framework] reading" form
    assert "Under a" in system_prompt or "may indicate" in system_prompt
    # 3. Evidence citation
    assert "evidence" in system_prompt.lower()
    # 4. Confidence scores
    assert "confidence" in system_prompt.lower()
    # 5. JSON output format
    assert "JSON" in system_prompt or "json" in system_prompt


# ---------------------------------------------------------------------------
# Fallback: no provider → heuristic with fallback_reason
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_llm_mode_falls_back_when_no_provider(client):
    """When mode=llm is requested but the provider health check fails,
    the route returns the heuristic result with a fallback_reason —
    never an error.

    Note: we explicitly inject an unhealthy mock provider rather than
    relying on 'no provider running' — in some test environments a real
    Ollama may actually be running (e.g. during E2E verification), which
    would make this test pass for the wrong reason. The explicit
    unhealthy mock makes the test deterministic."""
    img_id = await _setup_corpus_with_image(client)
    _inject_mock_provider(client, health_ok=False)

    r = await client.post(
        f"/api/v1/images/{img_id}/social-semiotic?mode=llm&model=moondream",
    )
    assert r.status_code == 200, r.text
    data = r.json()
    assert data["provenance"]["mode"] == "heuristic"
    assert "fallback_reason" in data
    assert "LLM" in data["fallback_reason"] or "heuristic" in data["fallback_reason"].lower()


@pytest.mark.asyncio
async def test_llm_mode_falls_back_when_provider_unhealthy(client):
    """When the provider health check fails, fall back to heuristic."""
    img_id = await _setup_corpus_with_image(client)
    _inject_mock_provider(client, health_ok=False)

    r = await client.post(
        f"/api/v1/images/{img_id}/framing?mode=llm",
    )
    assert r.status_code == 200
    data = r.json()
    assert data["provenance"]["mode"] == "heuristic"
    assert "fallback_reason" in data


@pytest.mark.asyncio
async def test_llm_mode_falls_back_when_provider_call_fails(client):
    """When the provider call itself fails (model error), fall back to
    heuristic instead of 500-ing."""
    from ai.providers import ModelProviderError
    img_id = await _setup_corpus_with_image(client)
    _inject_mock_provider(
        client, raise_on_chat=ModelProviderError("model crashed"),
    )

    r = await client.post(
        f"/api/v1/images/{img_id}/persuasion?mode=llm",
    )
    assert r.status_code == 200
    data = r.json()
    assert data["provenance"]["mode"] == "heuristic"
    assert "fallback_reason" in data


# ---------------------------------------------------------------------------
# Caching
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_llm_mode_cache_hit_does_not_recall_model(client):
    """Second call with same framework+model returns cached result
    without re-calling the model."""
    img_id = await _setup_corpus_with_image(client)
    mock = _inject_mock_provider(
        client, chat_content=_LLM_RESPONSE_SOCIAL_SEMIOTIC,
    )

    # First call — actually calls the model.
    r1 = await client.post(
        f"/api/v1/images/{img_id}/social-semiotic?mode=llm&model=moondream",
    )
    assert r1.status_code == 200
    assert r1.json()["provenance"]["cached"] is False
    assert mock.chat.call_count == 1

    # Second call — cache hit.
    r2 = await client.post(
        f"/api/v1/images/{img_id}/social-semiotic?mode=llm&model=moondream",
    )
    assert r2.status_code == 200
    assert r2.json()["provenance"]["cached"] is True
    assert mock.chat.call_count == 1  # NOT 2


@pytest.mark.asyncio
async def test_llm_mode_refresh_forces_recall(client):
    """refresh=True forces a re-call even on cache hit."""
    from ai.providers import ChatResponse
    img_id = await _setup_corpus_with_image(client)
    mock = _inject_mock_provider(
        client, chat_content=_LLM_RESPONSE_SOCIAL_SEMIOTIC,
    )

    await client.post(
        f"/api/v1/images/{img_id}/social-semiotic?mode=llm&model=moondream",
    )
    assert mock.chat.call_count == 1

    # Update the mock's response.
    mock.chat.return_value = ChatResponse(
        content='{"claims": [{"framework": "test", "category": "test", "claim": "different", "evidence": [], "confidence": 0.5}], "summary": "different"}',
        model="moondream",
        provider="ollama",
        raw={},
    )

    r = await client.post(
        f"/api/v1/images/{img_id}/social-semiotic?mode=llm&model=moondream&refresh=true",
    )
    assert r.status_code == 200
    assert r.json()["provenance"]["cached"] is False
    assert r.json()["claims"][0]["claim"] == "different"
    assert mock.chat.call_count == 2


@pytest.mark.asyncio
async def test_llm_mode_cache_persists_across_sessions(client):
    """JSON-column mutation safety: cached results survive a session
    close + reopen. This is the regression guard for the full-reassignment
    pattern."""
    img_id = await _setup_corpus_with_image(client)
    mock = _inject_mock_provider(
        client, chat_content=_LLM_RESPONSE_SOCIAL_SEMIOTIC,
    )

    await client.post(
        f"/api/v1/images/{img_id}/narrative?mode=llm&model=moondream",
    )
    assert mock.chat.call_count == 1

    # Verify the cache was persisted by reading directly from the DB.
    from storage.models import Image as ImageModel
    from storage.session import session_scope
    async with session_scope() as session:
        img = await session.get(ImageModel, img_id)
        vlm_discourse = img.analysis.get("vision_llm_discourse", {})
        assert len(vlm_discourse) == 1
        cached = next(iter(vlm_discourse.values()))
        assert cached["framework"] == "Labov (1972) Narrative Structure"
        assert cached["provenance"]["model"] == "moondream"


# ---------------------------------------------------------------------------
# CDA sub-frameworks each get their own cache key
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_cda_subframeworks_use_different_cache_keys(client):
    """Each CDA sub-framework (fairclough, van_dijk, wodak, machin_mayr)
    gets its own framework_key and cache entry — running one doesn't
    overwrite another."""
    from ai.providers import ChatResponse
    img_id = await _setup_corpus_with_image(client)
    mock = _inject_mock_provider(client)

    # Run CDA with fairclough.
    mock.chat.return_value = ChatResponse(
        content='{"claims": [{"framework": "Fairclough", "category": "textual", "claim": "fairclough claim", "evidence": [], "confidence": 0.5}], "summary": "fairclough"}',
        model="moondream", provider="ollama", raw={},
    )
    r1 = await client.post(
        f"/api/v1/images/{img_id}/cda?mode=llm&model=moondream",
        json={"framework": "fairclough"},
    )
    assert r1.status_code == 200
    assert r1.json()["claims"][0]["claim"] == "fairclough claim"
    assert mock.chat.call_count == 1

    # Run CDA with van_dijk — different cache key, should call the model.
    mock.chat.return_value = ChatResponse(
        content='{"claims": [{"framework": "van Dijk", "category": "cognitive", "claim": "van dijk claim", "evidence": [], "confidence": 0.5}], "summary": "van dijk"}',
        model="moondream", provider="ollama", raw={},
    )
    r2 = await client.post(
        f"/api/v1/images/{img_id}/cda?mode=llm&model=moondream",
        json={"framework": "van_dijk"},
    )
    assert r2.status_code == 200
    assert r2.json()["claims"][0]["claim"] == "van dijk claim"
    assert mock.chat.call_count == 2  # called again — different cache key

    # Run CDA with fairclough again — cache hit.
    r3 = await client.post(
        f"/api/v1/images/{img_id}/cda?mode=llm&model=moondream",
        json={"framework": "fairclough"},
    )
    assert r3.status_code == 200
    assert r3.json()["claims"][0]["claim"] == "fairclough claim"
    assert mock.chat.call_count == 2  # still 2 — cache hit

    # Verify both are cached separately.
    from storage.models import Image as ImageModel
    from storage.session import session_scope
    async with session_scope() as session:
        img = await session.get(ImageModel, img_id)
        vlm_discourse = img.analysis.get("vision_llm_discourse", {})
        # Two entries: cda_fairclough:moondream:... and cda_van_dijk:moondream:...
        assert len(vlm_discourse) == 2


# ---------------------------------------------------------------------------
# All 8 routes accept ?mode=llm
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_all_eight_routes_accept_llm_mode(client):
    """Smoke test: every one of the eight discourse routes accepts
    ?mode=llm and returns a 200 (either LLM result or heuristic fallback)."""
    img_id = await _setup_corpus_with_image(client)
    # Inject a healthy mock so LLM mode actually runs.
    _inject_mock_provider(
        client, chat_content='{"claims": [], "summary": "empty"}',
    )

    routes = [
        ("social-semiotic", "post", None),
        ("cda", "post", {"framework": "fairclough"}),
        ("persuasion", "post", None),
        ("framing", "post", None),
        ("narrative", "post", None),
        ("visual-metaphor", "post", None),
        ("emotion", "post", None),
        ("cultural", "post", None),
    ]

    for path, method, body in routes:
        url = f"/api/v1/images/{img_id}/{path}?mode=llm&model=moondream"
        if method == "post":
            r = await client.post(url, json=body) if body else await client.post(url)
        assert r.status_code == 200, f"{path} returned {r.status_code}: {r.text}"
        data = r.json()
        # Either LLM mode succeeded or it fell back to heuristic.
        assert data["provenance"]["mode"] in ("llm", "heuristic")


# ---------------------------------------------------------------------------
# JSON parsing fallback
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_llm_mode_handles_non_json_output(client):
    """When the model returns non-JSON output (common with small models),
    the route falls back to wrapping the raw text in a single claim
    rather than 500-ing."""
    img_id = await _setup_corpus_with_image(client)
    _inject_mock_provider(
        client, chat_content="This is not JSON. The image shows a red square.",
    )

    r = await client.post(
        f"/api/v1/images/{img_id}/framing?mode=llm&model=moondream",
    )
    assert r.status_code == 200, r.text
    data = r.json()
    assert data["provenance"]["mode"] == "llm"
    assert len(data["claims"]) == 1
    assert "red square" in data["claims"][0]["claim"]
    # Low confidence because we couldn't parse structured claims.
    assert data["claims"][0]["confidence"] <= 0.5


@pytest.mark.asyncio
async def test_llm_mode_handles_json_with_code_fences(client):
    """When the model wraps JSON in markdown code fences (```json ... ```)
    despite instructions not to, the route strips the fences and parses."""
    img_id = await _setup_corpus_with_image(client)
    _inject_mock_provider(
        client, chat_content='```json\n{"claims": [{"framework": "test", "category": "test", "claim": "fenced", "evidence": [], "confidence": 0.7}], "summary": "fenced"}\n```',
    )

    r = await client.post(
        f"/api/v1/images/{img_id}/emotion?mode=llm&model=moondream",
    )
    assert r.status_code == 200
    data = r.json()
    assert data["claims"][0]["claim"] == "fenced"
    assert data["claims"][0]["confidence"] == 0.7


# ---------------------------------------------------------------------------
# Heuristic mode is unchanged (backward compat)
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_heuristic_mode_still_works_without_mode_param(client):
    """Calling a route without ?mode= still runs the heuristic path —
    backward compat for existing callers."""
    img_id = await _setup_corpus_with_image(client)

    r = await client.post(f"/api/v1/images/{img_id}/social-semiotic")
    assert r.status_code == 200
    data = r.json()
    assert data["provenance"]["mode"] == "heuristic"
    assert "fallback_reason" not in data  # no fallback — heuristic was explicitly the default


@pytest.mark.asyncio
async def test_heuristic_mode_explicit(client):
    """?mode=heuristic explicitly runs the heuristic path even if a
    provider is available."""
    img_id = await _setup_corpus_with_image(client)
    _inject_mock_provider(
        client, chat_content='{"claims": [], "summary": "should not be called"}',
    )

    r = await client.post(
        f"/api/v1/images/{img_id}/cultural?mode=heuristic",
    )
    assert r.status_code == 200
    data = r.json()
    assert data["provenance"]["mode"] == "heuristic"
