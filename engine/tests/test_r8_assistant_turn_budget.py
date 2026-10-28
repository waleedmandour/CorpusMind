"""v1.2.14-8 (r8) — the assistant turn budget must never destroy a finished
answer (P0-2 field report).

r7 behaviour: ``assistant.answer`` ran pass1 + final + assess_confidence +
generate_mcqs SEQUENTIALLY and only PERSISTED the turn at the very end.
The 180 s overall deadline wrapped the whole chain, so a slow confidence
step (a) delayed the answer, and (b) when the deadline fired,
``asyncio.wait_for`` cancelled the coroutine — discarding a COMPLETED
answer and leaving the turn unpersisted. The user lost everything.

The r8 contract pinned here (fail-before / pass-after):

  1. A local provider turn reaches the client after pass1 + final ONLY —
     the confidence layer is skipped for local models by default
     (confidence_layer="auto"), so it can never delay or discard anything.
  2. With the confidence layer force-enabled and a pathologically slow
     confidence call, the answer is STILL persisted and returned: the
     layer runs under its own short cap, and on the overall deadline the
     endpoint returns the persisted partial answer (HTTP 200) instead of
     a bare 504.
  3. When the MODEL itself hangs (no answer exists), the endpoint still
     answers 504 and invents nothing — the guard that keeps the partial
     path honest.

The provider is a scripted stub swapped into app.state.providers, the same
harness as test_ai_chat_endpoint_e2e.py. ``ping`` is the cheapest real
tool, so the grounded path runs end-to-end without a corpus.
"""
from __future__ import annotations

import asyncio
import json
import os
import time
from collections.abc import AsyncIterator, Iterator
from typing import Any

import pytest
from httpx import ASGITransport, AsyncClient

os.environ["CORPUSMIND_DB_URL"] = "sqlite+aiosqlite:///:memory:"
os.environ["CORPUSMIND_DATA_DIR"] = "/tmp/cm-test-r8-budget"
from app.settings import get_settings

get_settings.cache_clear()

from ai.providers import ChatResponse as ProviderChatResponse  # noqa: E402

FINAL_ANSWER = "GROUND ANSWER 42"


class _ScriptedProvider:
    """Scripted provider: chat calls pop a step; chat_json (the confidence
    layer's entry point) sleeps for ``conf_delay`` seconds."""

    name = "ollama"

    def __init__(self, chat_delay: float = 0.05, conf_delay: float = 30.0) -> None:
        self.chat_delay = chat_delay
        self.conf_delay = conf_delay
        self.chat_calls = 0
        self.chat_json_calls = 0
        self._script: list[str] = ["tools", "final"]

    def script(self, steps: list[str]) -> None:
        self._script = list(steps)

    async def health(self) -> bool:
        return True

    async def supports_tools(self, model: str | None = None) -> bool:
        return True

    async def pick_default_model(self) -> str | None:
        return "fake-chat-model"

    async def chat(self, messages: list[Any], **kwargs: Any) -> ProviderChatResponse:
        self.chat_calls += 1
        step = self._script.pop(0) if self._script else "final"
        await asyncio.sleep(self.chat_delay)
        if step == "tools":
            return ProviderChatResponse(
                content="",
                model="fake-chat-model",
                provider=self.name,
                raw={"choices": [{"message": {"tool_calls": [{
                    "function": {"name": "ping", "arguments": "{}"},
                }]}}]},
            )
        if step == "hang":
            await asyncio.sleep(300)
        return ProviderChatResponse(
            content=FINAL_ANSWER, model="fake-chat-model", provider=self.name, raw={},
        )

    async def chat_json(self, messages: list[Any], **kwargs: Any) -> ProviderChatResponse:
        self.chat_json_calls += 1
        await asyncio.sleep(self.conf_delay)
        return ProviderChatResponse(
            content=json.dumps({"confidence": 0.2, "reasoning": "slow layer",
                                "unsupported_claims": ["x"]}),
            model="fake-chat-model", provider=self.name, raw={},
        )


class _StubRegistry:
    def __init__(self, provider: _ScriptedProvider) -> None:
        self._provider = provider

    def get(self, name: str | None = None) -> _ScriptedProvider:
        return self._provider


@pytest.fixture
async def client() -> AsyncIterator[AsyncClient]:
    from app.main import app
    from storage.session import dispose_db

    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as ac:
        async with app.router.lifespan_context(app):
            yield ac
    await dispose_db()


@pytest.fixture(autouse=True)
def _auto_confidence_layer(monkeypatch: pytest.MonkeyPatch) -> Iterator[None]:
    """Pin the default (auto) policy; monkeypatch restores the singleton."""
    s = get_settings()
    try:
        monkeypatch.setattr(s, "confidence_layer", "auto")
    except Exception:
        pass  # r7 Settings has no confidence_layer field yet (fail-before)
    yield


def _swap_provider(monkeypatch: pytest.MonkeyPatch, provider: _ScriptedProvider) -> None:
    from app.main import app

    monkeypatch.setattr(app.state, "providers", _StubRegistry(provider))


# --------------------------------------------------------------------------- #
# 1. Local default: the answer arrives after pass1 + final; confidence never
# --------------------------------------------------------------------------- #


async def test_local_turn_skips_confidence_layer(
    client: AsyncClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    provider = _ScriptedProvider(chat_delay=0.05)
    provider.script(["tools", "final"])
    _swap_provider(monkeypatch, provider)

    t0 = time.perf_counter()
    r = await client.post("/api/v1/ai/chat", json={
        "message": "What is the frequency of ocean in the corpus?",
        "provider": "ollama",
    })
    elapsed = time.perf_counter() - t0

    assert r.status_code == 200, r.text
    body = r.json()
    assert body["content"] == FINAL_ANSWER
    assert body["turn_id"] is not None, "the answer turn must be persisted"
    # The contract: exactly TWO model calls reach the client (pass1 + final).
    assert provider.chat_calls == 2, provider.chat_calls
    # r7 BUG: assess_confidence (one more full LLM call) ran on EVERY
    # grounded local turn before the response was built.
    assert provider.chat_json_calls == 0, "confidence layer must be skipped for local providers by default"
    assert elapsed < 10.0, f"local grounded turn took {elapsed:.1f}s — the confidence layer is delaying it"


# --------------------------------------------------------------------------- #
# 2. Force-enabled + slow confidence: answer persisted and returned anyway
# --------------------------------------------------------------------------- #


async def test_slow_confidence_never_discards_the_answer(
    client: AsyncClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    from storage.session import session_scope

    provider = _ScriptedProvider(chat_delay=0.2, conf_delay=30.0)
    provider.script(["tools", "final"])
    _swap_provider(monkeypatch, provider)

    s = get_settings()
    try:
        monkeypatch.setattr(s, "confidence_layer", "on")
    except Exception:
        pass  # r7 Settings has no confidence_layer field yet (fail-before)
    old_deadline = app_module_deadline()
    set_module_deadline(3.0)
    try:
        t0 = time.perf_counter()
        r = await client.post("/api/v1/ai/chat", json={
            "message": "What is the frequency of ocean in the corpus?",
            "provider": "ollama",
        })
        elapsed = time.perf_counter() - t0
    finally:
        try:
            monkeypatch.setattr(s, "confidence_layer", "auto")
        except Exception:
            pass
        set_module_deadline(old_deadline)
    assert r.status_code == 200, (
        f"a completed answer must be returned, not a bare 504 (elapsed {elapsed:.1f}s)"
    )
    body = r.json()
    assert body["content"] == FINAL_ANSWER
    assert body["turn_id"] is not None
    assert elapsed < 15.0, f"the slow confidence step delayed the answer {elapsed:.1f}s"

    # And the turn must be in the conversation history (persist-FIRST).
    convo_id = body["conversation_id"]
    async with session_scope() as session:
        from sqlalchemy import select

        from storage.models import ConversationTurn

        rows = (
            (await session.execute(
                select(ConversationTurn).where(ConversationTurn.conversation_id == convo_id)
            )).scalars().all()
        )
    roles = sorted(t.role for t in rows)
    assert roles == ["assistant", "user"], roles
    assert any(t.content == FINAL_ANSWER for t in rows)


async def test_partial_answer_flag_on_deadline_recovery(
    client: AsyncClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    """The deadline-recovery response is honestly flagged as partial."""

    provider = _ScriptedProvider(chat_delay=0.2, conf_delay=30.0)
    provider.script(["tools", "final"])
    _swap_provider(monkeypatch, provider)

    s = get_settings()
    try:
        monkeypatch.setattr(s, "confidence_layer", "on")
    except Exception:
        pass  # r7 Settings has no confidence_layer field yet (fail-before)
    old_deadline = app_module_deadline()
    set_module_deadline(3.0)
    try:
        r = await client.post("/api/v1/ai/chat", json={
            "message": "What is the frequency of ocean in the corpus?",
            "provider": "ollama",
        })
    finally:
        try:
            monkeypatch.setattr(s, "confidence_layer", "auto")
        except Exception:
            pass
        set_module_deadline(old_deadline)

    assert r.status_code == 200
    body = r.json()
    assert body.get("partial") is True, "a deadline-recovered answer must carry partial=true"
    assert body["confidence_assessed"] is False


# --------------------------------------------------------------------------- #
# 3. A hung MODEL still means 504 — the partial path invents nothing
# --------------------------------------------------------------------------- #


async def test_hung_model_still_times_out_with_504(
    client: AsyncClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    provider = _ScriptedProvider(chat_delay=0.1)
    provider.script(["hang"])
    _swap_provider(monkeypatch, provider)

    old_deadline = app_module_deadline()
    set_module_deadline(1.0)
    try:
        t0 = time.perf_counter()
        r = await client.post("/api/v1/ai/chat", json={
            "message": "What is the frequency of ocean in the corpus?",
            "provider": "ollama",
        })
        elapsed = time.perf_counter() - t0
    finally:
        set_module_deadline(old_deadline)

    assert r.status_code == 504
    assert elapsed < 10.0
    body = r.json()
    assert "chat_timeout" in body.get("error", "")


# --- helpers over the api.ai module deadline constant ----------------------- #


def app_module_deadline() -> float:
    from api import ai as ai_module

    return ai_module._CHAT_TIMEOUT_S


def set_module_deadline(value: float) -> None:
    from api import ai as ai_module

    ai_module._CHAT_TIMEOUT_S = value
