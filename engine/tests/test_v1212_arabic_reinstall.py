"""v1.2.12 gates: the Arabic data pack Re-install / repair path.

Field report (v1.2.12-rc3, Windows): an app reinstall left the CAMeL data
dir with the MSA morphology DB + dialect-ID model but WITHOUT the three
dialect morphology DBs. The pack still counted as "installed"
(camel_data_status keys on the data DIR existing), so Settings disabled its
install button and no in-app path could fetch the missing components - the
user had to hand-edit their profile directory.

The contract pinned here:
  1. A PARTIALLY installed pack stays installable: start() (no force)
     downloads exactly the missing packages. (Engine behaviour that
     predates this fix - now guarded so it can never regress.)
  2. A FULLY installed pack refuses a plain start() with "already
     installed", and start(force=True) reinstalls EVERYTHING (repair).
  3. A forced run REPLACES what is on disk: junk inside an installed
     destination directory is gone after force=True (the per-package
     installer swaps the destination directory wholesale).
  4. The HTTP layer accepts `force` on POST /arabic/data/install and maps
     the plain "already installed" conflict to 409.
  5. The new i18n keys exist in BOTH en and ar.

Everything runs WITHOUT network or the real pack: fabricated zips on a
local HTTP server, real verification code path (size + SHA256 + staging),
same pattern as test_v1211_arabic_followup.py.
"""
from __future__ import annotations

import hashlib
import io
import os
import threading
import time
import zipfile
from collections.abc import AsyncGenerator, Iterator
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import Any

import pytest
from httpx import ASGITransport, AsyncClient

os.environ["CORPUSMIND_DB_URL"] = "sqlite+aiosqlite:///:memory:"
os.environ["CORPUSMIND_DATA_DIR"] = "/tmp/cm-test-data"


@pytest.fixture
async def client() -> AsyncGenerator[AsyncClient, None]:
    from app.main import app
    from storage.session import dispose_db

    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as ac:
        async with app.router.lifespan_context(app):
            yield ac
    await dispose_db()


_ORDER = (
    "morphology-db-msa-r13",
    "morphology-db-egy-r13",
    "morphology-db-glf-01",
    "morphology-db-lev-01",
    "dialectid-model6",
)


class _FakePackServer:
    """Serves fabricated package zips (same shape as the v1.2.11 one)."""

    def __init__(self, packages: dict[str, bytes]) -> None:
        self.packages = packages
        self.hits: list[str] = []
        holder = self

        class H(BaseHTTPRequestHandler):
            def do_GET(self) -> None:
                path = self.path.lstrip("/")
                if path not in holder.packages:
                    self.send_error(404)
                    return
                holder.hits.append(path)
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


def _fake_descriptors(server: _FakePackServer) -> list[dict[str, Any]]:
    out = []
    for name in _ORDER:
        if name not in server.packages:
            continue
        data = server.packages[name]
        out.append(
            {
                "name": name,
                "url": server.url(name),
                "sha256": hashlib.sha256(data).hexdigest(),
                "size": len(data),
                "destination": f"fake/{name}",
                "version": "0.0.0-test",
                "license": "GPL v2" if "msa" in name or "egy" in name else "MIT",
            }
        )
    return out


@pytest.fixture
def tmp_camel_target(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> Path:
    target = tmp_path / "camel-home"
    monkeypatch.setenv("CAMELTOOLS_DATA", str(target))
    return target


@pytest.fixture(autouse=True)
def _reset_installer() -> Iterator[None]:
    from app import arabic_installer

    arabic_installer.reset_installer_for_tests()
    yield
    arabic_installer.reset_installer_for_tests()


def _wait_for_state(
    installer: Any, want: set[str], timeout: float = 20.0
) -> dict[str, Any]:
    deadline = time.time() + timeout
    while time.time() < deadline:
        s: dict[str, Any] = installer.status()
        if s.get("state") in want:
            return s
        time.sleep(0.05)
    pytest.fail(f"installer never reached {want}; last: {installer.status()}")


def _dest(target: Path, name: str) -> Path:
    return target / "data" / "fake" / name


# --------------------------------------------------------------------------- #
# 1. Partial pack: start() fills exactly the gaps (the field report)
# --------------------------------------------------------------------------- #


def test_partial_pack_installs_exactly_the_missing(
    tmp_camel_target: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """The rc3 field report: data dir has MSA + dialect-ID, the three dialect
    DBs are gone. A plain start() must fetch EXACTLY the three dialect DBs -
    never 409 "already installed"."""
    import app.arabic_installer as inst_mod

    server = _FakePackServer({n: _make_zip() for n in _ORDER})
    descs = _fake_descriptors(server)
    try:
        monkeypatch.setattr(inst_mod, "catalog_packages", lambda: descs)
        target = tmp_camel_target
        # Simulate the leftover state: MSA + dialect-ID on disk, dialects gone.
        for name in ("morphology-db-msa-r13", "dialectid-model6"):
            (_dest(target, name) / "db").mkdir(parents=True, exist_ok=True)

        inst = inst_mod.get_arabic_installer()
        s = inst.start()
        assert s["state"] == "running"
        assert s["packages_total"] == 3
        s = _wait_for_state(inst, {"done"})
        assert s["installed"] == [
            "morphology-db-egy-r13",
            "morphology-db-glf-01",
            "morphology-db-lev-01",
        ]
        for name in ("morphology-db-egy-r13", "morphology-db-glf-01", "morphology-db-lev-01"):
            assert (_dest(target, name) / "db").is_dir()
    finally:
        server.stop()


# --------------------------------------------------------------------------- #
# 2. Full pack: plain start refuses, force reinstalls everything
# --------------------------------------------------------------------------- #


def test_force_reinstalls_full_pack(
    tmp_camel_target: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Everything installed -> plain start() 409s, start(force=True)
    re-downloads all five and lands them again."""
    import app.arabic_installer as inst_mod

    server = _FakePackServer({n: _make_zip() for n in _ORDER})
    descs = _fake_descriptors(server)
    try:
        monkeypatch.setattr(inst_mod, "catalog_packages", lambda: descs)
        inst = inst_mod.get_arabic_installer()
        inst.start()
        _wait_for_state(inst, {"done"})

        with pytest.raises(inst_mod.ArabicInstallerError, match="already installed"):
            inst.start()

        server.hits.clear()
        s = inst.start(force=True)
        assert s["state"] == "running"
        assert s["packages_total"] == 5
        s = _wait_for_state(inst, {"done"})
        assert s["installed"] == list(_ORDER)
        # Every package was re-downloaded, installed ones included.
        assert sorted(server.hits) == sorted(_ORDER)
    finally:
        server.stop()


# --------------------------------------------------------------------------- #
# 3. Force replaces on-disk state (repair of a corrupt install)
# --------------------------------------------------------------------------- #


def test_force_replaces_corrupt_destination(
    tmp_camel_target: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Junk inside an installed destination is gone after a forced reinstall:
    the installer swaps the destination directory wholesale."""
    import app.arabic_installer as inst_mod

    server = _FakePackServer({n: _make_zip() for n in _ORDER})
    descs = _fake_descriptors(server)
    try:
        monkeypatch.setattr(inst_mod, "catalog_packages", lambda: descs)
        inst = inst_mod.get_arabic_installer()
        inst.start(include_dialect_id=False, include_dialects=False)
        _wait_for_state(inst, {"done"})
        dest = _dest(tmp_camel_target, "morphology-db-msa-r13")
        assert (dest / "db").is_dir()
        (dest / "junk.txt").write_text("half-written state", encoding="utf-8")

        s = inst.start(force=True, include_dialect_id=False, include_dialects=False)
        assert s["packages_total"] == 1
        _wait_for_state(inst, {"done"})
        assert (dest / "db").is_dir()
        assert not (dest / "junk.txt").exists(), "forced run must replace the destination"
    finally:
        server.stop()


# --------------------------------------------------------------------------- #
# 4. HTTP layer: force passes through; plain conflict stays 409
# --------------------------------------------------------------------------- #


@pytest.mark.asyncio
async def test_install_route_force_and_conflict(
    client: AsyncClient, monkeypatch: pytest.MonkeyPatch, tmp_camel_target: Path
) -> None:
    """POST /arabic/data/install: {"force": true} starts the job on a fully
    installed pack; the same body without force answers 409."""
    import app.arabic_installer as inst_mod

    server = _FakePackServer({n: _make_zip() for n in _ORDER})
    descs = _fake_descriptors(server)
    try:
        monkeypatch.setattr(inst_mod, "catalog_packages", lambda: descs)
        target = tmp_camel_target
        for name in _ORDER:
            (_dest(target, name) / "db").mkdir(parents=True, exist_ok=True)

        r = await client.post("/api/v1/arabic/data/install", json={})
        assert r.status_code == 409
        assert "already installed" in r.json()["detail"]

        r = await client.post("/api/v1/arabic/data/install", json={"force": True})
        assert r.status_code == 200
        assert r.json()["state"] == "running"
        assert r.json()["packages_total"] == 5

        inst = inst_mod.get_arabic_installer()
        s = _wait_for_state(inst, {"done"})
        assert s["installed"] == list(_ORDER)
    finally:
        server.stop()


# --------------------------------------------------------------------------- #
# 5. i18n keys in both languages
# --------------------------------------------------------------------------- #


def test_i18n_reinstall_keys_in_both_languages() -> None:
    repo_root = Path(__file__).resolve().parents[2]
    src = (repo_root / "web" / "src" / "lib" / "i18n.ts").read_text(encoding="utf-8")
    for key in (
        "ar_data_install_missing_btn",
        "ar_data_reinstall_btn",
        "ar_data_missing_badge",
        "ar_data_missing_components_hint",
    ):
        assert src.count(f"{key}:") >= 2, f"i18n key {key!r} must exist in en + ar"
