"""Analysis API routes: concordance, frequency, collocation, keyness, dispersion."""
from __future__ import annotations

import asyncio
from dataclasses import asdict
from typing import Literal

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field
from sqlalchemy.ext.asyncio import AsyncSession

from api.corpora import resolve_subcorpus_document_ids
from api.wordlists import resolve_stopword_set
from stats.service import (
    compute_collocations,
    compute_corpus_readability,
    compute_dispersion,
    compute_document_stats,
    compute_frequency,
    compute_group_frequency,
    compute_keyness,
    search_concordance,
)
from storage.models import Corpus
from storage.session import get_session

# Fix #8: Concurrency limiter for expensive analysis queries.
# Prevents a single user from exhausting RAM by issuing many concurrent
# collocation/keyness queries, each of which loads tokens into memory.
_analysis_semaphore = asyncio.Semaphore(4)

router = APIRouter()


# --------------------------------------------------------------------------- #
# Concordance (§8.4)
# --------------------------------------------------------------------------- #


class SortSpec(BaseModel):
    side: Literal["left", "right"] = "right"
    offset: int = Field(1, ge=1, le=3)


class ConcordanceRequest(BaseModel):
    query: str = Field(..., min_length=1)
    level: Literal["word", "lemma", "pos", "root", "pattern"] = "word"
    case_sensitive: bool = False
    regex: bool = False  # v1.0.1: Python-regex matching (word/lemma/pos)
    window: int = Field(5, ge=1, le=20)
    limit: int = Field(100, ge=1, le=1000)
    offset: int = Field(0, ge=0)
    subcorpus_id: str | None = None  # Issue 2: optional subcorpus restriction
    random_sample: int | None = Field(None, ge=1, le=10000)  # Issue 17
    sample_seed: int | None = None  # Issue 17: reproducible sampling
    sort: list[SortSpec] | None = None  # v1.0.1: KWIC sort (L1/R1/L2/R2…)


@router.post("/corpora/{cid}/concordance")
async def concordance(cid: str, body: ConcordanceRequest, session: AsyncSession = Depends(get_session)) -> dict:
    if not await session.get(Corpus, cid):
        raise HTTPException(404, "Corpus not found")
    document_ids = (
        await resolve_subcorpus_document_ids(session, body.subcorpus_id)
        if body.subcorpus_id
        else None
    )
    result = await search_concordance(
        session, cid, body.query,
        level=body.level, case_sensitive=body.case_sensitive,
        regex=body.regex,
        window=body.window, limit=body.limit, offset=body.offset,
        document_ids=document_ids,
        random_sample=body.random_sample, sample_seed=body.sample_seed,
        sort=[s.model_dump() for s in body.sort] if body.sort else None,
    )
    return {
        "lines": [asdict(l) for l in result.lines],
        "total": result.total,
        "query": result.query,
    }


# --------------------------------------------------------------------------- #
# Frequency (§8.5)
# --------------------------------------------------------------------------- #


class FrequencyRequest(BaseModel):
    unit: Literal["word", "lemma", "pos", "root", "pattern"] = "word"
    min_freq: int = Field(1, ge=1)
    limit: int = Field(1000, ge=1, le=10000)
    include_punct: bool = False
    subcorpus_id: str | None = None  # Issue 2: optional subcorpus restriction
    stopword_list_id: str | None = None  # v1.0.1: optional stopword filter


@router.post("/corpora/{cid}/frequency")
async def frequency(cid: str, body: FrequencyRequest, session: AsyncSession = Depends(get_session)) -> dict:
    if not await session.get(Corpus, cid):
        raise HTTPException(404, "Corpus not found")
    document_ids = (
        await resolve_subcorpus_document_ids(session, body.subcorpus_id)
        if body.subcorpus_id
        else None
    )
    stopword_set = await resolve_stopword_set(session, body.stopword_list_id)
    r = await compute_frequency(
        session, cid,
        unit=body.unit, min_freq=body.min_freq, limit=body.limit, include_punct=body.include_punct,
        document_ids=document_ids,
        stopword_set=stopword_set,
    )
    return asdict(r)


# --------------------------------------------------------------------------- #
# Collocation (§8.6)
# --------------------------------------------------------------------------- #


class CollocationRequest(BaseModel):
    node: str = Field(..., min_length=1)
    level: Literal["word", "lemma"] = "word"
    window: int = Field(5, ge=1, le=20)
    span_left: int | None = Field(None, ge=0, le=20)   # v1.0.1: asymmetric span
    span_right: int | None = Field(None, ge=0, le=20)  # v1.0.1: asymmetric span
    min_freq: int = Field(3, ge=1)
    measures: list[str] | None = None
    limit: int = Field(100, ge=1, le=1000)
    subcorpus_id: str | None = None  # Issue 2: optional subcorpus restriction
    pos_include: list[str] | None = None   # v1.0.1: collocate UPOS whitelist (prefix match)
    pos_exclude: list[str] | None = None   # v1.0.1: collocate UPOS blacklist (prefix match)
    stopword_list_id: str | None = None    # v1.0.1: optional stopword filter


@router.post("/corpora/{cid}/collocations")
async def collocations(cid: str, body: CollocationRequest, session: AsyncSession = Depends(get_session)) -> dict:
    # Fix #8: Limit concurrent expensive queries to prevent RAM exhaustion
    async with _analysis_semaphore:
        if not await session.get(Corpus, cid):
            raise HTTPException(404, "Corpus not found")
        document_ids = (
            await resolve_subcorpus_document_ids(session, body.subcorpus_id)
            if body.subcorpus_id
            else None
        )
        stopword_set = await resolve_stopword_set(session, body.stopword_list_id)
        r = await compute_collocations(
            session, cid, body.node,
            level=body.level, window=body.window,
            span_left=body.span_left, span_right=body.span_right,
            min_freq=body.min_freq,
            measures=body.measures, limit=body.limit,
            document_ids=document_ids,
            pos_include=body.pos_include, pos_exclude=body.pos_exclude,
            stopword_set=stopword_set,
        )
        return asdict(r)


# --------------------------------------------------------------------------- #
# Keyness (§8.7)
# --------------------------------------------------------------------------- #


class KeynessRequest(BaseModel):
    reference_corpus_id: str
    min_freq: int = Field(5, ge=1)
    measures: list[str] | None = None
    limit: int = Field(100, ge=1, le=1000)
    subcorpus_id: str | None = None  # Issue 2: optional subcorpus restriction on the TARGET corpus
    stopword_list_id: str | None = None  # v1.0.1: optional stopword filter


@router.post("/corpora/{cid}/keyness")
async def keyness(cid: str, body: KeynessRequest, session: AsyncSession = Depends(get_session)) -> dict:
    # Fix #8: Limit concurrent expensive queries
    async with _analysis_semaphore:
        if not await session.get(Corpus, cid):
            raise HTTPException(404, "Target corpus not found")
        if not await session.get(Corpus, body.reference_corpus_id):
            raise HTTPException(404, "Reference corpus not found")
        target_document_ids = (
            await resolve_subcorpus_document_ids(session, body.subcorpus_id)
            if body.subcorpus_id
            else None
        )
        try:
            r = await compute_keyness(
                session, cid, body.reference_corpus_id,
                min_freq=body.min_freq, measures=body.measures, limit=body.limit,
                target_document_ids=target_document_ids,
                stopword_set=await resolve_stopword_set(session, body.stopword_list_id),
            )
        except ValueError as e:
            raise HTTPException(status_code=422, detail=str(e)) from e
        return asdict(r)


# --------------------------------------------------------------------------- #
# Dispersion (§8.9)
# --------------------------------------------------------------------------- #


class DispersionRequest(BaseModel):
    term: str = Field(..., min_length=1)
    level: Literal["word", "lemma"] = "word"


@router.post("/corpora/{cid}/dispersion")
async def dispersion(cid: str, body: DispersionRequest, session: AsyncSession = Depends(get_session)) -> dict:
    if not await session.get(Corpus, cid):
        raise HTTPException(404, "Corpus not found")
    r = await compute_dispersion(session, cid, body.term, level=body.level)
    return asdict(r)


# --------------------------------------------------------------------------- #
# v1.0.1 — Document statistics, readability, metadata-group pivot
# --------------------------------------------------------------------------- #


@router.get("/corpora/{cid}/documents/stats")
async def document_stats(cid: str, session: AsyncSession = Depends(get_session)) -> dict:
    """Per-document statistics: tokens, types, sentences, TTR, LIX, RIX."""
    if not await session.get(Corpus, cid):
        raise HTTPException(404, "Corpus not found")
    rows = await compute_document_stats(session, cid)
    return {"items": rows}


@router.get("/corpora/{cid}/readability")
async def readability(cid: str, session: AsyncSession = Depends(get_session)) -> dict:
    """Corpus-level readability panel (Flesch for EN; LIX/RIX for all)."""
    if not await session.get(Corpus, cid):
        raise HTTPException(404, "Corpus not found")
    return await compute_corpus_readability(session, cid)


class GroupFrequencyRequest(BaseModel):
    meta_field: str = Field(..., min_length=1, max_length=64)
    unit: Literal["word", "lemma", "pos"] = "word"
    min_freq: int = Field(1, ge=1)
    limit: int = Field(200, ge=1, le=2000)
    subcorpus_id: str | None = None
    stopword_list_id: str | None = None


@router.post("/corpora/{cid}/groups/frequency")
async def group_frequency(cid: str, body: GroupFrequencyRequest, session: AsyncSession = Depends(get_session)) -> dict:
    """Frequency pivot grouped by a metadata variable (genre, year, …)."""
    if not await session.get(Corpus, cid):
        raise HTTPException(404, "Corpus not found")
    document_ids = (
        await resolve_subcorpus_document_ids(session, body.subcorpus_id)
        if body.subcorpus_id
        else None
    )
    stopword_set = await resolve_stopword_set(session, body.stopword_list_id)
    return await compute_group_frequency(
        session, cid, body.meta_field,
        unit=body.unit, min_freq=body.min_freq, limit=body.limit,
        document_ids=document_ids, stopword_set=stopword_set,
    )
