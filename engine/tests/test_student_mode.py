"""v1.2.9 — Student Mode (classroom server): middleware, allowlist, Caddy.

Covers:
  - the student route allowlist (what students may and may never call);
  - the auth middleware's classroom branch: proxy-stamped requests must
    present the teacher or student token; the student token gets the
    allowlist only; direct loopback stays trusted teacher access;
  - the /server-mode/* control plane being teacher-only;
  - Caddyfile generation for both connection modes;
  - caddy binary lookup order, config persistence, capacity math,
    and LAN IP enumeration being sane.
"""

from __future__ import annotations

import os
from pathlib import Path
from typing import Any

import pytest

# --------------------------------------------------------------------------- #
# Unit tests: allowlist
# --------------------------------------------------------------------------- #


def test_student_allowlist_covers_analysis_and_ai_chat():
    from app.server_mode import student_route_allowed

    # Analysis: allowed.
    for method, path in [
        ("POST", "/api/v1/corpora/abc123/concordance"),
        ("POST", "/api/v1/corpora/abc123/concordance/vector"),
        ("POST", "/api/v1/corpora/abc123/frequency"),
        ("POST", "/api/v1/corpora/abc123/collocations"),
        ("POST", "/api/v1/corpora/abc123/keyness"),
        ("POST", "/api/v1/corpora/abc123/dispersion"),
        ("POST", "/api/v1/corpora/abc123/ngrams"),
        ("POST", "/api/v1/corpora/abc123/pos-analysis"),
        ("POST", "/api/v1/corpora/abc123/grammar"),
        ("POST", "/api/v1/corpora/abc123/dependencies"),
        ("POST", "/api/v1/corpora/abc123/discourse"),
        ("POST", "/api/v1/corpora/abc123/sentiment"),
        ("GET", "/api/v1/corpora/abc123/readability"),
        ("POST", "/api/v1/ai/chat"),
        ("GET", "/api/v1/ai/tools"),
        ("GET", "/api/v1/health/resources"),
        ("GET", "/api/v1/discourse/persuasion/health"),
        ("POST", "/api/v1/corpora/abc123/learner/caf"),
        ("POST", "/api/v1/arabic/analyze"),
    ]:
        assert student_route_allowed(method, path), f"{method} {path} must be allowed"


def test_student_allowlist_denies_teacher_surface():
    from app.server_mode import student_route_allowed

    # Write/admin surface: denied.
    for method, path in [
        ("POST", "/api/v1/corpora/abc123/documents"),          # upload
        ("DELETE", "/api/v1/corpora/abc123"),                   # delete corpus
        ("DELETE", "/api/v1/corpora/abc123/documents/x"),      # delete doc
        ("POST", "/api/v1/corpora/abc123/recompile"),
        ("POST", "/api/v1/corpora/abc123/subcorpora"),
        ("PATCH", "/api/v1/corpora/abc123/tagset"),
        ("POST", "/api/v1/corpora/abc123/clean"),
        ("GET", "/api/v1/settings"),                             # settings
        ("POST", "/api/v1/ai/cloud-config"),
        ("POST", "/api/v1/ollama/pull"),                         # model mgmt
        ("DELETE", "/api/v1/ollama/models"),
        ("POST", "/api/v1/export/jobs"),                         # export queue
        ("POST", "/api/v1/reference-corpora/be06/download"),
        ("POST", "/api/v1/open-access/api-key"),
        ("POST", "/api/v1/facial-analysis/enabled"),
        ("POST", "/api/v1/troubleshoot/gemini-key"),
        ("POST", "/api/v1/projects/p1/saved-searches"),          # phase6 writes
        ("POST", "/api/v1/image-sets/abc/images"),               # vision uploads
        ("GET", "/api/v1/ai/conversations"),                     # teacher chats
        ("GET", "/api/v1/ai/conversations/xyz"),
        ("DELETE", "/api/v1/ai/conversations/xyz"),
        # The classroom control plane itself must never be student-visible.
        ("GET", "/api/v1/server-mode/status"),
        ("POST", "/api/v1/server-mode/enable"),
        ("POST", "/api/v1/server-mode/disable"),
    ]:
        assert not student_route_allowed(method, path), f"{method} {path} must be DENIED"


# --------------------------------------------------------------------------- #
# Unit tests: config persistence, Caddyfile, lookup, capacity, LAN IPs
# --------------------------------------------------------------------------- #


def test_config_roundtrip_and_sanitize(tmp_path):
    from app.server_mode import ServerModeConfig, load_config, save_config

    settings = type("S", (), {"data_dir": tmp_path})
    cfg = ServerModeConfig()
    cfg.mode = "bogus"
    cfg.https_port = 80  # below 1024
    cfg.num_parallel = 999
    cfg.sanitize()
    assert cfg.mode == "secure"
    assert cfg.https_port == 1024
    assert cfg.num_parallel == 16

    cfg2 = ServerModeConfig(enabled=True, mode="simple", student_token="s", teacher_token="t")
    save_config(settings, cfg2)
    loaded = load_config(settings)
    assert loaded.enabled and loaded.mode == "simple"
    assert loaded.student_token == "s"
    # Tokens never travel into world-readable files.
    assert (tmp_path / "server-mode" / "config.json").is_file()


def test_ensure_tokens_generates_and_rotates():
    from app.server_mode import ServerModeConfig, ensure_tokens

    cfg = ServerModeConfig()
    ensure_tokens(cfg)
    assert cfg.teacher_token.startswith("cm_teach_")
    assert cfg.student_token.startswith("cm_study_")
    t1, s1 = cfg.teacher_token, cfg.student_token
    ensure_tokens(cfg)  # idempotent
    assert (cfg.teacher_token, cfg.student_token) == (t1, s1)
    ensure_tokens(cfg, rotate=True)
    assert cfg.teacher_token not in ("", t1)
    assert cfg.student_token not in ("", s1)


def _settings_stub(tmp_path: Path, port: int = 8765) -> Any:
    return type("S", (), {"data_dir": tmp_path, "port": port})


def test_generate_caddyfile_secure_mode(tmp_path: Path) -> None:
    from app.server_mode import ServerModeConfig, generate_caddyfile

    cfg = ServerModeConfig(mode="secure", https_port=8443, http_port=8088)
    web = tmp_path / "web-dist"
    web.mkdir()
    ca = tmp_path / "ca-share"
    ca.mkdir()
    cert = tmp_path / "server.crt"
    key = tmp_path / "server.key"
    cert.write_text("CERT")
    key.write_text("KEY")
    text = generate_caddyfile(_settings_stub(tmp_path), cfg, web, ca,
                              server_cert=cert, server_key=key)

    assert f"https://:{cfg.https_port}" in text
    # v1.2.9: the engine issues the certificate itself (Caddy's `tls internal`
    # tries to sudo-install its root into the OS trust store, which is not
    # guaranteed on teacher machines) — the Caddyfile points at the files.
    # v1.2.10 release fix: paths are backtick-quoted so Windows home
    # directories with spaces (C:\Users\Waleed Mandour\...) tokenize safely.
    assert f"tls `{cert}` `{key}`" in text
    assert "tls internal" not in text
    assert 'header_up X-CorpusMind-Classroom "1"' in text
    assert "reverse_proxy 127.0.0.1:8765" in text
    assert f"root * `{web}`" in text
    assert "try_files {path} /index.html" in text
    # The cert-trust helper port serves the CA share over plain HTTP.
    assert f"http://:{cfg.http_port}" in text
    assert f"root * `{ca}`" in text


def test_generate_caddyfile_simple_mode(tmp_path: Path) -> None:
    from app.server_mode import ServerModeConfig, generate_caddyfile

    cfg = ServerModeConfig(mode="simple", http_port=8088)
    text = generate_caddyfile(
        _settings_stub(tmp_path), cfg, tmp_path / "w", tmp_path / "ca"
    )
    assert "tls" not in text
    assert f"http://:{cfg.http_port}" in text
    assert 'header_up X-CorpusMind-Classroom "1"' in text


def test_generate_caddyfile_windows_path_with_spaces(tmp_path: Path) -> None:
    """v1.2.10 release blocker regression: the teacher's Windows home
    directory is ``C:\\Users\\Waleed Mandour\\...`` — an unquoted path with
    a space lexes as two tokens, so Caddy exits code 1 immediately and
    Student Mode could never start. Every filesystem path must render as a
    backtick-quoted token (raw string in Caddyfile terms: no backslash
    escape processing, spaces preserved), with forward slashes (Go accepts
    them on Windows)."""
    from app.server_mode import ServerModeConfig, generate_caddyfile

    cfg = ServerModeConfig(mode="simple", http_port=8088)
    win_like = tmp_path / "Waleed Mandour" / "web-dist"
    win_like.mkdir(parents=True)
    ca = tmp_path / "CA share dir"
    ca.mkdir()
    text = generate_caddyfile(_settings_stub(tmp_path), cfg, win_like, ca)

    # The spaced paths must appear backtick-quoted, never bare.
    assert f"root * `{win_like}`" in text
    # simple mode serves no CA helper port (that block is secure-only).
    assert "root * " not in text.replace(f"root * `{win_like}`", "")
    # No line may carry a path argument with a space outside backticks.
    for line in text.splitlines():
        for directive in ("root *", "output file", "tls "):
            if directive in line:
                rest = line.split(directive, 1)[1]
                assert "`" in rest or " " not in rest.replace("\t", ""), (
                    f"unquoted spaced path in Caddyfile line: {line!r}"
                )


def test_generate_caddyfile_quotes_log_output(tmp_path: Path) -> None:
    """The global log output path lives in the server-mode dir under the
    (spaced) home directory — it must be backtick-quoted too."""
    from app.server_mode import ServerModeConfig, generate_caddyfile

    cfg = ServerModeConfig(mode="simple", http_port=8088)
    text = generate_caddyfile(
        _settings_stub(tmp_path), cfg, tmp_path / "w", tmp_path / "ca"
    )
    log_line = next(line for line in text.splitlines() if "output file" in line)
    assert "`" in log_line and log_line.rstrip().endswith("`")


def test_caddy_log_tail_helper(tmp_path: Path) -> None:
    """Teacher-facing spawn errors include the log tail; a missing log
    degrades to an empty string instead of a second exception."""
    from app.server_mode import _caddy_log_tail

    assert _caddy_log_tail(tmp_path) == ""
    log = tmp_path / "caddy-stdout.log"
    log.write_text("x" * 900 + "Error: loading initial config: parse error", encoding="utf-8")
    tail = _caddy_log_tail(tmp_path, limit=100)
    assert tail.endswith("parse error")
    assert len(tail) <= 100


def test_classroom_certificates_issued_and_persisted(tmp_path):
    """The engine issues its own classroom CA + leaf (no sudo, no bundler).
    The CA persists across calls; the leaf is refreshed with current SANs."""
    from cryptography import x509

    from app.server_mode import ServerModeConfig, ensure_classroom_certificates

    settings = _settings_stub(tmp_path)
    cfg = ServerModeConfig(mode="secure")
    cert, key, ca = ensure_classroom_certificates(settings, cfg)
    assert cert.is_file() and key.is_file() and ca.is_file()

    ca_cert = x509.load_pem_x509_certificate(ca.read_bytes())
    assert "CorpusMind Classroom CA" in ca_cert.subject.rfc4514_string()

    leaf = x509.load_pem_x509_certificate(cert.read_bytes())
    assert leaf.issuer == ca_cert.subject
    sans = leaf.extensions.get_extension_for_class(x509.SubjectAlternativeName).value
    names = sans.get_values_for_type(x509.DNSName)
    ips = sans.get_values_for_type(x509.IPAddress)
    assert "localhost" in names
    assert any(str(ip) == "127.0.0.1" for ip in ips)

    # Second call: CA unchanged (persisted and not expiring).
    _cert2, _key2, ca2 = ensure_classroom_certificates(settings, cfg)
    assert ca2.read_bytes() == ca.read_bytes()


def test_find_caddy_binary_order(tmp_path, monkeypatch):
    import sys as _sys

    from app import server_mode as sm

    exe = "caddy.exe" if _sys.platform.startswith("win") else "caddy"
    monkeypatch.delenv("CORPUSMIND_CADDY_BIN", raising=False)
    monkeypatch.setattr(sm.shutil, "which", lambda name: None)

    # 1. env wins.
    env_bin = tmp_path / "env" / exe
    env_bin.parent.mkdir()
    env_bin.write_text("x")
    monkeypatch.setenv("CORPUSMIND_CADDY_BIN", str(env_bin))
    assert sm.find_caddy_binary(_settings_stub(tmp_path)) == env_bin
    monkeypatch.delenv("CORPUSMIND_CADDY_BIN")

    # 2. sibling of the frozen executable (caddy/caddy).
    frozen = tmp_path / "frozen" / "caddy" / exe
    frozen.parent.mkdir(parents=True)
    frozen.write_text("x")
    fake_exe = tmp_path / "frozen" / "corpusmind-engine"
    fake_exe.write_text("x")
    monkeypatch.setattr(sm.sys, "executable", str(fake_exe))
    assert sm.find_caddy_binary(_settings_stub(tmp_path)) == frozen

    # 3. dev checkout (patched away here) — the real checkout may hold the
    # fetched binary, so point the constant at a missing path first.
    monkeypatch.setattr(sm, "_DEV_CADDY_DIR", tmp_path / "absent" / exe)
    path_bin = tmp_path / "on-path" / exe
    path_bin.parent.mkdir()
    path_bin.write_text("x")
    monkeypatch.setattr(sm.sys, "executable", str(tmp_path / "nowhere"))
    monkeypatch.setattr(sm.shutil, "which", lambda name: str(path_bin))
    assert sm.find_caddy_binary(_settings_stub(tmp_path)) == path_bin

    # 4. dev checkout hit when it exists.
    monkeypatch.setattr(sm, "_DEV_CADDY_DIR", path_bin)
    monkeypatch.setattr(sm.shutil, "which", lambda name: None)
    assert sm.find_caddy_binary(_settings_stub(tmp_path)) == path_bin

    # 5. nothing found → None.
    monkeypatch.setattr(sm, "_DEV_CADDY_DIR", tmp_path / "absent" / exe)
    assert sm.find_caddy_binary(_settings_stub(tmp_path)) is None


def test_find_web_dist_frozen_and_dev(tmp_path, monkeypatch):
    from app import server_mode as sm

    # Dev checkout: repo web/dist wins.
    repo = tmp_path / "repo"
    dist = repo / "web" / "dist"
    dist.mkdir(parents=True)
    (dist / "index.html").write_text("<html></html>")
    app_pkg = repo / "engine" / "app"
    app_pkg.mkdir(parents=True)
    fake_file = app_pkg / "server_mode.py"
    fake_file.write_text("")
    monkeypatch.setattr(sm, "__file__", str(fake_file))
    monkeypatch.delattr(sm.sys, "_MEIPASS", raising=False)
    assert sm.find_web_dist(_settings_stub(tmp_path)) == dist


def test_lan_ips_sane():
    from app.server_mode import lan_ips

    ips = lan_ips()
    assert isinstance(ips, list)
    for ip in ips:
        assert ip.count(".") == 3
        assert not ip.startswith("127.")
        assert not ip.startswith("169.254.")


def test_estimate_students_math(monkeypatch):
    from ai.hf_catalog import MachineProfile
    from app import server_mode as sm

    gb = 1024 ** 3
    profile = MachineProfile(
        ram_total=32 * gb, ram_available=24 * gb,
        vram_total=0, vram_available=0, gpu_name="",
        source="proc/meminfo",
    )
    monkeypatch.setattr(sm, "_machine_dict", lambda p: {})
    import ai.hf_catalog as hf

    monkeypatch.setattr(hf, "machine_profile", lambda **kw: profile)

    # 2 GB model, 4 parallel slots → fits several students in 24 GB RAM.
    est = sm.estimate_students(2 * gb, 4)
    assert est["students_max"] is not None
    assert 1 <= est["students_max"] <= sm.MAX_STUDENTS
    assert "not a guarantee" in est["note"]

    # Unknown model size → honest None, not a fake number.
    est0 = sm.estimate_students(0, 4)
    assert est0["students_max"] is None


def test_student_seen_window():
    from app.server_mode import ServerModeState

    st = ServerModeState()
    st.note_student("10.0.0.5")
    st.note_student("10.0.0.6")
    assert st.active_students() == 2
    # A stale timestamp beyond the active window stops counting.
    import time as _t

    st.student_seen["10.0.0.5"] = _t.monotonic() - 10 * 60 - 5
    assert st.active_students() == 1


# --------------------------------------------------------------------------- #
# API tests: middleware + control plane
# --------------------------------------------------------------------------- #


def _make_client_fixture(env: dict[str, str], unset: tuple[str, ...] = ()):
    async def client():
        for k in unset:
            os.environ.pop(k, None)
        for k, v in env.items():
            os.environ[k] = v
        os.environ["CORPUSMIND_DB_URL"] = "sqlite+aiosqlite:///:memory:"
        os.environ["CORPUSMIND_DATA_DIR"] = "/tmp/cm-sm-test-data"
        os.environ.pop("CORPUSMIND_STUDENT_TOKEN", None)
        # Isolate from any previous run's persisted classroom config.
        import shutil

        shutil.rmtree("/tmp/cm-sm-test-data/server-mode", ignore_errors=True)
        # v1.2.9: the classroom audit day-file must not leak across tests.
        shutil.rmtree("/tmp/cm-sm-test-data/classroom", ignore_errors=True)

        from app.settings import get_settings

        get_settings.cache_clear()
        from storage.session import _engine, dispose_db

        _engine.clear() if hasattr(_engine, "clear") else None

        from httpx import ASGITransport, AsyncClient

        from app.main import app

        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as ac:
            async with app.router.lifespan_context(app):
                yield ac
        await dispose_db()

    return pytest.fixture(client)


sm_client = _make_client_fixture({"CORPUSMIND_HOST": "127.0.0.1"})

PROXY = {"X-CorpusMind-Classroom": "1"}


@pytest.fixture()
def classroom(sm_client):
    """Flip the app's server-mode state into an enabled classroom with
    fixed tokens (no Caddy spawned — unit-level middleware testing)."""
    ac = sm_client
    app = ac._transport.app
    sm_state = app.state.server_mode
    sm_state.config.enabled = True
    sm_state.config.teacher_token = "teach-token-xyz"
    sm_state.config.student_token = "study-token-xyz"
    sm_state.config.student_model = "llama3.2:3b"
    yield ac, sm_state
    sm_state.config.enabled = False


def _app(ac):
    return ac._transport.app


@pytest.mark.asyncio
async def test_proxy_traffic_requires_token(classroom):
    ac, _ = classroom
    r = await ac.get("/api/v1/version", headers=PROXY)
    assert r.status_code == 401  # no token at all


@pytest.mark.asyncio
async def test_proxy_wrong_token_401(classroom):
    ac, _ = classroom
    r = await ac.get("/api/v1/version", headers={**PROXY, "Authorization": "Bearer nope"})
    assert r.status_code == 401


@pytest.mark.asyncio
async def test_teacher_token_full_access(classroom):
    ac, sm_state = classroom
    h = {**PROXY, "Authorization": f"Bearer {sm_state.config.teacher_token}"}
    r = await ac.get("/api/v1/version", headers=h)
    assert r.status_code == 200
    # Teacher may hit the classroom control plane.
    r = await ac.get("/api/v1/server-mode/status", headers=h)
    assert r.status_code == 200
    body = r.json()
    assert body["enabled"] is True
    assert body["student_token"] == "study-token-xyz"  # teacher-only field
    assert "lan_ips" in body and "caddy_running" in body


@pytest.mark.asyncio
async def test_student_token_allowlist_and_denials(classroom):
    ac, sm_state = classroom
    h = {**PROXY, "Authorization": f"Bearer {sm_state.config.student_token}"}

    # Allowed analysis route (the corpus doesn't exist → 404 from the
    # route handler, NOT 401/403 from the gate).
    r = await ac.get("/api/v1/version", headers=h)
    assert r.status_code == 200

    # Teacher-only control plane → 403 for students.
    r = await ac.get("/api/v1/server-mode/status", headers=h)
    assert r.status_code == 403

    # Upload / management surface → 403.
    r = await ac.post("/api/v1/projects", headers=h, json={"name": "x"})
    assert r.status_code == 403
    r = await ac.get("/api/v1/ai/conversations", headers=h)
    assert r.status_code == 403
    r = await ac.post("/api/v1/ollama/pull", headers=h, json={"model": "x"})
    assert r.status_code == 403


@pytest.mark.asyncio
async def test_direct_loopback_stays_teacher_no_auth(classroom):
    """No proxy header → the local desktop experience is untouched."""
    ac, _ = classroom
    r = await ac.get("/api/v1/version")  # no auth, no header
    assert r.status_code == 200
    r = await ac.get("/api/v1/server-mode/status")  # direct = teacher
    assert r.status_code == 200


@pytest.mark.asyncio
async def test_student_requests_counted_as_connected(classroom):
    ac, sm_state = classroom
    h = {**PROXY, "Authorization": f"Bearer {sm_state.config.student_token}"}
    assert sm_state.active_students() == 0
    await ac.get("/api/v1/version", headers=h)
    assert sm_state.active_students() >= 1


@pytest.mark.asyncio
async def test_health_stays_open_for_probes(classroom):
    ac, _sm_state = classroom
    # Docker-style health probes carry no credentials.
    r = await ac.get("/api/v1/health", headers=PROXY)
    assert r.status_code == 200


@pytest.mark.asyncio
async def test_enable_requires_caddy_and_reports_error(classroom, monkeypatch):
    """Enabling with no Caddy binary fails loudly but does not crash."""
    ac, sm_state = classroom
    import api.server_mode as router_mod
    from app import server_mode as sm

    sm_state.config.enabled = False
    monkeypatch.setattr(sm, "find_caddy_binary", lambda settings: None)
    monkeypatch.setattr(router_mod, "find_caddy_binary", lambda settings: None)
    r = await ac.post("/api/v1/server-mode/enable", json={"mode": "secure"})
    assert r.status_code == 500
    assert "Caddy" in r.json()["detail"]
    assert sm_state.config.enabled is False  # not persisted half-on


@pytest.mark.asyncio
async def test_status_reports_disabled_by_default(sm_client):
    ac = sm_client
    r = await ac.get("/api/v1/server-mode/status")
    assert r.status_code == 200
    body = r.json()
    assert body["enabled"] is False
    assert "student_token" not in body  # tokens only leak while enabled


# --------------------------------------------------------------------------- #
# v1.2.9 (follow-up): anonymous audit log + enforced seat limit
# --------------------------------------------------------------------------- #


def _read_audit(state):
    """All audit entries of the current day (oldest-first)."""
    return state.audit.read_tail(500)


@pytest.mark.asyncio
async def test_audit_written_and_anonymous(classroom):
    """Student traffic lands in the JSONL audit file with an anonymous
    alias — and NEVER with the IP, session ID or bearer tokens."""
    ac, sm_state = classroom
    h = {
        **PROXY,
        "Authorization": f"Bearer {sm_state.config.student_token}",
        "X-CorpusMind-Session": "very-secret-browser-uuid-42",
    }
    r = await ac.get("/api/v1/version", headers=h)
    assert r.status_code == 200

    entries = _read_audit(sm_state)
    events = [e["event"] for e in entries]
    assert "student_join" in events
    assert "api_request" in events
    join = next(e for e in entries if e["event"] == "student_join")
    assert join["alias"] == "S-1"
    assert sm_state.joined_total == 1

    import json as _json

    blob = _json.dumps(entries)
    assert "very-secret-browser-uuid-42" not in blob  # session ID never stored
    assert "study-token-xyz" not in blob and "teach-token-xyz" not in blob
    assert "testclient" not in blob and "127.0.0.1" not in blob  # no addresses


@pytest.mark.asyncio
async def test_seat_limit_rejects_new_students_only(classroom):
    """max_students=1: the first student gets a seat; the next NEW student
    is rejected with 429 while the seated student keeps working and the
    teacher is never capped."""
    ac, sm_state = classroom
    sm_state.config.max_students = 1

    student_a = {**PROXY, "Authorization": f"Bearer {sm_state.config.student_token}",
                 "X-CorpusMind-Session": "sess-A"}
    student_b = {**PROXY, "Authorization": f"Bearer {sm_state.config.student_token}",
                 "X-CorpusMind-Session": "sess-B"}
    teacher = {**PROXY, "Authorization": f"Bearer {sm_state.config.teacher_token}",
               "X-CorpusMind-Session": "sess-T"}

    r = await ac.get("/api/v1/version", headers=student_a)
    assert r.status_code == 200
    r = await ac.get("/api/v1/version", headers=student_a)  # seated → still fine
    assert r.status_code == 200

    r = await ac.get("/api/v1/version", headers=student_b)
    assert r.status_code == 429
    assert "full" in r.json()["detail"].lower()

    r = await ac.get("/api/v1/version", headers=teacher)
    assert r.status_code == 200  # teacher unaffected by the cap

    # The rejection is audited (rate-limited to one line per window).
    denials = [e for e in _read_audit(sm_state) if e["event"] == "denied"]
    assert any("classroom_full" in str(e.get("reason", "")) for e in denials)


@pytest.mark.asyncio
async def test_seat_limit_status_and_auto_fallback(classroom):
    """Status exposes the effective cap + its source; nulling the manual
    override falls back to the conservative auto ceiling (MAX_STUDENTS)."""
    ac, sm_state = classroom
    teacher = {"Authorization": f"Bearer {sm_state.config.teacher_token}"}

    r = await ac.post("/api/v1/server-mode/config", headers=teacher,
                      json={"max_students": 7})
    body = r.json()
    assert body["max_students"] == 7
    assert body["students_max"] == 7
    assert body["students_cap_source"] == "manual"

    r = await ac.post("/api/v1/server-mode/config", headers=teacher,
                      json={"max_students": None})  # back to auto
    body = r.json()
    assert body["max_students"] is None
    # No Ollama in the test env → model size unknown → hard fallback cap.
    from app.server_mode import MAX_STUDENTS as _MAX_STUDENTS

    assert body["students_max"] == _MAX_STUDENTS
    assert body["students_cap_source"] == "auto-fallback"


@pytest.mark.asyncio
async def test_audit_endpoint_teacher_only(classroom):
    ac, sm_state = classroom
    student = {**PROXY, "Authorization": f"Bearer {sm_state.config.student_token}"}
    teacher = {**PROXY, "Authorization": f"Bearer {sm_state.config.teacher_token}"}

    r = await ac.get("/api/v1/server-mode/audit", headers=student)
    assert r.status_code == 403

    await ac.get("/api/v1/version", headers=student)  # generate one event

    r = await ac.get("/api/v1/server-mode/audit?limit=50", headers=teacher)
    assert r.status_code == 200
    body = r.json()
    assert body["enabled"] is True
    assert body["audit_enabled"] is True
    assert body["chats_total"] == 0
    assert body["students_joined_total"] == 1
    assert any(e["event"] == "api_request" for e in body["entries"])
    assert body["summary"]["events_total"] >= 2


@pytest.mark.asyncio
async def test_audit_toggle_off_silences_writer(classroom):
    ac, sm_state = classroom
    teacher = {"Authorization": f"Bearer {sm_state.config.teacher_token}"}
    student = {**PROXY, "Authorization": f"Bearer {sm_state.config.student_token}",
               "X-CorpusMind-Session": "sess-quiet"}

    r = await ac.post("/api/v1/server-mode/config", headers=teacher,
                      json={"audit_enabled": False})
    assert r.json()["audit_enabled"] is False

    r = await ac.get("/api/v1/version", headers=student)
    assert r.status_code == 200
    assert _read_audit(sm_state) == []  # nothing written while off

    r = await ac.post("/api/v1/server-mode/config", headers=teacher,
                      json={"audit_enabled": True})
    assert r.json()["audit_enabled"] is True
    await ac.get("/api/v1/version", headers=student)
    assert len(_read_audit(sm_state)) >= 1


def test_audit_rotation_and_size_cap(tmp_path):
    """A day file over the size threshold rotates to .1; disabled writers
    and corrupt lines are handled without raising."""
    from app.classroom_audit import AUDIT_MAX_BYTES, ClassroomAudit

    a = ClassroomAudit(tmp_path, enabled=True)
    for i in range(3):
        a.write("api_request", alias=f"S-{i}", path="/api/v1/version")
    active = a.current_file()
    assert active.exists() and active.read_text().count("\n") == 3

    # Force the threshold and confirm rotation.
    active.write_text("x" * (AUDIT_MAX_BYTES + 1), encoding="utf-8")
    a.write("api_request", alias="S-9", path="/api/v1/version")
    rotated = active.with_suffix(active.suffix + ".1")
    assert rotated.exists()
    assert any(e.get("alias") == "S-9" for e in a.read_tail(10))

    # Disabled writer: no file, no error.
    off = ClassroomAudit(tmp_path / "off", enabled=False)
    off.write("chat", alias="S-1", question="q", response="r")
    assert not (tmp_path / "off").exists()

    # Corrupt lines are skipped by readers (the valid entry survives).
    with open(active, "a", encoding="utf-8") as f:
        f.write("not-json\n")
    tail = [e for e in a.read_tail(10) if e is not None]
    assert any(e.get("alias") == "S-9" for e in tail)


@pytest.mark.asyncio
async def test_student_chat_question_and_response_audited(classroom, monkeypatch):
    """The audit contract's core: what the student asked the local LM and
    what the model answered both land in the log, verbatim."""
    ac, sm_state = classroom

    class _StubProvider:
        name = "ollama"
        default_model = "llama3.2:3b"

        async def health(self):
            return True

        async def pick_default_model(self):
            return "llama3.2:3b"

        async def supports_tools(self, model=None):
            return True

        async def list_models(self):
            return ["llama3.2:3b"]

        async def chat(self, messages, model=None, temperature=0.2, tools=None):
            from ai.providers import ChatResponse

            return ChatResponse(
                content="The corpus shows heavy nominal style.",
                model=model or "llama3.2:3b",
                provider="ollama",
                raw={},
            )

    class _StubRegistry:
        def __init__(self, p):
            self._p = p

        def get(self, name=None):
            return self._p

    from ai import Assistant

    async def _fake_answer(self, convo_id, message, context=None):
        from types import SimpleNamespace

        return SimpleNamespace(
            turn_id=1,
            content="The corpus shows heavy nominal style.",
            grounded=False,
            tool_calls=[],
            evidence=[],
            elapsed_ms=42,
            confidence=0.9,
            confidence_reasoning="",
            needs_validation=False,
            mcqs=[],
        )

    monkeypatch.setattr(Assistant, "answer", _fake_answer)
    from app.main import app

    monkeypatch.setattr(app.state, "providers", _StubRegistry(_StubProvider()))

    h = {**PROXY, "Authorization": f"Bearer {sm_state.config.student_token}",
         "X-CorpusMind-Session": "sess-chat"}
    r = await ac.post(
        "/api/v1/ai/chat",
        headers=h,
        json={"message": "What is the dominant register of this corpus?"},
    )
    assert r.status_code == 200

    chats = [e for e in _read_audit(sm_state) if e["event"] == "chat"]
    assert len(chats) == 1
    entry = chats[0]
    assert entry["question"] == "What is the dominant register of this corpus?"
    assert entry["response"] == "The corpus shows heavy nominal style."
    assert entry["model"] == "llama3.2:3b"
    assert entry["elapsed_ms"] == 42
    assert sm_state.chats_total == 1
