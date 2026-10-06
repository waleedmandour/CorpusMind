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

from nlp.stopwords import (
    ARABIC_STOPWORDS,
    ENGLISH_STOPWORDS,
    FARSI_STOPWORDS,
    HINDI_STOPWORDS,
    URDU_STOPWORDS,
)
from storage.models import StopwordList
from storage.session import get_session

router = APIRouter()


class StopwordListCreate(BaseModel):
    name: str = Field(..., min_length=1, max_length=128)
    language: str = Field("en", max_length=8)
    words: list[str] = Field(..., min_length=1)


_BUILTIN_SETS: dict[str, frozenset[str]] = {
    "en": ENGLISH_STOPWORDS,
    "ar": ARABIC_STOPWORDS,
    "ur": URDU_STOPWORDS,
    "hi": HINDI_STOPWORDS,
    "fa": FARSI_STOPWORDS,
}

_BUILTIN_NAMES: dict[str, str] = {
    "en": "Built-in: English function words",
    "ar": "Built-in: Arabic function words (MSA)",
    "ur": "Built-in: Urdu function words (اردو)",
    "hi": "Built-in: Hindi function words (हिन्दी)",
    "fa": "Built-in: Farsi function words (فارسی)",
}


def builtin_stopword_lists() -> list[dict]:
    """The virtual built-in lists, in the same shape as DB rows.

    v1.2.11: Urdu, Hindi and Farsi join English and Arabic; the lists are
    the same bundled sets the cleaning step uses (nlp/stopwords.py), so
    what the manager shows is exactly what the engine applies.
    """
    return [
        {
            "id": f"builtin:{code}",
            "name": _BUILTIN_NAMES[code],
            "language": code,
            "words": sorted(_BUILTIN_SETS[code]),
            "builtin": True,
        }
        for code in ("en", "ar", "ur", "hi", "fa")
    ]


async def resolve_stopword_set(session: AsyncSession, stopword_list_id: str | None) -> set[str] | None:
    """Resolve a stopword_list_id ('builtin:<lang>' | db id) to a set."""
    if not stopword_list_id:
        return None
    if stopword_list_id.startswith("builtin:"):
        code = stopword_list_id.split(":", 1)[1]
        if code in _BUILTIN_SETS:
            return set(_BUILTIN_SETS[code])
        raise HTTPException(404, f"No built-in stopword list for language '{code}'")
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
