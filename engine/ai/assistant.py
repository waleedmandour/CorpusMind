"""
Grounded-AI Assistant scaffold (§11).

Phase 0 ships the *plumbing*: tool registry, conversation audit trail, and the
"every claim must be grounded or visibly flagged" rendering contract. The
actual tool implementations (search_concordance, compute_collocations, ...)
land in Phase 1 alongside the stats engine (§12).

The scaffold is fully exercisable today via the /api/v1/ai/chat round-trip:
  - user sends a message
  - assistant selects between "tool-calling turn" and "free answer"
  - if free answer, the response is marked `grounded: false` and the UI MUST
    render it with a visible "ungrounded" badge (§11.1, load-bearing).
"""
from __future__ import annotations

import json
import time
import uuid
from dataclasses import asdict, dataclass, field
from typing import Any, Awaitable, Callable, Literal

from app.logging import get_logger
from ai.providers import ChatResponse, Message, ModelProvider

log = get_logger(__name__)

ToolFn = Callable[..., Awaitable[Any]]


# --------------------------------------------------------------------------- #
# Tool registry
# --------------------------------------------------------------------------- #


@dataclass(frozen=True, slots=True)
class ToolSpec:
    name: str
    description: str
    parameters: dict[str, Any]  # JSON-schema fragment
    fn: ToolFn


class ToolRegistry:
    """
    Holds the deterministic engine functions the model is allowed to call.
    In Phase 0 only `ping` is registered — enough to prove the round-trip.
    """

    def __init__(self) -> None:
        self._tools: dict[str, ToolSpec] = {}
        self.register(ToolSpec(
            name="ping",
            description="Health-check tool. Returns the engine version and current time. Use this to verify tool-calling works.",
            parameters={"type": "object", "properties": {}},
            fn=self._ping,
        ))

    def register(self, spec: ToolSpec) -> None:
        self._tools[spec.name] = spec

    def schemas(self) -> list[dict[str, Any]]:
        return [
            {"type": "function", "function": {"name": s.name, "description": s.description, "parameters": s.parameters}}
            for s in self._tools.values()
        ]

    async def call(self, name: str, args: dict[str, Any]) -> Any:
        spec = self._tools.get(name)
        if not spec:
            raise KeyError(f"Unknown tool: {name}")
        return await spec.fn(**args)

    async def _ping(self) -> dict[str, Any]:
        return {"ok": True, "engine": "corpusmind-engine", "ts": time.time()}


# --------------------------------------------------------------------------- #
# Conversation audit trail (§4.8, §11.1)
# --------------------------------------------------------------------------- #


@dataclass
class Evidence:
    kind: Literal["concordance_line", "stat", "image_region", "tool_result"]
    ref: str  # stable ID, e.g. "line:42" or "stat:ll:node=bank"
    snippet: str = ""


@dataclass
class AssistantTurn:
    role: Literal["assistant"] = "assistant"
    content: str = ""
    grounded: bool = False
    evidence: list[Evidence] = field(default_factory=list)
    tool_calls: list[dict[str, Any]] = field(default_factory=list)
    elapsed_ms: int = 0


@dataclass
class Conversation:
    id: str = field(default_factory=lambda: uuid.uuid4().hex[:12])
    messages: list[Message] = field(default_factory=list)
    turns: list[AssistantTurn] = field(default_factory=list)
    provider: str = "ollama"
    model: str = ""

    def append_user(self, content: str) -> None:
        self.messages.append(Message(role="user", content=content))

    def append_system(self, content: str) -> None:
        # system messages are always prepended — keeps the prompt template at the front
        self.messages.insert(0, Message(role="system", content=content))

    def to_export(self) -> dict[str, Any]:
        return {
            "id": self.id,
            "provider": self.provider,
            "model": self.model,
            "messages": [asdict(m) for m in self.messages],
            "turns": [asdict(t) for t in self.turns],
        }


# --------------------------------------------------------------------------- #
# Assistant
# --------------------------------------------------------------------------- #


class Assistant:
    """
    Orchestrates one grounded chat round-trip.

    Phase 0 policy (kept deliberately simple — Phase 1 adds true tool-calling
    loop + RAG retrieval):
      1. Prepend the grounded-AI system prompt (§11.1).
      2. Call the model with the registered tools available.
      3. If the model returned a tool call, execute it, append the result, and
         re-prompt the model for a natural-language answer.
      4. Mark the answer `grounded=True` iff at least one tool was actually
         invoked during this turn. Otherwise `grounded=False` — the UI MUST
         surface this (§11.1, load-bearing).
    """

    SYSTEM_PROMPT = (
        "You are the CorpusMind AI Assistant. You are a tool-using agent, NOT a chatbot.\n"
        "Rules:\n"
        "1. Every empirical claim you make (about word frequencies, collocations, "
        "keyness, image content, etc.) MUST come from a tool call. If you have not "
        "called a tool for a claim, do not make the claim.\n"
        "2. If a user asks something you cannot ground in a tool result, say so "
        "explicitly: 'I cannot ground this in corpus evidence — answering from parametric "
        "memory only.' The UI will mark your answer as ungrounded.\n"
        "3. Interpretive claims (CDA, ideology, power, metaphor) MUST be phrased as "
        "framework-lensed hypotheses — 'Under a [Framework] reading, X may indicate Y' — "
        "never as bare assertions of fact (§4 Principle 5).\n"
        "4. Never state ideology, bias, or power relations as settled fact.\n"
        "5. Cite evidence IDs verbatim from tool results when you reference them.\n"
    )

    def __init__(self, provider: ModelProvider, tools: ToolRegistry, *, model: str | None = None) -> None:
        self.provider = provider
        self.tools = tools
        self.model = model

    async def answer(self, convo: Conversation, user_text: str) -> AssistantTurn:
        convo.append_user(user_text)
        # ensure the system prompt is in place (idempotent)
        if not convo.messages or convo.messages[0].role != "system":
            convo.append_system(self.SYSTEM_PROMPT)

        started = time.perf_counter()
        tool_calls: list[dict[str, Any]] = []
        evidence: list[Evidence] = []
        content = ""

        # Pass 1: ask the model — it may emit a tool call or a direct answer.
        first = await self.provider.chat(
            convo.messages,
            model=self.model,
            temperature=0.2,
            tools=self.tools.schemas(),
        )
        content = first.content

        # OpenAI-compatible tool_calls (Ollama + LM Studio both speak this).
        tool_call_reqs = (first.raw.get("choices", [{}])[0]
                          .get("message", {})
                          .get("tool_calls", []))

        if tool_call_reqs:
            # Execute every requested tool, append results to the conversation,
            # then ask the model for a final grounded answer.
            convo.messages.append(Message(role="assistant", content=content or "(tool call)"))
            for req in tool_call_reqs:
                fn = req.get("function", {})
                name = fn.get("name", "")
                raw_args = fn.get("arguments", "{}")
                try:
                    args = json.loads(raw_args) if isinstance(raw_args, str) else (raw_args or {})
                except json.JSONDecodeError:
                    args = {}
                try:
                    result = await self.tools.call(name, args)
                    tool_calls.append({"name": name, "args": args, "ok": True})
                    evidence.append(Evidence(
                        kind="tool_result",
                        ref=f"tool:{name}:{len(tool_calls)}",
                        snippet=json.dumps(result)[:500],
                    ))
                    convo.messages.append(Message(role="tool", content=json.dumps(result), name=name))
                except Exception as e:
                    tool_calls.append({"name": name, "args": args, "ok": False, "error": str(e)})
                    convo.messages.append(Message(role="tool", content=f"ERROR: {e}", name=name))

            # Pass 2: grounded final answer
            final = await self.provider.chat(convo.messages, model=self.model, temperature=0.2)
            content = final.content

        elapsed = int((time.perf_counter() - started) * 1000)
        turn = AssistantTurn(
            content=content,
            grounded=bool(tool_calls),
            evidence=evidence,
            tool_calls=tool_calls,
            elapsed_ms=elapsed,
        )
        convo.turns.append(turn)
        convo.messages.append(Message(role="assistant", content=content))
        log.info("assistant_turn",
                 conversation=convo.id,
                 grounded=turn.grounded,
                 tools=[t["name"] for t in tool_calls],
                 ms=elapsed)
        return turn
