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

        _sessionmaker = async_sessionmaker(_engine, expire_on_commit=False, class_=AsyncSession)
    return _engine


async def init_db() -> None:
    """Create all tables. Idempotent — safe to call on every startup."""
    engine = _get_engine()
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)


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
