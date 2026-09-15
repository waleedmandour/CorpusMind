"""Learner Research API routes (v1.2.0 item 5).

Four endpoints over the learner-corpus engine:

  * POST /corpora/{cid}/learner/caf      — CAF battery report (optionally
    grouped by the learner facets L1 / CEFR proficiency).
  * POST /corpora/{cid}/learner/errors   — rule-based error CANDIDATES
    (English + Arabic seed rules; human/LLM review required).
  * POST /corpora/{cid}/learner/cia      — Contrastive Interlanguage Analysis
    (Granger 1998): keyness against a reference corpus / bundled frequency
    list, plus CAF deltas against a reference or a second learner corpus.
  * POST /learner/caf-text               — CAF on raw pasted text (no corpus
    needed); with a corpus_id it powers the AI-text-vs-learner-corpus
    comparator (caf_delta text-vs-corpus).

Methodological honesty lives in the service/docstrings: accuracy numbers are
heuristic proxies from seed rules, and every response carries notes/citations
saying so.
"""
from __future__ import annotations

from dataclasses import asdict
from typing import Literal

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field
from sqlalchemy.ext.asyncio import AsyncSession

from api.corpora import resolve_subcorpus_document_ids
from app.logging import get_logger
from learner.caf import caf_delta, compute_caf
from learner.errors import detect_error_candidates
from learner.service import cia_compare, learner_caf_report, load_sentences
from nlp.general.pipeline import get_pipeline
from storage.models import Corpus
from storage.session import get_session

log = get_logger(__name__)

router = APIRouter()


# --------------------------------------------------------------------------- #
# POST /corpora/{cid}/learner/caf — the CAF battery
# --------------------------------------------------------------------------- #


class LearnerCAFRequest(BaseModel):
    group_by: Literal["none", "l1", "proficiency"] = "none"
    subcorpus_id: str | None = None


@router.post("/corpora/{cid}/learner/caf")
async def learner_caf(cid: str, body: LearnerCAFRequest, session: AsyncSession = Depends(get_session)) -> dict:
    """Complexity-Accuracy-Fluency indices over the latest annotation version.

    ``group_by`` partitions documents by the learner facet stored in
    ``Document.meta`` (falling back to the corpus-level L1/proficiency
    columns). Every response carries the formulas panel + citations so no
    number ever appears without its definition (§4 Principle 3).
    """
    corpus = await session.get(Corpus, cid)
    if not corpus:
        raise HTTPException(404, "Corpus not found")
    document_ids = (
        await resolve_subcorpus_document_ids(session, body.subcorpus_id)
        if body.subcorpus_id
        else None
    )
    return await learner_caf_report(
        session, cid, group_by=body.group_by, document_ids=document_ids
    )


# --------------------------------------------------------------------------- #
# POST /corpora/{cid}/learner/errors — error candidates (never confirmed errors)
# --------------------------------------------------------------------------- #


class LearnerErrorsRequest(BaseModel):
    language: str | None = None  # default: corpus language ("ar*" → Arabic rules, else English)
    rule_ids: list[str] | None = None
    limit: int = Field(200, ge=1, le=2000)


@router.post("/corpora/{cid}/learner/errors")
async def learner_errors(cid: str, body: LearnerErrorsRequest, session: AsyncSession = Depends(get_session)) -> dict:
    """Rule-based error-candidate detection (ERRANT-lineage seed rules).

    Candidates carry a stable ``line_ref`` (``{document_id}:{sentence_idx}:{token_idx}``)
    so the UI (and the AI Assistant) can cite them. Nothing here is a
    confirmed error — ``verified_count`` is always 0 until a human or a
    human-confirmed LLM triage says otherwise.
    """
    corpus = await session.get(Corpus, cid)
    if not corpus:
        raise HTTPException(404, "Corpus not found")
    language = body.language or corpus.language or "en"
    effective = "ar" if language.startswith("ar") else "en"
    try:
        result = await detect_error_candidates(
            session, cid, language=effective, rule_ids=body.rule_ids, limit=body.limit
        )
    except ValueError as e:
        raise HTTPException(status_code=422, detail=str(e)) from e
    return {
        "corpus": {"id": corpus.id, "language": corpus.language or "en"},
        "language": effective,
        **asdict(result),
    }


# --------------------------------------------------------------------------- #
# POST /corpora/{cid}/learner/cia — Contrastive Interlanguage Analysis
# --------------------------------------------------------------------------- #


class LearnerCIARequest(BaseModel):
    reference_corpus_id: str | None = None
    reference_list: str | None = None  # installed bundled reference name
    compare_corpus_id: str | None = None
    min_freq: int = Field(5, ge=1)
    limit: int = Field(100, ge=1, le=1000)


@router.post("/corpora/{cid}/learner/cia")
async def learner_cia(cid: str, body: LearnerCIARequest, session: AsyncSession = Depends(get_session)) -> dict:
    """Granger (1998) CIA: learner L2 vs target-language reference (keyness +
    CAF delta) and/or vs another learner variety (CAF delta)."""
    corpus = await session.get(Corpus, cid)
    if not corpus:
        raise HTTPException(404, "Corpus not found")
    if body.reference_corpus_id and not await session.get(Corpus, body.reference_corpus_id):
        raise HTTPException(404, "Reference corpus not found")
    if body.compare_corpus_id and not await session.get(Corpus, body.compare_corpus_id):
        raise HTTPException(404, "Compare corpus not found")
    try:
        return await cia_compare(
            session, cid,
            reference_corpus_id=body.reference_corpus_id,
            reference_list=body.reference_list,
            compare_corpus_id=body.compare_corpus_id,
            min_freq=body.min_freq, limit=body.limit,
        )
    except ValueError as e:
        raise HTTPException(404, str(e)) from e


# --------------------------------------------------------------------------- #
# POST /learner/caf-text — CAF on raw text (AI-vs-learner comparator)
# --------------------------------------------------------------------------- #


class LearnerCAFTextRequest(BaseModel):
    text: str = Field(..., min_length=1, max_length=20000)
    language: Literal["en", "ar"] = "en"
    corpus_id: str | None = None


@router.post("/learner/caf-text")
async def learner_caf_text(body: LearnerCAFTextRequest, session: AsyncSession = Depends(get_session)) -> dict:
    """CAF on raw pasted text — no corpus required.

    The text is parsed with the standard NLP pipeline (same backend the
    ingestion path uses), so the indices are directly comparable with a
    corpus CAF report. When ``corpus_id`` is given, the corpus CAF and the
    text-vs-corpus deltas (``caf_delta``) are returned alongside — the
    "AI-generated text vs learner corpus" comparator. A missing NLP model is
    a 503 with an actionable install hint, not a stack trace.
    """
    corpus = None
    if body.corpus_id:
        corpus = await session.get(Corpus, body.corpus_id)
        if not corpus:
            raise HTTPException(404, "Corpus not found")

    try:
        pipeline = get_pipeline("spacy", body.language)
        parsed = pipeline.parse_document(body.text)
    except Exception as e:  # noqa: BLE001 — any pipeline failure is a 503, not a 500
        hint = (
            "Install the spaCy model: pip install en_core_web_sm or "
            "python -m spacy download en_core_web_sm."
            if body.language == "en"
            else "Arabic requires CAMeL Tools: pip install camel-tools && "
            "camel_data -i morphology-db-msa-r13."
        )
        log.warning("learner_caf_text_pipeline_unavailable", language=body.language, error=str(e))
        raise HTTPException(
            status_code=503,
            detail=f"NLP pipeline unavailable for language '{body.language}': {e}. {hint}",
        ) from e

    info = pipeline.info()
    sentences: list[list[dict]] = []
    for si, sent in enumerate(parsed.sentences):
        toks = [
            {
                "text": t.text,
                "lemma": t.lemma,
                "pos": t.pos,
                "morph": t.morph,
                "dep_rel": t.dep_rel,
                "token_idx": t_i,
            }
            for t_i, t in enumerate(sent.tokens, start=1)
            if not t.is_punct and t.pos != "SPACE"
        ]
        if toks:
            sentences.append(toks)

    text_caf = compute_caf(sentences, language=body.language)
    notes = list(text_caf.notes)
    notes.append(
        f"Parsed with {info.backend}:{info.model_name} (spaCy {info.spacy_version}); "
        f"if the model is missing, a tokenizer-only fallback was used and clause/"
        f"morphology indices are omitted."
    )

    corpus_caf = None
    deltas = None
    if corpus is not None:
        corpus_sentences, meta = await load_sentences(session, body.corpus_id)
        corpus_caf = compute_caf(corpus_sentences, language=meta["language"])
        deltas = caf_delta(text_caf, corpus_caf)

    log.info(
        "learner_caf_text", tokens=text_caf.tokens, sentences=text_caf.sentences,
        corpus_id=body.corpus_id,
    )
    return {
        "text_caf": asdict(text_caf),
        "corpus_caf": asdict(corpus_caf) if corpus_caf is not None else None,
        "deltas": deltas,
        "notes": notes,
    }
