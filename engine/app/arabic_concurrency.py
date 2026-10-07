"""Process-wide concurrency cap for Arabic analysis (v1.2.11 follow-up).

Why: every CAMeL-backed Arabic route and every grounded-AI Arabic tool runs
the same CPU-bound pipeline against the same ~400MB resident morphology DB.
Letting N of them run at once multiplies peak memory and makes each request
slower exactly when the machine is under the most load (a lab full of
students hitting the same classroom server). One shared, tiny cap keeps
latency predictable and memory flat.

Contract:
  - The cap is 1 by default, overridable via ``CORPUSMIND_ARABIC_CONCURRENCY``
    and clamped to 1..2 (the useful range: above 2 the calima analyzer's own
    GIL-bound work serialises anyway, so callers would only pay memory).
  - Acquiring is NON-BLOCKING and happens on the event loop thread; the
    actual work still runs in worker threads (asyncio.to_thread). No
    request ever waits in a hidden queue: when the cap is full the caller
    gets an immediate, explicit signal and can retry.
  - HTTP callers map "busy" to 429 + Retry-After (api/arabic.py); the AI
    tool dispatcher records ArabicBusyError as a failed tool call the model
    can explain to the user (ai/tools.py + ai/assistant.py).
"""

from __future__ import annotations

import os
import threading

from app.logging import get_logger

log = get_logger(__name__)


class ArabicBusyError(RuntimeError):
    """Raised when the Arabic concurrency cap is already fully used.

    Deliberately NOT an HTTPException: the HTTP layer translates this to
    429 (+ Retry-After), while the AI tool layer records the message as a
    failed tool call so the model can tell the user to retry in a moment.
    """

    def __init__(self, message: str | None = None) -> None:
        super().__init__(
            message
            or "An Arabic analysis is already running and the engine's "
            "concurrency cap is fully used. Try again in a few seconds."
        )


def _resolve_cap() -> int:
    """Read + clamp the configured cap. Kept pure for tests."""
    raw = os.environ.get("CORPUSMIND_ARABIC_CONCURRENCY", "1").strip()
    try:
        value = int(float(raw))
    except ValueError:
        value = 1
    return max(1, min(2, value))


class _ArabicGate:
    """A re-configurable non-blocking gate for Arabic work.

    The semaphore is (re)built lazily from the current env so tests can
    exercise different caps in one process, and so a change to
    CORPUSMIND_ARABIC_CONCURRENCY on process start is honoured without
    import-order coupling. ``held`` counts acquired slots; only threads on
    the event loop touch ``acquire``/``release`` (non-blocking), while the
    heavy work itself happens in ``asyncio.to_thread`` workers.
    """

    def __init__(self) -> None:
        self._lock = threading.Lock()
        self._sem: threading.BoundedSemaphore | None = None
        self._cap: int | None = None
        self._held = 0

    @property
    def cap(self) -> int:
        self._ensure_sem()
        assert self._cap is not None
        return self._cap

    @property
    def held(self) -> int:
        with self._lock:
            return self._held

    def _ensure_sem(self) -> threading.BoundedSemaphore:
        cap = _resolve_cap()
        with self._lock:
            if self._sem is None or self._cap != cap:
                # Cap changed (or first use): swap in a fresh semaphore.
                # Safe because acquire() only ever happens on the event
                # loop thread while no reconfiguration can interleave.
                self._sem = threading.BoundedSemaphore(cap)
                self._cap = cap
                self._held = 0
            return self._sem

    def acquire(self) -> bool:
        """Try to take one slot WITHOUT blocking. True = you may proceed."""
        sem = self._ensure_sem()
        if sem.acquire(blocking=False):
            with self._lock:
                self._held += 1
            return True
        return False

    def release(self) -> None:
        sem = self._ensure_sem()
        sem.release()
        with self._lock:
            self._held = max(0, self._held - 1)

    def reset_for_tests(self) -> None:
        """Force the next acquire() to rebuild from the current env."""
        with self._lock:
            self._sem = None
            self._cap = None
            self._held = 0


gate = _ArabicGate()
