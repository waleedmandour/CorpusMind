"""Structlog-based logging setup — JSON in production, pretty in dev.

v1.2.8 (rebuild): engine output now goes to stdout AND a best-effort
rotating file log under ``<data_dir>/logs/engine.log``, through one tee
stream so the rendered JSON lines stay byte-identical to earlier releases
(structlog PrintLogger semantics preserved; uvicorn's stdlib logs share
the same sink).

Why: the desktop sidecar is a windowed PyInstaller binary whose stdout is
discarded by the bootloader, so a boot-time failure was invisible — the
release pipeline's Windows smoke gate caught an engine that stayed alive
but never bound its port, with zero observable output. The file log gives
users ("Run Diagnostics") and the smoke gate a durable trace. File logging
never blocks startup: an unwritable data dir degrades to stdout only.
"""
from __future__ import annotations

import logging
import logging.handlers
import sys
from pathlib import Path

import structlog

from app.settings import get_settings


class _Tee:
    """Fan one stream's writes out to several streams (None-safe)."""

    def __init__(self, *streams):
        self._streams = [s for s in streams if s is not None]

    def write(self, s: str) -> int:
        for st in self._streams:
            st.write(s)
        return len(s)

    def flush(self) -> None:
        for st in self._streams:
            try:
                st.flush()
            except Exception:
                pass


def _open_engine_log():
    """Best-effort line-buffered engine.log under <data_dir>/logs/."""
    try:
        log_dir = Path(get_settings().data_dir) / "logs"
        log_dir.mkdir(parents=True, exist_ok=True)
        return open(
            log_dir / "engine.log", "a", buffering=1, encoding="utf-8"
        )
    except Exception:
        # Diagnostics must never prevent startup (frozen app with an
        # unwritable data dir, odd permissions, ...).
        return None


def configure_logging() -> None:
    settings = get_settings()
    level = getattr(logging, settings.log_level.upper())

    # One sink for everything: stdout (uvicorn/Tauri capture) plus the file
    # log when it could be opened. In a windowed PyInstaller build sys.stdout
    # is None and _Tee drops it, leaving only the file — which is exactly the
    # observability we want there.
    engine_log = _open_engine_log()
    sink = _Tee(sys.stdout, engine_log)

    logging.basicConfig(
        format="%(message)s",
        stream=sink,
        level=level,
    )

    structlog.configure(
        processors=[
            structlog.contextvars.merge_contextvars,
            structlog.processors.add_log_level,
            structlog.processors.TimeStamper(fmt="iso"),
            structlog.dev.set_exc_info,
            (
                structlog.dev.ConsoleRenderer(colors=True)
                if settings.log_level == "debug"
                else structlog.processors.JSONRenderer()
            ),
        ],
        wrapper_class=structlog.make_filtering_bound_logger(level),
        context_class=dict,
        logger_factory=structlog.PrintLoggerFactory(file=sink),
        cache_logger_on_first_use=True,
    )


def get_logger(name: str | None = None) -> structlog.stdlib.BoundLogger:
    return structlog.get_logger(name)
