"""Analysis API routes: concordance, frequency, collocation, keyness, dispersion."""
from __future__ import annotations

from dataclasses import asdict
from typing import Literal

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field
from sqlalchemy.ext.asyncio import AsyncSession

from stats.service import (
    compute_collocations,
    compute_dispersion,
    compute_frequency,
    compute_keyness,
    search_concordance,
)
from storage.models import Corpus
from storage.session import get_session

router = APIRouter()


# --------------------------------------------------------------------------- #
# Concordance (§8.4)
# --------------------------------------------------------------------------- #


class ConcordanceRequest(BaseModel):
    query: str = Field(..., min_length=1)
    level: Literal["word", "lemma", "pos"] = "word"
    case_sensitive: bool = False
    window: int = Field(5, ge=1, le=20)
    limit: int = Field(100, ge=1, le=1000)
    offset: int = Field(0, ge=0)


@router.post("/corpora/{cid}/concordance")
async def concordance(cid: str, body: ConcordanceRequest, session: AsyncSession = Depends(get_session)) -> dict:
    if not await session.get(Corpus, cid):
        raise HTTPException(404, "Corpus not found")
    result = await search_concordance(
        session, cid, body.query,
        level=body.level, case_sensitive=body.case_sensitive,
        window=body.window, limit=body.limit, offset=body.offset,
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
    unit: Literal["word", "lemma", "pos"] = "word"
    min_freq: int = Field(1, ge=1)
    limit: int = Field(1000, ge=1, le=10000)
    include_punct: bool = False


@router.post("/corpora/{cid}/frequency")
async def frequency(cid: str, body: FrequencyRequest, session: AsyncSession = Depends(get_session)) -> dict:
    if not await session.get(Corpus, cid):
        raise HTTPException(404, "Corpus not found")
    r = await compute_frequency(
        session, cid,
        unit=body.unit, min_freq=body.min_freq, limit=body.limit, include_punct=body.include_punct,
    )
    return asdict(r)


# --------------------------------------------------------------------------- #
# Collocation (§8.6)
# --------------------------------------------------------------------------- #


class CollocationRequest(BaseModel):
    node: str = Field(..., min_length=1)
    level: Literal["word", "lemma"] = "word"
    window: int = Field(5, ge=1, le=20)
    min_freq: int = Field(3, ge=1)
    measures: list[str] | None = None
    limit: int = Field(100, ge=1, le=1000)


@router.post("/corpora/{cid}/collocations")
async def collocations(cid: str, body: CollocationRequest, session: AsyncSession = Depends(get_session)) -> dict:
    if not await session.get(Corpus, cid):
        raise HTTPException(404, "Corpus not found")
    r = await compute_collocations(
        session, cid, body.node,
        level=body.level, window=body.window, min_freq=body.min_freq,
        measures=body.measures, limit=body.limit,
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


@router.post("/corpora/{cid}/keyness")
async def keyness(cid: str, body: KeynessRequest, session: AsyncSession = Depends(get_session)) -> dict:
    if not await session.get(Corpus, cid):
        raise HTTPException(404, "Target corpus not found")
    if not await session.get(Corpus, body.reference_corpus_id):
        raise HTTPException(404, "Reference corpus not found")
    r = await compute_keyness(
        session, cid, body.reference_corpus_id,
        min_freq=body.min_freq, measures=body.measures, limit=body.limit,
    )
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
