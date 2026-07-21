"""On-disk manifest of installed reference corpora.

The manifest is a JSON file at ``Settings.data_dir / "reference-corpora" /
"manifest.json"``. It is the single source of truth for "what is installed"
— the API never trusts the filesystem alone, because partial downloads and
stale files from old versions can lurk there.

Schema (v1):
    {
      "version": 1,
      "entries": [
        {
          "name": "be06-top1000",
          "display_name": "BE06 — British English Written (top 1000)",
          "language": "en",
          "format": "tsv_freq",
          "sha256": "3e632ede...",
          "size_bytes": 4321,
          "installed_at": "2026-07-22T10:30:00Z",
          "source_url": "https://...",
          "license": "CC-BY-4.0",
          "citation": "Baker, P. (2009)...",
          "catalogue_version": "0.1.15",
          "file_path": "be06-top1000.tsv"
        },
        ...
      ]
    }

``file_path`` is relative to the manifest's directory, so the whole
``reference-corpora/`` folder is relocatable (just move it and the manifest
still works).
"""
from __future__ import annotations

import json
from dataclasses import asdict, dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from app.logging import get_logger

log = get_logger(__name__)

MANIFEST_VERSION = 1
MANIFEST_FILENAME = "manifest.json"


# --------------------------------------------------------------------------- #
# Entry dataclass
# --------------------------------------------------------------------------- #


@dataclass(frozen=True, slots=True)
class ManifestEntry:
    """One installed reference corpus as recorded in the manifest."""

    name: str
    display_name: str
    language: str
    format: str
    sha256: str
    size_bytes: int
    installed_at: str  # ISO-8601 UTC
    source_url: str
    license: str
    citation: str
    catalogue_version: str
    file_path: str  # relative to manifest dir

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)

    @classmethod
    def from_dict(cls, d: dict[str, Any]) -> "ManifestEntry":
        # Forward-compat: ignore unknown keys, require known ones.
        required = {
            "name", "display_name", "language", "format", "sha256",
            "size_bytes", "installed_at", "source_url", "license",
            "citation", "catalogue_version", "file_path",
        }
        missing = required - set(d)
        if missing:
            raise ValueError(f"Manifest entry missing keys: {missing}")
        return cls(
            name=d["name"],
            display_name=d["display_name"],
            language=d["language"],
            format=d["format"],
            sha256=d["sha256"],
            size_bytes=int(d["size_bytes"]),
            installed_at=d["installed_at"],
            source_url=d["source_url"],
            license=d["license"],
            citation=d["citation"],
            catalogue_version=d["catalogue_version"],
            file_path=d["file_path"],
        )


# --------------------------------------------------------------------------- #
# Manifest
# --------------------------------------------------------------------------- #


class ReferenceManifest:
    """JSON-backed manifest of installed reference corpora.

    The manifest is loaded lazily and rewritten atomically (write-to-tmp +
    rename) so a crash mid-write cannot corrupt it. Concurrent writers are
    NOT supported — the manifest is owned by the single engine process.
    """

    def __init__(self, manifest_dir: Path) -> None:
        self._dir = manifest_dir
        self._path = manifest_dir / MANIFEST_FILENAME
        self._entries: dict[str, ManifestEntry] = {}
        self._loaded = False

    # ------------------------------------------------------------------ #
    # Loading / saving
    # ------------------------------------------------------------------ #

    def _load(self) -> None:
        if self._loaded:
            return
        self._loaded = True
        if not self._path.exists():
            self._entries = {}
            return
        try:
            raw = json.loads(self._path.read_text(encoding="utf-8"))
        except (json.JSONDecodeError, OSError) as e:
            # A corrupt manifest is recoverable: log, ignore, and let the
            # caller decide whether to re-verify files on disk.
            log.warning("manifest_corrupt_ignoring", path=str(self._path), error=str(e))
            self._entries = {}
            return
        for entry_dict in raw.get("entries", []):
            try:
                entry = ManifestEntry.from_dict(entry_dict)
                self._entries[entry.name] = entry
            except (ValueError, TypeError) as e:
                log.warning("manifest_entry_skipped", error=str(e), entry=entry_dict)

    def _save(self) -> None:
        self._dir.mkdir(parents=True, exist_ok=True)
        payload = {
            "version": MANIFEST_VERSION,
            "entries": [e.to_dict() for e in self._entries.values()],
        }
        tmp = self._path.with_suffix(".json.tmp")
        tmp.write_text(json.dumps(payload, indent=2, ensure_ascii=False), encoding="utf-8")
        # Atomic on POSIX; on Windows, replaces target if it exists.
        tmp.replace(self._path)

    # ------------------------------------------------------------------ #
    # Public API
    # ------------------------------------------------------------------ #

    @property
    def path(self) -> Path:
        return self._path

    @property
    def dir(self) -> Path:
        return self._dir

    def list_entries(self) -> list[ManifestEntry]:
        self._load()
        return list(self._entries.values())

    def get(self, name: str) -> ManifestEntry | None:
        self._load()
        return self._entries.get(name)

    def has(self, name: str) -> bool:
        self._load()
        return name in self._entries

    def upsert(self, entry: ManifestEntry) -> None:
        self._load()
        self._entries[entry.name] = entry
        self._save()

    def remove(self, name: str) -> bool:
        self._load()
        if name not in self._entries:
            return False
        del self._entries[name]
        self._save()
        return True

    def file_path_for(self, name: str) -> Path | None:
        """Absolute path to the on-disk file for an installed reference."""
        self._load()
        entry = self._entries.get(name)
        if entry is None:
            return None
        return self._dir / entry.file_path

    @staticmethod
    def now_iso() -> str:
        """ISO-8601 UTC timestamp — exposed for tests + entry construction."""
        return datetime.now(UTC).isoformat(timespec="seconds")
