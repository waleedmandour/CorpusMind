"""
Phase 1 grounded-AI tool registry (§11.2).

Each tool is a closure over an async session factory so it can run DB queries
on demand. Every tool returns plain dict / list output that the model can cite
in its final answer — and the assistant layer's `grounded: bool` flag flips
true whenever at least one tool was invoked.
"""
from __future__ import annotations

import json
import time
from typing import Any

from sqlalchemy.ext.asyncio import AsyncSession

from app.logging import get_logger
from stats.service import (
    compute_collocations,
    compute_dispersion,
    compute_frequency,
    compute_keyness,
    search_concordance,
)
from storage.session import session_scope

log = get_logger(__name__)


# --------------------------------------------------------------------------- #
# Tool implementations
# --------------------------------------------------------------------------- #
# Each is an async function taking a session and the tool's args.
# They return JSON-serializable dicts that get fed back to the LLM.


async def _search_concordance(session: AsyncSession, *, corpus_id: str, query: str,
                              level: str = "word", window: int = 5, limit: int = 20) -> dict:
    r = await search_concordance(
        session, corpus_id, query, level=level, window=window, limit=limit,
    )
    return {
        "total_matches": r.total,
        "query": r.query,
        "lines": [
            {
                "line_id": l.line_id,
                "document": l.document_filename,
                "left": l.left,
                "node": l.node,
                "right": l.right,
                "pos": l.pos,
                "lemma": l.lemma,
            }
            for l in r.lines
        ],
    }


async def _get_frequency(session: AsyncSession, *, corpus_id: str, unit: str = "word",
                         limit: int = 20) -> dict:
    r = await compute_frequency(session, corpus_id, unit=unit, limit=limit)
    return {
        "unit": r.unit,
        "total_tokens": r.total_tokens,
        "total_types": r.total_types,
        "sttr": r.sttr,
        "top_items": r.rows[:limit],
    }


async def _compute_collocations(session: AsyncSession, *, corpus_id: str, node: str,
                                 window: int = 5, min_freq: int = 3,
                                 measures: list[str] | None = None) -> dict:
    r = await compute_collocations(
        session, corpus_id, node, window=window, min_freq=min_freq, measures=measures, limit=20,
    )
    return {
        "node": r.node,
        "window": r.window,
        "measures": r.measures,
        "top_collocates": r.rows,
    }


async def _compute_keyness(session: AsyncSession, *, target_corpus_id: str,
                           reference_corpus_id: str, limit: int = 20) -> dict:
    r = await compute_keyness(session, target_corpus_id, reference_corpus_id, limit=limit)
    return {
        "target_corpus_id": r.target_corpus_id,
        "reference_corpus_id": r.reference_corpus_id,
        "N1": r.N1,
        "N2": r.N2,
        "positive_keywords": r.positive_keywords[:limit],
        "negative_keywords": r.negative_keywords[:limit],
    }


async def _get_dispersion(session: AsyncSession, *, corpus_id: str, term: str,
                          level: str = "word") -> dict:
    r = await compute_dispersion(session, corpus_id, term, level=level)
    return {
        "term": r.term,
        "juillands_d": r.juillands_d,
        "gries_dp": r.gries_dp,
        "per_part_freqs": r.per_part_freqs,
    }


# --------------------------------------------------------------------------- #
# Registry factory
# --------------------------------------------------------------------------- #
# The tool schemas passed to the LLM. These match OpenAI's function-calling
# schema. Keep them tight — the more parameters the model has to fill, the
# more it gets wrong.


TOOL_SCHEMAS: list[dict] = [
    {
        "type": "function",
        "function": {
            "name": "search_concordance",
            "description": (
                "Search the corpus for a word, lemma, or POS tag and return KWIC concordance "
                "lines with stable line IDs. Cite the line_id in your answer. Use this whenever "
                "the user asks 'where does X appear' or 'find examples of X'."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "corpus_id": {"type": "string", "description": "The active corpus ID"},
                    "query": {"type": "string", "description": "The search term (use * for wildcard)"},
                    "level": {"type": "string", "enum": ["word", "lemma", "pos"], "default": "word"},
                    "window": {"type": "integer", "default": 5, "minimum": 1, "maximum": 20},
                    "limit": {"type": "integer", "default": 20, "minimum": 1, "maximum": 50},
                },
                "required": ["corpus_id", "query"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "get_frequency",
            "description": (
                "Get frequency statistics (top items, total tokens/types, STTR) for a corpus. "
                "Use unit='word' for word frequencies, 'lemma' for lemmas, 'pos' for POS tags."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "corpus_id": {"type": "string"},
                    "unit": {"type": "string", "enum": ["word", "lemma", "pos"], "default": "word"},
                    "limit": {"type": "integer", "default": 20},
                },
                "required": ["corpus_id"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "compute_collocations",
            "description": (
                "Compute collocation measures (MI, T-score, log-likelihood, Dice, LogDice, "
                "chi-square, Delta P) for a node word. Always report the window size alongside "
                "the measures (collocations without a stated window are not reproducible)."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "corpus_id": {"type": "string"},
                    "node": {"type": "string", "description": "The node word"},
                    "window": {"type": "integer", "default": 5},
                    "min_freq": {"type": "integer", "default": 3},
                },
                "required": ["corpus_id", "node"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "compute_keyness",
            "description": (
                "Compare target vs reference corpus and return positive + negative keywords "
                "with both significance (log-likelihood, chi-square) and effect-size "
                "(Log Ratio, %DIFF, Simple Maths, Odds Ratio) measures. Always pair "
                "significance with effect size in your answer."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "target_corpus_id": {"type": "string"},
                    "reference_corpus_id": {"type": "string"},
                    "limit": {"type": "integer", "default": 20},
                },
                "required": ["target_corpus_id", "reference_corpus_id"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "get_dispersion",
            "description": (
                "Compute dispersion statistics (Juilland's D, Gries' DP) for a term across "
                "the corpus's documents. Values closer to 1 (Juilland's D) or 0 (Gries' DP) "
                "mean more even distribution."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "corpus_id": {"type": "string"},
                    "term": {"type": "string"},
                    "level": {"type": "string", "enum": ["word", "lemma"], "default": "word"},
                },
                "required": ["corpus_id", "term"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "ping",
            "description": "Health-check tool. Returns engine version + timestamp.",
            "parameters": {"type": "object", "properties": {}},
        },
    },
]


# Maps tool name → async implementation that takes (session, **args)
TOOL_IMPLS = {
    "search_concordance": _search_concordance,
    "get_frequency": _get_frequency,
    "compute_collocations": _compute_collocations,
    "compute_keyness": _compute_keyness,
    "get_dispersion": _get_dispersion,
    "ping": lambda **_: {"ok": True, "engine": "corpusmind-engine", "ts": __import__("time").time()},
}


async def execute_tool(name: str, args: dict) -> Any:
    """Execute a tool by name with the given args, opening a fresh session if needed."""
    impl = TOOL_IMPLS.get(name)
    if impl is None:
        raise KeyError(f"Unknown tool: {name}")
    # `ping` doesn't need a session
    if name == "ping":
        return await impl(**args)
    # All other tools need an async session
    async with session_scope() as session:
        return await impl(session, **args)


def schemas_for_llm() -> list[dict]:
    """Return the JSON-schema list to pass to the model's `tools` parameter."""
    return TOOL_SCHEMAS


def list_tools() -> list[dict]:
    """Return a UI-facing summary of available tools."""
    return [{"name": s["function"]["name"], "description": s["function"]["description"]}
            for s in TOOL_SCHEMAS]
