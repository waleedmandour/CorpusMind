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
async def ngrams(
    cid: str, body: NGramRequest, session: AsyncSession = Depends(get_session)
) -> dict:
    if not await session.get(Corpus, cid):
        raise HTTPException(404, "Corpus not found")
    r = await compute_ngrams(
        session,
        cid,
        n=body.n,
        min_freq=body.min_freq,
        min_range=body.min_range,
        limit=body.limit,
        skip_punct=body.skip_punct,
        skip_stop=body.skip_stop,
    )
    return asdict(r)


# --------------------------------------------------------------------------- #
# §8.11 POS analysis
# --------------------------------------------------------------------------- #


class POSRequest(BaseModel):
    n: int = Field(2, ge=1, le=5, description="POS n-gram size (1=distribution, 2=bigrams, etc.)")
    min_freq: int = Field(2, ge=1)
    limit: int = Field(100, ge=1, le=1000)
    tagset: str = Field("upos", description="upos | ptb | claws7 (en) | calima (ar) — v1.2.0")


@router.post("/corpora/{cid}/pos-analysis")
async def pos_analysis(
    cid: str, body: POSRequest, session: AsyncSession = Depends(get_session)
) -> dict:
    corpus = await session.get(Corpus, cid)
    if not corpus:
        raise HTTPException(404, "Corpus not found")
    # v1.2.0: validate the tagset against the corpus language.
    from nlp.tagsets import is_valid_tagset

    if not is_valid_tagset(body.tagset, corpus.language or "en"):
        from nlp.tagsets import valid_tagsets_for_language

        raise HTTPException(
            422,
            f"Tagset '{body.tagset}' is not valid for a '{corpus.language}' corpus. "
            f"Valid tagsets: {', '.join(valid_tagsets_for_language(corpus.language or 'en'))}.",
        )
    r = await compute_pos_analysis(
        session, cid, n=body.n, min_freq=body.min_freq, limit=body.limit, tagset=body.tagset
    )
    return asdict(r)


# --------------------------------------------------------------------------- #
# §8.11b Semantic analysis — USAS top-level (v1.2.0, Issue 4)
# --------------------------------------------------------------------------- #


class SemanticRequest(BaseModel):
    limit: int = Field(100, ge=1, le=100)


@router.post("/corpora/{cid}/semantic-analysis")
async def semantic_analysis(
    cid: str, body: SemanticRequest, session: AsyncSession = Depends(get_session)
) -> dict:
    """USAS top-level semantic distribution (lexicon-based, experimental)."""
    from discourse.service import compute_semantic_analysis

    corpus = await session.get(Corpus, cid)
    if not corpus:
        raise HTTPException(404, "Corpus not found")
    from nlp.tagsets import load_semantic_lexicon

    if not load_semantic_lexicon(corpus.language or "en"):
        raise HTTPException(
            503,
            "The USAS semantic lexicon for this language is not installed. "
            "See reference-data/tagsets/ in the repository.",
        )
    r = await compute_semantic_analysis(session, cid, limit=body.limit)
    return asdict(r)


# --------------------------------------------------------------------------- #
# §8.12 Grammar analysis
# --------------------------------------------------------------------------- #


class GrammarRequest(BaseModel):
    patterns: list[str] | None = None
    limit: int = Field(50, ge=1, le=500)


@router.post("/corpora/{cid}/grammar")
async def grammar(
    cid: str, body: GrammarRequest, session: AsyncSession = Depends(get_session)
) -> dict:
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
async def dependencies(
    cid: str, body: DependencyRequest, session: AsyncSession = Depends(get_session)
) -> dict:
    if not await session.get(Corpus, cid):
        raise HTTPException(404, "Corpus not found")
    r = await compute_dependency_analysis(session, cid, relation=body.relation, limit=body.limit)
    return asdict(r)


# --------------------------------------------------------------------------- #
# §8.15 Discourse analysis — multi-taxonomy (v1.2.6)
# --------------------------------------------------------------------------- #


class DiscourseRequest(BaseModel):
    taxonomy: str = Field(
        "hyland2005",
        description=(
            "hyland2005 (default) | hallidayhasan1976 | martinwhite2005 | "
            "usas (CLAWS/USAS top-level semantic tagset)"
        ),
    )


@router.get("/corpora/{cid}/discourse/taxonomies")
async def discourse_taxonomies(cid: str) -> dict:
    """Registry of supported discourse taxonomies (keys, names, citations)."""
    from discourse.service import discourse_taxonomy_list

    return {"taxonomies": discourse_taxonomy_list()}


@router.post("/corpora/{cid}/discourse")
async def discourse(
    cid: str,
    body: DiscourseRequest | None = None,
    session: AsyncSession = Depends(get_session),
) -> dict:
    """Discourse analysis under a named taxonomy (§8.15).

    Body is OPTIONAL for backward compatibility: a bodyless POST keeps the
    default Hyland 2005 metadiscourse lens.
    """
    if not await session.get(Corpus, cid):
        raise HTTPException(404, "Corpus not found")
    taxonomy = (body.taxonomy if body else "hyland2005") or "hyland2005"
    try:
        r = await compute_discourse_analysis(session, cid, taxonomy=taxonomy)
    except ValueError as e:
        msg = str(e)
        if msg.startswith("usas_lexicon_missing:"):
            lang = msg.split(":", 1)[1]
            raise HTTPException(
                503,
                f"The USAS semantic lexicon for '{lang}' is not installed. "
                "See reference-data/tagsets/ in the repository, or use the "
                "Grammatical tagsets setting to check availability.",
            ) from e
        raise HTTPException(400, msg) from e
    return asdict(r)


# --------------------------------------------------------------------------- #
# §8.10 Vocabulary profiling
# --------------------------------------------------------------------------- #


class VocabProfileRequest(BaseModel):
    rare_threshold: int = Field(
        1, ge=1, description="Words appearing <= this many times are 'rare'"
    )
    limit: int = Field(100, ge=1, le=500)


@router.post("/corpora/{cid}/vocab-profile")
async def vocab_profile(
    cid: str, body: VocabProfileRequest, session: AsyncSession = Depends(get_session)
) -> dict:
    if not await session.get(Corpus, cid):
        raise HTTPException(404, "Corpus not found")
    r = await compute_vocab_profile(
        session, cid, rare_threshold=body.rare_threshold, limit=body.limit
    )
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
async def metaphor_candidates(
    cid: str, body: MetaphorRequest, session: AsyncSession = Depends(get_session)
) -> dict:
    """Find metaphor candidates (§8.17). The LLM triages these via the
    metaphor_triage tool, and the human must verify before any candidate
    counts as a confirmed metaphor in export/statistics."""
    if not await session.get(Corpus, cid):
        raise HTTPException(404, "Corpus not found")
    r = await compute_metaphor_candidates(session, cid, limit=body.limit)
    return asdict(r)
