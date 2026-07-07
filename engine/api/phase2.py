"""Phase 2 analysis API routes: n-grams, POS, grammar, dependency, discourse, vocabulary, sentiment, metaphor."""
from __future__ import annotations

from dataclasses import asdict

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field
from sqlalchemy.ext.asyncio import AsyncSession

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
from storage.models import Corpus
from storage.session import get_session

router = APIRouter()


# --------------------------------------------------------------------------- #
# §8.8 N-grams
# --------------------------------------------------------------------------- #


class NGramRequest(BaseModel):
    n: int = Field(2, ge=2, le=10)
    min_freq: int = Field(5, ge=1)
    min_range: int = Field(1, ge=1, description="Minimum distinct documents (§8.8 lexical bundles)")
    limit: int = Field(200, ge=1, le=1000)
    skip_punct: bool = True
    skip_stop: bool = False


@router.post("/corpora/{cid}/ngrams")
async def ngrams(cid: str, body: NGramRequest, session: AsyncSession = Depends(get_session)) -> dict:
    if not await session.get(Corpus, cid):
        raise HTTPException(404, "Corpus not found")
    r = await compute_ngrams(session, cid, n=body.n, min_freq=body.min_freq,
                              min_range=body.min_range, limit=body.limit,
                              skip_punct=body.skip_punct, skip_stop=body.skip_stop)
    return asdict(r)


# --------------------------------------------------------------------------- #
# §8.11 POS analysis
# --------------------------------------------------------------------------- #


class POSRequest(BaseModel):
    n: int = Field(2, ge=1, le=5, description="POS n-gram size (1=distribution, 2=bigrams, etc.)")
    min_freq: int = Field(2, ge=1)
    limit: int = Field(100, ge=1, le=1000)


@router.post("/corpora/{cid}/pos-analysis")
async def pos_analysis(cid: str, body: POSRequest, session: AsyncSession = Depends(get_session)) -> dict:
    if not await session.get(Corpus, cid):
        raise HTTPException(404, "Corpus not found")
    r = await compute_pos_analysis(session, cid, n=body.n, min_freq=body.min_freq, limit=body.limit)
    return asdict(r)


# --------------------------------------------------------------------------- #
# §8.12 Grammar analysis
# --------------------------------------------------------------------------- #


class GrammarRequest(BaseModel):
    patterns: list[str] | None = None
    limit: int = Field(50, ge=1, le=500)


@router.post("/corpora/{cid}/grammar")
async def grammar(cid: str, body: GrammarRequest, session: AsyncSession = Depends(get_session)) -> dict:
    if not await session.get(Corpus, cid):
        raise HTTPException(404, "Corpus not found")
    r = await compute_grammar_analysis(session, cid, patterns=body.patterns, limit=body.limit)
    return asdict(r)


@router.get("/corpora/{cid}/grammar/patterns")
async def grammar_patterns(cid: str) -> dict:
    """List the available grammar pattern detectors."""
    from discourse.service import GRAMMAR_DETECTORS
    return {"patterns": list(GRAMMAR_DETECTORS.keys())}


# --------------------------------------------------------------------------- #
# §8.13 Dependency analysis
# --------------------------------------------------------------------------- #


class DependencyRequest(BaseModel):
    relation: str = Field("nsubj", description="UD relation: nsubj, obj, iobj, obl, etc.")
    limit: int = Field(100, ge=1, le=1000)


@router.post("/corpora/{cid}/dependencies")
async def dependencies(cid: str, body: DependencyRequest, session: AsyncSession = Depends(get_session)) -> dict:
    if not await session.get(Corpus, cid):
        raise HTTPException(404, "Corpus not found")
    r = await compute_dependency_analysis(session, cid, relation=body.relation, limit=body.limit)
    return asdict(r)


# --------------------------------------------------------------------------- #
# §8.15 Discourse analysis
# --------------------------------------------------------------------------- #


@router.post("/corpora/{cid}/discourse")
async def discourse(cid: str, session: AsyncSession = Depends(get_session)) -> dict:
    """Hyland's metadiscourse taxonomy (§8.15)."""
    if not await session.get(Corpus, cid):
        raise HTTPException(404, "Corpus not found")
    r = await compute_discourse_analysis(session, cid)
    return asdict(r)


# --------------------------------------------------------------------------- #
# §8.10 Vocabulary profiling
# --------------------------------------------------------------------------- #


class VocabProfileRequest(BaseModel):
    rare_threshold: int = Field(1, ge=1, description="Words appearing <= this many times are 'rare'")
    limit: int = Field(100, ge=1, le=500)


@router.post("/corpora/{cid}/vocab-profile")
async def vocab_profile(cid: str, body: VocabProfileRequest, session: AsyncSession = Depends(get_session)) -> dict:
    if not await session.get(Corpus, cid):
        raise HTTPException(404, "Corpus not found")
    r = await compute_vocab_profile(session, cid, rare_threshold=body.rare_threshold, limit=body.limit)
    return asdict(r)


# --------------------------------------------------------------------------- #
# §8.18 Sentiment analysis
# --------------------------------------------------------------------------- #


@router.post("/corpora/{cid}/sentiment")
async def sentiment(cid: str, session: AsyncSession = Depends(get_session)) -> dict:
    if not await session.get(Corpus, cid):
        raise HTTPException(404, "Corpus not found")
    r = await compute_sentiment(session, cid)
    return asdict(r)


# --------------------------------------------------------------------------- #
# §8.17 Metaphor candidates
# --------------------------------------------------------------------------- #


class MetaphorRequest(BaseModel):
    limit: int = Field(50, ge=1, le=500)


@router.post("/corpora/{cid}/metaphor-candidates")
async def metaphor_candidates(cid: str, body: MetaphorRequest, session: AsyncSession = Depends(get_session)) -> dict:
    """Find metaphor candidates (§8.17). The LLM triages these via the
    metaphor_triage tool, and the human must verify before any candidate
    counts as a confirmed metaphor in export/statistics."""
    if not await session.get(Corpus, cid):
        raise HTTPException(404, "Corpus not found")
    r = await compute_metaphor_candidates(session, cid, limit=body.limit)
    return asdict(r)
