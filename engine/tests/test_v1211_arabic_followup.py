"""v1.2.11 follow-up gates: concurrency cap, data-pack installer, bulk job,
inline size guard, and the licence-statement contract.

Everything here runs WITHOUT the real CAMeL data pack or network:
  - the concurrency tests use slow stubs, not real morphology,
  - the installer tests run against a local HTTP server serving fabricated
    zips, so the pinned-URL/SHA machinery is exercised with the REAL
    verification code path (size check, SHA256 check, staging, versions.json)
    while the package descriptors are monkeypatched to point at the fake
    server,
  - the bulk job tests use real ArabicToken objects through a stubbed
    analyze function,
  - the licence test pins the verified statements into THIRD_PARTY_LICENSES.md
    so they cannot silently drift.
"""
from __future__ import annotations

import asyncio
import hashlib
import io
import json
import os
import threading
import time
import zipfile
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

import pytest
from httpx import ASGITransport, AsyncClient

os.environ["CORPUSMIND_DB_URL"] = "sqlite+aiosqlite:///:memory:"
os.environ["CORPUSMIND_DATA_DIR"] = "/tmp/cm-test-data"
from app.settings import get_settings

get_settings.cache_clear()


# --------------------------------------------------------------------------- #
# Shared fixtures
# --------------------------------------------------------------------------- #


@pytest.fixture
async def client():
    from app.main import app
    from storage.session import dispose_db

    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as ac:
        async with app.router.lifespan_context(app):
            yield ac
    await dispose_db()


@pytest.fixture(autouse=True)
def _reset_gates():
    """Every test starts with an empty concurrency gate and fresh job
    singletons, whatever a previous test left behind."""
    from app import arabic_bulk, arabic_concurrency, arabic_installer

    arabic_concurrency.gate.reset_for_tests()
    arabic_installer.reset_installer_for_tests()
    arabic_bulk.reset_bulk_job_for_tests()
    yield
    arabic_concurrency.gate.reset_for_tests()
    arabic_installer.reset_installer_for_tests()
    arabic_bulk.reset_bulk_job_for_tests()


def _slow_stub(seconds: float, result=None):
    """Sync CPU-bound stand-in for a real CAMeL analysis."""
    import time as _t

    def _fn(*args, **kwargs):
        _t.sleep(seconds)
        return result

    return _fn


def _fake_analysis(text: str):
    """Real ArabicToken objects (the aggregator's and routes' actual input
    type)."""
    from nlp.arabic.pipeline import ArabicAnalysis, ArabicToken

    tokens = [
        ArabicToken(
            text=w, lemma=w, root="ك.ت.ب", pattern="1َ2َ3َل", pos="noun",
            stem=w, buckwalter="ktb", dediacritized=w,
        )
        for w in text.split()
    ]
    return ArabicAnalysis(text=text, tokens=tokens, detected_dialect="msa", backend="camel")


# --------------------------------------------------------------------------- #
# 1. Concurrency cap
# --------------------------------------------------------------------------- #


@pytest.mark.asyncio
async def test_second_concurrent_analysis_gets_429_with_retry_after(client, monkeypatch):
    """While one Arabic analysis holds the cap (default 1), a second
    /arabic/* request must get an IMMEDIATE 429 with Retry-After - never a
    hidden queue and never a freeze."""
    from api import arabic as arabic_routes

    monkeypatch.setattr(
        arabic_routes, "analyze_arabic",
        _slow_stub(1.0, result=_fake_analysis("المكتبة الكبيرة")),
    )

    first = asyncio.create_task(
        client.post(
            "/api/v1/arabic/analyze", json={"text": "المكتبة الكبيرة", "dialect": "msa"}
        )
    )
    await _async_sleep(0.15)  # let request 1 take the slot
    t0 = time.perf_counter()
    second = await client.post("/api/v1/arabic/roots", json={"text": "المكتبة"})
    busy_latency = time.perf_counter() - t0
    assert second.status_code == 429, second.text
    assert second.headers.get("retry-after") == "2"
    detail = second.json()["detail"]
    assert "already running" in detail and "Try again" in detail
    # Busy must be answered instantly (non-blocking gate, no queue).
    assert busy_latency < 1.0, f"429 took {busy_latency:.2f}s - the gate is queueing"
    r1 = await first
    assert r1.status_code == 200


@pytest.fixture
def _reset_camel_backend_cache():
    """Drop the lru_cached Arabic backend singleton around tests that fiddle
    with data resolution: a WARM backend (loaded by an earlier test in the
    same process) skips the data pre-flight entirely, so the 503 branch below
    would never fire. Mirrors the fixture in test_phase3_arabic.py."""
    from nlp.arabic.pipeline import get_arabic_backend

    get_arabic_backend.cache_clear()
    yield
    get_arabic_backend.cache_clear()


@pytest.mark.usefixtures("_reset_camel_backend_cache")
@pytest.mark.asyncio
async def test_gate_released_after_error_paths(client, monkeypatch):
    """A 503 (missing data) or 504 (timeout) must never leak its slot - a
    leaked slot would wedge every Arabic route until restart."""
    from api import arabic as arabic_routes
    from app import resource_paths
    from app.arabic_concurrency import gate
    from app.resource_paths import camel_tools_data_dir as _ct_resolver

    # Simulate an unprovisioned machine (this dev machine HAS ~/.camel_tools):
    # patch the resolver the pipeline actually uses and clear its cache, the
    # same way the original 503 test does.
    monkeypatch.delenv("CAMELTOOLS_DATA", raising=False)
    monkeypatch.setattr(resource_paths, "camel_tools_data_dir", lambda: None)
    _ct_resolver.cache_clear()
    try:
        r = await client.post("/api/v1/arabic/roots", json={"text": "المكتبة"})
        assert r.status_code == 503
        assert gate.held == 0, "503 path leaked a concurrency slot"

        monkeypatch.setattr(arabic_routes, "analyze_arabic", _slow_stub(0.5))
        monkeypatch.setattr(arabic_routes, "ARABIC_TIMEOUT_S", 0.1)
        r = await client.post(
            "/api/v1/arabic/analyze", json={"text": "المكتبة", "dialect": "msa"}
        )
        assert r.status_code == 504
        assert gate.held == 0, "504 path leaked a concurrency slot"
    finally:
        _ct_resolver.cache_clear()


@pytest.mark.asyncio
async def test_ai_arabic_tool_busy_is_clean_error(client, monkeypatch):
    """With the cap full, the grounded-AI Arabic tools raise ArabicBusyError
    (recorded by the assistant as a failed tool call), while non-Arabic
    tools keep working."""
    from ai import tools as ai_tools
    from app.arabic_concurrency import ArabicBusyError, gate

    assert gate.acquire()  # simulate an in-flight analysis
    try:
        with pytest.raises(ArabicBusyError):
            await ai_tools.execute_tool("arabic_morphology", {"text": "المكتبة"})
        # Non-Arabic stateless tools are NOT capped.
        assert (await ai_tools.execute_tool("ping", {}))["ok"] is True
    finally:
        gate.release()
    # After release the tool runs again (stubbed so it stays offline;
    # TOOL_IMPLS holds the live reference, not the module attribute).
    monkeypatch.setitem(
        ai_tools.TOOL_IMPLS, "arabic_morphology", lambda **kwargs: {"stub": True}
    )
    out = await ai_tools.execute_tool("arabic_morphology", {"text": "المكتبة"})
    assert out == {"stub": True}


@pytest.mark.asyncio
async def test_cap_env_clamped_to_1_2(monkeypatch):
    """CORPUSMIND_ARABIC_CONCURRENCY clamps to the 1..2 range the review
    asked for; garbage falls back to 1."""
    from app.arabic_concurrency import _resolve_cap

    for raw, want in (("0", 1), ("1", 1), ("2", 2), ("5", 2), ("abc", 1), ("", 1)):
        monkeypatch.setenv("CORPUSMIND_ARABIC_CONCURRENCY", raw)
        assert _resolve_cap() == want, f"env={raw!r} -> cap {_resolve_cap()}, want {want}"


@pytest.mark.asyncio
async def test_cap_2_admits_second_request(client, monkeypatch):
    """Cap=2: a second concurrent Arabic analysis is admitted; the third is
    rejected."""
    from api import arabic as arabic_routes

    monkeypatch.setenv("CORPUSMIND_ARABIC_CONCURRENCY", "2")
    monkeypatch.setattr(
        arabic_routes, "analyze_arabic",
        _slow_stub(0.8, result=_fake_analysis("المكتبة الكبيرة")),
    )

    async def _fire():
        return await client.post(
            "/api/v1/arabic/analyze", json={"text": "المكتبة الكبيرة", "dialect": "msa"}
        )

    t1 = asyncio.create_task(_fire())
    await _async_sleep(0.1)
    t2 = asyncio.create_task(_fire())
    await _async_sleep(0.1)
    t3 = asyncio.create_task(_fire())  # third one must be rejected at cap 2
    await _async_sleep(0.05)
    responses = [await t1, await t2, await t3]
    assert responses[0].status_code == 200
    assert responses[1].status_code == 200
    assert responses[2].status_code == 429


async def _async_sleep(s: float) -> None:
    import asyncio

    await asyncio.sleep(s)


# --------------------------------------------------------------------------- #
# 2. Installer
# --------------------------------------------------------------------------- #


class _FakePackServer:
    """Serves fabricated package zips with controllable behaviour:
    normal, corrupt (bad bytes), or stalled (accept, never respond)."""

    def __init__(self, packages: dict[str, bytes], corrupt: set[str] | None = None,
                 stall_paths: set[str] | None = None):
        self.packages = packages
        self.corrupt = corrupt or set()
        self.stall_paths = stall_paths or set()
        self.hits: list[str] = []
        holder = self

        class H(BaseHTTPRequestHandler):
            def do_GET(self):
                path = self.path.lstrip("/")
                if path in holder.stall_paths:
                    self.close_connection = True
                    time.sleep(5.0)
                    return
                if path not in holder.packages:
                    self.send_error(404)
                    return
                holder.hits.append(path)
                body = holder.packages[path]
                if path in holder.corrupt:
                    body = body[:-64] + b"\x00" * 64
                self.send_response(200)
                self.send_header("Content-Type", "application/zip")
                self.send_header("Content-Length", str(len(body)))
                self.end_headers()
                self.wfile.write(body)

            def log_message(self, *args):
                pass

        self.server = ThreadingHTTPServer(("127.0.0.1", 0), H)
        self.port = self.server.server_address[1]
        self.thread = threading.Thread(target=self.server.serve_forever, daemon=True)
        self.thread.start()

    def url(self, name: str) -> str:
        return f"http://127.0.0.1:{self.port}/{name}"

    def stop(self):
        self.server.shutdown()
        self.server.server_close()


def _make_zip() -> bytes:
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w", zipfile.ZIP_DEFLATED) as zf:
        zf.writestr("db/lexicon.txt", "ب ك ت ب")
        zf.writestr("db/dict.txt", "kataba")
    return buf.getvalue()


def _fake_descriptors(server: _FakePackServer, sizes: dict[str, int] | None = None) -> list[dict]:
    """Descriptors shaped exactly like catalog_packages() output, but with
    real sha256/size of the fabricated zips."""
    out = []
    for name in ("morphology-db-msa-r13", "dialectid-model6"):
        data = server.packages[name]
        out.append(
            {
                "name": name,
                "url": server.url(name),
                "sha256": hashlib.sha256(data).hexdigest(),
                "size": (sizes or {}).get(name, len(data)),
                "destination": f"fake/{name}",
                "version": "0.0.0-test",
                "license": "GPL v2" if "msa" in name else "MIT",
            }
        )
    return out


@pytest.fixture
def tmp_camel_target(monkeypatch, tmp_path):
    """Point the installer at a writable temp dir (CAMELTOOLS_DATA path)."""
    target = tmp_path / "camel-home"
    monkeypatch.setenv("CAMELTOOLS_DATA", str(target))
    return target


def _wait_for_state(installer, want: set[str], timeout: float = 20.0) -> dict:
    deadline = time.time() + timeout
    while time.time() < deadline:
        s = installer.status()
        if s.get("state") in want:
            return s
        time.sleep(0.05)
    pytest.fail(f"installer never reached {want}; last: {installer.status()}")


def test_installer_happy_path(tmp_camel_target, monkeypatch):
    """Download -> size+SHA verify -> install -> versions.json + catalogue.json
    written, data dirs in place, status reaches done."""
    import app.arabic_installer as inst_mod

    server = _FakePackServer(
        {"morphology-db-msa-r13": _make_zip(), "dialectid-model6": _make_zip()}
    )
    descs = _fake_descriptors(server)
    try:
        monkeypatch.setattr(inst_mod, "catalog_packages", lambda: descs)
        inst = inst_mod.get_arabic_installer()
        s = inst.start()
        assert s["state"] == "running"
        assert s["bytes_total"] == sum(d["size"] for d in descs)
        s = _wait_for_state(inst, {"done"})
        assert s["packages_done"] == 2
        assert s["installed"] == ["morphology-db-msa-r13", "dialectid-model6"]
        target = tmp_camel_target
        assert (target / "catalogue.json").is_file(), "resolver marker missing"
        versions = json.loads((target / "versions.json").read_text())
        assert versions["morphology-db-msa-r13"] == "0.0.0-test"
        assert versions["dialectid-model6"] == "0.0.0-test"
        assert (target / "data" / "fake" / "morphology-db-msa-r13" / "db").is_dir()
        assert (target / "data" / "fake" / "dialectid-model6" / "db").is_dir()
        assert not (target / ".staging").exists(), "staging left behind"
    finally:
        server.stop()


def test_installer_rejects_corrupt_sha256(tmp_camel_target, monkeypatch):
    """A corrupted download must be rejected on SHA256; NOTHING is installed
    (no data dirs, no versions entry) and staging is cleaned."""
    import app.arabic_installer as inst_mod

    server = _FakePackServer(
        {"morphology-db-msa-r13": _make_zip(), "dialectid-model6": _make_zip()},
        corrupt={"morphology-db-msa-r13"},
    )
    descs = _fake_descriptors(server)
    try:
        monkeypatch.setattr(inst_mod, "catalog_packages", lambda: descs)
        inst = inst_mod.get_arabic_installer()
        inst.start(include_dialect_id=True)
        s = _wait_for_state(inst, {"error"})
        assert "SHA256" in (s.get("error") or "")
        assert not (tmp_camel_target / "data" / "fake" / "morphology-db-msa-r13").exists()
        assert not (tmp_camel_target / ".staging").exists()
    finally:
        server.stop()


def test_installer_rejects_size_mismatch(tmp_camel_target, monkeypatch):
    """Content-Length smaller than the pinned size must be refused before
    the digest is even considered."""
    import app.arabic_installer as inst_mod

    server = _FakePackServer(
        {"morphology-db-msa-r13": _make_zip(), "dialectid-model6": _make_zip()}
    )
    descs = _fake_descriptors(server, sizes={"morphology-db-msa-r13": 999999999})
    try:
        monkeypatch.setattr(inst_mod, "catalog_packages", lambda: descs)
        inst = inst_mod.get_arabic_installer()
        inst.start()
        s = _wait_for_state(inst, {"error"})
        assert "server reports" in (s.get("error") or "")
        assert "Refusing to install" in (s.get("error") or "")
        assert not (tmp_camel_target / "data" / "fake").exists()
    finally:
        server.stop()


def test_installer_cancel_between_chunks(tmp_camel_target, monkeypatch):
    """Cancel is honoured between chunks; final state is cancelled and no
    package lands."""
    import app.arabic_installer as inst_mod

    server = _FakePackServer(
        {"morphology-db-msa-r13": _make_zip(), "dialectid-model6": _make_zip()}
    )
    descs = _fake_descriptors(server)
    try:
        monkeypatch.setattr(inst_mod, "catalog_packages", lambda: descs)
        inst = inst_mod.get_arabic_installer()
        inst.start()
        s = inst.cancel()
        assert s["busy"] is True  # cancel requested while still running
        s = _wait_for_state(inst, {"cancelled", "done"}, timeout=10.0)
        if s["state"] == "done":  # download beat the cancel request: legal
            assert s["packages_done"] == 2
        else:
            assert not (tmp_camel_target / "data" / "fake").exists()
    finally:
        server.stop()


def test_installer_read_timeout_on_stalled_server(tmp_camel_target, monkeypatch):
    """A server that accepts but never responds must fail inside the READ
    timeout (default 60s; the test tightens it) - this is the bounded-
    network contract that keeps the installer from hanging forever."""
    import app.arabic_installer as inst_mod

    server = _FakePackServer(
        {"morphology-db-msa-r13": _make_zip(), "dialectid-model6": _make_zip()},
        stall_paths={"morphology-db-msa-r13"},
    )
    descs = _fake_descriptors(server)
    try:
        monkeypatch.setenv("CORPUSMIND_ARABIC_INSTALL_CONNECT_TIMEOUT_S", "2")
        monkeypatch.setenv("CORPUSMIND_ARABIC_INSTALL_READ_TIMEOUT_S", "1")
        monkeypatch.setattr(inst_mod, "catalog_packages", lambda: descs)
        inst = inst_mod.get_arabic_installer()
        t0 = time.perf_counter()
        inst.start()
        s = _wait_for_state(inst, {"error"}, timeout=15.0)
        elapsed = time.perf_counter() - t0
        assert elapsed < 10, f"stalled server hit at {elapsed:.1f}s - timeout not applied"
        assert s.get("error"), "error status must carry the reason"
    finally:
        server.stop()


def test_installer_start_conflicts(tmp_camel_target, monkeypatch):
    """Second start while running -> ArabicInstallerError (409 at the HTTP
    layer); start when everything is installed -> ArabicInstallerError too."""
    import app.arabic_installer as inst_mod

    server = _FakePackServer(
        {"morphology-db-msa-r13": _make_zip(), "dialectid-model6": _make_zip()}
    )
    descs = _fake_descriptors(server)
    try:
        monkeypatch.setattr(inst_mod, "catalog_packages", lambda: descs)
        inst = inst_mod.get_arabic_installer()
        inst.start()
        with pytest.raises(inst_mod.ArabicInstallerError, match="already running"):
            inst.start()
        _wait_for_state(inst, {"done"})
        with pytest.raises(inst_mod.ArabicInstallerError, match="already installed"):
            inst.start()
    finally:
        server.stop()


def test_installer_catalog_snapshot_integrity():
    """The REAL shipped snapshot must exist, parse, match the release-verified
    URLs/sizes/digests, and carry the licence fields the docs state."""
    from app.arabic_installer import catalog_packages

    pkgs = catalog_packages()
    assert [p["name"] for p in pkgs] == ["morphology-db-msa-r13", "dialectid-model6"]
    msa, did = pkgs
    assert msa["license"] == "GPL v2" and msa["version"] == "0.4.0"
    assert did["license"] == "MIT" and did["version"] == "1.1.2"
    # Digests pinned to the OBSERVED release assets (2026-10-07): the msa
    # asset was re-uploaded upstream (content diffed identical to a fresh
    # `camel_data -i` install); the dialectid sha matches the catalogue.
    assert msa["size"] == 40488532 and did["size"] == 127877916
    assert msa["sha256"].startswith("fe653125") and did["sha256"].startswith("579258f6")


def test_installer_refuses_tampered_snapshot(monkeypatch):
    """If the shipped snapshot ever disagrees with the release-verified
    digests, catalog_packages must fail loudly instead of installing
    unverified data."""
    import app.arabic_installer as inst_mod

    fake_cat = {
        "version": "1.6.0",
        "packages": {
            "morphology-db-msa-r13": {
                "url": "https://evil.example/x.zip",
                "sha256": "0" * 64,
                "size": 1,
                "destination": "morphology_db/calima-msa-r13",
                "version": "9.9.9",
                "license": "GPL v2",
                "private": False,
            },
            "dialectid-model6": {
                "url": "https://evil.example/y.zip",
                "sha256": "1" * 64,
                "size": 2,
                "destination": "dialectid/model6",
                "version": "9.9.9",
                "license": "MIT",
                "private": False,
            },
        },
        "components": {},
    }
    monkeypatch.setattr(inst_mod, "_load_catalogue_snapshot", lambda: fake_cat)
    with pytest.raises(inst_mod.ArabicInstallerError, match="release-pinned URL"):
        inst_mod.catalog_packages()


@pytest.mark.asyncio
async def test_installer_routes_conflict_and_status(client, monkeypatch, tmp_camel_target):
    """HTTP layer: status answers with a preview when idle; start returns
    409 with the reason when a job cannot start."""
    import app.arabic_installer as inst_mod

    r = await client.get("/api/v1/arabic/data/install/status")
    assert r.status_code == 200
    body = r.json()
    assert body["state"] == "idle"
    assert "camel_tools" in body  # filesystem truth for the UI buttons
    # camel_tools IS provisioned on dev machines / CI; the offer lists the
    # packages with their per-dataset state either way.
    assert set(body["offer"]["packages"][0]) >= {"name", "size", "sha256", "license", "state"}

    # Make start() fail with "already installed" and check the 409 mapping.
    monkeypatch.setattr(
        inst_mod.ArabicDataInstaller, "start",
        lambda self, include_dialect_id=True: (_ for _ in ()).throw(
            inst_mod.ArabicInstallerError("The Arabic data pack is already installed (nothing to download).")
        ),
    )
    r = await client.post("/api/v1/arabic/data/install", json={"include_dialect_id": True})
    assert r.status_code == 409
    assert "already installed" in r.json()["detail"]


# --------------------------------------------------------------------------- #
# 3. Bulk analysis job + inline size guard
# --------------------------------------------------------------------------- #


@pytest.mark.asyncio
async def test_analyze_inline_token_cap_413(client, monkeypatch):
    """Text above the inline cap answers 413 with the measured numbers and
    points at the bulk job; it must NOT take a worker slot or time out."""
    from api import arabic as arabic_routes

    monkeypatch.setattr(arabic_routes, "ARABIC_INLINE_MAX_TOKENS", 10)
    big = " ".join(["كلمة"] * 11)
    r = await client.post(
        "/api/v1/arabic/analyze", json={"text": big, "dialect": "msa"}
    )
    assert r.status_code == 413
    detail = r.json()["detail"]
    assert "3,950 tokens/s" in detail and "/arabic/analyze/job" in detail


@pytest.mark.asyncio
async def test_bulk_job_progress_result_and_download(client, monkeypatch):
    """Bulk job: progress fields move, final state done, result downloadable
    and aggregated (roots/lemmas/POS), not a token dump."""
    import app.arabic_bulk as bulk_mod

    monkeypatch.setattr(
        bulk_mod, "analyze_arabic", lambda text, **kwargs: _fake_analysis(text)
    )
    # 3 chunks: 6000 tokens of one-word sentences -> 3 x 2000-token chunks.
    text = " ".join(["كتاب"] * 6000)
    job = bulk_mod.get_bulk_job()
    s = job.start(text)
    assert s["chunks_total"] == 3
    assert s["tokens_total"] == 6000
    s = _wait_for_state(job, {"done"}, timeout=30.0)
    assert s["chunks_done"] == 3 and s["tokens_done"] == 6000
    assert s["eta_s"] is not None or s["elapsed_s"] >= 0

    r = await client.get("/api/v1/arabic/analyze/job/result")
    assert r.status_code == 200
    payload = r.json()
    assert payload["token_count"] == 6000
    assert payload["unique_tokens"] == 1
    assert ["ك.ت.ب", 6000] in payload["top_roots"]  # JSON turns tuples into lists
    assert payload["pos_distribution"].get("noun") == 6000
    # Aggregated: no per-token array to download for 1M-token inputs.
    assert "tokens" not in payload


@pytest.mark.asyncio
async def test_bulk_job_busy_409_and_cancel(client, monkeypatch):
    """A running bulk job rejects a second start with 409, and cancel lands
    the job in `cancelled`."""
    import app.arabic_bulk as bulk_mod

    def _slow(text, **kwargs):
        time.sleep(1.2)
        return _fake_analysis(text)

    monkeypatch.setattr(bulk_mod, "analyze_arabic", _slow)
    job = bulk_mod.get_bulk_job()
    job.start(" ".join(["كتاب"] * 8000))
    r = await client.post("/api/v1/arabic/analyze/job", json={"text": "كتاب"})
    assert r.status_code == 409
    assert "already running" in r.json()["detail"]

    c = await client.post("/api/v1/arabic/analyze/job/cancel")
    assert c.status_code == 200
    s = _wait_for_state(job, {"cancelled", "done"}, timeout=10.0)
    assert s["state"] in ("cancelled", "done")  # done only if it raced ahead


@pytest.mark.asyncio
async def test_bulk_result_404_when_idle(client):
    r = await client.get("/api/v1/arabic/analyze/job/result")
    assert r.status_code == 404
    assert "No bulk analysis result" in r.json()["detail"]


# --------------------------------------------------------------------------- #
# 4. Licence statement contract (docs cannot silently drift)
# --------------------------------------------------------------------------- #


def test_third_party_licenses_states_verified_facts():
    """The verified licence facts must stay stated in THIRD_PARTY_LICENSES.md:
    calima-msa-r13 is GPL-2.0-only (the DB's own LICENSE file says Version 2,
    no 'or later'), dialectid-model6 is MIT per the camel_tools catalogue,
    and the file says plainly what is and is not redistributed."""
    repo_root = Path(__file__).resolve().parents[2]
    text = (repo_root / "THIRD_PARTY_LICENSES.md").read_text(encoding="utf-8")
    assert "GPL-2.0-only" in text, "calima-msa-r13 must be stated as GPL-2.0-only"
    assert "no \"or later\"" in text or "no 'or later'" in text
    assert "dialectid-model6" in text and "MIT" in text
    assert "not redistributed" in text.lower() or "IS redistributed" in text
