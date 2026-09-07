"""End-to-end coverage for POST /api/v1/ai/chat — the endpoint both desktop
apps (CorpusMind and CorpusMind Lens) call for the grounded AI assistant.

Why this file exists (v1.0.10): every piece around this endpoint was unit
tested — system-prompt snapshot injection (assistant tests), the cross-modal
corpus-overview tool (test_assistant_vision_tools), provider behaviour
(test_vision_providers) — but nothing exercised the real route end to end.
These tests assemble the whole thing over a real HTTP round trip (httpx
ASGITransport against the actual FastAPI app, with its lifespan running):

  1. A plain chat round trip returns the response shape the frontend
     expects, auto-selects a model via the provider, and persists the
     conversation and both turns (user + assistant) to the database.
  2. A corpus shared between the two apps — an annotated text document AND
     an analysed image set, exactly what using the same project in
     CorpusMind and then CorpusMind Lens produces — grounds the actual
     system prompt the model receives: the token count from the text side,
     the image-set name from the vision side, and the explicit
     cross-modal instruction.
  3. An unknown provider name returns a clean 400, not a crash.

The provider is a recording stub swapped into app.state.providers for tests
1 and 2. The endpoint health-gates on provider.health() BEFORE .chat() is
ever reached (and auto-selects the model via pick_default_model() before
that), so a stub that only fakes .chat() dies at the 503 gate — those two
methods are stubbed too. Test 3 deliberately uses the REAL registry so the
production unknown-provider path is what's exercised.

Uses a file-based SQLite DB (answer() and execute_tool() open their own
session_scope — same reason as the Lens round tests).
"""
from __future__ import annotations

import os
import uuid
from datetime import UTC, datetime

import pytest
from httpx import ASGITransport, AsyncClient

_DB_FILE = "/tmp/cm-test-ai-chat-e2e.db"
if os.path.exists(_DB_FILE):
    os.remove(_DB_FILE)
os.environ["CORPUSMIND_DB_URL"] = f"sqlite+aiosqlite:///{_DB_FILE}"
os.environ["CORPUSMIND_DATA_DIR"] = "/tmp/cm-test-data-aichat-e2e"
from app.settings import get_settings  # noqa: E402 — env must be set first

get_settings.cache_clear()


REPLY = "Test reply: this answer is grounded in the corpus snapshot."


@pytest.fixture
async def client():
    from app.main import app
    from storage.session import dispose_db

    if os.path.exists(_DB_FILE):
        os.remove(_DB_FILE)
    get_settings.cache_clear()
    await dispose_db()
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as ac:
        async with app.router.lifespan_context(app):
            yield ac
    await dispose_db()
    if os.path.exists(_DB_FILE):
        os.remove(_DB_FILE)


# --------------------------------------------------------------------------- #
# Recording provider stub
# --------------------------------------------------------------------------- #


class _RecordingProvider:
    """Ollama stand-in that records every chat() call's message list.

    Mirrors the ModelProvider surface the /chat endpoint actually touches:
    health() (the 503 gate), pick_default_model() (auto-selection),
    supports_tools() (capability gate) and chat().
    """

    name = "ollama"
    default_model = "llama3.2:3b"

    def __init__(self) -> None:
        self.calls: list[dict] = []

    async def health(self) -> bool:
        return True

    async def pick_default_model(self) -> str | None:
        return "llama3.2:3b"

    async def supports_tools(self, model: str | None = None) -> bool:
        return True

    async def list_models(self) -> list[str]:
        return ["llama3.2:3b"]

    async def chat(self, messages, model=None, temperature=0.2, tools=None):
        from ai.providers import ChatResponse

        self.calls.append(
            {
                "messages": [(m.role, m.content) for m in messages],
                "model": model,
                "tools": tools,
            }
        )
        return ChatResponse(
            content=REPLY, model=model or "llama3.2:3b", provider="ollama", raw={}
        )


class _StubRegistry:
    """Duck-typed ProviderRegistry: hands out the recording provider, raises
    for anything else (same contract as ProviderRegistry.get)."""

    def __init__(self, provider: _RecordingProvider) -> None:
        self._provider = provider

    def get(self, name: str | None = None):
        if (name or "ollama").lower() == "ollama":
            return self._provider
        from ai.providers import ModelProviderError

        raise ModelProviderError(f"Unknown model provider: {name}")


def _swap_provider(monkeypatch, provider: _RecordingProvider) -> None:
    from app.main import app

    monkeypatch.setattr(app.state, "providers", _StubRegistry(provider))


# --------------------------------------------------------------------------- #
# Cross-modal seeding (the shared-corpus scenario)
# --------------------------------------------------------------------------- #


async def _seed_shared_corpus() -> str:
    """Project + corpus + annotated text document + analysed image set —
    exactly the state a project reaches by being used in CorpusMind (text)
    and then CorpusMind Lens (images). Returns the corpus id."""
    from storage.models import AnnotationVersion, Corpus, Document, Image, ImageSet, Project
    from storage.session import session_scope

    pid = uuid.uuid4().hex[:16]
    cid = uuid.uuid4().hex[:16]
    sid = uuid.uuid4().hex[:16]
    async with session_scope() as s:
        s.add(Project(id=pid, name="E2E chat project", language="en"))
        s.add(Corpus(id=cid, project_id=pid, name="E2E shared corpus", language="en"))
        # Text side: a document plus its (latest) annotation version.
        s.add(Document(id=uuid.uuid4().hex[:16], corpus_id=cid, filename="doc1.txt"))
        s.add(
            AnnotationVersion(
                id=uuid.uuid4().hex[:16],
                corpus_id=cid,
                token_count=1234,
                type_count=321,
                sentence_count=45,
            )
        )
        # Vision side: an image set with two analysed images (cached OCR +
        # vision-LM descriptions, as produced by the Lens analysis pipeline).
        s.add(ImageSet(id=sid, corpus_id=cid, name="Front pages 2026"))
        for i in range(2):
            s.add(
                Image(
                    id=uuid.uuid4().hex[:16],
                    image_set_id=sid,
                    filename=f"front{i}.png",
                    analysis={
                        "ocr": {
                            "text": f"Breaking news headline {i}",
                            "confidence": 0.9,
                            "word_count": 4,
                            "engine": "tesseract",
                            "language": "eng",
                        },
                        "vision_llm": {
                            "default:abc": {
                                "description": f"Image {i} shows a protest crowd.",
                                "model": "qwen3-vl:2b",
                                "provider": "ollama",
                                "prompt": "Describe this image.",
                                "prompt_hash": "abc",
                                "timestamp": datetime.now(UTC).isoformat(),
                            }
                        },
                    },
                )
            )
    return cid


# --------------------------------------------------------------------------- #
# 1. The assembled endpoint: request -> gate -> assistant -> persistence
# --------------------------------------------------------------------------- #


@pytest.mark.asyncio
async def test_chat_round_trip_returns_frontend_shape(client, monkeypatch):
    provider = _RecordingProvider()
    _swap_provider(monkeypatch, provider)

    r = await client.post("/api/v1/ai/chat", json={"message": "hello", "provider": "ollama"})
    assert r.status_code == 200, r.text

    body = r.json()
    # The exact ChatResponse fields AssistantView/FloatingAssistant consume.
    for key in (
        "conversation_id",
        "turn_id",
        "content",
        "grounded",
        "tool_calls",
        "evidence",
        "elapsed_ms",
        "provider",
        "model",
        "confidence",
        "confidence_reasoning",
        "needs_validation",
        "mcqs",
    ):
        assert key in body, f"missing response field: {key}"

    assert body["content"] == REPLY
    assert body["provider"] == "ollama"
    # Model auto-selection ran (endpoint called pick_default_model, not the
    # frontend): the request sent no model, the response carries one.
    assert body["model"] == "llama3.2:3b"
    assert body["grounded"] is False
    assert body["tool_calls"] == []
    assert body["evidence"] == []
    assert isinstance(body["elapsed_ms"], int) and body["elapsed_ms"] >= 0
    # Issue 5 fix: the persisted turn id must come back so the frontend can
    # call POST /research/turns/{turn_id}/verify.
    assert body["turn_id"] is not None

    # The model really was asked exactly once, through the recording stub.
    assert len(provider.calls) == 1
    roles = [role for role, _content in provider.calls[0]["messages"]]
    assert roles[0] == "system"
    assert roles[-1] == "user"

    # Both turns are persisted and retrievable via the conversations route.
    convo_id = body["conversation_id"]
    r2 = await client.get(f"/api/v1/ai/conversations/{convo_id}")
    assert r2.status_code == 200, r2.text
    turns = sorted(r2.json()["turns"], key=lambda t: t["idx"])
    assert [t["role"] for t in turns] == ["user", "assistant"]
    assert turns[0]["content"] == "hello"
    assert turns[1]["content"] == REPLY
    assert turns[1]["id"] == body["turn_id"]


# --------------------------------------------------------------------------- #
# 2. Cross-modal grounding: the system prompt the model actually receives
# --------------------------------------------------------------------------- #


@pytest.mark.asyncio
async def test_chat_cross_modal_system_prompt_grounding(client, monkeypatch):
    corpus_id = await _seed_shared_corpus()
    provider = _RecordingProvider()
    _swap_provider(monkeypatch, provider)

    r = await client.post(
        "/api/v1/ai/chat",
        json={"message": "hello", "provider": "ollama", "corpus_id": corpus_id},
    )
    assert r.status_code == 200, r.text
    assert r.json()["content"] == REPLY
    assert len(provider.calls) == 1

    system_prompt = provider.calls[0]["messages"][0][1]
    # The live corpus snapshot section was injected into the system prompt.
    assert "Current corpus snapshot" in system_prompt
    # Text side made it in: the annotation's token count.
    assert "1234" in system_prompt
    # Vision side made it in: the image-set name.
    assert "Front pages 2026" in system_prompt
    # The corpus identity flows through so the model can pass corpus_id to tools.
    assert corpus_id in system_prompt
    # The snapshot's cross-modal note (both sides populated) is included.
    assert "BOTH text documents and image sets" in system_prompt
    # And the static cross-modal instruction from the system prompt itself.
    assert "interpret them together" in system_prompt


# --------------------------------------------------------------------------- #
# 3. Unknown provider: clean 400 via the real registry
# --------------------------------------------------------------------------- #


@pytest.mark.asyncio
async def test_chat_unknown_provider_returns_400(client):
    # No stub here: the real ProviderRegistry raises ModelProviderError for
    # unknown names, which the endpoint must translate into a clean 400.
    r = await client.post(
        "/api/v1/ai/chat",
        json={"message": "hello", "provider": "not-a-real-provider"},
    )
    assert r.status_code == 400, r.text
    assert "not-a-real-provider" in r.json()["detail"]
