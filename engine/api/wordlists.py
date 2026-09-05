"""Word-list API (v1.0.1) — user-editable stopword lists.

Stopword lists are an option in frequency, collocation and keyness
analysis (``stopword_list_id``). Built-in lists resolve virtually:

  * ``builtin:en`` — English function words (nlp/stopwords.py)
  * ``builtin:ar`` — Arabic function words (dediacritized MSA set)

Custom lists are stored in the ``stopword_lists`` table and seeded on
first use from the built-ins if the user wants a starting point.
"""
from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from nlp.stopwords import ARABIC_STOPWORDS, ENGLISH_STOPWORDS
from storage.models import StopwordList
from storage.session import get_session

router = APIRouter()


class StopwordListCreate(BaseModel):
    name: str = Field(..., min_length=1, max_length=128)
    language: str = Field("en", max_length=8)
    words: list[str] = Field(..., min_length=1)


def builtin_stopword_lists() -> list[dict]:
    """The two virtual built-in lists, in the same shape as DB rows."""
    return [
        {
            "id": "builtin:en",
            "name": "Built-in: English function words",
            "language": "en",
            "words": sorted(ENGLISH_STOPWORDS),
            "builtin": True,
        },
        {
            "id": "builtin:ar",
            "name": "Built-in: Arabic function words (MSA)",
            "language": "ar",
            "words": sorted(ARABIC_STOPWORDS),
            "builtin": True,
        },
    ]


async def resolve_stopword_set(session: AsyncSession, stopword_list_id: str | None) -> set[str] | None:
    """Resolve a stopword_list_id ('builtin:en' | 'builtin:ar' | db id) to a set."""
    if not stopword_list_id:
        return None
    if stopword_list_id == "builtin:en":
        return set(ENGLISH_STOPWORDS)
    if stopword_list_id == "builtin:ar":
        return set(ARABIC_STOPWORDS)
    row = await session.get(StopwordList, stopword_list_id)
    if row is None:
        raise HTTPException(404, f"Stopword list '{stopword_list_id}' not found")
    return {str(w) for w in (row.words or [])}


@router.get("/stopword-lists")
async def list_stopword_lists(session: AsyncSession = Depends(get_session)) -> dict:
    rows = (await session.execute(select(StopwordList).order_by(StopwordList.name))).scalars().all()
    items = builtin_stopword_lists() + [
        {
            "id": r.id,
            "name": r.name,
            "language": r.language,
            "words": r.words or [],
            "builtin": False,
        }
        for r in rows
    ]
    return {"items": items}


@router.post("/stopword-lists")
async def create_stopword_list(body: StopwordListCreate, session: AsyncSession = Depends(get_session)) -> dict:
    cleaned = sorted({w.strip().lower() for w in body.words if w.strip()})
    if not cleaned:
        raise HTTPException(422, "Stopword list must contain at least one word")
    row = StopwordList(name=body.name, language=body.language, words=cleaned)
    session.add(row)
    await session.flush()
    return {"id": row.id, "name": row.name, "language": row.language,
            "words": cleaned, "builtin": False}


@router.delete("/stopword-lists/{list_id}")
async def delete_stopword_list(list_id: str, session: AsyncSession = Depends(get_session)) -> dict:
    if list_id.startswith("builtin:"):
        raise HTTPException(400, "Built-in stopword lists cannot be deleted")
    row = await session.get(StopwordList, list_id)
    if row is None:
        raise HTTPException(404, "Stopword list not found")
    await session.delete(row)
    return {"deleted": list_id}
