"""
Phase 6 research workflow service (§8.23).

Saved searches, bookmarks, favorites — the research-workflow features that
let a researcher build up an analysis session over time rather than
re-deriving everything from scratch each session.
"""
from __future__ import annotations

import secrets
from dataclasses import dataclass

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.logging import get_logger
from storage.models import Bookmark, Favorite, SavedSearch, SharedProject, SyncEvent

log = get_logger(__name__)


# --------------------------------------------------------------------------- #
# §8.23 Saved searches
# --------------------------------------------------------------------------- #


@dataclass(frozen=True, slots=True)
class SavedSearchOut:
    id: str
    project_id: str
    corpus_id: str | None
    name: str
    query: str
    search_type: str
    parameters: dict
    created_at: str


async def create_saved_search(
    session: AsyncSession, project_id: str, name: str, query: str,
    *, search_type: str = "concordance", corpus_id: str | None = None,
    parameters: dict | None = None,
) -> SavedSearchOut:
    ss = SavedSearch(
        project_id=project_id, corpus_id=corpus_id, name=name, query=query,
        search_type=search_type, parameters=parameters or {},
    )
    session.add(ss)
    await session.flush()
    return SavedSearchOut(
        id=ss.id, project_id=ss.project_id, corpus_id=ss.corpus_id,
        name=ss.name, query=ss.query, search_type=ss.search_type,
        parameters=ss.parameters, created_at=ss.created_at.isoformat(),
    )


async def list_saved_searches(session: AsyncSession, project_id: str) -> list[SavedSearchOut]:
    stmt = select(SavedSearch).where(SavedSearch.project_id == project_id).order_by(SavedSearch.created_at.desc())
    items = (await session.execute(stmt)).scalars().all()
    return [SavedSearchOut(
        id=s.id, project_id=s.project_id, corpus_id=s.corpus_id, name=s.name,
        query=s.query, search_type=s.search_type, parameters=s.parameters,
        created_at=s.created_at.isoformat(),
    ) for s in items]


async def delete_saved_search(session: AsyncSession, search_id: str) -> bool:
    ss = await session.get(SavedSearch, search_id)
    if not ss:
        return False
    await session.delete(ss)
    return True


# --------------------------------------------------------------------------- #
# §8.23 Bookmarks
# --------------------------------------------------------------------------- #


@dataclass(frozen=True, slots=True)
class BookmarkOut:
    id: str
    project_id: str
    corpus_id: str
    label: str
    reference_type: str
    reference_id: str
    note: str
    created_at: str


async def create_bookmark(
    session: AsyncSession, project_id: str, corpus_id: str,
    reference_type: str, reference_id: str,
    *, label: str = "", note: str = "",
) -> BookmarkOut:
    bm = Bookmark(
        project_id=project_id, corpus_id=corpus_id, label=label,
        reference_type=reference_type, reference_id=reference_id, note=note,
    )
    session.add(bm)
    await session.flush()
    return BookmarkOut(
        id=bm.id, project_id=bm.project_id, corpus_id=bm.corpus_id,
        label=bm.label, reference_type=bm.reference_type,
        reference_id=bm.reference_id, note=bm.note,
        created_at=bm.created_at.isoformat(),
    )


async def list_bookmarks(session: AsyncSession, project_id: str) -> list[BookmarkOut]:
    stmt = select(Bookmark).where(Bookmark.project_id == project_id).order_by(Bookmark.created_at.desc())
    items = (await session.execute(stmt)).scalars().all()
    return [BookmarkOut(
        id=b.id, project_id=b.project_id, corpus_id=b.corpus_id, label=b.label,
        reference_type=b.reference_type, reference_id=b.reference_id, note=b.note,
        created_at=b.created_at.isoformat(),
    ) for b in items]


async def delete_bookmark(session: AsyncSession, bookmark_id: str) -> bool:
    bm = await session.get(Bookmark, bookmark_id)
    if not bm:
        return False
    await session.delete(bm)
    return True


# --------------------------------------------------------------------------- #
# §8.23 Favorites
# --------------------------------------------------------------------------- #


@dataclass(frozen=True, slots=True)
class FavoriteOut:
    id: str
    project_id: str
    item_type: str
    item_id: str
    created_at: str


async def create_favorite(
    session: AsyncSession, project_id: str, item_type: str, item_id: str,
) -> FavoriteOut:
    fav = Favorite(project_id=project_id, item_type=item_type, item_id=item_id)
    session.add(fav)
    await session.flush()
    return FavoriteOut(
        id=fav.id, project_id=fav.project_id, item_type=fav.item_type,
        item_id=fav.item_id, created_at=fav.created_at.isoformat(),
    )


async def list_favorites(session: AsyncSession, project_id: str) -> list[FavoriteOut]:
    stmt = select(Favorite).where(Favorite.project_id == project_id).order_by(Favorite.created_at.desc())
    items = (await session.execute(stmt)).scalars().all()
    return [FavoriteOut(
        id=f.id, project_id=f.project_id, item_type=f.item_type,
        item_id=f.item_id, created_at=f.created_at.isoformat(),
    ) for f in items]


async def delete_favorite(session: AsyncSession, favorite_id: str) -> bool:
    fav = await session.get(Favorite, favorite_id)
    if not fav:
        return False
    await session.delete(fav)
    return True


# --------------------------------------------------------------------------- #
# §10.2 Project sharing (save-and-sync, not CRDT)
# --------------------------------------------------------------------------- #


@dataclass(frozen=True, slots=True)
class SharedProjectOut:
    id: str
    project_id: str
    share_token: str
    visibility: str
    sync_enabled: bool
    last_synced_at: str | None
    created_at: str


async def share_project(
    session: AsyncSession, project_id: str,
    *, visibility: str = "private",
) -> SharedProjectOut:
    """Mark a project as shared (§10.2). Generates a share token for public access."""
    # Check if already shared
    existing = await session.scalar(
        select(SharedProject).where(SharedProject.project_id == project_id)
    )
    if existing:
        existing.visibility = visibility
        await session.flush()
        return SharedProjectOut(
            id=existing.id, project_id=existing.project_id,
            share_token=existing.share_token, visibility=existing.visibility,
            sync_enabled=existing.sync_enabled,
            last_synced_at=existing.last_synced_at.isoformat() if existing.last_synced_at else None,
            created_at=existing.created_at.isoformat(),
        )

    sp = SharedProject(
        project_id=project_id,
        share_token=secrets.token_urlsafe(32),
        visibility=visibility,
    )
    session.add(sp)
    await session.flush()
    return SharedProjectOut(
        id=sp.id, project_id=sp.project_id, share_token=sp.share_token,
        visibility=sp.visibility, sync_enabled=sp.sync_enabled,
        last_synced_at=None, created_at=sp.created_at.isoformat(),
    )


async def get_shared_project(session: AsyncSession, project_id: str) -> SharedProjectOut | None:
    sp = await session.scalar(select(SharedProject).where(SharedProject.project_id == project_id))
    if not sp:
        return None
    return SharedProjectOut(
        id=sp.id, project_id=sp.project_id, share_token=sp.share_token,
        visibility=sp.visibility, sync_enabled=sp.sync_enabled,
        last_synced_at=sp.last_synced_at.isoformat() if sp.last_synced_at else None,
        created_at=sp.created_at.isoformat(),
    )


async def unshare_project(session: AsyncSession, project_id: str) -> bool:
    sp = await session.scalar(select(SharedProject).where(SharedProject.project_id == project_id))
    if not sp:
        return False
    await session.delete(sp)
    return True


# --------------------------------------------------------------------------- #
# §7.4 Sync events (audit trail)
# --------------------------------------------------------------------------- #


async def log_sync_event(
    session: AsyncSession, project_id: str, event_type: str, summary: str = "",
) -> dict:
    """Log a sync event (push/pull/conflict/resolve) to the audit trail."""
    event = SyncEvent(
        project_id=project_id, event_type=event_type, summary=summary,
    )
    session.add(event)
    await session.flush()
    return {
        "id": event.id, "project_id": event.project_id,
        "event_type": event.event_type, "summary": event.summary,
        "created_at": event.created_at.isoformat(),
    }


async def list_sync_events(session: AsyncSession, project_id: str, limit: int = 50) -> list[dict]:
    stmt = (
        select(SyncEvent)
        .where(SyncEvent.project_id == project_id)
        .order_by(SyncEvent.created_at.desc())
        .limit(limit)
    )
    events = (await session.execute(stmt)).scalars().all()
    return [{
        "id": e.id, "project_id": e.project_id, "event_type": e.event_type,
        "summary": e.summary, "created_at": e.created_at.isoformat(),
    } for e in events]
