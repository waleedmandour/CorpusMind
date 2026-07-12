"""Corpus cleaning API routes — on-demand re-cleaning of an ingested corpus.

POST /api/v1/corpora/{cid}/clean
  Apply user-selected cleaning operations to every document in the corpus,
  re-run the NLP pipeline, and replace the annotation version.
"""
from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field
from sqlalchemy.ext.asyncio import AsyncSession

from app.logging import get_logger
from ingestion.cleaning import CleaningOptions, clean_corpus
from storage.models import Corpus
from storage.session import get_session

log = get_logger(__name__)
router = APIRouter()


class CleaningRequest(BaseModel):
    """User-selected cleaning options. All default to False — the user
    must explicitly opt in to each operation."""

    collapse_whitespace: bool = True
    strip_leading_trailing: bool = True
    remove_empty_lines: bool = False
    remove_urls: bool = False
    remove_email_addresses: bool = False
    remove_html_entities: bool = False
    lowercase: bool = False
    remove_punctuation: bool = False
    remove_numbers: bool = False
    remove_extra_symbols: bool = False
    remove_stopwords: bool = False
    min_token_length: int = Field(0, ge=0, le=20, description="Drop tokens shorter than this (0 = no filter)")
    normalize_arabic: bool = False
    strip_arabic_diacritics: bool = False
    remove_arabic_tatweel: bool = False
    create_new_version: bool = True


class CleaningResponse(BaseModel):
    corpus_id: str
    documents_cleaned: int
    old_token_count: int
    new_token_count: int
    old_type_count: int
    new_type_count: int
    new_version_id: str | None
    options_applied: dict


@router.post("/corpora/{cid}/clean", response_model=CleaningResponse)
async def clean_corpus_route(
    cid: str,
    body: CleaningRequest,
    session: AsyncSession = Depends(get_session),
) -> CleaningResponse:
    """Re-clean every document in the corpus with the selected options.

    This is a destructive operation: it replaces the corpus's cleaned text
    and re-runs the NLP pipeline. The old annotation versions are deleted
    (their tokens are rebuilt from the newly-cleaned text). Make sure the
    user has confirmed in the UI before calling this.
    """
    corpus = await session.get(Corpus, cid)
    if not corpus:
        raise HTTPException(404, "Corpus not found")

    opts = CleaningOptions(
        collapse_whitespace=body.collapse_whitespace,
        strip_leading_trailing=body.strip_leading_trailing,
        remove_empty_lines=body.remove_empty_lines,
        remove_urls=body.remove_urls,
        remove_email_addresses=body.remove_email_addresses,
        remove_html_entities=body.remove_html_entities,
        lowercase=body.lowercase,
        remove_punctuation=body.remove_punctuation,
        remove_numbers=body.remove_numbers,
        remove_extra_symbols=body.remove_extra_symbols,
        remove_stopwords=body.remove_stopwords,
        min_token_length=body.min_token_length,
        normalize_arabic=body.normalize_arabic,
        strip_arabic_diacritics=body.strip_arabic_diacritics,
        remove_arabic_tatweel=body.remove_arabic_tatweel,
        create_new_version=body.create_new_version,
    )

    try:
        result = await clean_corpus(session, corpus, opts)
    except Exception as e:
        log.error("clean_failed", corpus_id=cid, error=str(e))
        raise HTTPException(500, f"Cleaning failed: {e}") from e

    return CleaningResponse(
        corpus_id=result.corpus_id,
        documents_cleaned=result.documents_cleaned,
        old_token_count=result.old_token_count,
        new_token_count=result.new_token_count,
        old_type_count=result.old_type_count,
        new_type_count=result.new_type_count,
        new_version_id=result.new_version_id,
        options_applied=result.options_applied,
    )
