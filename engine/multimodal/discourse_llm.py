"""Vision-LM-backed discourse analysis (CorpusMind Lens build step 4).

This module provides the LLM sibling path for the eight discourse-
framework routes in api/phase5.py. Each route already has a purely
heuristic path (analyse_social_semiotic, analyse_cda, etc. in
multimodal/discourse.py) that looks at colour statistics, composition
geometry, OCR text, and caption. This module adds the missing piece:
it sends the actual image bytes + the framework's theoretical lens to
a local vision-LM, so the analysis can finally look at what the image
actually depicts.

Design:

  - Each framework gets a system prompt that bakes in the hedging
    contract from multimodal/discourse.py's own docstring: every
    interpretive claim must be phrased as a hypothesis ("Under a
    [Framework] reading, X may indicate Y") citing the specific
    triggering visual or textual feature. This is the project's
    §4 Principle 5 — never state ideology, bias, or power relations
    as settled fact.

  - The user prompt asks for JSON output matching the DiscourseClaim
    shape (framework, category, claim, evidence, confidence). The
    vision-LM's JSON is parsed defensively — if it doesn't match the
    schema, we fall back to a single claim wrapping the raw text.

  - Results are cached in img.analysis["vision_llm_discourse"]
    [f"{framework_key}:{model}:{prompt_hash}"] using full reassignment
    (img.analysis = {**img.analysis, ...}), never in-place mutation.
    This is a separate cache key from the /describe route's
    img.analysis["vision_llm"] key, so discourse analyses and plain
    descriptions don't collide.

  - Provenance metadata (model, provider, prompt_hash, timestamp,
    mode) is returned alongside the claims so a researcher can
    reproduce an analysis in a manuscript (§4 Principle 8).

  - If no vision-LM provider is available or healthy, the caller
    falls back to the heuristic path — never an error state. The
    response includes mode="heuristic" + fallback_reason so the UI
    can show the user which path produced the output.

  - Consent gate (§3.4): NOT enforced here. A vision-LM asked to
    analyse a photo will volunteer person-descriptive commentary.
    Build step 5 wires the vision/facial.py consent gate across all
    person-descriptive vision-LM output. For now, this module
    returns whatever the model says — step 5 adds the filter.
"""
from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from ai.providers import ChatResponse, Message, ModelProvider, ModelProviderError
from app.logging import get_logger
from storage.models import Image as ImageModel

log = get_logger(__name__)


# ---------------------------------------------------------------------------
# Types
# ---------------------------------------------------------------------------


@dataclass(frozen=True, slots=True)
class LLMProvenance:
    """Reproducibility metadata for a vision-LM discourse analysis.

    Returned alongside the claims so a researcher can cite the exact
    model + prompt that produced a given reading (§4 Principle 8).
    """
    mode: str               # "llm"
    model: str
    provider: str
    prompt_hash: str
    timestamp: str
    cached: bool = False


@dataclass(frozen=True, slots=True)
class LLMDiscourseResult:
    """The result of a vision-LM-backed discourse analysis.

    `claims` follows the same shape as multimodal/discourse.py's
    DiscourseClaim (framework, category, claim, evidence, confidence)
    so the UI can render both modes with the same component.

    `provenance` is None for the heuristic path, non-None for the LLM
    path. `fallback_reason` is set when the LLM path was requested but
    couldn't run (no provider, provider unhealthy, model call failed)
    and the heuristic path was used instead.
    """
    analysis_type: str
    framework: str
    claims: list[dict[str, Any]]
    summary: str
    provenance: LLMProvenance | None = None
    fallback_reason: str | None = None


# ---------------------------------------------------------------------------
# Framework prompt templates
# ---------------------------------------------------------------------------


# The hedging contract — every framework's system prompt includes this.
# Source: multimodal/discourse.py module docstring, §4 Principle 5.
_HEDGING_CONTRACT = """\
You are analysing an image through a specific theoretical lens from
multimodal discourse analysis. Every interpretive claim you make MUST
follow these rules:

1. Phrase claims as HYPOTHESES, not settled fact. Use the form:
   "Under a [Framework] reading, X may indicate Y."
   Never state ideology, bias, or power relations as fact.

2. Cite the specific visual or textual feature that triggered each
   claim. A claim without evidence is not a claim — it's a guess.

3. Include a confidence score (0.0–1.0) for each claim. Be honest:
   if the image doesn't clearly support a claim, confidence should
   be below 0.5.

4. If the image doesn't contain enough information for a claim under
   this framework, say so. Do not invent features that aren't there.

5. Output STRICT JSON in this exact shape:
   {
     "claims": [
       {
         "framework": "<framework name>",
         "category": "<one-word category>",
         "claim": "<hedged claim citing a specific feature>",
         "evidence": ["<feature 1>", "<feature 2>"],
         "confidence": 0.6
       }
     ],
     "summary": "<one-sentence summary of the analysis>"
   }

   Do not include any text outside the JSON. Do not wrap the JSON in
   markdown code fences."""


# Framework-specific prompt fragments. Each maps a framework key (used
# in the route + cache key) to (framework_name, lens_description).
# The framework_name goes into the system prompt header; the
# lens_description tells the model what to look for under this lens.
_FRAMEWORK_PROMPTS: dict[str, tuple[str, str]] = {
    "social_semiotic": (
        "Kress & van Leeuwen (Social Semiotics 2006)",
        "Analyse the image's representational meaning (what it depicts — "
        "narrative processes, participants, vectors), interactive meaning "
        "(the relationship it constructs between viewer and represented — "
        "gaze, social distance, angle, modality), and compositional meaning "
        "(information value, framing, salience). Look at the actual visual "
        "content: who/what is depicted, how they are arranged, where the "
        "viewer's eye is drawn, what the gaze direction constructs.",
    ),
    "cda_fairclough": (
        "Fairclough (1995) Three-Dimensional CDA",
        "Analyse the image across three dimensions: textual (what is "
        "visually and textually present), discursive practice (how the "
        "image is produced, distributed, consumed), and social practice "
        "(ideological effects, power relations, naturalisation). Look for "
        "visual choices that may naturalise particular power relations "
        "or ideologies. Remember: claims about ideology are hypotheses.",
    ),
    "cda_van_dijk": (
        "van Dijk (2008) Socio-Cognitive Approach",
        "Analyse the image's role in constructing mental models and social "
        "representations. Look at how the image may reinforce or challenge "
        "existing schemas, how it positions social actors (in-group vs "
        "out-group), and what cognitive structures it invokes. Look at the "
        "actual depicted content, not just colours.",
    ),
    "cda_wodak": (
        "Wodak (2001) Discourse-Historical Approach",
        "Analyse the image's historical and intertextual context. Look at "
        "how the image references or implicates historical events, how it "
        "positions subjects historically, and what discursive strategies "
        "it employs (referential, predication, argumentation, perspectivisation, "
        "intensification/mitigation). Focus on the depicted content.",
    ),
    "cda_machin_mayr": (
        "Machin & Mayr (2012) Multimodal CDA",
        "Analyse the image's visual choices as ideological: depictions of "
        "social actors (individualised vs genericised, personalised vs "
        "impersonalised), actions (what is done, by whom, to whom), "
        "settings and contexts, and the relationship offered to the viewer. "
        "Look at who is depicted and how — not just colours.",
    ),
    "persuasion": (
        "Aristotle's Rhetoric + Toulmin's Argumentation Model",
        "Analyse the image for persuasive strategies: ethos (credibility, "
        "authority cues), pathos (emotional appeals — depicted expressions, "
        "colours, composition), logos (logical argument, evidence depicted), "
        "and Toulmin's elements (claim, grounds, warrant, backing, qualifier, "
        "rebuttal). Look at what the image actually shows and how it tries "
        "to persuade the viewer.",
    ),
    "framing": (
        "Entman (1993) Framing Theory",
        "Analyse how the image frames its subject: what is selected "
        "(included/excluded), what is emphasised (salience — size, position, "
        "contrast), how it's framed as a problem (definition), what causes "
        "are implied (causal diagnosis), what moral judgments are suggested "
        "(evaluation), and what remedies are implied (treatment). Look at "
        "the actual depicted content and how it's framed.",
    ),
    "narrative": (
        "Labov (1972) Narrative Structure",
        "Analyse the image for narrative elements: orientation (who, what, "
        "where, when — the depicted setting), complicating action (what is "
        "happening, what event is captured), evaluation (why this is "
        "noteworthy — expressions, salience), resolution (what is the "
        "outcome or implied outcome), and coda (connection to the present). "
        "A single image is a frozen moment — infer the narrative around it.",
    ),
    "visual_metaphor": (
        "MIPVU-inspired Visual Metaphor Analysis",
        "Analyse the image for visual and cross-modal metaphors. Look for "
        "conceptual mappings where a source domain is depicted visually to "
        "stand for a target domain. Consider: is there a tension between "
        "the literal depiction and a figurative reading? What is the "
        "source domain (the depicted thing)? What is the implied target "
        "domain (what it stands for)? Look at the actual visual content "
        "for metaphorical mappings.",
    ),
    "emotion": (
        "Combined Image + Text Emotion Analysis",
        "Analyse the emotional content of the image: what emotions are "
        "depicted (in faces, postures, colours, composition)? What "
        "emotional response does the image seem designed to evoke in the "
        "viewer? How do the visual and textual elements (if any) combine "
        "to produce an emotional effect? Look at the actual depicted "
        "expressions and visual cues.",
    ),
    "cultural": (
        "Culture-Specific Symbolic Analysis",
        "Analyse the image for culture-specific symbols, references, and "
        "meanings. Look at depicted objects, gestures, colours, clothing, "
        "settings, and text that may carry culture-specific significance. "
        "Remember: cultural readings are ALWAYS culture-relative, not "
        "universal. State which cultural context you're reading from and "
        "acknowledge other readings may exist. Look at the actual depicted "
        "content for cultural markers.",
    ),
}


def _prompt_hash(prompt: str) -> str:
    """SHA-256 of the prompt, truncated to 16 hex chars. Used as the
    cache key suffix so re-running with a different prompt doesn't
    overwrite a previous cached result."""
    return hashlib.sha256(prompt.encode("utf-8")).hexdigest()[:16]


def _build_system_prompt(framework_key: str) -> str:
    """Build the system prompt for a given framework.

    Combines the hedging contract (§4 Principle 5) with the framework-
    specific lens description. The hedging contract is the same for all
    frameworks — it's the project-wide commitment to phrasing
    interpretive claims as hypotheses.
    """
    if framework_key not in _FRAMEWORK_PROMPTS:
        raise ValueError(
            f"Unknown framework key: {framework_key!r}. "
            f"Supported: {list(_FRAMEWORK_PROMPTS.keys())}"
        )
    framework_name, lens_description = _FRAMEWORK_PROMPTS[framework_key]
    return (
        f"{_HEDGING_CONTRACT}\n\n"
        f"Framework: {framework_name}\n\n"
        f"What to look for under this lens:\n{lens_description}"
    )


def _build_user_prompt(
    framework_key: str,
    caption: str,
    cached_ocr: str,
    custom_prompt: str | None = None,
) -> str:
    """Build the user prompt sent alongside the image bytes.

    The user prompt is intentionally short (small vision models struggle
    with long prompts — see step 3 finding). It includes the framework
    name, any caption/OCR context, and the request for JSON output.
    The bulk of the instruction is in the system prompt.
    """
    framework_name = _FRAMEWORK_PROMPTS[framework_key][0]
    parts = [f"Analyse this image under the {framework_name} framework."]
    if caption:
        parts.append(f"Caption: {caption!r}")
    if cached_ocr:
        parts.append(f"OCR text: {cached_ocr!r}")
    if custom_prompt:
        parts.append(f"Additional instruction: {custom_prompt}")
    parts.append("Output the JSON now.")
    return " ".join(parts)


# ---------------------------------------------------------------------------
# JSON parsing (defensive)
# ---------------------------------------------------------------------------


def _parse_claims_json(
    raw: str,
    framework_name: str,
    framework_key: str,
) -> tuple[list[dict[str, Any]], str]:
    """Parse the vision-LM's JSON output into a list of claim dicts.

    Defensive: if the model didn't return valid JSON (common with small
    models — they wrap JSON in prose or code fences), fall back to a
    single claim wrapping the raw text. This keeps the route from
    500-ing on a model that didn't follow the format instructions.

    Returns (claims, summary).
    """
    # Strip markdown code fences if present (small models often add them
    # despite instructions not to).
    cleaned = raw.strip()
    if cleaned.startswith("```"):
        # Remove the opening fence (```json or ```)
        first_newline = cleaned.find("\n")
        if first_newline != -1:
            cleaned = cleaned[first_newline + 1:]
        # Remove the closing fence
        if cleaned.rstrip().endswith("```"):
            cleaned = cleaned.rstrip()[:-3]

    try:
        data = json.loads(cleaned)
    except json.JSONDecodeError:
        # Fallback: wrap the raw text in a single claim. The user can
        # still see what the model said; they just don't get structured
        # claims. Mark confidence low since we couldn't parse it.
        log.warning(
            "vlm_discourse_json_parse_failed",
            framework=framework_key,
            raw_preview=raw[:200],
        )
        return (
            [{
                "framework": framework_name,
                "category": "unstructured",
                "claim": raw.strip(),
                "evidence": [],
                "confidence": 0.3,
            }],
            "Vision-LM output could not be parsed as JSON; raw text wrapped in a single claim.",
        )

    claims_raw = data.get("claims", [])
    summary = data.get("summary", "")

    # Normalize each claim to the expected shape. If a required field
    # is missing, fill it in rather than dropping the claim.
    claims: list[dict[str, Any]] = []
    for c in claims_raw:
        if not isinstance(c, dict):
            continue
        claims.append({
            "framework": c.get("framework", framework_name),
            "category": c.get("category", "unspecified"),
            "claim": c.get("claim", ""),
            "evidence": c.get("evidence", []) if isinstance(c.get("evidence"), list) else [],
            "confidence": float(c.get("confidence", 0.5)),
        })

    if not claims:
        claims = [{
            "framework": framework_name,
            "category": "no_claims",
            "claim": summary or "The vision-LM produced no structured claims for this image.",
            "evidence": [],
            "confidence": 0.2,
        }]

    if not summary:
        summary = f"Vision-LM analysis produced {len(claims)} claims under {framework_name}."

    return claims, summary


# ---------------------------------------------------------------------------
# Cache helpers
# ---------------------------------------------------------------------------


def _cache_key(framework_key: str, model: str, prompt_hash: str) -> str:
    """Build the cache key for a discourse analysis.

    Keyed on framework + model + prompt_hash so re-running with a
    different framework, model, or prompt doesn't overwrite a previous
    cached result."""
    return f"{framework_key}:{model}:{prompt_hash}"


def _get_cached(
    img: ImageModel,
    key: str,
) -> dict[str, Any] | None:
    """Look up a cached discourse analysis. Returns None on miss."""
    vlm_discourse = (img.analysis or {}).get("vision_llm_discourse", {})
    return vlm_discourse.get(key)


def _store_cached(
    img: ImageModel,
    key: str,
    result: dict[str, Any],
) -> None:
    """Store a discourse analysis in the cache.

    CRITICAL: img.analysis is a plain JSON column, not wrapped in
    MutableDict.as_mutable(). In-place mutation will NOT be detected
    by SQLAlchemy and will be silently lost on commit. This project
    has shipped that exact bug twice already (delete_document,
    recompile_corpus in api/corpora.py). Always reassign the full dict.
    """
    new_analysis = dict(img.analysis or {})
    vlm_discourse = dict(new_analysis.get("vision_llm_discourse", {}))
    vlm_discourse[key] = result
    new_analysis["vision_llm_discourse"] = vlm_discourse
    img.analysis = new_analysis  # full reassignment


# ---------------------------------------------------------------------------
# Main entry point
# ---------------------------------------------------------------------------


async def run_llm_discourse_analysis(
    img: ImageModel,
    framework_key: str,
    provider: ModelProvider,
    *,
    model: str | None = None,
    custom_prompt: str | None = None,
    refresh: bool = False,
) -> LLMDiscourseResult:
    """Run a vision-LM-backed discourse analysis on an image.

    This is the shared entry point called by all eight discourse routes
    when mode=llm is requested. It:

      1. Looks up the framework's prompt template.
      2. Checks the cache (img.analysis["vision_llm_discourse"]).
      3. On cache hit (and not refresh), returns the cached result.
      4. On cache miss, builds the system + user prompts, sends the
         image bytes + prompts to the vision-LM, parses the JSON
         response, caches the result, and returns it.

    Raises:
      ValueError: if framework_key is unknown.
      ModelProviderError: if the provider call fails (caller catches
        and falls back to heuristic).
    """
    if framework_key not in _FRAMEWORK_PROMPTS:
        raise ValueError(
            f"Unknown framework key: {framework_key!r}. "
            f"Supported: {list(_FRAMEWORK_PROMPTS.keys())}"
        )

    framework_name, _ = _FRAMEWORK_PROMPTS[framework_key]

    # --- Resolve model name ---------------------------------------------
    model_name = model or getattr(provider, "default_model", None)
    if not model_name:
        try:
            available = await provider.list_models()
            if available:
                model_name = available[0]
                log.info(
                    "vlm_discourse_auto_selected_model",
                    model=model_name,
                    framework=framework_key,
                )
        except Exception as e:
            log.warning("vlm_discourse_auto_select_failed", error=str(e))

    if not model_name:
        raise ModelProviderError(
            "No model specified and provider has no default model. "
            "Specify a model name."
        )

    # --- Cache lookup ---------------------------------------------------
    system_prompt = _build_system_prompt(framework_key)
    cached_ocr = (img.analysis or {}).get("ocr", {}).get("text", "")
    caption = img.caption or ""
    user_prompt = _build_user_prompt(framework_key, caption, cached_ocr, custom_prompt)
    ph = _prompt_hash(system_prompt + user_prompt)
    key = _cache_key(framework_key, model_name, ph)

    if not refresh:
        cached = _get_cached(img, key)
        if cached:
            log.info(
                "vlm_discourse_cache_hit",
                image_id=img.id,
                framework=framework_key,
                model=model_name,
            )
            return LLMDiscourseResult(
                analysis_type=cached["analysis_type"],
                framework=cached["framework"],
                claims=cached["claims"],
                summary=cached["summary"],
                provenance=LLMProvenance(
                    mode="llm",
                    model=cached["provenance"]["model"],
                    provider=cached["provenance"]["provider"],
                    prompt_hash=cached["provenance"]["prompt_hash"],
                    timestamp=cached["provenance"]["timestamp"],
                    cached=True,
                ),
            )

    # --- Read image bytes + call the provider ---------------------------
    if not img.storage_path or not Path(img.storage_path).exists():
        raise ModelProviderError(
            "Image file not found on disk. Re-ingest the image."
        )
    image_bytes = Path(img.storage_path).read_bytes()

    messages = [
        Message(role="system", content=system_prompt),
        Message(
            role="user",
            content=user_prompt,
            images=(image_bytes,),
        ),
    ]

    log.info(
        "vlm_discourse_request",
        image_id=img.id,
        framework=framework_key,
        provider=provider.name,
        model=model_name,
        prompt_hash=ph,
        image_bytes=len(image_bytes),
        refresh=refresh,
    )

    response: ChatResponse = await provider.chat(
        messages,
        model=model_name,
        temperature=0.2,  # slightly higher than /describe — analysis benefits from some variation
        timeout=120.0,
        json_mode=True,   # request JSON format from the model
    )

    raw_content = response.content.strip()
    if not raw_content:
        raise ModelProviderError(
            f"Vision-LM returned empty content for {framework_key} analysis. "
            f"Model: {model_name}. This can happen with small models if the "
            f"prompt doesn't match their expected template."
        )

    claims, summary = _parse_claims_json(raw_content, framework_name, framework_key)

    timestamp = datetime.now(UTC).isoformat()

    # --- Cache the result (full reassignment per §2.4) ------------------
    cached_result = {
        "analysis_type": framework_key.split("_")[0] if "_" in framework_key else framework_key,
        "framework": framework_name,
        "claims": claims,
        "summary": summary,
        "provenance": {
            "mode": "llm",
            "model": response.model or model_name,
            "provider": provider.name,
            "prompt_hash": ph,
            "timestamp": timestamp,
        },
    }
    _store_cached(img, key, cached_result)

    log.info(
        "vlm_discourse_success",
        image_id=img.id,
        framework=framework_key,
        model=response.model or model_name,
        claim_count=len(claims),
    )

    return LLMDiscourseResult(
        analysis_type=cached_result["analysis_type"],
        framework=framework_name,
        claims=claims,
        summary=summary,
        provenance=LLMProvenance(
            mode="llm",
            model=response.model or model_name,
            provider=provider.name,
            prompt_hash=ph,
            timestamp=timestamp,
            cached=False,
        ),
    )
