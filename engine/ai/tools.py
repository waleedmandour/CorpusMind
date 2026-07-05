"""
Phase 1+2 grounded-AI tool registry (§11.2).

Each tool is a closure over an async session factory so it can run DB queries
on demand. Every tool returns plain dict / list output that the model can cite
in its final answer — and the assistant layer's `grounded: bool` flag flips
true whenever at least one tool was invoked.
"""
from __future__ import annotations

import time
from typing import Any

from sqlalchemy.ext.asyncio import AsyncSession

from app.logging import get_logger
from discourse.service import (
    compute_dependency_analysis,
    compute_discourse_analysis,
    compute_grammar_analysis,
    compute_metaphor_candidates,
    compute_ngrams,
    compute_pos_analysis,
    compute_sentiment,
    compute_vocab_profile,
)
from nlp.arabic.pipeline import (
    analyze_arabic,
    detect_arabic_register,
    extract_arabic_roots,
    identify_arabic_dialect,
    transliterate_buckwalter,
)
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
# Phase 2 tools
# --------------------------------------------------------------------------- #


async def _get_ngrams(session: AsyncSession, *, corpus_id: str, n: int = 2,
                     min_freq: int = 5, min_range: int = 1, limit: int = 20) -> dict:
    r = await compute_ngrams(session, corpus_id, n=n, min_freq=min_freq,
                              min_range=min_range, limit=limit)
    return {
        "n": r.n, "total_tokens": r.total_tokens,
        "top_ngrams": r.rows,
        "min_freq": r.min_freq, "min_range": r.min_range,
    }


async def _get_pos_analysis(session: AsyncSession, *, corpus_id: str,
                            n: int = 2, limit: int = 20) -> dict:
    r = await compute_pos_analysis(session, corpus_id, n=n, limit=limit)
    return {
        "total_tokens": r.total_tokens,
        "distribution_top": r.distribution[:10],
        "pos_ngrams_top": r.pos_ngrams[:limit],
    }


async def _grammar_query(session: AsyncSession, *, corpus_id: str,
                         patterns: list[str] | None = None, limit: int = 10) -> dict:
    r = await compute_grammar_analysis(session, corpus_id, patterns=patterns, limit=limit)
    return {
        "counts": r.counts,
        "examples": {p: r.patterns.get(p, [])[:limit] for p in (patterns or r.counts.keys())},
    }


async def _dependency_query(session: AsyncSession, *, corpus_id: str,
                             relation: str = "nsubj", limit: int = 20) -> dict:
    r = await compute_dependency_analysis(session, corpus_id, relation=relation, limit=limit)
    return {"relation": r.relation, "top_pairs": r.rows}


async def _discourse_analysis(session: AsyncSession, *, corpus_id: str) -> dict:
    r = await compute_discourse_analysis(session, corpus_id)
    return {
        "taxonomy": r.taxonomy,
        "total_tokens": r.total_tokens,
        "categories": r.categories,
    }


async def _vocab_profile(session: AsyncSession, *, corpus_id: str) -> dict:
    r = await compute_vocab_profile(session, corpus_id)
    return {
        "total_tokens": r.total_tokens,
        "total_types": r.total_types,
        "bands": r.bands,
        "rare_words_count": len(r.rare_words),
        "academic_words_count": len(r.academic_words),
    }


async def _sentiment(session: AsyncSession, *, corpus_id: str) -> dict:
    r = await compute_sentiment(session, corpus_id)
    return {
        "total_sentences": r.total_sentences,
        "positive": r.positive, "negative": r.negative, "neutral": r.neutral,
        "avg_score": r.avg_score,
    }


async def _metaphor_candidates(session: AsyncSession, *, corpus_id: str,
                                limit: int = 10) -> dict:
    r = await compute_metaphor_candidates(session, corpus_id, limit=limit)
    return {
        "pipeline": r.pipeline,
        "verified_count": r.verified_count,
        "candidate_count": len(r.candidates),
        "candidates": r.candidates[:limit],
        "note": ("These are candidates only — the LLM triages via MIPVU decision "
                 "steps, and a human must verify before any candidate counts as a "
                 "confirmed metaphor in export/statistics (§8.17)."),
    }


# --------------------------------------------------------------------------- #
# Phase 3 tools — Arabic (§8.21)
# --------------------------------------------------------------------------- #


def _arabic_morphology(*, text: str, dialect: str = "msa") -> dict:
    """Analyze Arabic text — root extraction, pattern (وزن) identification,
    lemma normalization, POS, Buckwalter transliteration. No session needed."""
    analysis = analyze_arabic(text, dialect=dialect)
    return {
        "backend": analysis.backend,
        "detected_dialect": analysis.detected_dialect,
        "token_count": len(analysis.tokens),
        "top_tokens": [
            {
                "text": t.text, "root": t.root, "pattern": t.pattern,
                "lemma": t.lemma, "pos": t.pos, "buckwalter": t.buckwalter,
            }
            for t in analysis.tokens[:20]
        ],
    }


def _arabic_dialect_id(*, text: str) -> dict:
    """Identify Arabic dialect (MSA / Egyptian / Gulf / Levantine).
    Returns a probability distribution."""
    return {"dialect_distribution": identify_arabic_dialect(text)}


def _arabic_roots(*, text: str) -> dict:
    """Extract roots (الجذر) + patterns (الوزن) from Arabic text."""
    return {"roots": extract_arabic_roots(text)[:20]}


def _arabic_register(*, text: str) -> dict:
    """Detect Arabic register: Classical / MSA / Dialectal."""
    return {"register_distribution": detect_arabic_register(text)}


def _arabic_transliterate(*, text: str) -> dict:
    """Transliterate Arabic to Buckwalter encoding."""
    return {"buckwalter": transliterate_buckwalter(text)}


# --------------------------------------------------------------------------- #
# Phase 5 tools — multimodal discourse (§9.10–9.14)
# --------------------------------------------------------------------------- #
# These wrap the engine's discourse functions for the AI Assistant.
# They're stateless + sync because the heavy DB work (image loading) is
# done by the caller — these functions just take pre-fetched analysis data.


def _visual_grammar(*, colours: dict, composition: dict, ocr: dict, caption: str = "") -> dict:
    """Analyse an image against Kress & van Leeuwen's Visual Grammar (§9.10)."""
    from multimodal.visual_grammar import analyse_visual_grammar
    from vision.pipeline import ColourAnalysis, CompositionAnalysis, ImageInfo, OCRResult
    info = ImageInfo(width=0, height=0, format="", mode="RGB", size_bytes=0)
    ocr_obj = OCRResult(
        text=ocr.get("text", ""), confidence=ocr.get("confidence", 0),
        word_count=ocr.get("word_count", 0), engine=ocr.get("engine", "none"),
        language=ocr.get("language", "auto"),
    )
    colours_obj = ColourAnalysis(
        dominant_colours=colours.get("dominant_colours", []),
        warm_cold_balance=colours.get("warm_cold_balance", 0),
        brightness=colours.get("brightness", 0),
        contrast=colours.get("contrast", 0),
        saturation=colours.get("saturation", 0),
        colour_symbolism_notes=colours.get("colour_symbolism_notes", []),
    )
    comp_obj = CompositionAnalysis(
        information_value=composition.get("information_value", {}),
        rule_of_thirds_intersections=composition.get("rule_of_thirds_intersections", []),
        salience_centre=tuple(composition.get("salience_centre", [0.5, 0.5])),
        visual_balance=composition.get("visual_balance", 0),
        framing_balance=composition.get("framing_balance", 0),
        vectors=composition.get("vectors", []),
    )
    vg = analyse_visual_grammar(info, ocr_obj, colours_obj, comp_obj)
    return {
        "framework": vg.framework,
        "claim_count": len(vg.claims),
        "top_claims": [
            {"metafunction": c.metafunction, "category": c.category,
             "claim": c.claim, "confidence": c.confidence}
            for c in vg.claims[:5]
        ],
    }


def _social_semiotic(*, colours: dict, composition: dict, ocr: dict, caption: str = "") -> dict:
    """Social semiotic analysis (§9.11)."""
    from multimodal.discourse import analyse_social_semiotic
    from vision.pipeline import ColourAnalysis, CompositionAnalysis, OCRResult
    colours_obj = ColourAnalysis(
        dominant_colours=colours.get("dominant_colours", []),
        warm_cold_balance=colours.get("warm_cold_balance", 0),
        brightness=colours.get("brightness", 0),
        contrast=colours.get("contrast", 0),
        saturation=colours.get("saturation", 0),
        colour_symbolism_notes=colours.get("colour_symbolism_notes", []),
    )
    comp_obj = CompositionAnalysis(
        information_value=composition.get("information_value", {}),
        rule_of_thirds_intersections=composition.get("rule_of_thirds_intersections", []),
        salience_centre=tuple(composition.get("salience_centre", [0.5, 0.5])),
        visual_balance=composition.get("visual_balance", 0),
        framing_balance=composition.get("framing_balance", 0),
        vectors=composition.get("vectors", []),
    )
    ocr_obj = OCRResult(
        text=ocr.get("text", ""), confidence=ocr.get("confidence", 0),
        word_count=ocr.get("word_count", 0), engine=ocr.get("engine", "none"),
        language=ocr.get("language", "auto"),
    )
    r = analyse_social_semiotic(colours_obj, comp_obj, ocr_obj, caption)
    return {
        "framework": r.framework,
        "claim_count": len(r.claims),
        "top_claims": [
            {"category": c.category, "claim": c.claim, "confidence": c.confidence}
            for c in r.claims[:5]
        ],
    }


def _cda(*, colours: dict, composition: dict, ocr: dict, caption: str = "",
         framework: str = "fairclough") -> dict:
    """Critical Discourse Analysis (§9.12) — user-selectable framework."""
    from multimodal.discourse import analyse_cda
    from vision.pipeline import ColourAnalysis, CompositionAnalysis, OCRResult
    colours_obj = ColourAnalysis(
        dominant_colours=colours.get("dominant_colours", []),
        warm_cold_balance=colours.get("warm_cold_balance", 0),
        brightness=colours.get("brightness", 0),
        contrast=colours.get("contrast", 0),
        saturation=colours.get("saturation", 0),
        colour_symbolism_notes=colours.get("colour_symbolism_notes", []),
    )
    comp_obj = CompositionAnalysis(
        information_value=composition.get("information_value", {}),
        rule_of_thirds_intersections=composition.get("rule_of_thirds_intersections", []),
        salience_centre=tuple(composition.get("salience_centre", [0.5, 0.5])),
        visual_balance=composition.get("visual_balance", 0),
        framing_balance=composition.get("framing_balance", 0),
        vectors=composition.get("vectors", []),
    )
    ocr_obj = OCRResult(
        text=ocr.get("text", ""), confidence=ocr.get("confidence", 0),
        word_count=ocr.get("word_count", 0), engine=ocr.get("engine", "none"),
        language=ocr.get("language", "auto"),
    )
    r = analyse_cda(colours_obj, comp_obj, ocr_obj, caption, framework=framework)
    return {
        "framework": r.framework,
        "claim_count": len(r.claims),
        "top_claims": [
            {"category": c.category, "claim": c.claim, "confidence": c.confidence}
            for c in r.claims[:5]
        ],
    }


def _persuasion(*, ocr: dict, caption: str = "") -> dict:
    """Persuasion analysis (§9.13) — Aristotle + Toulmin."""
    from multimodal.discourse import analyse_persuasion
    from vision.pipeline import OCRResult
    ocr_obj = OCRResult(
        text=ocr.get("text", ""), confidence=ocr.get("confidence", 0),
        word_count=ocr.get("word_count", 0), engine=ocr.get("engine", "none"),
        language=ocr.get("language", "auto"),
    )
    r = analyse_persuasion(ocr_obj, caption)
    return {
        "framework": r.framework,
        "claim_count": len(r.claims),
        "top_claims": [
            {"category": c.category, "claim": c.claim, "confidence": c.confidence}
            for c in r.claims[:5]
        ],
    }


def _framing(*, ocr: dict, caption: str = "") -> dict:
    """Framing analysis (§9.14) — Entman's 4 functions."""
    from multimodal.discourse import analyse_framing
    from vision.pipeline import OCRResult
    ocr_obj = OCRResult(
        text=ocr.get("text", ""), confidence=ocr.get("confidence", 0),
        word_count=ocr.get("word_count", 0), engine=ocr.get("engine", "none"),
        language=ocr.get("language", "auto"),
    )
    r = analyse_framing(ocr_obj, caption)
    return {
        "framework": r.framework,
        "claim_count": len(r.claims),
        "top_claims": [
            {"category": c.category, "claim": c.claim, "confidence": c.confidence}
            for c in r.claims[:5]
        ],
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
            "name": "get_ngrams",
            "description": (
                "Compute n-grams (2-10) with the frequency-and-range criterion (§8.8). "
                "Lexical bundles require BOTH a minimum frequency AND a minimum number "
                "of distinct documents — report both when summarizing."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "corpus_id": {"type": "string"},
                    "n": {"type": "integer", "default": 2, "minimum": 2, "maximum": 10},
                    "min_freq": {"type": "integer", "default": 5},
                    "min_range": {"type": "integer", "default": 1, "description": "Min distinct documents"},
                    "limit": {"type": "integer", "default": 20},
                },
                "required": ["corpus_id"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "get_pos_analysis",
            "description": (
                "Get POS distribution + POS n-grams (§8.11). Use n=1 for distribution, "
                "n=2 for POS bigrams, etc. Useful for stylistic analysis."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "corpus_id": {"type": "string"},
                    "n": {"type": "integer", "default": 2, "minimum": 1, "maximum": 5},
                    "limit": {"type": "integer", "default": 20},
                },
                "required": ["corpus_id"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "grammar_query",
            "description": (
                "Run dependency-driven grammar pattern detectors (§8.12): passive_voice, "
                "modal, negation, relative_clause, complex_np, tense. Returns counts and "
                "example sentences with evidence IDs."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "corpus_id": {"type": "string"},
                    "patterns": {
                        "type": "array", "items": {"type": "string"},
                        "description": "Subset of: passive_voice, modal, negation, relative_clause, complex_np, tense. Default: all.",
                    },
                    "limit": {"type": "integer", "default": 10},
                },
                "required": ["corpus_id"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "dependency_query",
            "description": (
                "Query dependency relations (§8.13): most common governor-dependent pairs "
                "for a given relation (nsubj, obj, iobj, obl, etc.). Useful for verb-valency "
                "and argument-structure analysis."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "corpus_id": {"type": "string"},
                    "relation": {"type": "string", "default": "nsubj"},
                    "limit": {"type": "integer", "default": 20},
                },
                "required": ["corpus_id"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "discourse_analysis",
            "description": (
                "Detect Hyland's metadiscourse markers (§8.15): interactive (transitions, "
                "frame_markers, endophoric_markers, evidentials, code_glosses) + interactional "
                "(hedges, boosters, attitude_markers, self_mentions, engagement_markers). "
                "Always cite the taxonomy (Hyland 2005) in your answer."
            ),
            "parameters": {
                "type": "object",
                "properties": {"corpus_id": {"type": "string"}},
                "required": ["corpus_id"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "vocab_profile",
            "description": (
                "Profile vocabulary into frequency bands (K1, K2-K9, AWL, Off-list) — §8.10. "
                "Also reports rare words and academic words. Uses a starter AWL subset; "
                "Phase 3 swaps in a proper open frequency corpus."
            ),
            "parameters": {
                "type": "object",
                "properties": {"corpus_id": {"type": "string"}},
                "required": ["corpus_id"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "sentiment",
            "description": (
                "Per-sentence sentiment analysis (§8.18). Returns positive/negative/neutral "
                "counts + average score (-1 to +1). Lexicon-based; Phase 3 swaps in VADER or "
                "a transformers model behind the same interface."
            ),
            "parameters": {
                "type": "object",
                "properties": {"corpus_id": {"type": "string"}},
                "required": ["corpus_id"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "metaphor_candidates",
            "description": (
                "Find metaphor candidates (§8.17) — verbs with abstract subjects. These are "
                "CANDIDATES ONLY. You (the LLM) triage them via MIPVU decision steps, and a "
                "HUMAN must verify before any candidate counts as a confirmed metaphor in "
                "export/statistics. This verification gate is load-bearing for validity."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "corpus_id": {"type": "string"},
                    "limit": {"type": "integer", "default": 10},
                },
                "required": ["corpus_id"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "arabic_morphology",
            "description": (
                "Analyze Arabic text morphologically (§8.21): tokenization + root "
                "extraction (الجذر) + pattern identification (الوزن) + lemma + POS + "
                "Buckwalter transliteration. Backend: CAMeL Tools (calima-msa-r13). "
                "Use this whenever the user asks about Arabic word structure, roots, "
                "or patterns."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "text": {"type": "string", "description": "Arabic text to analyze"},
                    "dialect": {
                        "type": "string", "enum": ["msa", "egy", "glf", "lev"], "default": "msa",
                        "description": "Dialect-specific morphology DB",
                    },
                },
                "required": ["text"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "arabic_dialect_id",
            "description": (
                "Identify the Arabic dialect of a text (§8.21): MSA, Egyptian, Gulf, "
                "or Levantine. Returns a probability distribution. Phase 4 will swap "
                "in the full CAMeL DialectIdentifier model (274 MB)."
            ),
            "parameters": {
                "type": "object",
                "properties": {"text": {"type": "string"}},
                "required": ["text"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "arabic_roots",
            "description": (
                "Extract triliteral roots (الجذر) and patterns (الوزن) from Arabic "
                "text. Useful for semantic-field analysis: all words sharing a root "
                "are semantically related (e.g. ك.ت.ب → كتاب، مكتبة، كاتب، يكتب)."
            ),
            "parameters": {
                "type": "object",
                "properties": {"text": {"type": "string"}},
                "required": ["text"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "arabic_register",
            "description": (
                "Detect Arabic register: Classical (Quranic/Classical), MSA, or "
                "Dialectal. Useful for diachronic corpus analysis."
            ),
            "parameters": {
                "type": "object",
                "properties": {"text": {"type": "string"}},
                "required": ["text"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "arabic_transliterate",
            "description": (
                "Transliterate Arabic text to Buckwalter encoding (Latin). Useful "
                "for researchers who can't read Arabic script but need to cite "
                "specific forms."
            ),
            "parameters": {
                "type": "object",
                "properties": {"text": {"type": "string"}},
                "required": ["text"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "visual_grammar",
            "description": (
                "Analyse an image against Kress & van Leeuwen's Visual Grammar (§9.10). "
                "Pass the image's cached colour, composition, and OCR analysis dicts. "
                "Returns framework-lensed claims across the 3 metafunctions."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "colours": {"type": "object", "description": "The image's colour analysis dict"},
                    "composition": {"type": "object", "description": "The image's composition analysis dict"},
                    "ocr": {"type": "object", "description": "The image's OCR result dict"},
                    "caption": {"type": "string", "description": "Optional co-occurring caption text"},
                },
                "required": ["colours", "composition", "ocr"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "social_semiotic",
            "description": (
                "Social semiotic analysis (§9.11) — actors, processes, symbolic meaning, "
                "power, identity. Grounded in Kress & van Leeuwen's Social Semiotics."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "colours": {"type": "object"},
                    "composition": {"type": "object"},
                    "ocr": {"type": "object"},
                    "caption": {"type": "string"},
                },
                "required": ["colours", "composition", "ocr"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "cda",
            "description": (
                "Critical Discourse Analysis (§9.12). Framework-selectable: "
                "fairclough, van_dijk, wodak, machin_mayr. Every claim is a "
                "framework-lensed hypothesis per §4 Principle 5."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "colours": {"type": "object"},
                    "composition": {"type": "object"},
                    "ocr": {"type": "object"},
                    "caption": {"type": "string"},
                    "framework": {
                        "type": "string",
                        "enum": ["fairclough", "van_dijk", "wodak", "machin_mayr"],
                        "default": "fairclough",
                    },
                },
                "required": ["colours", "composition", "ocr"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "persuasion",
            "description": (
                "Persuasion analysis (§9.13) — Aristotle's ethos/pathos/logos + "
                "Toulmin's argument structure. This is analysis of existing texts, "
                "not content generation."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "ocr": {"type": "object"},
                    "caption": {"type": "string"},
                },
                "required": ["ocr"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "framing",
            "description": (
                "Framing analysis (§9.14) — Entman's 4 functions: problem definition, "
                "causal interpretation, moral evaluation, treatment recommendation."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "ocr": {"type": "object"},
                    "caption": {"type": "string"},
                },
                "required": ["ocr"],
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


# Maps tool name → implementation.
# - Async functions taking (session, **args) for corpus-backed tools
# - Sync functions taking (**args) for stateless tools (Arabic, ping)
TOOL_IMPLS = {
    # Phase 1 — corpus-backed
    "search_concordance": _search_concordance,
    "get_frequency": _get_frequency,
    "compute_collocations": _compute_collocations,
    "compute_keyness": _compute_keyness,
    "get_dispersion": _get_dispersion,
    # Phase 2 — corpus-backed
    "get_ngrams": _get_ngrams,
    "get_pos_analysis": _get_pos_analysis,
    "grammar_query": _grammar_query,
    "dependency_query": _dependency_query,
    "discourse_analysis": _discourse_analysis,
    "vocab_profile": _vocab_profile,
    "sentiment": _sentiment,
    "metaphor_candidates": _metaphor_candidates,
    # Phase 3 — Arabic (stateless, sync)
    "arabic_morphology": _arabic_morphology,
    "arabic_dialect_id": _arabic_dialect_id,
    "arabic_roots": _arabic_roots,
    "arabic_register": _arabic_register,
    "arabic_transliterate": _arabic_transliterate,
    # Phase 5 — multimodal discourse (stateless, sync — wraps engine functions)
    "visual_grammar": _visual_grammar,
    "social_semiotic": _social_semiotic,
    "cda": _cda,
    "persuasion": _persuasion,
    "framing": _framing,
    # Utility — stateless, sync
    "ping": lambda **_: {"ok": True, "engine": "corpusmind-engine", "ts": time.time()},
}

# Tools that don't need a DB session (stateless / sync)
_STATELESS_TOOLS = {
    "arabic_morphology", "arabic_dialect_id", "arabic_roots",
    "arabic_register", "arabic_transliterate", "ping",
    # Phase 5 — discourse tools take pre-fetched analysis dicts, not DB sessions
    "visual_grammar", "social_semiotic", "cda", "persuasion", "framing",
}


async def execute_tool(name: str, args: dict) -> Any:
    """Execute a tool by name with the given args.

    Corpus-backed tools (Phase 1+2) are async and take an AsyncSession.
    Stateless tools (Phase 3 Arabic, ping) are sync and don't need a session.
    """
    impl = TOOL_IMPLS.get(name)
    if impl is None:
        raise KeyError(f"Unknown tool: {name}")

    if name in _STATELESS_TOOLS:
        # Stateless sync tool — call directly
        result = impl(**args)
        # If it returns a coroutine (async), await it
        import inspect
        if inspect.isawaitable(result):
            return await result
        return result

    # Corpus-backed async tool — open a fresh session
    async with session_scope() as session:
        return await impl(session, **args)


def schemas_for_llm() -> list[dict]:
    """Return the JSON-schema list to pass to the model's `tools` parameter."""
    return TOOL_SCHEMAS


def list_tools() -> list[dict]:
    """Return a UI-facing summary of available tools."""
    return [{"name": s["function"]["name"], "description": s["function"]["description"]}
            for s in TOOL_SCHEMAS]
