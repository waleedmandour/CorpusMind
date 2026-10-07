"""v1.2.11-rc1 bug regression: the Arabic data-dir resolver's lru_cache went
STALE after the in-app installer changed the on-disk state.

User-visible report (rc1, clean machine):
    "Even after downloading the Arabic Data Pack for CAMeL, the sample text
     cannot be analyzed."

Root cause (proven against rc1 by a standalone repro): camel_tools_data_dir()
is @lru_cache(1). On a clean machine the FIRST Arabic request (or
/health/resources poll) runs before any pack exists, the resolver returns
None and the cache stores that None FOREVER. The installer then installs the
pack fine, but every later analysis in the same process still 503s "not
installed" until the app is restarted.

A second facet from the same report: the Dialect DB dropdown offered
Egyptian/Gulf/Levantine DBs that no installer path provisions, so those
requests could only ever 503 with a hint whose suggested "fix" (the in-app
installer) could never fix them. Covered here by the per-dataset hint test
and the camel_data_status per-dialect test; the web dropdown now disables
missing DBs (ArabicView.tsx).

Everything here runs WITHOUT the real CAMeL data pack or network: the
installer is exercised against a local HTTP server serving fabricated zips
(the same harness as test_v1211_arabic_followup.py).
"""
from __future__ import annotations

import hashlib
import io
import os
import threading
import time
import zipfile
from collections.abc import Iterator
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import Any

import pytest

os.environ["CORPUSMIND_DB_URL"] = "sqlite+aiosqlite:///:memory:"
os.environ["CORPUSMIND_DATA_DIR"] = "/tmp/cm-test-data"

from app.resource_paths import camel_tools_data_dir, refresh_camel_tools_data_dir
from nlp.arabic.pipeline import (
    ArabicDataMissingError,
    _require_camel_data,
    camel_data_status,
)


@pytest.fixture(autouse=True)
def _reset_installer_singleton() -> Iterator[None]:
    """Fresh installer job singleton per test (mirrors the follow-up suite)."""
    from app import arabic_installer

    arabic_installer.reset_installer_for_tests()
    yield
    arabic_installer.reset_installer_for_tests()


@pytest.fixture
async def client():  # type: ignore[no-untyped-def]
    from httpx import ASGITransport, AsyncClient

    from app.main import app
    from storage.session import dispose_db

    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as ac:
        async with app.router.lifespan_context(app):
            yield ac
    await dispose_db()


@pytest.fixture(autouse=True)
def _hermetic_camel_home(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> Iterator[None]:
    """Hermetic resolver inputs: a private HOME and a private installer
    target, plus a clean resolver cache around every test. The resolver is
    process-global lru_cache state - leaving it poisoned (or pre-warmed with
    another test's directories) would leak between tests."""
    monkeypatch.setenv("HOME", str(tmp_path / "home"))
    monkeypatch.setenv("CAMELTOOLS_DATA", str(tmp_path / "camel-target"))
    (tmp_path / "home").mkdir()
    refresh_camel_tools_data_dir()
    yield
    refresh_camel_tools_data_dir()


# --------------------------------------------------------------------------- #
# Harness (mirrors test_v1211_arabic_followup.py, destinations shaped so the
# REAL pre-flight directory checks pass once the fabricated zip lands)
# --------------------------------------------------------------------------- #


class _FakePackServer:
    def __init__(self, packages: dict[str, bytes]):
        self.packages = packages
        holder = self

        class H(BaseHTTPRequestHandler):
            def do_GET(self) -> None:
                path = self.path.lstrip("/")
                if path not in holder.packages:
                    self.send_error(404)
                    return
                body = holder.packages[path]
                self.send_response(200)
                self.send_header("Content-Type", "application/zip")
                self.send_header("Content-Length", str(len(body)))
                self.end_headers()
                self.wfile.write(body)

            def log_message(self, *args: Any) -> None:
                pass

        self.server = ThreadingHTTPServer(("127.0.0.1", 0), H)
        self.port = self.server.server_address[1]
        self.thread = threading.Thread(target=self.server.serve_forever, daemon=True)
        self.thread.start()

    def url(self, name: str) -> str:
        return f"http://127.0.0.1:{self.port}/{name}"

    def stop(self) -> None:
        self.server.shutdown()
        self.server.server_close()


def _make_zip() -> bytes:
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w", zipfile.ZIP_DEFLATED) as zf:
        zf.writestr("db/lexicon.txt", "ب ك ت ب")
    return buf.getvalue()


def _real_layout_descriptors(server: _FakePackServer) -> list[dict[str, Any]]:
    """Descriptors like catalog_packages() but pointing at the fake server,
    with the REAL on-disk destinations the pre-flight checks."""
    out = []
    for name, destination in (
        ("morphology-db-msa-r13", "morphology_db/calima-msa-r13"),
        ("dialectid-model6", "dialectid/model6"),
    ):
        data = server.packages[name]
        out.append(
            {
                "name": name,
                "url": server.url(name),
                "sha256": hashlib.sha256(data).hexdigest(),
                "size": len(data),
                "destination": destination,
                "version": "0.0.0-test",
                "license": "GPL v2" if "msa" in name else "MIT",
            }
        )
    return out


def _wait_for_state(installer: Any, want: set[str], timeout: float = 20.0) -> dict[str, Any]:
    deadline = time.time() + timeout
    while time.time() < deadline:
        s: dict[str, Any] = installer.status()
        if s.get("state") in want:
            return s
        time.sleep(0.05)
    pytest.fail(f"installer never reached {want}; last: {installer.status()}")


# --------------------------------------------------------------------------- #
# The user's bug, end to end in one process
# --------------------------------------------------------------------------- #


def test_resolver_poisoned_before_install_is_fresh_after_installer_job(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """THE rc1 bug: resolve (pre-install request) -> install via the REAL
    installer job -> the SAME process must now pass the pre-flight without
    any restart or manual cache invalidation."""
    import app.arabic_installer as inst_mod

    # 1. The pre-install request: nothing on disk yet -> the resolver caches
    #    None (this is the poison the old code never cleared).
    assert camel_tools_data_dir() is None
    with pytest.raises(ArabicDataMissingError):
        _require_camel_data(("calima-msa-r13",))

    # 2. The user clicks Install: the real job downloads (fake server),
    #    verifies size+SHA256, lands the packages, and (the fix) refreshes
    #    the resolver cache as the on-disk state changes.
    server = _FakePackServer(
        {"morphology-db-msa-r13": _make_zip(), "dialectid-model6": _make_zip()}
    )
    try:
        monkeypatch.setattr(
            inst_mod, "catalog_packages",
            lambda: _real_layout_descriptors(server),
        )
        inst = inst_mod.get_arabic_installer()
        s = inst.start()
        assert s["state"] == "running"
        s = _wait_for_state(inst, {"done"})
        assert s["packages_done"] == 2
    finally:
        server.stop()

    # 3. The user's next analysis attempt, same process, NO restart:
    #    the pre-flight MUST see the freshly installed pack now.
    data_dir = _require_camel_data(("calima-msa-r13",))
    assert data_dir is not None
    assert (Path(data_dir) / "data" / "morphology_db" / "calima-msa-r13").is_dir()

    # 4. The health/status view flips too (badge + installer card truth).
    status = camel_data_status()
    assert status["installed"] is True
    assert status["morphology_dbs"]["msa"] is True


def test_refresh_helper_clears_poisoned_none() -> None:
    """Unit: poison -> pack appears on disk -> stale None until refresh."""
    assert camel_tools_data_dir() is None  # poison
    target = Path(os.environ["CAMELTOOLS_DATA"])
    (target / "data" / "morphology_db" / "calima-msa-r13").mkdir(parents=True)
    (target / "catalogue.json").write_text("{}", encoding="utf-8")
    # Stale: the cache still holds the pre-install None.
    assert camel_tools_data_dir() is None
    refresh_camel_tools_data_dir()
    # Fresh: the resolver now reports the pack.
    assert camel_tools_data_dir() == target


def test_resolver_unpoisons_when_pack_removed() -> None:
    """The inverse direction must hold too (cleanup/removal re-syncs)."""
    target = Path(os.environ["CAMELTOOLS_DATA"])
    (target / "data" / "morphology_db" / "calima-msa-r13").mkdir(parents=True)
    (target / "catalogue.json").write_text("{}", encoding="utf-8")
    refresh_camel_tools_data_dir()
    assert camel_tools_data_dir() == target
    import shutil

    shutil.rmtree(target)
    refresh_camel_tools_data_dir()
    assert camel_tools_data_dir() is None


# --------------------------------------------------------------------------- #
# The second facet: honest hints + per-dialect status
# --------------------------------------------------------------------------- #


def test_missing_dialect_hint_names_exact_package(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    """With only the MSA pack present, requesting the Egyptian DB must 503
    with the EXACT terminal package (morphology-db-egy-r13) - the old hint
    pointed every missing-data case at the in-app installer, which provisions
    the MSA pack only and could never fix this one."""
    target = Path(os.environ["CAMELTOOLS_DATA"])
    (target / "data" / "morphology_db" / "calima-msa-r13").mkdir(parents=True)
    (target / "catalogue.json").write_text("{}", encoding="utf-8")
    refresh_camel_tools_data_dir()

    with pytest.raises(ArabicDataMissingError) as ei:
        _require_camel_data(("calima-egy-r13",))
    msg = str(ei.value)
    assert "missing calima-egy-r13 (terminal: camel_data -i morphology-db-egy-r13)" in msg
    # Contracts the API-layer tests and the web 503-card matcher rely on.
    assert "Arabic morphology data is incomplete" in msg
    assert "camel_data -i" in msg
    assert "never downloads data at request time" in msg


def test_camel_data_status_reports_per_dialect_dbs() -> None:
    """camel_data_status exposes morphology_dbs keyed by the UI's dialect
    codes so the dropdown can disable what is genuinely not on disk."""
    status = camel_data_status()
    assert status["installed"] is False
    assert status["morphology_dbs"] == {"msa": False, "egy": False, "glf": False, "lev": False}

    target = Path(os.environ["CAMELTOOLS_DATA"])
    (target / "data" / "morphology_db" / "calima-msa-r13").mkdir(parents=True)
    (target / "catalogue.json").write_text("{}", encoding="utf-8")
    refresh_camel_tools_data_dir()

    status = camel_data_status()
    assert status["installed"] is True
    assert status["morphology_dbs"] == {"msa": True, "egy": False, "glf": False, "lev": False}
    # Back-compat keys unchanged.
    assert status["morphology_db_msa"] is True
    assert status["dialectid_model6"] is False


async def test_install_status_route_carries_morphology_dbs(client: Any) -> None:
    """The status endpoint the installer card and ArabicView poll must carry
    the per-dialect truth (camel_tools.morphology_dbs)."""
    target = Path(os.environ["CAMELTOOLS_DATA"])
    (target / "data" / "morphology_db" / "calima-msa-r13").mkdir(parents=True)
    (target / "catalogue.json").write_text("{}", encoding="utf-8")
    refresh_camel_tools_data_dir()

    r = await client.get("/api/v1/arabic/data/install/status")
    assert r.status_code == 200
    camel = r.json()["camel_tools"]
    assert camel["morphology_dbs"]["msa"] is True
    assert camel["morphology_dbs"]["egy"] is False
