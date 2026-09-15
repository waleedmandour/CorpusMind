"""Async SQLAlchemy session management."""
from __future__ import annotations

from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from app.settings import get_settings
from storage.models import Base

# Module-level engine — created lazily on first use.
_engine = None
_sessionmaker: async_sessionmaker[AsyncSession] | None = None


def _get_engine():
    global _engine, _sessionmaker
    if _engine is None:
        settings = get_settings()
        _engine = create_async_engine(
            settings.sqlite_url,
            echo=False,
            future=True,
            # SQLite needs this for foreign keys + concurrent writes from one process.
            connect_args={"check_same_thread": False, "timeout": 30.0},
        )
        # v1.0.1: register a REGEXP function on every raw SQLite connection so
        # concordance queries can use `col REGEXP pattern` (Python re syntax).
        # The function itself is case-sensitive; callers prepend (?i) for
        # case-insensitive matching.
        from sqlalchemy import event

        @event.listens_for(_engine.sync_engine, "connect")
        def _register_regexp(dbapi_connection, _record):
            import re as _re

            def _regexp(pattern, value):
                if pattern is None or value is None:
                    return None
                try:
                    return _re.search(pattern, str(value)) is not None
                except _re.error:
                    return None

            dbapi_connection.create_function("REGEXP", 2, _regexp)

            # v1.2.0 (item 6): Arabic normalization as a SQL scalar function so
            # frequency/collocation/keyness/n-gram aggregations can GROUP BY a
            # normalized key without streaming every token into Python. Mirrors
            # the ingestion-time cleaning: strip harakat, unify
            # أ إ آ → ا, ة → ه, ى → ي (+ lowercase for Latin safety).
            def _arnorm(value):
                if value is None:
                    return None
                s = str(value).lower()
                s = _re.sub(r"[\u064B-\u065F\u0670\u0640]", "", s)  # harakat + tatweel
                s = _re.sub(r"[\u0623\u0625\u0622]", "\u0627", s)  # أ إ آ → ا
                s = s.replace("\u0629", "\u0647")                 # ة → ه
                s = s.replace("\u0649", "\u064A")                 # ى → ي
                return s

            dbapi_connection.create_function("arnorm", 1, _arnorm)

        _sessionmaker = async_sessionmaker(_engine, expire_on_commit=False, class_=AsyncSession)
    return _engine


async def _migrate_sqlite(conn) -> None:
    """Lightweight column migrations for databases created before v1.0.9.

    create_all() only creates missing TABLES — it never alters existing ones.
    The v1.0.9 Lens round added ImageSet.description and Image.meta, so
    engines upgrading an existing data directory would crash on first SELECT
    (or silently drop the new fields) without these ALTERs. Each migration
    checks PRAGMA table_info first, so it is idempotent.
    """
    from sqlalchemy import text

    async def _columns(table: str) -> set[str]:
        rows = await conn.execute(text(f"PRAGMA table_info({table})"))
        return {row[1] for row in rows.fetchall()}

    image_set_cols = await _columns("image_sets")
    if image_set_cols and "description" not in image_set_cols:
        await conn.execute(text("ALTER TABLE image_sets ADD COLUMN description TEXT NOT NULL DEFAULT ''"))

    image_cols = await _columns("images")
    if image_cols and "meta" not in image_cols:
        # JSON columns are TEXT underneath in SQLite; '{}' deserializes to {}.
        await conn.execute(text("ALTER TABLE images ADD COLUMN meta TEXT NOT NULL DEFAULT '{}'"))

    # v1.2.0 (item 5): Learner Research corpus facets (optional L1 + CEFR level).
    corpus_cols = await _columns("corpora")
    if corpus_cols and "l1" not in corpus_cols:
        await conn.execute(text("ALTER TABLE corpora ADD COLUMN l1 VARCHAR(64) NOT NULL DEFAULT ''"))
    if corpus_cols and "proficiency" not in corpus_cols:
        await conn.execute(text("ALTER TABLE corpora ADD COLUMN proficiency VARCHAR(16) NOT NULL DEFAULT ''"))


async def init_db() -> None:
    """Create all tables + run idempotent column migrations. Safe on every startup."""
    engine = _get_engine()
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
        await _migrate_sqlite(conn)


async def dispose_db() -> None:
    global _engine, _sessionmaker
    if _engine is not None:
        await _engine.dispose()
        _engine = None
        _sessionmaker = None


@asynccontextmanager
async def session_scope() -> AsyncIterator[AsyncSession]:
    """Context manager that yields a session and commits/rolls back automatically."""
    _get_engine()
    assert _sessionmaker is not None
    async with _sessionmaker() as s:
        try:
            yield s
            await s.commit()
        except Exception:
            await s.rollback()
            raise


async def get_session() -> AsyncIterator[AsyncSession]:
    """FastAPI dependency — yields a session per request, commits on success."""
    _get_engine()
    assert _sessionmaker is not None
    async with _sessionmaker() as s:
        try:
            yield s
            await s.commit()
        except Exception:
            await s.rollback()
            raise
        finally:
            await s.close()
