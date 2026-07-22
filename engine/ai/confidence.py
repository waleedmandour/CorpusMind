"""
Deterministic AI interpretation layer.

Shifts the AI's interpretive output from purely stochastic to grounded +
confidence-assessed. The flow:

  1. The LLM produces its grounded answer (existing flow in assistant.py).
  2. A second LLM call asks: "Given this evidence, how confident are you
     (0.0–1.0) in this interpretation? List the specific evidence IDs
     that support it."
  3. If confidence >= threshold (default 0.7): return the interpretation
     with the confidence score + supporting evidence IDs.
  4. If confidence < threshold: generate 2–3 multiple-choice questions
     (MCQs) that the user must answer before the interpretation is
     revealed. The MCQs test whether the user can verify the key claims
     from the retrieved evidence.

This makes the interpretive layer deterministic in the sense that:
  - The evidence is always cited (grounded, existing)
  - The confidence is always reported (new)
  - Low-confidence interpretations require human validation (new)
  - The MCQ answers are recorded in the audit trail (new)
"""
from __future__ import annotations

import json
from typing import Any

from ai.providers import Message, ModelProvider
from app.logging import get_logger

log = get_logger(__name__)

CONFIDENCE_THRESHOLD = 0.7

CONFIDENCE_SYSTEM_PROMPT = """You are a confidence assessor for a corpus linguistics AI assistant.

Given:
  1. The user's question
  2. The retrieved evidence (tool results with cited IDs)
  3. The AI's interpretation

Assess how confident you are that the interpretation is fully supported
by the cited evidence. Be strict — if the interpretation makes claims
not directly supported by the evidence, lower the confidence.

Output EXACTLY this JSON (no markdown, no prose):
{
  "confidence": 0.0-1.0,
  "supporting_evidence_ids": ["id1", "id2", ...],
  "unsupported_claims": ["claim that isn't directly backed by evidence", ...],
  "reasoning": "1-2 sentences explaining the confidence score"
}

Rules:
- confidence = 1.0 only if EVERY claim in the interpretation is directly
  backed by a cited evidence item.
- confidence < 0.5 if the interpretation makes significant claims beyond
  what the evidence shows.
- supporting_evidence_ids should reference the evidence IDs provided.
- unsupported_claims should list any interpretive leaps."""

MCQ_SYSTEM_PROMPT = """You are a validation question generator for a corpus linguistics AI assistant.

The AI produced an interpretation with LOW confidence. Generate 2-3
multiple-choice questions that test whether the user can verify the
KEY claims from the retrieved evidence. The questions should be
answerable directly from the evidence — not from external knowledge.

Output EXACTLY this JSON array (no markdown, no prose):
[
  {
    "question": "According to the concordance evidence, what is the most common POS tag for 'fox'?",
    "options": ["NOUN", "VERB", "ADJ", "ADV"],
    "correct_answer": 0,
    "evidence_ref": "line:abc123",
    "explanation": "The concordance shows 'fox' tagged as NOUN in 4 of 5 occurrences."
  }
]

Rules:
- 2-3 questions only
- Each question must be answerable from the cited evidence
- The correct_answer is the 0-indexed position of the right option
- Include an evidence_ref pointing to the specific evidence item
- The explanation should reference the evidence directly"""


async def assess_confidence(
    provider: ModelProvider,
    model: str,
    user_question: str,
    evidence: list[dict[str, Any]],
    interpretation: str,
) -> dict[str, Any]:
    """Assess the LLM's confidence in its interpretation.

    Returns:
      {
        "confidence": float,
        "supporting_evidence_ids": list[str],
        "unsupported_claims": list[str],
        "reasoning": str,
      }
    """
    # Build the evidence summary
    evidence_text = "\n".join(
        f"  [{e.get('ref', '?')}] {e.get('snippet', '')[:200]}"
        for e in evidence
    ) if evidence else "  (no evidence retrieved)"

    prompt = f"""USER QUESTION:
{user_question}

RETRIEVED EVIDENCE:
{evidence_text}

AI INTERPRETATION:
{interpretation}

Assess your confidence in this interpretation."""

    messages = [
        Message(role="system", content=CONFIDENCE_SYSTEM_PROMPT),
        Message(role="user", content=prompt),
    ]

    try:
        # Issue 2b: use chat_json() instead of chat() so the provider sets
        # the JSON-format flag (Ollama: "format":"json"; OpenAI-compat:
        # response_format=json_object). This forces the model to return
        # valid JSON instead of wrapping it in prose/code fences.
        response = await provider.chat_json(
            messages,
            model=model,
            temperature=0.1,  # Low temperature for deterministic assessment
        )
        parsed = json.loads(response.content)
        return {
            "confidence": float(parsed.get("confidence", 0.0)),
            "supporting_evidence_ids": parsed.get("supporting_evidence_ids", []),
            "unsupported_claims": parsed.get("unsupported_claims", []),
            "reasoning": parsed.get("reasoning", ""),
        }
    except (json.JSONDecodeError, ValueError, KeyError) as e:
        log.warning("confidence_assessment_failed", error=str(e))
        # If assessment fails, default to moderate confidence
        return {
            "confidence": 0.5,
            "supporting_evidence_ids": [],
            "unsupported_claims": [],
            "reasoning": f"Confidence assessment failed: {e}",
        }


async def generate_mcqs(
    provider: ModelProvider,
    model: str,
    user_question: str,
    evidence: list[dict[str, Any]],
    interpretation: str,
    unsupported_claims: list[str],
) -> list[dict[str, Any]]:
    """Generate MCQs for the user to validate when confidence is low.

    Returns a list of:
      {
        "question": str,
        "options": list[str],
        "correct_answer": int (0-indexed),
        "evidence_ref": str,
        "explanation": str,
      }
    """
    evidence_text = "\n".join(
        f"  [{e.get('ref', '?')}] {e.get('snippet', '')[:200]}"
        for e in evidence
    ) if evidence else "  (no evidence retrieved)"

    unsupported_text = "\n".join(f"  - {c}" for c in unsupported_claims) if unsupported_claims else "  (none)"

    prompt = f"""USER QUESTION:
{user_question}

RETRIEVED EVIDENCE:
{evidence_text}

AI INTERPRETATION:
{interpretation}

UNSUPPORTED CLAIMS (claims not directly backed by evidence):
{unsupported_text}

Generate validation questions."""

    messages = [
        Message(role="system", content=MCQ_SYSTEM_PROMPT),
        Message(role="user", content=prompt),
    ]

    try:
        # Issue 2b: use chat_json() for the same reason as assess_confidence()
        response = await provider.chat_json(
            messages,
            model=model,
            temperature=0.1,
        )
        mcqs = json.loads(response.content)
        if isinstance(mcqs, list):
            return mcqs[:3]  # Max 3 questions
        return []
    except (json.JSONDecodeError, ValueError, KeyError) as e:
        log.warning("mcq_generation_failed", error=str(e))
        return []


def needs_user_validation(confidence: float) -> bool:
    """Returns True if the confidence is below the threshold and the
    user should answer MCQs before the interpretation is revealed."""
    return confidence < CONFIDENCE_THRESHOLD
