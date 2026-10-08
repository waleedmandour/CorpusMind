"""v1.2.12 — Arabic first-analysis cold-load fixes (field report).

Field report: "even after the Arabic data pack installation and updates,
the Sample text fails to be analyzed." The pack was fine (the backends chip
showed camel/calima-msa-r13 green); what failed was the FIRST analysis on a
slow machine: the ~400MB calima DB load exceeded the 30s per-request
deadline, and — worse — every concurrent/retried request queued behind the
old exclusive load lock burning its OWN deadline, so retries 504'd too.

Three fixes, three test groups:
  1. pipeline: one designated loader; concurrent callers piggyback on the
     in-flight load instead of stacking duplicate loaders (and a failed
     loader hands the duty to the first waiter);
  2. api: the default request deadline is 120s (env-overridable; tests that
     exercise the 504 path monkeypatch the module constant, so the default
     literal itself is pinned here so a silent regression cannot ship);
  3. app: the engine pre-loads the MSA backend in a daemon thread at
     startup (kill-switch CORPUSMIND_ARABIC_WARMUP=0).
"""

from __future__ import annotations

import inspect
import threading
import time
from collections.abc import Callable, Iterator
from typing import Any

import pytest

import nlp.arabic.pipeline as pipeline
from app.logging import get_logger
from nlp.arabic.pipeline import CamelBackend


@pytest.fixture(autouse=True)
def _fresh_load_state() -> Iterator[None]:
    """Isolate the module-global loader state (cond + flag) per test and
    restore the real ones afterwards."""
    old_cond = pipeline._CAMEL_LOAD_COND
    old_flag = pipeline._CAMEL_LOADING
    pipeline._CAMEL_LOAD_COND = threading.Condition()
    pipeline._CAMEL_LOADING = False
    try:
        yield
    finally:
        pipeline._CAMEL_LOAD_COND = old_cond
        pipeline._CAMEL_LOADING = old_flag


class _LoadRecorder:
    """Callable stand-in for CamelBackend._load_locked (which is called
    with no arguments and warms ``backend._analyzers`` on success)."""

    def __init__(
        self,
        backend: CamelBackend,
        *,
        fail_first: bool = False,
        hold: threading.Event | None = None,
    ) -> None:
        self.backend = backend
        self.calls = 0
        self.fail_first = fail_first
        self.hold = hold

    def __call__(self, *args: Any, **kwargs: Any) -> None:
        self.calls += 1
        if self.hold is not None and self.calls == 1:
            self.hold.wait(timeout=10.0)
        if self.fail_first and self.calls == 1:
            raise RuntimeError("simulated cold-load failure")
        self.backend._analyzers["msa"] = object()  # warm the cache


def _run_in_thread(fn: Callable[[], None]) -> threading.Thread:
    t = threading.Thread(target=fn, daemon=True)
    t.start()
    return t


def _wait_for_loader_started(recorder: _LoadRecorder, timeout: float = 5.0) -> None:
    deadline = time.monotonic() + timeout
    while recorder.calls == 0 and time.monotonic() < deadline:
        time.sleep(0.01)
    assert recorder.calls == 1, "designated loader never started"


class TestSharedColdLoad:
    def test_concurrent_first_load_loads_once(self) -> None:
        """Two threads racing the cold load must produce exactly ONE
        _load_locked call; the waiter reuses the loader's warm cache."""
        backend = CamelBackend(default_dialect="msa")
        hold = threading.Event()
        recorder = _LoadRecorder(backend, hold=hold)
        backend._load_locked = recorder  # type: ignore[method-assign]

        t1 = _run_in_thread(backend._load)
        _wait_for_loader_started(recorder)

        t2 = _run_in_thread(backend._load)
        time.sleep(0.25)  # give t2 the chance to (wrongly) become a loader
        assert recorder.calls == 1, (
            "a concurrent cold load started a SECOND loader — the piggyback "
            "regressed to duplicate ~400MB loads behind an exclusive lock"
        )

        hold.set()
        t1.join(timeout=10.0)
        t2.join(timeout=10.0)
        assert not t1.is_alive() and not t2.is_alive()
        assert recorder.calls == 1, "loader ran more than once"
        assert backend._analyzers, "waiter finished without a warm cache"

    def test_failed_loader_hands_duty_to_waiter(self) -> None:
        """If the first loader raises, a waiting thread must take over and
        succeed — not exit cold, and not hang forever."""
        backend = CamelBackend(default_dialect="msa")
        hold = threading.Event()
        first = _LoadRecorder(backend, fail_first=True, hold=hold)
        second = _LoadRecorder(backend)
        dispatch: dict[str, _LoadRecorder] = {"rec": first}

        def _loader() -> None:
            dispatch["rec"]()

        backend._load_locked = _loader  # type: ignore[method-assign]

        t1_err: list[BaseException] = []

        def _first_loader() -> None:
            try:
                backend._load()
            except RuntimeError as e:  # the simulated cold-load failure
                t1_err.append(e)

        t1 = _run_in_thread(_first_loader)
        _wait_for_loader_started(first)

        t2 = _run_in_thread(backend._load)
        time.sleep(0.25)  # let t2 park as a waiter
        assert second.calls == 0, "waiter became a loader while one was active"

        # First loader fails (once released); the waiter must take over.
        dispatch["rec"] = second
        hold.set()
        t1.join(timeout=10.0)
        t2.join(timeout=10.0)
        assert not t1.is_alive() and not t2.is_alive()
        assert t1_err, "first loader did not raise as simulated"
        assert first.calls == 1 and second.calls == 1, (
            "waiter did not take over after a failed load"
        )
        assert backend._analyzers, "cache cold after takeover"

    def test_warm_path_never_touches_loader(self) -> None:
        """Once warm, _load returns without invoking the loader machinery."""
        backend = CamelBackend(default_dialect="msa")
        recorder = _LoadRecorder(backend)
        backend._load_locked = recorder  # type: ignore[method-assign]
        backend._analyzers["msa"] = object()
        backend._load()
        backend._load()
        assert recorder.calls == 0


class TestDeadlineDefault:
    def test_default_deadline_literal_is_120s(self) -> None:
        """The 30s default 504'd on real Windows machines whose first cold
        load (antivirus + cold disk) takes minutes. Pin the DEFAULT literal
        in the source (env may legitimately override the runtime value)."""
        from api import arabic as arabic_routes

        src = inspect.getsource(arabic_routes)
        assert 'os.environ.get("CORPUSMIND_ARABIC_TIMEOUT_S", "120")' in src, (
            "ARABIC_TIMEOUT_S default regressed from 120s"
        )


class TestStartupWarmup:
    def test_warmup_loads_msa_backend(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """The daemon warm-up thread calls the MSA backend's info() (which
        triggers the cold load) exactly once."""
        import app.main as app_main

        calls: list[str] = []

        class _FakeBackend:
            def info(self) -> object:
                calls.append("info")
                return object()

        monkeypatch.setenv("CORPUSMIND_ARABIC_WARMUP", "1")
        monkeypatch.setattr(pipeline, "get_arabic_backend", lambda *a, **k: _FakeBackend())
        log = get_logger("test.warmup")
        t = app_main._start_arabic_warmup(log)
        assert t is not None
        t.join(timeout=10.0)
        assert not t.is_alive()
        assert calls == ["info"], "warm-up did not load the MSA backend"

    def test_warmup_kill_switch(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """CORPUSMIND_ARABIC_WARMUP=0 must spawn nothing (low-RAM machines)."""
        import app.main as app_main

        calls: list[str] = []

        class _FakeBackend:
            def info(self) -> object:
                calls.append("info")
                return object()

        monkeypatch.setenv("CORPUSMIND_ARABIC_WARMUP", "0")
        monkeypatch.setattr(pipeline, "get_arabic_backend", lambda *a, **k: _FakeBackend())
        log = get_logger("test.warmup")
        t = app_main._start_arabic_warmup(log)
        assert t is None
        assert calls == []
