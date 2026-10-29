"""Unit: Ollama loopback-vs-LAN exposure detection (v1.2.10, item 5a).

BUILD_GUIDE.md used to advise opening port 11434 "if remote" — the exact
opposite of safe for a classroom server. Student Mode now detects a
LAN-facing Ollama at every /server-mode/status poll via two independent
signals, and these tests pin both:

  1. OLLAMA_HOST env pointing off loopback (the bind Ollama itself uses);
  2. a live TCP answer on a LAN interface's port (a loopback-bound Ollama
     never answers there, whatever bound it).

The probe port is injected (``api.server_mode._OLLAMA_PORT``) and the
interface list monkeypatched, so the tests never touch a real Ollama.
"""

from __future__ import annotations

import socket
import threading
from collections.abc import Iterator

import pytest

from api.server_mode import _ollama_lan_exposure


@pytest.fixture(autouse=True)
def _no_real_ollama(monkeypatch: pytest.MonkeyPatch) -> Iterator[None]:
    """Isolate from the host: no OLLAMA_HOST env, probe only our ports."""
    monkeypatch.delenv("OLLAMA_HOST", raising=False)
    monkeypatch.setattr("api.server_mode.lan_ips", lambda: ["127.0.0.1"])
    yield


def _listener(port: int) -> socket.socket:
    srv = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    srv.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
    srv.bind(("127.0.0.1", port))
    srv.listen(4)
    threading.Thread(target=_accept_and_close, args=(srv,), daemon=True).start()
    return srv


def _accept_and_close(srv: socket.socket) -> None:
    # Accept connections briefly so create_connection() succeeds, then let
    # the fixture close everything.
    srv.settimeout(5.0)
    try:
        while True:
            conn, _ = srv.accept()
            conn.close()
    except OSError:
        pass


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "value",
    ["0.0.0.0:11434", "0.0.0.0", "192.168.1.10:11434", "192.168.1.10"],
)
async def test_ollama_host_off_loopback_is_exposed(
    monkeypatch: pytest.MonkeyPatch, value: str
) -> None:
    monkeypatch.setenv("OLLAMA_HOST", value)
    out = await _ollama_lan_exposure()
    assert out["exposed"] is True
    assert out["source"] == "env"
    assert out["addr"] == value.split(":")[0]


@pytest.mark.asyncio
async def test_ollama_host_loopback_forms_fall_through_to_probe(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    # Probe path with nothing answering on the injected port → not exposed.
    monkeypatch.setattr("api.server_mode._OLLAMA_PORT", 54322)
    out = await _ollama_lan_exposure()
    assert out == {"exposed": False, "source": None, "addr": None}


@pytest.mark.asyncio
async def test_probe_detects_lan_listener(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr("api.server_mode._OLLAMA_PORT", 54321)
    srv = _listener(54321)
    try:
        out = await _ollama_lan_exposure()
    finally:
        srv.close()
    assert out["exposed"] is True
    assert out["source"] == "probe"
    assert out["addr"] == "127.0.0.1"


@pytest.mark.asyncio
async def test_probe_closed_port_is_not_exposed(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr("api.server_mode._OLLAMA_PORT", 54323)
    # Bind + close so we KNOW the port is free right now.
    srv = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    srv.bind(("127.0.0.1", 54323))
    srv.close()
    out = await _ollama_lan_exposure()
    assert out == {"exposed": False, "source": None, "addr": None}
