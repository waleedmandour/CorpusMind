"""Tests for the consent-gate filter on vision-LM output
(CorpusMind Lens build step 5).

The consent gate (vision/facial.py::is_facial_analysis_enabled) has
historically only protected the dedicated /facial-analysis route. Step 5
extends it to ALL vision-LM output: the /describe route (step 3) and
the eight discourse routes' LLM mode (step 4). A vision-LM asked to
describe a photo will volunteer age/emotion/gender-presentation
commentary about people in it whether or not anyone asked — this filter
catches that and redacts it when the gate is closed.

Coverage:
  - Unit tests for the filter module itself (keyword detection, sentence-
    level redaction, gate-open vs gate-closed behavior).
  - Integration tests for the /describe route: person-descriptive
    description is redacted when gate is closed, passes through when
    gate is open.
  - Integration tests for a discourse route: person-descriptive claims
    are redacted when gate is closed.
  - The `person_descriptive_redacted` field is present in every response
    so the UI can show the user that filtering happened.
  - Non-person-descriptive content is never filtered (no false positives
    on colour/geometry descriptions).
"""
from __future__ import annotations

import io
import os
from unittest.mock import AsyncMock, MagicMock

import pytest
from httpx import ASGITransport, AsyncClient

os.environ["CORPUSMIND_DB_URL"] = "sqlite+aiosqlite:///:memory:"
os.environ["CORPUSMIND_DATA_DIR"] = "/tmp/cm-test-consent-gate"
# Ensure the gate is CLOSED for tests by default (it's the production
# default too, but we set it explicitly so the tests don't depend on
# whatever the dev machine's env happens to be).
os.environ.pop("CORPUSMIND_FACIAL_ANALYSIS_ENABLED", None)
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
    chat_content: str = "A red square.",
    chat_model: str = "moondream",
) -> MagicMock:
    from ai.providers import ChatResponse
    from app.main import app
    registry = app.state.providers
    mock = MagicMock()
    mock.name = provider_name
    mock.default_model = chat_model
    mock.health = AsyncMock(return_value=health_ok)
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


# ---------------------------------------------------------------------------
# Unit tests for the filter module
# ---------------------------------------------------------------------------


class TestFilterPersonDescriptive:
    """Unit tests for vision.consent_gate.filter_person_descriptive."""

    def test_no_filtering_when_gate_open(self, monkeypatch):
        """When CORPUSMIND_FACIAL_ANALYSIS_ENABLED=1, no filtering happens
        even if the text contains person-descriptive keywords."""
        monkeypatch.setenv("CORPUSMIND_FACIAL_ANALYSIS_ENABLED", "1")
        from vision.consent_gate import filter_person_descriptive
        text = "A young woman with a smiling face is standing in the frame."
        result = filter_person_descriptive(text)
        assert result.was_filtered is False
        assert result.filtered_text == text  # unchanged

    def test_filters_age_keywords_when_gate_closed(self, monkeypatch):
        """When the gate is closed, age-related keywords trigger redaction."""
        monkeypatch.delenv("CORPUSMIND_FACIAL_ANALYSIS_ENABLED", raising=False)
        from vision.consent_gate import filter_person_descriptive
        text = "The image shows a child playing in the park."
        result = filter_person_descriptive(text)
        assert result.was_filtered is True
        assert "redacted" in result.filtered_text.lower()
        assert "child" not in result.filtered_text.lower()

    def test_filters_gender_keywords_when_gate_closed(self, monkeypatch):
        """Gender-related keywords trigger redaction."""
        monkeypatch.delenv("CORPUSMIND_FACIAL_ANALYSIS_ENABLED", raising=False)
        from vision.consent_gate import filter_person_descriptive
        text = "A woman is standing next to a man in the photograph."
        result = filter_person_descriptive(text)
        assert result.was_filtered is True
        assert "woman" not in result.filtered_text.lower()
        assert "man" not in result.filtered_text.lower() or "redacted" in result.filtered_text.lower()

    def test_filters_expression_keywords_when_gate_closed(self, monkeypatch):
        """Facial-expression keywords trigger redaction."""
        monkeypatch.delenv("CORPUSMIND_FACIAL_ANALYSIS_ENABLED", raising=False)
        from vision.consent_gate import filter_person_descriptive
        text = "The person has a smiling expression and appears happy."
        result = filter_person_descriptive(text)
        assert result.was_filtered is True

    def test_filters_appearance_keywords_when_gate_closed(self, monkeypatch):
        """Physical-appearance keywords trigger redaction."""
        monkeypatch.delenv("CORPUSMIND_FACIAL_ANALYSIS_ENABLED", raising=False)
        from vision.consent_gate import filter_person_descriptive
        text = "An attractive blonde woman is the central subject."
        result = filter_person_descriptive(text)
        assert result.was_filtered is True

    def test_filters_ethnicity_keywords_when_gate_closed(self, monkeypatch):
        monkeypatch.delenv("CORPUSMIND_FACIAL_ANALYSIS_ENABLED", raising=False)
        from vision.consent_gate import filter_person_descriptive
        text = "An Asian woman is standing in the centre of the image."
        result = filter_person_descriptive(text)
        assert result.was_filtered is True
        assert "asian" not in result.filtered_text.lower()

    def test_filters_religious_attire_keywords_when_gate_closed(self, monkeypatch):
        monkeypatch.delenv("CORPUSMIND_FACIAL_ANALYSIS_ENABLED", raising=False)
        from vision.consent_gate import filter_person_descriptive
        text = "A woman wearing a hijab is visible in the background."
        result = filter_person_descriptive(text)
        assert result.was_filtered is True
        assert "hijab" not in result.filtered_text.lower()

    def test_filters_socioeconomic_keywords_when_gate_closed(self, monkeypatch):
        monkeypatch.delenv("CORPUSMIND_FACIAL_ANALYSIS_ENABLED", raising=False)
        from vision.consent_gate import filter_person_descriptive
        text = "The man appears wealthy and is wearing expensive clothing."
        result = filter_person_descriptive(text)
        assert result.was_filtered is True
        assert "wealthy" not in result.filtered_text.lower()

    def test_no_false_positives_on_colour_descriptions(self, monkeypatch):
        """Colour/geometry descriptions should NOT be filtered — no
        person-descriptive keywords."""
        monkeypatch.delenv("CORPUSMIND_FACIAL_ANALYSIS_ENABLED", raising=False)
        from vision.consent_gate import filter_person_descriptive
        text = "A red square on a blue background with high contrast."
        result = filter_person_descriptive(text)
        assert result.was_filtered is False
        assert result.filtered_text == text

    def test_no_false_positives_on_composition(self, monkeypatch):
        """Composition descriptions should NOT be filtered."""
        monkeypatch.delenv("CORPUSMIND_FACIAL_ANALYSIS_ENABLED", raising=False)
        from vision.consent_gate import filter_person_descriptive
        text = "The salient element is centred, creating a balanced composition with strong vectors."
        result = filter_person_descriptive(text)
        assert result.was_filtered is False

    def test_redacts_at_sentence_level(self, monkeypatch):
        """When a multi-sentence description has person-descriptive content
        in only some sentences, only those sentences are redacted — the
        rest pass through unchanged."""
        monkeypatch.delenv("CORPUSMIND_FACIAL_ANALYSIS_ENABLED", raising=False)
        from vision.consent_gate import filter_person_descriptive
        text = (
            "The image has a red background. "
            "A young woman is standing in the centre. "
            "The composition uses strong vectors."
        )
        result = filter_person_descriptive(text)
        assert result.was_filtered is True
        # The non-person sentences should survive
        assert "red background" in result.filtered_text
        assert "strong vectors" in result.filtered_text
        # The person-descriptive sentence should be redacted
        assert "young woman" not in result.filtered_text
        assert "redacted" in result.filtered_text.lower()

    def test_empty_text_returns_empty(self, monkeypatch):
        monkeypatch.delenv("CORPUSMIND_FACIAL_ANALYSIS_ENABLED", raising=False)
        from vision.consent_gate import filter_person_descriptive
        result = filter_person_descriptive("")
        assert result.was_filtered is False
        assert result.filtered_text == ""

    def test_matched_keywords_are_returned_for_audit(self, monkeypatch):
        """The matched_keywords list is returned so the caller can log/
        audit what triggered the filter."""
        monkeypatch.delenv("CORPUSMIND_FACIAL_ANALYSIS_ENABLED", raising=False)
        from vision.consent_gate import filter_person_descriptive
        text = "An elderly man with a serious expression."
        result = filter_person_descriptive(text)
        assert result.was_filtered is True
        assert len(result.matched_keywords) > 0
        # Keywords are lowercased
        assert all(kw == kw.lower() for kw in result.matched_keywords)


# ---------------------------------------------------------------------------
# Integration tests for the /describe route
# ---------------------------------------------------------------------------


class TestDescribeRouteConsentGate:
    """Integration tests: the /describe route filters person-descriptive
    output through the consent gate."""

    @pytest.mark.asyncio
    async def test_describe_redacts_person_descriptive_when_gate_closed(self, client, monkeypatch):
        """When the gate is closed and the vision-LM volunteers person-
        descriptive content, the response redacts it and sets
        person_descriptive_redacted=True."""
        monkeypatch.delenv("CORPUSMIND_FACIAL_ANALYSIS_ENABLED", raising=False)
        img_id = await _setup_corpus_with_image(client)
        _inject_mock_provider(
            client,
            chat_content="A red square. A young woman is smiling in the centre.",
        )

        r = await client.post(f"/api/v1/images/{img_id}/describe")
        assert r.status_code == 200, r.text
        data = r.json()
        assert data["person_descriptive_redacted"] is True
        assert "young woman" not in data["description"].lower()
        assert "redacted" in data["description"].lower()
        # The non-person part survives
        assert "red square" in data["description"].lower()

    @pytest.mark.asyncio
    async def test_describe_passes_through_when_gate_open(self, client, monkeypatch):
        """When the gate is open (user opted in), person-descriptive
        content passes through unchanged."""
        monkeypatch.setenv("CORPUSMIND_FACIAL_ANALYSIS_ENABLED", "1")
        img_id = await _setup_corpus_with_image(client)
        _inject_mock_provider(
            client,
            chat_content="A young woman is smiling in the centre.",
        )

        r = await client.post(f"/api/v1/images/{img_id}/describe")
        assert r.status_code == 200, r.text
        data = r.json()
        assert data["person_descriptive_redacted"] is False
        assert "young woman" in data["description"].lower()
        assert "smiling" in data["description"].lower()

    @pytest.mark.asyncio
    async def test_describe_no_redaction_for_non_person_content(self, client, monkeypatch):
        """When the vision-LM output has no person-descriptive content,
        person_descriptive_redacted=False and the text is unchanged."""
        monkeypatch.delenv("CORPUSMIND_FACIAL_ANALYSIS_ENABLED", raising=False)
        img_id = await _setup_corpus_with_image(client)
        _inject_mock_provider(
            client,
            chat_content="A red square on a white background.",
        )

        r = await client.post(f"/api/v1/images/{img_id}/describe")
        assert r.status_code == 200
        data = r.json()
        assert data["person_descriptive_redacted"] is False
        assert data["description"] == "A red square on a white background."

    @pytest.mark.asyncio
    async def test_describe_cache_hit_also_filters(self, client, monkeypatch):
        """The consent gate is applied even on cache hits — a cached
        description with person-descriptive content is redacted when
        the gate is closed, even though the model isn't re-called.

        This matters because a user might have run /describe with the
        gate open (caching the unredacted description), then closed the
        gate and re-requested. The cached unredacted text must be
        redacted on the way out."""
        monkeypatch.delenv("CORPUSMIND_FACIAL_ANALYSIS_ENABLED", raising=False)
        img_id = await _setup_corpus_with_image(client)
        _inject_mock_provider(
            client,
            chat_content="A young woman is smiling.",
        )

        # First call — caches the (unredacted at cache time) description.
        # The gate filters on the way OUT, but the cache stores the raw
        # model output so that re-opening the gate later shows the full
        # text without re-calling the model.
        r1 = await client.post(f"/api/v1/images/{img_id}/describe")
        assert r1.status_code == 200
        assert r1.json()["person_descriptive_redacted"] is True
        assert "young woman" not in r1.json()["description"]

        # Second call — cache hit. The gate must STILL filter the cached
        # text on the way out.
        r2 = await client.post(f"/api/v1/images/{img_id}/describe")
        assert r2.status_code == 200
        assert r2.json()["cached"] is True
        assert r2.json()["person_descriptive_redacted"] is True
        assert "young woman" not in r2.json()["description"]


# ---------------------------------------------------------------------------
# Integration tests for the discourse LLM routes
# ---------------------------------------------------------------------------


class TestDiscourseRouteConsentGate:
    """Integration tests: the discourse LLM routes filter person-
    descriptive claims through the consent gate."""

    @pytest.mark.asyncio
    async def test_discourse_redacts_person_descriptive_claims(self, client, monkeypatch):
        """When the gate is closed and the vision-LM produces claims with
        person-descriptive content, those claims are redacted."""
        monkeypatch.delenv("CORPUSMIND_FACIAL_ANALYSIS_ENABLED", raising=False)
        img_id = await _setup_corpus_with_image(client)
        _inject_mock_provider(
            client,
            chat_content='{"claims": [{"framework": "test", "category": "representational", "claim": "A young woman is depicted smiling in the centre.", "evidence": ["depicted_subject"], "confidence": 0.6}], "summary": "The image shows a woman."}',
        )

        r = await client.post(
            f"/api/v1/images/{img_id}/social-semiotic?mode=llm&model=moondream",
        )
        assert r.status_code == 200, r.text
        data = r.json()
        assert data["person_descriptive_redacted"] is True
        # The claim text should be redacted
        claim_text = data["claims"][0]["claim"].lower()
        assert "young woman" not in claim_text
        assert "redacted" in claim_text
        # The summary should also be redacted
        assert "woman" not in data["summary"].lower()
        assert "redacted" in data["summary"].lower()

    @pytest.mark.asyncio
    async def test_discourse_passes_through_when_gate_open(self, client, monkeypatch):
        """When the gate is open, person-descriptive claims pass through."""
        monkeypatch.setenv("CORPUSMIND_FACIAL_ANALYSIS_ENABLED", "1")
        img_id = await _setup_corpus_with_image(client)
        _inject_mock_provider(
            client,
            chat_content='{"claims": [{"framework": "test", "category": "representational", "claim": "A young woman is depicted smiling.", "evidence": [], "confidence": 0.6}], "summary": "Shows a woman."}',
        )

        r = await client.post(
            f"/api/v1/images/{img_id}/framing?mode=llm&model=moondream",
        )
        assert r.status_code == 200
        data = r.json()
        assert data["person_descriptive_redacted"] is False
        assert "young woman" in data["claims"][0]["claim"].lower()

    @pytest.mark.asyncio
    async def test_discourse_partial_redaction(self, client, monkeypatch):
        """When only SOME claims have person-descriptive content, only
        those claims are redacted — the others pass through unchanged."""
        monkeypatch.delenv("CORPUSMIND_FACIAL_ANALYSIS_ENABLED", raising=False)
        img_id = await _setup_corpus_with_image(client)
        _inject_mock_provider(
            client,
            chat_content='{"claims": [{"framework": "test", "category": "colour", "claim": "The red colour dominates the composition.", "evidence": [], "confidence": 0.7}, {"framework": "test", "category": "representational", "claim": "An elderly man is the central subject.", "evidence": [], "confidence": 0.5}], "summary": "Two claims."}',
        )

        r = await client.post(
            f"/api/v1/images/{img_id}/narrative?mode=llm&model=moondream",
        )
        assert r.status_code == 200
        data = r.json()
        assert data["person_descriptive_redacted"] is True
        # First claim (colour) should survive
        assert "red colour" in data["claims"][0]["claim"].lower()
        # Second claim (person) should be redacted
        assert "elderly man" not in data["claims"][1]["claim"].lower()
        assert "redacted" in data["claims"][1]["claim"].lower()

    @pytest.mark.asyncio
    async def test_discourse_no_redaction_for_non_person_claims(self, client, monkeypatch):
        """When no claims have person-descriptive content,
        person_descriptive_redacted=False."""
        monkeypatch.delenv("CORPUSMIND_FACIAL_ANALYSIS_ENABLED", raising=False)
        img_id = await _setup_corpus_with_image(client)
        _inject_mock_provider(
            client,
            chat_content='{"claims": [{"framework": "test", "category": "colour", "claim": "Red dominates.", "evidence": [], "confidence": 0.7}], "summary": "Colour claim."}',
        )

        r = await client.post(
            f"/api/v1/images/{img_id}/emotion?mode=llm&model=moondream",
        )
        assert r.status_code == 200
        data = r.json()
        assert data["person_descriptive_redacted"] is False
        assert data["claims"][0]["claim"] == "Red dominates."
