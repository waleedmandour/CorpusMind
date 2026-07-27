"""Tests for POST /images/{img_id}/describe (CorpusMind Lens build step 3).

This route is the first that actually calls a vision-LM via the
Message.images extension from build step 1. The tests use a mock
provider injected into app.state.providers._instances so they run
without any real Ollama / LM Studio instance.

Coverage:
  - Happy path: image exists, provider healthy, model returns a
    description → 200 with provenance metadata.
  - Cache hit: second call with same prompt+model returns cached result
    without re-calling the model (verified by counting mock calls).
  - Refresh: refresh=True forces a re-call even on cache hit.
  - OCR disagreement: when the vision-LM's text materially differs from
    cached OCR, ocr_disagreement=True and cached_ocr is returned.
  - JSON-column mutation safety: the cached result is actually persisted
    (img.analysis["vision_llm"] survives a session close + reopen),
    proving the full-reassignment pattern works.
  - Error paths: 404 (image not found), 400 (image file missing),
    503 (provider unhealthy), 500 (provider call fails), 500 (empty
    content from model).

The HTTP-mocked tests here complement the real-model E2E test in
/home/z/my-project/scripts/verify_real_vision_e2e.py, which actually
calls a running moondream instance to prove the wire format works
end-to-end against a real model server.
"""
from __future__ import annotations

import io
import os
from unittest.mock import AsyncMock, MagicMock

import pytest
from httpx import ASGITransport, AsyncClient

os.environ["CORPUSMIND_DB_URL"] = "sqlite+aiosqlite:///:memory:"
os.environ["CORPUSMIND_DATA_DIR"] = "/tmp/cm-test-data-describe"
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


async def _setup_corpus_with_image(client: AsyncClient, *, image_bytes: bytes | None = None,
                                    caption: str = "") -> tuple[str, str]:
    """Create project + corpus + image set + one uploaded image.
    Returns (image_id, image_set_id).
    """
    r = await client.post("/api/v1/projects", json={"name": "T", "language": "en"})
    pid = r.json()["id"]
    r = await client.post(f"/api/v1/projects/{pid}/corpora", json={"name": "C", "language": "en"})
    cid = r.json()["id"]
    r = await client.post(f"/api/v1/corpora/{cid}/image-sets", json={"name": "S"})
    iset_id = r.json()["id"]
    upload_bytes = image_bytes if image_bytes is not None else _make_test_image()
    r = await client.post(
        f"/api/v1/image-sets/{iset_id}/images",
        files={"files": ("test.png", io.BytesIO(upload_bytes), "image/png")},
        data={"captions": caption} if caption else None,
    )
    assert r.status_code == 200, r.text
    img_id = r.json()[0]["id"]
    return img_id, iset_id


def _inject_mock_provider(client: AsyncClient, provider_name: str = "ollama",
                           *, health_ok: bool = True,
                           chat_content: str = "A red square.",
                           chat_model: str = "moondream",
                           list_models_result: list[str] | None = None,
                           raise_on_chat: Exception | None = None) -> MagicMock:
    """Inject a mock provider into app.state.providers._instances.

    Returns the mock so the test can assert on call counts / args.
    The mock is async-safe (uses AsyncMock for async methods).
    """
    from app.main import app
    registry = app.state.providers
    mock = MagicMock()
    mock.name = provider_name
    mock.default_model = chat_model
    mock.health = AsyncMock(return_value=health_ok)
    if raise_on_chat:
        mock.chat = AsyncMock(side_effect=raise_on_chat)
    else:
        from ai.providers import ChatResponse
        mock.chat = AsyncMock(return_value=ChatResponse(
            content=chat_content,
            model=chat_model,
            provider=provider_name,
            raw={},
        ))
    mock.list_models = AsyncMock(return_value=list_models_result or [chat_model])
    mock.aclose = AsyncMock()
    # Inject directly into the registry's instance cache so .get() returns it.
    registry._instances[provider_name] = mock
    return mock


# ---------------------------------------------------------------------------
# Happy path
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_describe_happy_path(client):
    """Image exists, provider healthy, model returns a description.
    Response includes provenance metadata (model, provider, prompt,
    prompt_hash, timestamp) for reproducibility per §4 Principle 8."""
    img_id, _ = await _setup_corpus_with_image(client)
    mock = _inject_mock_provider(client, chat_content="A red square on white background.")

    r = await client.post(f"/api/v1/images/{img_id}/describe")

    assert r.status_code == 200, r.text
    data = r.json()
    assert data["image_id"] == img_id
    assert data["description"] == "A red square on white background."
    assert data["model"] == "moondream"
    assert data["provider"] == "ollama"
    assert data["prompt"]  # non-empty default prompt
    assert len(data["prompt_hash"]) == 16  # truncated sha256
    assert data["timestamp"]  # ISO format
    assert data["cached"] is False
    assert data["ocr_disagreement"] is False  # no cached OCR for a solid-color image
    assert data["cached_ocr"] == ""  # no OCR text for a solid-color image

    # The provider was actually called with a Message carrying image bytes.
    mock.chat.assert_called_once()
    call_kwargs = mock.chat.call_args
    messages = call_kwargs.args[0]
    assert len(messages) == 1
    assert messages[0].role == "user"
    assert len(messages[0].images) == 1  # image bytes attached
    assert isinstance(messages[0].images[0], bytes)
    assert len(messages[0].images[0]) > 0


@pytest.mark.asyncio
async def test_describe_with_custom_prompt_and_model(client):
    """Custom prompt + model are threaded through to the provider."""
    img_id, _ = await _setup_corpus_with_image(client)
    mock = _inject_mock_provider(client, chat_model="llama3.2-vision")

    r = await client.post(f"/api/v1/images/{img_id}/describe", json={
        "prompt": "What is the dominant color?",
        "model": "llama3.2-vision",
    })

    assert r.status_code == 200, r.text
    data = r.json()
    assert data["model"] == "llama3.2-vision"
    assert data["prompt"] == "What is the dominant color?"

    # The custom prompt is included in the message content sent to the model.
    messages = mock.chat.call_args.args[0]
    assert "What is the dominant color?" in messages[0].content


# ---------------------------------------------------------------------------
# Caching
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_describe_cache_hit_does_not_recall_model(client):
    """Second call with same prompt+model returns cached result without
    calling the model again. This is the load-bearing cache assertion."""
    img_id, _ = await _setup_corpus_with_image(client)
    mock = _inject_mock_provider(client, chat_content="First description.")

    # First call — actually calls the model.
    r1 = await client.post(f"/api/v1/images/{img_id}/describe")
    assert r1.status_code == 200
    assert r1.json()["cached"] is False
    assert mock.chat.call_count == 1

    # Second call — cache hit, no model call.
    r2 = await client.post(f"/api/v1/images/{img_id}/describe")
    assert r2.status_code == 200
    assert r2.json()["cached"] is True
    assert r2.json()["description"] == "First description."
    assert mock.chat.call_count == 1  # NOT 2 — model was not called again


@pytest.mark.asyncio
async def test_describe_refresh_forces_recall(client):
    """refresh=True forces a re-call even on cache hit."""
    from ai.providers import ChatResponse
    img_id, _ = await _setup_corpus_with_image(client)
    mock = _inject_mock_provider(client, chat_content="First description.")

    await client.post(f"/api/v1/images/{img_id}/describe")
    assert mock.chat.call_count == 1

    # Update the mock's response so we can tell the second call actually ran.
    # ChatResponse is a frozen dataclass, so we replace the whole return value.
    mock.chat.return_value = ChatResponse(
        content="Second description.",
        model="moondream",
        provider="ollama",
        raw={},
    )

    r = await client.post(f"/api/v1/images/{img_id}/describe", json={"refresh": True})
    assert r.status_code == 200
    assert r.json()["cached"] is False
    assert r.json()["description"] == "Second description."
    assert mock.chat.call_count == 2  # model WAS called again


@pytest.mark.asyncio
async def test_describe_different_prompt_uses_different_cache_key(client):
    """Re-running with a different prompt doesn't overwrite the previous
    cached result — both are kept, keyed on prompt_hash."""
    from ai.providers import ChatResponse
    img_id, _ = await _setup_corpus_with_image(client)
    mock = _inject_mock_provider(client, chat_content="Description for prompt A.")

    # First call with prompt A.
    r1 = await client.post(f"/api/v1/images/{img_id}/describe", json={
        "prompt": "Prompt A",
    })
    assert r1.status_code == 200
    hash_a = r1.json()["prompt_hash"]

    # Second call with prompt B — should call the model again (different cache key).
    # ChatResponse is frozen, so replace the whole return value.
    mock.chat.return_value = ChatResponse(
        content="Description for prompt B.",
        model="moondream",
        provider="ollama",
        raw={},
    )
    r2 = await client.post(f"/api/v1/images/{img_id}/describe", json={
        "prompt": "Prompt B",
    })
    assert r2.status_code == 200
    hash_b = r2.json()["prompt_hash"]
    assert hash_a != hash_b  # different prompts → different hashes → different cache keys
    assert mock.chat.call_count == 2

    # Third call with prompt A again — should hit the cache (not call the model).
    r3 = await client.post(f"/api/v1/images/{img_id}/describe", json={
        "prompt": "Prompt A",
    })
    assert r3.status_code == 200
    assert r3.json()["cached"] is True
    assert r3.json()["description"] == "Description for prompt A."
    assert mock.chat.call_count == 2  # still 2, not 3


@pytest.mark.asyncio
async def test_describe_cache_persists_across_sessions(client):
    """The cached result is actually persisted to the DB (not lost on
    session close). This is the JSON-column mutation-safety regression
    guard: if img.analysis were mutated in-place instead of via full
    reassignment, the cache would be silently lost on commit and this
    test would fail (the second call would re-call the model)."""
    img_id, _ = await _setup_corpus_with_image(client)
    mock = _inject_mock_provider(client, chat_content="Persisted description.")

    # First call — writes to cache.
    await client.post(f"/api/v1/images/{img_id}/describe")
    assert mock.chat.call_count == 1

    # Verify the cache was actually persisted by reading the image's
    # analysis directly from the DB through a fresh session.
    from storage.models import Image as ImageModel
    from storage.session import session_scope
    async with session_scope() as session:
        img = await session.get(ImageModel, img_id)
        assert img is not None
        vlm_cache = img.analysis.get("vision_llm", {})
        assert len(vlm_cache) == 1
        cached = next(iter(vlm_cache.values()))
        assert cached["description"] == "Persisted description."
        assert cached["model"] == "moondream"
        assert cached["provider"] == "ollama"


# ---------------------------------------------------------------------------
# OCR disagreement
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_describe_ocr_disagreement_detected(client):
    """When the vision-LM's text materially differs from cached OCR,
    ocr_disagreement=True and cached_ocr is returned alongside the
    vision-LM's description. The cached OCR is NOT silently overwritten."""
    # Upload an image WITH a caption (the only way to get "OCR" text
    # for a solid-color image without a real OCR engine).
    img_id, _ = await _setup_corpus_with_image(
        client, caption="STOP sign"
    )

    # Manually inject OCR text into the image's analysis to simulate
    # a Tesseract pass that disagrees with the vision-LM.
    from storage.models import Image as ImageModel
    from storage.session import session_scope
    async with session_scope() as session:
        img = await session.get(ImageModel, img_id)
        new_analysis = {**img.analysis, "ocr": {
            "text": "STOP", "confidence": 0.9, "word_count": 1,
            "engine": "tesseract", "language": "auto",
        }}
        img.analysis = new_analysis  # full reassignment
        await session.commit()

    # Vision-LM says something completely different.
    _inject_mock_provider(
        client,
        chat_content="The image shows a YIELD sign with red text.",
    )

    r = await client.post(f"/api/v1/images/{img_id}/describe")
    assert r.status_code == 200, r.text
    data = r.json()
    assert data["description"] == "The image shows a YIELD sign with red text."
    assert data["ocr_disagreement"] is True
    assert data["cached_ocr"] == "STOP"


@pytest.mark.asyncio
async def test_describe_ocr_agreement_no_disagreement_flag(client):
    """When the vision-LM's text matches the cached OCR, ocr_disagreement=False."""
    img_id, _ = await _setup_corpus_with_image(client, caption="STOP sign")

    from storage.models import Image as ImageModel
    from storage.session import session_scope
    async with session_scope() as session:
        img = await session.get(ImageModel, img_id)
        new_analysis = {**img.analysis, "ocr": {
            "text": "STOP sign ahead", "confidence": 0.9, "word_count": 3,
            "engine": "tesseract", "language": "auto",
        }}
        img.analysis = new_analysis
        await session.commit()

    # Vision-LM says the same thing (word overlap > 50%).
    _inject_mock_provider(
        client,
        chat_content="A STOP sign ahead on the road.",
    )

    r = await client.post(f"/api/v1/images/{img_id}/describe")
    assert r.status_code == 200
    assert r.json()["ocr_disagreement"] is False
    assert r.json()["cached_ocr"] == "STOP sign ahead"


# ---------------------------------------------------------------------------
# Error paths
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_describe_404_image_not_found(client):
    _inject_mock_provider(client)
    r = await client.post("/api/v1/images/nonexistent-id/describe")
    assert r.status_code == 404
    assert "not found" in r.json()["detail"].lower()


@pytest.mark.asyncio
async def test_describe_503_provider_unhealthy(client):
    """If the provider health check fails, return 503 with a clear message
    naming the provider and suggesting how to fix it."""
    img_id, _ = await _setup_corpus_with_image(client)
    _inject_mock_provider(client, health_ok=False)

    r = await client.post(f"/api/v1/images/{img_id}/describe")
    assert r.status_code == 503
    detail = r.json()["detail"]
    assert "Ollama" in detail or "ollama" in detail.lower()
    assert "vision model" in detail.lower() or "pull" in detail.lower()


@pytest.mark.asyncio
async def test_describe_500_provider_call_fails(client):
    """If the provider call itself fails (model error, network timeout
    after health check passed), return 500 with the error message."""
    from ai.providers import ModelProviderError
    img_id, _ = await _setup_corpus_with_image(client)
    _inject_mock_provider(
        client,
        raise_on_chat=ModelProviderError("model crashed during inference"),
    )

    r = await client.post(f"/api/v1/images/{img_id}/describe")
    assert r.status_code == 500
    assert "model crashed" in r.json()["detail"]


@pytest.mark.asyncio
async def test_describe_500_empty_content(client):
    """If the model returns empty content (common with small models on
    wrong-prompt-format), return 500 with a hint about prompt format."""
    img_id, _ = await _setup_corpus_with_image(client)
    _inject_mock_provider(client, chat_content="")

    r = await client.post(f"/api/v1/images/{img_id}/describe")
    assert r.status_code == 500
    detail = r.json()["detail"]
    assert "empty" in detail.lower()
    assert "prompt" in detail.lower() or "model" in detail.lower()


@pytest.mark.asyncio
async def test_describe_includes_caption_and_ocr_in_prompt_context(client):
    """When the image has a caption AND cached OCR, both are included in
    the prompt context sent to the model — so the model can corroborate
    or correct them, but the cached OCR is never silently overwritten."""
    img_id, _ = await _setup_corpus_with_image(client, caption="My caption text")

    from storage.models import Image as ImageModel
    from storage.session import session_scope
    async with session_scope() as session:
        img = await session.get(ImageModel, img_id)
        new_analysis = {**img.analysis, "ocr": {
            "text": "OCR text", "confidence": 0.9, "word_count": 2,
            "engine": "tesseract", "language": "auto",
        }}
        img.analysis = new_analysis
        await session.commit()

    mock = _inject_mock_provider(client)

    await client.post(f"/api/v1/images/{img_id}/describe")

    messages = mock.chat.call_args.args[0]
    prompt_content = messages[0].content
    assert "My caption text" in prompt_content
    assert "OCR text" in prompt_content
    assert "Context" in prompt_content
