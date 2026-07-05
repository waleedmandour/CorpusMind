"""Phase 6 API routes — research workflow (§8.23) + collaboration (§10.2)."""
from __future__ import annotations

from dataclasses import asdict

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field
from sqlalchemy.ext.asyncio import AsyncSession

from storage.research import (
    create_bookmark,
    create_favorite,
    create_saved_search,
    delete_bookmark,
    delete_favorite,
    delete_saved_search,
    get_shared_project,
    list_bookmarks,
    list_favorites,
    list_saved_searches,
    list_sync_events,
    log_sync_event,
    share_project,
    unshare_project,
)
from storage.session import get_session

router = APIRouter()


# --------------------------------------------------------------------------- #
# §8.23 Saved searches
# --------------------------------------------------------------------------- #


class SavedSearchCreate(BaseModel):
    name: str = Field(..., min_length=1, max_length=255)
    query: str = Field(..., min_length=1)
    search_type: str = "concordance"
    corpus_id: str | None = None
    parameters: dict = {}


@router.post("/projects/{pid}/saved-searches")
async def create_search_route(pid: str, body: SavedSearchCreate,
                               session: AsyncSession = Depends(get_session)) -> dict:
    ss = await create_saved_search(
        session, pid, body.name, body.query,
        search_type=body.search_type, corpus_id=body.corpus_id,
        parameters=body.parameters,
    )
    return asdict(ss)


@router.get("/projects/{pid}/saved-searches")
async def list_searches_route(pid: str, session: AsyncSession = Depends(get_session)) -> list:
    return [asdict(s) for s in await list_saved_searches(session, pid)]


@router.delete("/saved-searches/{sid}")
async def delete_search_route(sid: str, session: AsyncSession = Depends(get_session)) -> dict:
    if not await delete_saved_search(session, sid):
        raise HTTPException(404, "Saved search not found")
    return {"deleted": sid}


# --------------------------------------------------------------------------- #
# §8.23 Bookmarks
# --------------------------------------------------------------------------- #


class BookmarkCreate(BaseModel):
    corpus_id: str
    reference_type: str = "concordance_line"
    reference_id: str
    label: str = ""
    note: str = ""


@router.post("/projects/{pid}/bookmarks")
async def create_bookmark_route(pid: str, body: BookmarkCreate,
                                  session: AsyncSession = Depends(get_session)) -> dict:
    bm = await create_bookmark(
        session, pid, body.corpus_id, body.reference_type, body.reference_id,
        label=body.label, note=body.note,
    )
    return asdict(bm)


@router.get("/projects/{pid}/bookmarks")
async def list_bookmarks_route(pid: str, session: AsyncSession = Depends(get_session)) -> list:
    return [asdict(b) for b in await list_bookmarks(session, pid)]


@router.delete("/bookmarks/{bid}")
async def delete_bookmark_route(bid: str, session: AsyncSession = Depends(get_session)) -> dict:
    if not await delete_bookmark(session, bid):
        raise HTTPException(404, "Bookmark not found")
    return {"deleted": bid}


# --------------------------------------------------------------------------- #
# §8.23 Favorites
# --------------------------------------------------------------------------- #


class FavoriteCreate(BaseModel):
    item_type: str = "corpus"
    item_id: str


@router.post("/projects/{pid}/favorites")
async def create_favorite_route(pid: str, body: FavoriteCreate,
                                  session: AsyncSession = Depends(get_session)) -> dict:
    fav = await create_favorite(session, pid, body.item_type, body.item_id)
    return asdict(fav)


@router.get("/projects/{pid}/favorites")
async def list_favorites_route(pid: str, session: AsyncSession = Depends(get_session)) -> list:
    return [asdict(f) for f in await list_favorites(session, pid)]


@router.delete("/favorites/{fid}")
async def delete_favorite_route(fid: str, session: AsyncSession = Depends(get_session)) -> dict:
    if not await delete_favorite(session, fid):
        raise HTTPException(404, "Favorite not found")
    return {"deleted": fid}


# --------------------------------------------------------------------------- #
# §10.2 Project sharing + §7.4 sync
# --------------------------------------------------------------------------- #


class ShareRequest(BaseModel):
    visibility: str = Field("private", description="private | public")


@router.post("/projects/{pid}/share")
async def share_route(pid: str, body: ShareRequest,
                       session: AsyncSession = Depends(get_session)) -> dict:
    """Mark a project as shared (§10.2). Generates a share token for public access."""
    sp = await share_project(session, pid, visibility=body.visibility)
    return asdict(sp)


@router.get("/projects/{pid}/share")
async def get_share_route(pid: str, session: AsyncSession = Depends(get_session)) -> dict:
    sp = await get_shared_project(session, pid)
    if not sp:
        raise HTTPException(404, "Project is not shared")
    return asdict(sp)


@router.delete("/projects/{pid}/share")
async def unshare_route(pid: str, session: AsyncSession = Depends(get_session)) -> dict:
    if not await unshare_project(session, pid):
        raise HTTPException(404, "Project is not shared")
    return {"unshared": pid}


class SyncRequest(BaseModel):
    event_type: str = Field("push", description="push | pull | conflict | resolve")
    summary: str = ""


@router.post("/projects/{pid}/sync")
async def sync_route(pid: str, body: SyncRequest,
                      session: AsyncSession = Depends(get_session)) -> dict:
    """Log a sync event (§7.4 save-and-sync audit trail).

    Phase 6 implements save-and-sync, NOT real-time CRDT co-editing (per
    the §7.4 decision). Each sync push/pull is logged here for auditability.
    """
    return await log_sync_event(session, pid, body.event_type, body.summary)


@router.get("/projects/{pid}/sync-events")
async def sync_events_route(pid: str, session: AsyncSession = Depends(get_session)) -> list:
    return await list_sync_events(session, pid)
