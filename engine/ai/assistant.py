"""
Grounded-AI Assistant (§11) — Phase 1.

Differences from Phase 0:
  - Tool surface expanded: search_concordance, get_frequency,
    compute_collocations, compute_keyness, get_dispersion, ping.
  - Conversations persist in SQLite (storage.Conversation / ConversationTurn).
  - Each tool call opens its own DB session (the model doesn't get to
    see the request-scoped one).
  - Evidence is structured: {kind, ref, snippet} per tool result.
"""
from __future__ import annotations

import json
import time
from dataclasses import dataclass, field
from typing import Any, Literal

from sqlalchemy.ext.asyncio import AsyncSession

from ai.providers import Message, ModelProvider
from ai.tools import execute_tool, schemas_for_llm
from app.logging import get_logger
from storage.models import Conversation, ConversationTurn

log = get_logger(__name__)


@dataclass
class Evidence:
    kind: Literal["concordance_line", "stat", "image_region", "tool_result"]
    ref: str
    snippet: str = ""


@dataclass
class AssistantTurn:
    role: Literal["assistant"] = "assistant"
    content: str = ""
    grounded: bool = False
    evidence: list[Evidence] = field(default_factory=list)
    tool_calls: list[dict[str, Any]] = field(default_factory=list)
    elapsed_ms: int = 0
    # Confidence layer (deterministic interpretation)
    confidence: float = 1.0
    confidence_reasoning: str = ""
    needs_validation: bool = False
    mcqs: list[dict[str, Any]] = field(default_factory=list)


class Assistant:
    """Tool-using agent. The LLM is given the registered tools and may call
    them; each call's result is appended to the conversation and cited in
    the final answer. If no tool is called, `grounded: false` — the UI MUST
    render the ungrounded badge (§11.1, load-bearing)."""

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
        "5. Cite evidence IDs verbatim from tool results when you reference them "
        "(e.g. 'line doc-abc:5:12' or 'frequency row for \"the\"').\n"
        "6. For collocations, always state the window size and minimum frequency.\n"
        "7. For keyness, always pair significance (log-likelihood) with effect size "
        "(Log Ratio or %DIFF) — never report significance alone.\n"
    )

    def __init__(self, provider: ModelProvider, *, model: str | None = None,
                 corpus_id: str | None = None) -> None:
        self.provider = provider
        self.model = model
        self.corpus_id = corpus_id

    async def answer(self, session: AsyncSession, convo: Conversation, user_text: str) -> AssistantTurn:
        """One grounded chat round-trip. Persists the user turn + assistant turn."""

        # Append the user message
        user_turn = ConversationTurn(
            conversation_id=convo.id,
            idx=len(convo.turns),
            role="user",
            content=user_text,
            grounded=False,
        )
        session.add(user_turn)
        # CRITICAL: Flush + commit before calling the LLM provider.
        # The LLM provider does a sync HTTP call (httpx) which blocks the
        # event loop. If the SQLAlchemy AsyncSession has pending greenlets
        # at this point, the sync call triggers "greenlet_spawn has not been
        # called; can't call await_only() here" — because the sync IO
        # happens in a different greenlet context.
        # By flushing + committing first, we ensure all pending DB operations
        # are complete before the blocking LLM call.
        await session.flush()
        await session.commit()

        # Build the LLM message list
        # If corpus_id is set, prepend a system hint about which corpus is active
        corpus_hint = (
            f"\n\nThe user is currently working with corpus_id={self.corpus_id}. "
            f"Pass this corpus_id to tools that need it."
            if self.corpus_id else ""
        )
        messages: list[Message] = [Message(role="system", content=self.SYSTEM_PROMPT + corpus_hint)]
        # Replay prior turns
        for t in convo.turns:
            if t.role == "user":
                messages.append(Message(role="user", content=t.content))
            elif t.role == "assistant":
                messages.append(Message(role="assistant", content=t.content))
        messages.append(Message(role="user", content=user_text))

        started = time.perf_counter()
        tool_calls: list[dict[str, Any]] = []
        evidence: list[Evidence] = []
        content = ""

        # Pass 1: ask the model — it may emit a tool call or a direct answer.
        first = await self.provider.chat(
            messages,
            model=self.model,
            temperature=0.2,
            tools=schemas_for_llm(),
        )
        content = first.content

        tool_call_reqs = (first.raw.get("choices", [{}])[0]
                          .get("message", {})
                          .get("tool_calls", []))

        if tool_call_reqs:
            # Append the assistant's tool-call message
            messages.append(Message(role="assistant", content=content or "(tool call)"))

            for req in tool_call_reqs:
                fn = req.get("function", {})
                name = fn.get("name", "")
                raw_args = fn.get("arguments", "{}")
                try:
                    args = json.loads(raw_args) if isinstance(raw_args, str) else (raw_args or {})
                except json.JSONDecodeError:
                    args = {}

                # Auto-inject corpus_id if the tool needs it and the model omitted it
                if self.corpus_id and "corpus_id" in _tool_param_names(name):
                    if "corpus_id" not in args:
                        args["corpus_id"] = self.corpus_id

                try:
                    result = await execute_tool(name, args)
                    tool_calls.append({"name": name, "args": args, "ok": True})
                    # Build evidence references from the result
                    if name == "search_concordance" and "lines" in result:
                        for line in result["lines"][:5]:  # cite first 5 lines
                            evidence.append(Evidence(
                                kind="concordance_line",
                                ref=f"line:{line['line_id']}",
                                snippet=f"{line['left']} [{line['node']}] {line['right']}",
                            ))
                    else:
                        evidence.append(Evidence(
                            kind="tool_result",
                            ref=f"tool:{name}:{len(tool_calls)}",
                            snippet=json.dumps(result)[:500],
                        ))
                    messages.append(Message(role="tool", content=json.dumps(result), name=name))
                except Exception as e:
                    tool_calls.append({"name": name, "args": args, "ok": False, "error": str(e)})
                    messages.append(Message(role="tool", content=f"ERROR: {e}", name=name))

            # Pass 2: grounded final answer
            final = await self.provider.chat(messages, model=self.model, temperature=0.2)
            content = final.content

        elapsed = int((time.perf_counter() - started) * 1000)

        # Confidence layer: assess how well the interpretation is supported
        # by the retrieved evidence. If confidence is low, generate MCQs
        # for the user to validate before the interpretation is revealed.
        confidence = 1.0
        confidence_reasoning = ""
        needs_validation = False
        mcqs: list[dict[str, Any]] = []

        if tool_calls and evidence:
            try:
                from ai.confidence import assess_confidence, generate_mcqs, needs_user_validation
                evidence_dicts = [{"kind": e.kind, "ref": e.ref, "snippet": e.snippet} for e in evidence]
                conf_result = await assess_confidence(
                    self.provider, self.model, user_text, evidence_dicts, content,
                )
                confidence = conf_result.get("confidence", 0.5)
                confidence_reasoning = conf_result.get("reasoning", "")
                if needs_user_validation(confidence):
                    needs_validation = True
                    mcqs = await generate_mcqs(
                        self.provider, self.model, user_text,
                        evidence_dicts, content,
                        conf_result.get("unsupported_claims", []),
                    )
                    log.info("confidence_low",
                             confidence=confidence,
                             mcqs=len(mcqs),
                             unsupported=len(conf_result.get("unsupported_claims", [])))
                else:
                    log.info("confidence_ok", confidence=confidence)
            except Exception as e:
                log.warning("confidence_layer_error", error=str(e))
                # Non-fatal — continue without confidence assessment

        turn = AssistantTurn(
            content=content,
            grounded=bool(tool_calls),
            evidence=evidence,
            tool_calls=tool_calls,
            elapsed_ms=elapsed,
            confidence=confidence,
            confidence_reasoning=confidence_reasoning,
            needs_validation=needs_validation,
            mcqs=mcqs,
        )

        # Persist the assistant turn
        at = ConversationTurn(
            conversation_id=convo.id,
            idx=len(convo.turns) + 1,
            role="assistant",
            content=content,
            grounded=turn.grounded,
            tool_calls=tool_calls,
            evidence=[{"kind": e.kind, "ref": e.ref, "snippet": e.snippet} for e in evidence],
            elapsed_ms=elapsed,
        )
        session.add(at)
        convo.updated_at = time.time()  # touch; SQLAlchemy onupdate handles it

        log.info("assistant_turn",
                 conversation=convo.id,
                 grounded=turn.grounded,
                 tools=[t["name"] for t in tool_calls],
                 ms=elapsed)
        return turn


def _tool_param_names(tool_name: str) -> set[str]:
    """Helper — return the parameter names of a tool, for corpus_id auto-injection."""
    from ai.tools import TOOL_SCHEMAS
    for s in TOOL_SCHEMAS:
        if s["function"]["name"] == tool_name:
            return set(s["function"]["parameters"].get("properties", {}).keys())
    return set()
