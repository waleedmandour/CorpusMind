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

from sqlalchemy import select
from sqlalchemy.orm import selectinload

from ai.providers import Message, ModelProvider
from ai.tools import execute_tool, schemas_for_llm
from app.logging import get_logger
from storage.models import Conversation, ConversationTurn
from storage.session import session_scope

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
    # Issue 5 fix: DB id of the persisted assistant turn. Without it the
    # frontend can never call /research/turns/{id}/verify, so the
    # human-in-the-loop verification loop was unreachable end-to-end.
    turn_id: int | None = None
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
        "You are the CorpusMind AI Assistant — a corpus linguistics expert.\n"
        "You are a tool-using agent, NOT a chatbot.\n\n"
        "## How to Read CorpusMind Tool Results\n\n"
        "### Frequency Results\n"
        "Each row has: item (word/lemma/POS), freq (raw count), per_million "
        "(normalized frequency), percent (proportion of all tokens). Higher "
        "per_million means more frequent relative to corpus size.\n\n"
        "### Collocation Results\n"
        "Each row has: collocate, O (co-occurrence count), fx (node freq), "
        "fy (collocate freq), N (corpus size), plus measures:\n"
        "- MI (Mutual Information): >3 = strong association. Negative = repulsion.\n"
        "- t_score: >2 = significant. Higher = stronger.\n"
        "- log_likelihood: higher = more significant co-occurrence.\n"
        "- Dice: 0-1, higher = stronger.\n"
        "- LogDice: higher = stronger (range typically -15 to 0).\n"
        "- chi_square: higher = more significant.\n"
        "- Delta P: -1 to 1, positive = collocate depends on node.\n"
        "Always report window size and minimum frequency with collocations.\n\n"
        "### Keyness Results\n"
        "positive_keywords = over-represented in target vs reference.\n"
        "negative_keywords = under-represented in target.\n"
        "Each row has: term, f1 (target freq), f2 (reference freq), plus:\n"
        "- log_likelihood: significance test (>3.84 = p<0.05, >6.63 = p<0.01).\n"
        "- chi_square: significance test.\n"
        "- log_ratio: effect size. Positive = more in target. Negative = less.\n"
        "- pct_diff: percentage difference. Positive = more in target.\n"
        "ALWAYS pair significance (LL) with effect size (Log Ratio or %DIFF).\n\n"
        "### Concordance (KWIC) Results\n"
        "Each line has: line_id, left context, node (matched word), right "
        "context, POS tag, lemma. The node is the word being studied.\n\n"
        "## Rules\n"
        "1. Every empirical claim MUST come from a tool call. Do not make "
        "claims without tool evidence.\n"
        "2. If you cannot ground a claim, say: 'I cannot ground this in corpus "
        "evidence — answering from parametric memory only.'\n"
        "3. Interpretive claims (CDA, ideology, metaphor) MUST be phrased as "
        "framework-lensed hypotheses, never as settled fact.\n"
        "4. Cite evidence IDs verbatim (e.g. 'line doc-abc:5:12').\n"
        "5. When interpreting statistics, explain what the numbers mean in "
        "plain language for a linguist who may not be a statistician.\n"
        "6. If tool results are large (>50 rows), summarize the top findings "
        "rather than listing every row.\n"
    )

    def __init__(
        self, provider: ModelProvider, *, model: str | None = None, corpus_id: str | None = None
    ) -> None:
        self.provider = provider
        self.model = model
        self.corpus_id = corpus_id

    async def answer(self, convo_id: str, user_text: str, context: str | None = None) -> AssistantTurn:
        """One grounded chat round-trip. Uses its own session_scope() for ALL
        database operations — no external session is passed in. This eliminates
        the greenlet conflict that occurs when two async sessions (the request's
        and execute_tool's) coexist in the same event loop.

        Args:
            convo_id: The conversation ID (already created/loaded by the caller).
            user_text: The user's message text.
        """
        # Use our OWN session for all DB operations — no shared session
        async with session_scope() as session:
            # Load the conversation WITH turns eagerly loaded.
            # CRITICAL: use selectinload() instead of session.get() because
            # lazy-loading the turns relationship inside an async session
            # triggers implicit synchronous IO, causing the greenlet_spawn
            # error: "greenlet_spawn has not been called; can't call await_only()
            # here".
            stmt = (
                select(Conversation)
                .options(selectinload(Conversation.turns))
                .where(Conversation.id == convo_id)
            )
            result = await session.execute(stmt)
            convo = result.scalar_one_or_none()
            if convo is None:
                raise ValueError(f"Conversation {convo_id} not found")

            # Append the user message
            user_turn = ConversationTurn(
                conversation_id=convo.id,
                idx=len(convo.turns),
                role="user",
                content=user_text,
                grounded=False,
            )
            session.add(user_turn)
            await session.flush()

            # Build the LLM message list
            corpus_hint = (
                f"\n\nThe user is currently working with corpus_id={self.corpus_id}. "
                f"Pass this corpus_id to tools that need it."
                if self.corpus_id
                else ""
            )
            messages: list[Message] = [
                Message(role="system", content=self.SYSTEM_PROMPT + corpus_hint)
            ]
            # Replay prior turns
            for t in convo.turns:
                if t.role == "user":
                    messages.append(Message(role="user", content=t.content))
                elif t.role == "assistant":
                    messages.append(Message(role="assistant", content=t.content))
            messages.append(Message(role="user", content=user_text))

        # === LLM calls happen OUTSIDE any DB session ===
        # This is the key fix: no async session is open during the LLM call,
        # so there's no greenlet conflict when execute_tool() opens its own session.
        started = time.perf_counter()
        tool_calls: list[dict[str, Any]] = []
        evidence: list[Evidence] = []
        content = ""

        # Issue 2a fix: only pass tools when the user's message genuinely
        # needs grounding. The OllamaProvider's own docstring says the
        # native /api/chat path (used when tools=None) is "more reliable
        # with small models (1.5B-3B)" — which is what most desktop users
        # run. Forcing every turn through the OpenAI-compatible /v1/chat/
        # completions fallback (needed for tool calls) made the assistant
        # unreliable on exactly the models our users are most likely to
        # have installed.
        #
        # Heuristic: pass tools when the user asks an empirical question
        # (frequency, concordance, collocation, keyness, dispersion, etc.)
        # or references the corpus's content. Pure conversational turns
        # ("thanks", "what can you do?", "explain X") go through the
        # reliable native path with no tool surface.
        needs_tools = _user_message_needs_tools(user_text)

        # v1.2.0: skip the tool surface entirely when the selected model
        # can't do tool calling (Ollama /api/tags capabilities). Sending a
        # tool payload to a non-tool model (embedding models are common in
        # /api/tags) made every grounded turn fail with HTTP 502/400.
        if needs_tools:
            try:
                model_supports_tools = await self.provider.supports_tools(self.model)
            except Exception:
                model_supports_tools = True  # gate is best-effort
            if not model_supports_tools:
                log.info(
                    "assistant_tools_skipped_model_capability",
                    model=self.model,
                )
                messages.append(
                    Message(
                        role="system",
                        content=(
                            "NOTE: The currently selected model does not support "
                            "tool calling, so corpus tools cannot be run this turn. "
                            "Answer from the conversation, and tell the user they "
                            "can pick a tool-capable model (e.g. llama3.1, qwen2.5) "
                            "in Settings to restore grounded answers."
                        ),
                    )
                )
                needs_tools = False

        # Pass 1: ask the model
        if needs_tools:
            first = await self.provider.chat(
                messages,
                model=self.model,
                temperature=0.2,
                tools=schemas_for_llm(),
            )
        else:
            # No tools → OllamaProvider uses the more reliable native /api/chat
            first = await self.provider.chat(
                messages,
                model=self.model,
                temperature=0.2,
            )
        content = first.content

        # Issue 8: parse tool calls from the response. The response format
        # differs between the native /api/chat and OpenAI-compat endpoints:
        #   - OpenAI-compat: raw["choices"][0]["message"]["tool_calls"]
        #   - Native /api/chat: raw["message"]["tool_calls"] (Ollama 0.4+)
        # We check both paths.
        tool_call_reqs = first.raw.get("choices", [{}])[0].get("message", {}).get("tool_calls", [])
        if not tool_call_reqs:
            # Try native /api/chat format
            native_msg = first.raw.get("message", {})
            tool_call_reqs = native_msg.get("tool_calls", [])

        if tool_call_reqs:
            messages.append(Message(role="assistant", content=content or "(tool call)"))

            for req in tool_call_reqs:
                fn = req.get("function", {})
                name = fn.get("name", "")
                raw_args = fn.get("arguments", "{}")
                try:
                    args = json.loads(raw_args) if isinstance(raw_args, str) else (raw_args or {})
                except json.JSONDecodeError:
                    args = {}

                if self.corpus_id and "corpus_id" in _tool_param_names(name):
                    if "corpus_id" not in args:
                        args["corpus_id"] = self.corpus_id

                try:
                    result = await execute_tool(name, args)
                    tool_calls.append({"name": name, "args": args, "ok": True})
                    if name == "search_concordance" and "lines" in result:
                        for line in result["lines"][:5]:
                            evidence.append(
                                Evidence(
                                    kind="concordance_line",
                                    ref=f"line:{line['line_id']}",
                                    snippet=f"{line['left']} [{line['node']}] {line['right']}",
                                )
                            )
                    else:
                        evidence.append(
                            Evidence(
                                kind="tool_result",
                                ref=f"tool:{name}:{len(tool_calls)}",
                                snippet=json.dumps(result)[:500],
                            )
                        )
                    # Task 4: Summarize large tool results before sending to LLM
                    # to avoid token-limit truncation and hallucination.
                    result_str = _summarize_tool_result(name, result)
                    messages.append(Message(role="tool", content=result_str, name=name))
                except Exception as e:
                    tool_calls.append({"name": name, "args": args, "ok": False, "error": str(e)})
                    messages.append(Message(role="tool", content=f"ERROR: {e}", name=name))

            # Pass 2: grounded final answer — NO tools (uses the more reliable
            # native /api/chat path instead of the OpenAI-compat fallback).
            # This is important: the second pass just needs the model to
            # synthesize the tool results into a natural-language answer,
            # not to call more tools.
            final = await self.provider.chat(messages, model=self.model, temperature=0.2)
            content = final.content

        elapsed = int((time.perf_counter() - started) * 1000)

        # Confidence layer
        confidence = 1.0
        confidence_reasoning = ""
        needs_validation = False
        mcqs: list[dict[str, Any]] = []

        if tool_calls and evidence:
            try:
                from ai.confidence import assess_confidence, generate_mcqs, needs_user_validation

                evidence_dicts = [
                    {"kind": e.kind, "ref": e.ref, "snippet": e.snippet} for e in evidence
                ]
                conf_result = await assess_confidence(
                    self.provider,
                    self.model,
                    user_text,
                    evidence_dicts,
                    content,
                )
                confidence = conf_result.get("confidence", 0.5)
                confidence_reasoning = conf_result.get("reasoning", "")
                if needs_user_validation(confidence):
                    needs_validation = True
                    mcqs = await generate_mcqs(
                        self.provider,
                        self.model,
                        user_text,
                        evidence_dicts,
                        content,
                        conf_result.get("unsupported_claims", []),
                    )
            except Exception as e:
                log.warning("confidence_layer_error", error=str(e))

        # === Persist the assistant turn in a NEW session ===
        persisted_turn_id: int | None = None
        async with session_scope() as session:
            # Use selectinload to eagerly load turns (avoid greenlet lazy-load error)
            stmt = (
                select(Conversation)
                .options(selectinload(Conversation.turns))
                .where(Conversation.id == convo_id)
            )
            result = await session.execute(stmt)
            convo = result.scalar_one_or_none()
            if convo is not None:
                at = ConversationTurn(
                    conversation_id=convo.id,
                    idx=len(convo.turns),
                    role="assistant",
                    content=content,
                    grounded=bool(tool_calls),
                    tool_calls=tool_calls,
                    evidence=[
                        {"kind": e.kind, "ref": e.ref, "snippet": e.snippet} for e in evidence
                    ],
                    elapsed_ms=elapsed,
                )
                session.add(at)
                await session.flush()  # Issue 5 fix: populate the autoincrement id
                persisted_turn_id = at.id

        log.info(
            "assistant_turn",
            conversation=convo_id,
            grounded=bool(tool_calls),
            tools=[t["name"] for t in tool_calls],
            ms=elapsed,
        )

        return AssistantTurn(
            content=content,
            grounded=bool(tool_calls),
            evidence=evidence,
            tool_calls=tool_calls,
            elapsed_ms=elapsed,
            confidence=confidence,
            confidence_reasoning=confidence_reasoning,
            needs_validation=needs_validation,
            mcqs=mcqs,
            turn_id=persisted_turn_id,
        )


def _tool_param_names(tool_name: str) -> set[str]:
    """Helper — return the parameter names of a tool, for corpus_id auto-injection."""
    from ai.tools import TOOL_SCHEMAS

    for s in TOOL_SCHEMAS:
        if s["function"]["name"] == tool_name:
            return set(s["function"]["parameters"].get("properties", {}).keys())
    return set()


# Issue 2a: keyword heuristic for deciding whether a user message needs
# tool-calling (and therefore the less-reliable OpenAI-compat path) or can
# go through the more-reliable native /api/chat path.
#
# The lists below are deliberately broad — if we're unsure, we pass tools
# (the safer default for a corpus-linguistics assistant where most questions
# ARE empirical). The goal is to skip tools only for clearly conversational
# turns, not to be clever about edge cases.
_TOOL_FREE_PATTERNS = (
    # Greetings / pleasantries
    "hello",
    "hi ",
    "hey",
    "thanks",
    "thank you",
    "please",
    "ok",
    "okay",
    # Meta questions about the assistant itself
    "what can you do",
    "who are you",
    "help me",
    "how do you work",
    # Pure methodology / theory questions (no corpus data needed)
    "what is log-likelihood",
    "what is mutual information",
    "what is keyness",
    "explain",
    "define",
    "what does",
    "what's the difference",
    "how do i",
    "how should i",
    "methodology",
)

_GROUNDING_PATTERNS = (
    # Direct tool names
    "frequency",
    "frequent",
    "concordance",
    "collocat",
    "keyness",
    "keyword",
    "dispersion",
    "n-gram",
    "ngram",
    "bigram",
    "trigram",
    "pos tag",
    "pos-tag",
    # Analysis verbs
    "find all",
    "show me",
    "search for",
    "compare",
    "how many",
    "how often",
    "top 10",
    "top 20",
    "top 5",
    "most common",
    "most frequent",
    "strongest",
    "distribution",
    "patterns",
    "occurrences",
    "contexts",
    # Corpus references
    "this corpus",
    "the corpus",
    "my corpus",
    "in the text",
    "in this",
    # Specific word lookups (quoted or not)
    "word '",
    'word "',
    "of '",
    'of "',
    "for '",
    'for "',
)


def _user_message_needs_tools(user_text: str) -> bool:
    """Decide whether the user's message needs tool-calling.

    Returns True (pass tools) when the message looks like an empirical
    question about corpus data. Returns False (skip tools, use the more
    reliable native /api/chat path) when the message is clearly
    conversational.

    Issue 8: the previous heuristic was too conservative — it defaulted
    to False for short messages (< 120 chars) that weren't greetings.
    This meant simple questions like "top 10 words" (14 chars) went
    through without tools and got an ungrounded answer. Now we default
    to True for any message that contains a question mark or an
    analysis-related word, regardless of length.
    """
    text = user_text.lower().strip()
    if not text:
        return False

    # Check tool-free patterns first — these are definitely conversational
    for pat in _TOOL_FREE_PATTERNS:
        if text.startswith(pat) or text == pat.rstrip():
            return False

    # Check grounding patterns — these definitely need tools
    for pat in _GROUNDING_PATTERNS:
        if pat in text:
            return True

    # Issue 8: if the message contains a question mark, it's likely a
    # question that should be grounded. Default to tools=True.
    if "?" in text:
        return True

    # Default: pass tools for any message longer than 30 chars (likely
    # a real question). Short non-question messages are conversational.
    return len(text) > 30


# Task 4: Summarize large tool results to fit within LLM token limits.
# Without this, large frequency lists or concordance results get truncated
# by the LLM's context window, causing hallucinated interpretations.
def _summarize_tool_result(tool_name: str, result: dict) -> str:
    """Format tool results as structured text for the LLM.

    For large results (>50 rows), only the top 20 rows are included,
    plus a summary of the rest.
    """
    MAX_ROWS = 20

    if not isinstance(result, dict):
        return json.dumps(result)[:2000]

    # Concordance: show first 20 lines + total count
    if "lines" in result and isinstance(result["lines"], list):
        lines = result["lines"]
        total = result.get("total", len(lines))
        if len(lines) <= MAX_ROWS:
            return json.dumps(result)
        summary = {
            "total": total,
            "showing": f"Top {MAX_ROWS} of {len(lines)} lines",
            "lines": lines[:MAX_ROWS],
            "note": f"{len(lines) - MAX_ROWS} more lines omitted. Total matches: {total}.",
        }
        return json.dumps(summary, ensure_ascii=False)

    # Frequency: show top 20 rows + stats
    if "rows" in result and isinstance(result["rows"], list):
        rows = result["rows"]
        total_tokens = result.get("total_tokens", "?")
        total_types = result.get("total_types", "?")
        sttr = result.get("sttr", "?")
        if len(rows) <= MAX_ROWS:
            return json.dumps(result, ensure_ascii=False)
        summary = {
            "total_tokens": total_tokens,
            "total_types": total_types,
            "sttr": sttr,
            "showing": f"Top {MAX_ROWS} of {len(rows)} types",
            "rows": rows[:MAX_ROWS],
            "note": f"{len(rows) - MAX_ROWS} more types omitted.",
        }
        return json.dumps(summary, ensure_ascii=False)

    # Keyness: show top 20 positive + top 20 negative
    if "positive_keywords" in result and "negative_keywords" in result:
        pos = result["positive_keywords"]
        neg = result["negative_keywords"]
        N1 = result.get("N1", "?")
        N2 = result.get("N2", "?")
        measures = result.get("measures", [])
        summary = {
            "N1": N1,
            "N2": N2,
            "measures": measures,
            "positive_keywords": pos[:MAX_ROWS],
            "negative_keywords": neg[:MAX_ROWS],
            "note": f"{len(pos)} positive + {len(neg)} negative keywords total. Showing top {MAX_ROWS} of each.",
        }
        return json.dumps(summary, ensure_ascii=False)

    # Collocations: show top 20 rows
    if "rows" in result and "node" in result:
        rows = result["rows"]
        summary = {
            "node": result.get("node"),
            "window": result.get("window"),
            "min_freq": result.get("min_freq"),
            "measures": result.get("measures"),
            "showing": f"Top {MAX_ROWS} of {len(rows)} collocates",
            "rows": rows[:MAX_ROWS],
            "note": f"{len(rows) - MAX_ROWS} more collocates omitted."
            if len(rows) > MAX_ROWS
            else "",
        }
        return json.dumps(summary, ensure_ascii=False)

    # Default: if result is very large, truncate
    result_str = json.dumps(result, ensure_ascii=False)
    if len(result_str) > 4000:
        return result_str[:4000] + "\n... [truncated: result was too large]"
    return result_str
