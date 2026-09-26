"""Classroom audit log — anonymous, append-only JSONL (v1.2.9).

When Student Mode is active the teacher gets a durable, *anonymous* record
of what happened in the classroom session:

  - ``classroom_started`` / ``classroom_stopped``  (with session totals)
  - ``student_join``        — a new anonymous student appeared (seat taken)
  - ``api_request``         — every student API call (method, path, status)
  - ``chat``                — the exact question a student sent to the local
                              LM and the full response the model produced
  - ``chat_error``          — a chat that failed (error text, truncated)
  - ``denied``              — 403 (route not allowed) and 429 (classroom
                              full) rejections, with the reason

ANONYMITY CONTRACT (deliberate, enforced by construction)
---------------------------------------------------------
Students appear as rotating aliases ``S-1, S-2, …`` assigned in first-seen
order per classroom session. The alias key is the student PWA's random
per-browser-session ID (``X-CorpusMind-Session`` header) when present, or a
per-session-salted hash of the LAN IP otherwise. NEITHER the raw IP, NOR the
session header value, NOR the bearer tokens is ever written to the audit
file — the mapping lives in memory only (``ServerModeState``) and dies with
the process, so the log cannot be de-anonymised after the fact. There are no
usernames: students never authenticate with anything but the shared class
token.

STORAGE
-------
One JSONL file per UTC day under ``<data_dir>/classroom/audit/``:
``classroom-audit-YYYYMMDD.jsonl``. When the active file exceeds
``AUDIT_MAX_BYTES`` it is rotated to ``.1`` (previous ``.1`` is replaced) so
a runaway day cannot fill the teacher's disk. Reads (teacher UI) tail the
current file, falling back to yesterday's ``.1`` for completeness.

Writes are crash-safe: open → append one line → close on every event. The
classroom's write volume is tiny (a question is seconds of model time), so
the per-write open cost is irrelevant next to the durability win.
"""

from __future__ import annotations

import hashlib
import json
import os
import threading
import time
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

# Rotation threshold for the active day file.
AUDIT_MAX_BYTES = 5_000_000
# Long free-text fields (questions/responses) are kept full up to this many
# characters — "all possible details" — then truncated with a marker so the
# log stays useful without risking pathological single-line sizes.
AUDIT_TEXT_MAX = 20_000
AUDIT_TEXT_ELISION = " …[truncated]"
# Error strings are capped harder; they can embed stack-ish noise.
AUDIT_ERROR_MAX = 800


def audit_dir(settings: Any) -> Path:
    return Path(settings.data_dir).expanduser() / "classroom" / "audit"


class ClassroomAudit:
    """Append-only anonymous JSONL writer + tail reader (one per app)."""

    def __init__(self, root: Path, enabled: bool = True) -> None:
        self.root = Path(root)
        self.enabled = enabled
        # Per-instance salt for IP-derived alias keys: regenerated on every
        # engine start, never persisted → aliases cannot be re-linked across
        # restarts even from the raw key material.
        self._salt = os.urandom(8).hex()
        self._lock = threading.Lock()

    # ------------------------------------------------------------------ #
    # Alias assignment (called by ServerModeState, which owns the map)
    # ------------------------------------------------------------------ #

    def alias_key(self, session_header: str, client_ip: str) -> str:
        """Stable-within-session, anonymity-preserving alias key.

        Prefers the PWA's random session ID (stable across WiFi roaming,
        distinct even behind a NAT); falls back to a salted hash of the LAN
        IP. The key is used ONLY to look up the alias in memory — it is not
        written anywhere.
        """
        if session_header:
            return f"sid:{session_header}"
        digest = hashlib.sha256(f"{self._salt}:{client_ip}".encode()).hexdigest()[:12]
        return f"ip:{digest}"

    # ------------------------------------------------------------------ #
    # Writing
    # ------------------------------------------------------------------ #

    def write(self, event: str, **fields: Any) -> None:
        """Append one event. Never raises — audit must not break the class."""
        if not self.enabled:
            return
        try:
            entry = {"ts": datetime.now(UTC).isoformat(timespec="milliseconds"), "event": event}
            for k, v in fields.items():
                if v is None:
                    continue
                if isinstance(v, str):
                    cap = AUDIT_ERROR_MAX if k == "error" else AUDIT_TEXT_MAX
                    if len(v) > cap:
                        v = v[:cap] + AUDIT_TEXT_ELISION
                entry[k] = v
            line = json.dumps(entry, ensure_ascii=False)
            with self._lock:
                path = self._active_file()
                self._rotate_if_needed(path)
                path.parent.mkdir(parents=True, exist_ok=True)
                with open(path, "a", encoding="utf-8") as f:
                    f.write(line + "\n")
        except Exception:
            # Audit is strictly best-effort: a full disk or a permissions
            # problem must never take the classroom down mid-lesson.
            pass

    def _active_file(self) -> Path:
        day = datetime.now(UTC).strftime("%Y%m%d")
        return self.root / f"classroom-audit-{day}.jsonl"

    def _rotate_if_needed(self, path: Path) -> None:
        try:
            if path.exists() and path.stat().st_size >= AUDIT_MAX_BYTES:
                rotated = path.with_suffix(path.suffix + ".1")
                if rotated.exists():
                    rotated.unlink()
                path.rename(rotated)
        except OSError:
            pass

    # ------------------------------------------------------------------ #
    # Reading (teacher UI)
    # ------------------------------------------------------------------ #

    def read_tail(self, limit: int = 200) -> list[dict[str, Any]]:
        """Last ``limit`` events, oldest-first, across current + rotated file."""
        out: list[dict[str, Any]] = []
        with self._lock:
            current = self._active_file()
            rotated = current.with_suffix(current.suffix + ".1")
            for path in (rotated, current):
                if len(out) >= limit:
                    break
                try:
                    if not path.is_file():
                        continue
                    lines = path.read_text(encoding="utf-8").splitlines()
                    need = limit - len(out)
                    out.extend(
                        _safe_json(ln) for ln in lines[-need:] if _safe_json(ln) is not None
                    )
                except OSError:
                    continue
        return out[-limit:] if len(out) > limit else out

    def summarize(self) -> dict[str, Any]:
        """Quick counters over the current day file (+rotated sibling)."""
        counts: dict[str, int] = {}
        aliases: set[str] = set()
        chats = 0
        errors = 0
        with self._lock:
            current = self._active_file()
            rotated = current.with_suffix(current.suffix + ".1")
            for path in (rotated, current):
                try:
                    if not path.is_file():
                        continue
                    for ln in path.read_text(encoding="utf-8").splitlines():
                        e = _safe_json(ln)
                        if not e:
                            continue
                        ev = e.get("event", "?")
                        counts[ev] = counts.get(ev, 0) + 1
                        if ev == "chat":
                            chats += 1
                        elif ev == "chat_error":
                            errors += 1
                        a = e.get("alias")
                        if isinstance(a, str) and a.startswith("S-"):
                            aliases.add(a)
                except OSError:
                    continue
        return {
            "events_total": sum(counts.values()),
            "by_event": counts,
            "students_seen": len(aliases),
            "chats": chats,
            "chat_errors": errors,
        }

    def current_file(self) -> Path:
        return self._active_file()


def _safe_json(line: str) -> dict[str, Any] | None:
    try:
        e = json.loads(line)
        return e if isinstance(e, dict) else None
    except ValueError:
        return None


def elapsed_ms_since(monotonic_start: float) -> int:
    return int((time.monotonic() - monotonic_start) * 1000)
