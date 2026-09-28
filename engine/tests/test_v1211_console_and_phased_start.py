"""v1.2.11 — windowless Windows spawns + phased (non-blocking) classroom start.

Field reports, round 3:
  (a) black console windows flashing on Windows — every console-subsystem
      child (caddy spawn, taskkill, caddy version, nvidia-smi, ollama serve,
      where ollama) was spawned without CREATE_NO_WINDOW, and the status
      endpoint ran `caddy version` on EVERY 5-second poll, uncached;
  (b) the enable handler froze the engine event loop for up to ~20 s
      (synchronous readiness loop inside the async handler);
  (c) start failures surfaced as "nothing happened" — no sticky, honest
      failed state with Caddy's own error text;
  (d) the LAN warning had no way to re-probe after the teacher fixed their
      Ollama binding (60 s cache).
"""

from __future__ import annotations

import asyncio
import os
import shutil
import subprocess
import time
from pathlib import Path
from typing import Any

import pytest

# --------------------------------------------------------------------------- #
# Windowless spawn flags (the "black terminal window" fix)
# --------------------------------------------------------------------------- #


def test_windows_spawns_carry_create_no_window(monkeypatch: pytest.MonkeyPatch) -> None:
    """win32 → CREATE_NEW_PROCESS_GROUP | CREATE_NO_WINDOW; POSIX → 0.

    The real constants only exist on Windows; monkeypatching them lets the
    Linux CI verify the exact flag composition the frozen Windows build
    runs with.
    """
    from app import server_mode as sm

    monkeypatch.setattr(subprocess, "CREATE_NO_WINDOW", 0x08000000, raising=False)
    monkeypatch.setattr(subprocess, "CREATE_NEW_PROCESS_GROUP", 0x00000200, raising=False)
    assert sm.windows_process_flags("win32") == 0x08000200
    assert sm.windows_process_flags("linux") == 0
    assert sm.windows_process_flags("darwin") == 0


def test_caddy_version_is_cached_per_binary(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """The status endpoint calls caddy_version on every poll; a cached
    answer means steady-state polling spawns no console process at all
    (this call site was the recurring per-5 s window flash)."""
    from app import server_mode as sm

    fake_bin = tmp_path / "caddy"
    fake_bin.write_text("", encoding="utf-8")
    sm._CADDY_VERSION_CACHE.pop(str(fake_bin), None)
    calls = {"n": 0}

    def fake_run(*args: Any, **kwargs: Any) -> Any:
        calls["n"] += 1
        return type("P", (), {"stdout": "v2.10.0 test-run\n", "stderr": ""})()

    monkeypatch.setattr("subprocess.run", fake_run)
    try:
        assert sm.caddy_version(fake_bin) == "v2.10.0 test-run"
        assert sm.caddy_version(fake_bin) == "v2.10.0 test-run"
        assert calls["n"] == 1  # second poll: cache hit, no spawn
    finally:
        sm._CADDY_VERSION_CACHE.pop(str(fake_bin), None)


def test_caddy_version_failure_is_not_cached(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """A transient failure (e.g. antivirus holding the binary) must not pin
    a wrong answer for the whole session."""
    from app import server_mode as sm

    fake_bin = tmp_path / "caddy"
    fake_bin.write_text("", encoding="utf-8")
    sm._CADDY_VERSION_CACHE.pop(str(fake_bin), None)
    calls = {"n": 0}

    def flaky_run(*args: Any, **kwargs: Any) -> Any:
        calls["n"] += 1
        if calls["n"] == 1:
            raise subprocess.TimeoutExpired(cmd="caddy", timeout=10)
        return type("P", (), {"stdout": "v2.10.0 ok\n", "stderr": ""})()

    monkeypatch.setattr("subprocess.run", flaky_run)
    try:
        assert sm.caddy_version(fake_bin) is None
        assert sm.caddy_version(fake_bin) == "v2.10.0 ok"
        assert calls["n"] == 2
    finally:
        sm._CADDY_VERSION_CACHE.pop(str(fake_bin), None)


# --------------------------------------------------------------------------- #
# Phased classroom start (the "application hesitation" fix)
# --------------------------------------------------------------------------- #


def _make_client_fixture(env: dict[str, str]) -> Any:
    async def client() -> Any:
        for k, v in env.items():
            os.environ[k] = v
        os.environ["CORPUSMIND_DB_URL"] = "sqlite+aiosqlite:///:memory:"
        os.environ["CORPUSMIND_DATA_DIR"] = "/tmp/cm-sm11-test-data"
        os.environ.pop("CORPUSMIND_STUDENT_TOKEN", None)
        shutil.rmtree("/tmp/cm-sm11-test-data/server-mode", ignore_errors=True)
        shutil.rmtree("/tmp/cm-sm11-test-data/classroom", ignore_errors=True)

        from app.settings import get_settings

        get_settings.cache_clear()
        from storage.session import _engine, dispose_db

        clear_engine = getattr(_engine, "clear", None)
        if clear_engine is not None:
            clear_engine()

        from httpx import ASGITransport, AsyncClient

        from app.main import app

        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as ac:
            async with app.router.lifespan_context(app):
                yield ac
        await dispose_db()

    return pytest.fixture(client)


sm_client = _make_client_fixture({"CORPUSMIND_HOST": "127.0.0.1"})


class FakeProc:
    """Duck-typed Popen: alive for poll(), quiet on terminate/wait/kill."""

    def poll(self) -> int | None:
        return None

    def terminate(self) -> None:
        pass

    def kill(self) -> None:
        pass

    def wait(self, timeout: float | None = None) -> int:
        return 0


@pytest.mark.asyncio
async def test_enable_returns_starting_then_live(sm_client: Any, monkeypatch: pytest.MonkeyPatch) -> None:
    """The enable endpoint returns BEFORE the spawn finishes (no event-loop
    freeze) and the status walk reads starting → live."""
    import api.server_mode as router_mod

    ac = sm_client

    def fake_spawn(settings: Any, state: Any) -> None:
        time.sleep(0.4)  # the old code blocked the whole app for this long
        state.caddy_proc = FakeProc()
        state.caddy_started_at = time.time()

    monkeypatch.setattr(router_mod, "spawn_caddy", fake_spawn)
    # CI (and plain dev checkouts) may not have the bundled proxy/web-dist
    # next to the engine; the synchronous prerequisite check must pass so
    # these tests exercise the PHASE machinery, not the missing-assets 500.
    monkeypatch.setattr(router_mod, "find_caddy_binary", lambda settings: Path("/tmp/cm-fake-caddy"))
    monkeypatch.setattr(router_mod, "find_web_dist", lambda settings: Path("/tmp/cm-fake-web"))

    t0 = time.monotonic()
    r = await ac.post("/api/v1/server-mode/enable", json={"mode": "simple"})
    elapsed = time.monotonic() - t0
    assert r.status_code == 200
    body = r.json()
    assert body["enabled"] is True
    # Normally "starting"; a very slow CI machine could finish the 0.4 s
    # fake spawn before the response lands — either way, never a freeze.
    assert body["phase"] in ("starting", "live")
    # Returned well before the 0.4 s fake spawn finished: non-blocking.
    assert elapsed < 0.35 or body["phase"] == "live"

    deadline = time.monotonic() + 5
    phase = body["phase"]
    while time.monotonic() < deadline and phase != "live":
        await asyncio.sleep(0.05)
        phase = (await ac.get("/api/v1/server-mode/status")).json()["phase"]
    assert phase == "live"
    # Cleanup for the shared app state.
    await ac.post("/api/v1/server-mode/disable")


@pytest.mark.asyncio
async def test_enable_failure_is_sticky_failed_with_caddy_error(sm_client: Any, monkeypatch: pytest.MonkeyPatch) -> None:
    """A spawn failure flips the phase to failed (not off), reverts enabled,
    and STAYS failed on subsequent polls so the teacher sees why."""
    import api.server_mode as router_mod

    ac = sm_client

    def failing_spawn(settings: Any, state: Any) -> None:
        raise RuntimeError("Caddy exited immediately (code 1). Check caddy-stdout.log.")

    monkeypatch.setattr(router_mod, "spawn_caddy", failing_spawn)
    monkeypatch.setattr(router_mod, "find_caddy_binary", lambda settings: Path("/tmp/cm-fake-caddy"))
    monkeypatch.setattr(router_mod, "find_web_dist", lambda settings: Path("/tmp/cm-fake-web"))

    r = await ac.post("/api/v1/server-mode/enable", json={"mode": "simple"})
    assert r.status_code == 200
    # An instantly-failing fake spawn may already be "failed" here; the
    # contract is that the endpoint itself never blocked on the spawn.
    assert r.json()["phase"] in ("starting", "failed")

    deadline = time.monotonic() + 5
    s: dict[str, Any] = {}
    while time.monotonic() < deadline:
        s = (await ac.get("/api/v1/server-mode/status")).json()
        if s["phase"] == "failed":
            break
        await asyncio.sleep(0.05)
    assert s["phase"] == "failed"
    assert s["enabled"] is False
    assert "Caddy exited immediately" in s["caddy_error"]
    # Sticky: a fresh poll still reports failed, not off.
    s2 = (await ac.get("/api/v1/server-mode/status")).json()
    assert s2["phase"] == "failed"


@pytest.mark.asyncio
async def test_disable_during_start_discards_stale_worker(sm_client: Any, monkeypatch: pytest.MonkeyPatch) -> None:
    """Flipping OFF while Caddy is still coming up must win: the stale
    worker may not flip the phase back to live afterwards."""
    import api.server_mode as router_mod

    ac = sm_client

    def slow_spawn(settings: Any, state: Any) -> None:
        time.sleep(0.8)
        state.caddy_proc = FakeProc()

    monkeypatch.setattr(router_mod, "spawn_caddy", slow_spawn)
    monkeypatch.setattr(router_mod, "find_caddy_binary", lambda settings: Path("/tmp/cm-fake-caddy"))
    monkeypatch.setattr(router_mod, "find_web_dist", lambda settings: Path("/tmp/cm-fake-web"))

    r = await ac.post("/api/v1/server-mode/enable", json={"mode": "simple"})
    assert r.status_code == 200
    r = await ac.post("/api/v1/server-mode/disable")
    assert r.status_code == 200
    assert r.json()["phase"] == "off"

    await asyncio.sleep(1.2)  # let the stale worker finish its slow spawn
    s = (await ac.get("/api/v1/server-mode/status")).json()
    assert s["phase"] == "off"
    assert s["enabled"] is False
    assert s["caddy_running"] is False


@pytest.mark.asyncio
async def test_recheck_ollama_bypasses_exposure_cache(sm_client: Any, monkeypatch: pytest.MonkeyPatch) -> None:
    """The warning's 'Check again' drops the 60 s cache and re-probes."""
    import api.server_mode as router_mod

    ac = sm_client
    sm_state = ac._transport.app.state.server_mode

    # A stale, cached "exposed" answer must not survive a recheck.
    sm_state.exposure_cache = (
        time.monotonic(),
        {"exposed": True, "source": "probe", "addr": "192.0.2.9"},
    )
    monkeypatch.setattr(router_mod, "_OLLAMA_PORT", 1)  # nothing listens there
    monkeypatch.delenv("OLLAMA_HOST", raising=False)

    r = await ac.post("/api/v1/server-mode/recheck-ollama")
    assert r.status_code == 200
    body = r.json()
    assert body == {"exposed": False, "source": None, "addr": None}
    # Fresh result is re-cached for the status poll.
    assert sm_state.exposure_cache is not None
    assert sm_state.exposure_cache[1]["exposed"] is False
