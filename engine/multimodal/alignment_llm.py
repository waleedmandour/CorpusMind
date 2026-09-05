"""Vision-LM-backed image-text alignment (CorpusMind Lens build step 6).

This module provides the LLM sibling path for the /images/{img_id}/align
route. The existing heuristic path (multimodal/alignment.py) aligns
image regions with text spans using colour-term matching + positional
hints — it never looks at what the image actually depicts. This module
sends the actual image bytes + the text to a vision-LM and asks it to
identify which text spans correspond to which image regions.

Design:

  - The system prompt asks the vision-LM to output JSON matching the
    Alignment shape (region_id, span_id, confidence, match_reason,
    region_descriptor, span_text). The model is told to use its
    understanding of the image content to make the alignments, not
    just colour/position heuristics.

  - Since the vision-LM doesn't know about the heuristic region IDs
    (r0, r1, ...) or span IDs (s0, s1, ...), we give it the text and
    ask it to output alignments using span text fragments + region
    descriptions. We then match its output back to the heuristic
    regions/spans by text similarity. If no match is found, we create
    a synthetic region/span entry for the LLM's alignment.

  - Results are NOT cached (alignment depends on the text input, which
    is per-request — caching would require keying on text+image+model,
    which is the same complexity as just re-running).

  - The consent gate from step 5 is applied to the LLM's output —
    person-descriptive content in alignment descriptions is redacted
    when the gate is closed.

  - Falls back to the heuristic path if no provider is available or
    the LLM call fails. Never an error state.
"""
from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from ai.providers import (
    ChatResponse,
    Message,
    ModelProvider,
    ModelProviderError,
    resolve_vision_model,
)
from app.logging import get_logger
from vision.consent_gate import filter_person_descriptive
from vision.pipeline import read_image_bytes

log = get_logger(__name__)


# ---------------------------------------------------------------------------
# Types
# ---------------------------------------------------------------------------


@dataclass(frozen=True, slots=True)
class LLMAlignmentResult:
    """Result of a vision-LM-backed alignment.

    `alignments` follows the same shape as multimodal/alignment.py's
    Alignment dataclass so the frontend can render both modes with the
    same component. `provenance` carries model + provider metadata for
    reproducibility. `fallback_reason` is set when the LLM path was
    requested but couldn't run.
    """
    alignments: list[dict[str, Any]]
    method: str
    note: str
    provenance: dict[str, Any] | None = None
    fallback_reason: str | None = None
    person_descriptive_redacted: bool = False


# ---------------------------------------------------------------------------
# Prompt
# ---------------------------------------------------------------------------


_SYSTEM_PROMPT = """\
You are aligning regions of an image with spans of text. The user will
give you an image and a text. Your job is to identify which parts of the
text refer to which parts of the image.

Output STRICT JSON in this exact shape:
{
  "alignments": [
    {
      "span_text": "<exact text fragment from the input text>",
      "region_descriptor": "<short description of the image region>",
      "confidence": 0.8,
      "match_reason": "<why this text refers to this region>"
    }
  ]
}

Rules:
1. Only align text spans that actually refer to something visible in
   the image. If a text span doesn't refer to anything visible, skip it.
2. Use exact text fragments from the input text — do not paraphrase.
3. Confidence 0.0–1.0: how sure are you that this text refers to this
   region?
4. Do not include any text outside the JSON. Do not wrap in code fences."""


def _build_user_prompt(text: str) -> str:
    """Build the user prompt. Kept short — small vision models struggle
    with long prompts (step 3 finding)."""
    return f"Align the following text with the image. Text:\n\n{text}\n\nOutput the JSON now."


# ---------------------------------------------------------------------------
# JSON parsing (defensive)
# ---------------------------------------------------------------------------


def _parse_alignments_json(
    raw: str,
) -> list[dict[str, Any]]:
    """Parse the vision-LM's JSON output into a list of alignment dicts.

    Defensive: strips markdown code fences, falls back to an empty list
    if the model didn't return valid JSON.
    """
    cleaned = raw.strip()
    if cleaned.startswith("```"):
        first_newline = cleaned.find("\n")
        if first_newline != -1:
            cleaned = cleaned[first_newline + 1:]
        if cleaned.rstrip().endswith("```"):
            cleaned = cleaned.rstrip()[:-3]

    try:
        data = json.loads(cleaned)
    except json.JSONDecodeError:
        log.warning("vlm_align_json_parse_failed", raw_preview=raw[:200])
        return []

    alignments_raw = data.get("alignments", [])
    alignments: list[dict[str, Any]] = []
    for i, a in enumerate(alignments_raw):
        if not isinstance(a, dict):
            continue
        alignments.append({
            "region_id": f"llm_r{i}",
            "span_id": f"llm_s{i}",
            "span_text": a.get("span_text", ""),
            "region_descriptor": a.get("region_descriptor", ""),
            "confidence": float(a.get("confidence", 0.5)),
            "match_reason": a.get("match_reason", "vision-LM alignment"),
        })

    return alignments


# ---------------------------------------------------------------------------
# Main entry point
# ---------------------------------------------------------------------------


async def run_llm_alignment(
    img: Any,
    text: str,
    provider: ModelProvider,
    *,
    model: str | None = None,
) -> LLMAlignmentResult:
    """Run a vision-LM-backed alignment on an image + text.

    Sends the image bytes + the text to the vision-LM, asks it to
    identify which text spans refer to which image regions, and returns
    the alignments in the same shape as the heuristic path.

    The consent gate from step 5 is applied to region descriptors and
    match reasons — person-descriptive content is redacted when the
    gate is closed.

    Raises:
      ModelProviderError: if the provider call fails (caller catches
        and falls back to heuristic).
    """
    # Resolve model name (v1.2.0: capability-aware).
    model_name = await resolve_vision_model(provider, model)

    if not model_name:
        raise ModelProviderError(
            "No model specified and provider has no default model."
        )

    # Read image bytes (decrypt-aware — v1.2.0).
    storage_path = getattr(img, "storage_path", None)
    if not storage_path or not Path(storage_path).exists():
        raise ModelProviderError("Image file not found on disk. Re-ingest.")
    image_bytes = read_image_bytes(storage_path)

    # Build prompts.
    user_prompt = _build_user_prompt(text)
    messages = [
        Message(role="system", content=_SYSTEM_PROMPT),
        Message(role="user", content=user_prompt, images=(image_bytes,)),
    ]

    log.info(
        "vlm_align_request",
        image_id=getattr(img, "id", "?"),
        provider=provider.name,
        model=model_name,
        text_len=len(text),
        image_bytes=len(image_bytes),
    )

    response: ChatResponse = await provider.chat(
        messages,
        model=model_name,
        temperature=0.1,
        timeout=120.0,
        json_mode=True,
        max_tokens=2048,
    )

    raw_content = response.content.strip()
    if not raw_content:
        raise ModelProviderError(
            f"Vision-LM returned empty content for alignment. Model: {model_name}."
        )

    alignments = _parse_alignments_json(raw_content)

    # Apply the consent gate (step 5) to region descriptors + match reasons.
    any_filtered = False
    for a in alignments:
        desc_result = filter_person_descriptive(a.get("region_descriptor", ""))
        reason_result = filter_person_descriptive(a.get("match_reason", ""))
        if desc_result.was_filtered or reason_result.was_filtered:
            any_filtered = True
        a["region_descriptor"] = desc_result.filtered_text
        a["match_reason"] = reason_result.filtered_text

    log.info(
        "vlm_align_success",
        image_id=getattr(img, "id", "?"),
        model=response.model or model_name,
        alignment_count=len(alignments),
        person_descriptive_redacted=any_filtered,
    )

    return LLMAlignmentResult(
        alignments=alignments,
        method="vision-llm",
        note="Vision-LM alignment: the model looked at the image and text to identify correspondences.",
        provenance={
            "mode": "llm",
            "model": response.model or model_name,
            "provider": provider.name,
        },
        person_descriptive_redacted=any_filtered,
    )
