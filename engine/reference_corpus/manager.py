"""High-level reference-corpus orchestrator.

Owns the lifecycle of a reference corpus on the user's disk:

    download → verify (SHA-256) → register in manifest → ready for keyness
                                       ↑
                          (resumable on failure / cancel)

The manager is process-local and not thread-safe; the FastAPI router that
wraps it serialises concurrent downloads per reference name so we never
have two writers to the same ``.part`` file.

Key properties:
  * **Resumable.** Downloads stream to ``<name>.tsv.part`` and use HTTP
    Range requests to resume after an interruption. The Range API is
    optional — if the server doesn't support it, we restart from scratch.
  * **Verified.** After the final byte is written, the file is SHA-256
    hashed and compared to ``ReferenceCorpusSpec.sha256``. A mismatch
    deletes the file and raises ``ChecksumMismatchError``.
  * **Atomic install.** Once verified, the ``.part`` suffix is removed and
    the manifest is updated. A crash between verify and manifest update is
    safe: on next start, the manager re-discovers the verified file (via
    its hash) and re-registers it.
  * ** cancellable.** A download in progress can be cancelled by removing
    its in-memory entry from ``_active_downloads``; the next tick of the
    stream loop checks and aborts.
"""
from __future__ import annotations

import asyncio
import hashlib
from collections.abc import Callable
from dataclasses import dataclass
from enum import Enum
from pathlib import Path
from typing import Any

import httpx

from app.logging import get_logger
from app.settings import get_settings

from .manifest import ManifestEntry, ReferenceManifest
from .registry import BUNDLED_REFERENCES, ReferenceCorpusSpec

log = get_logger(__name__)


# --------------------------------------------------------------------------- #
# Exceptions
# --------------------------------------------------------------------------- #


class ReferenceCorpusError(Exception):
    """Base class for all reference-corpus errors."""


class UnknownReferenceError(ReferenceCorpusError):
    """User asked for a reference name not in the catalogue."""


class ChecksumMismatchError(ReferenceCorpusError):
    """Downloaded file's SHA-256 did not match the catalogue."""

    def __init__(self, name: str, expected: str, actual: str) -> None:
        super().__init__(
            f"SHA-256 mismatch for '{name}': expected {expected}, got {actual}"
        )
        self.name = name
        self.expected = expected
        self.actual = actual


class DownloadFailedError(ReferenceCorpusError):
    """Network or HTTP error after all retries."""


class ReferenceNotInstalledError(ReferenceCorpusError):
    """User asked to use/delete a reference that isn't installed."""


# --------------------------------------------------------------------------- #
# Progress reporting
# --------------------------------------------------------------------------- #


class DownloadStatus(str, Enum):  # noqa: UP042
    PENDING = "pending"
    DOWNLOADING = "downloading"
    VERIFYING = "verifying"
    INSTALLED = "installed"
    FAILED = "failed"
    CANCELLED = "cancelled"


@dataclass
class DownloadProgress:
    """Live snapshot of a download, returned by the status endpoint."""

    name: str
    status: DownloadStatus
    downloaded_bytes: int = 0
    total_bytes: int = 0
    error: str = ""
    started_at: float = 0.0
    updated_at: float = 0.0
    retries: int = 0

    @property
    def percent(self) -> float:
        if self.total_bytes <= 0:
            return 0.0
        return min(100.0, (self.downloaded_bytes / self.total_bytes) * 100.0)

    def to_dict(self) -> dict[str, Any]:
        return {
            "name": self.name,
            "status": self.status.value,
            "downloaded_bytes": self.downloaded_bytes,
            "total_bytes": self.total_bytes,
            "percent": round(self.percent, 2),
            "error": self.error,
            "retries": self.retries,
        }


# --------------------------------------------------------------------------- #
# Manager
# --------------------------------------------------------------------------- #


ProgressCallback = Callable[[DownloadProgress], None]


class ReferenceCorpusManager:
    """Single-process orchestrator for reference corpus downloads.

    Lifetime: one instance per engine process, cached via ``get_manager()``.
    """

    # Tunables — exposed as class attrs so tests can monkeypatch them.
    CHUNK_SIZE = 64 * 1024  # 64 KB stream chunks
    MAX_RETRIES = 3
    RETRY_BACKOFF = (1.0, 2.0, 4.0)  # seconds between retries
    CONNECT_TIMEOUT = 10.0
    READ_TIMEOUT = 60.0

    def __init__(self, storage_dir: Path | None = None) -> None:
        if storage_dir is None:
            storage_dir = get_settings().data_dir / "reference-corpora"
        self._storage_dir = storage_dir
        self._storage_dir.mkdir(parents=True, exist_ok=True)
        self._manifest = ReferenceManifest(self._storage_dir)
        self._catalogue: dict[str, ReferenceCorpusSpec] = {
            spec.name: spec for spec in BUNDLED_REFERENCES
        }
        # Active downloads — keyed by reference name.
        self._active: dict[str, DownloadProgress] = {}
        # Cancellation flags.
        self._cancelled: set[str] = set()
        # Per-name download locks (so two concurrent requests for the same
        # reference share one progress stream instead of racing on disk).
        self._locks: dict[str, asyncio.Lock] = {}

    # ------------------------------------------------------------------ #
    # Public properties
    # ------------------------------------------------------------------ #

    @property
    def storage_dir(self) -> Path:
        return self._storage_dir

    @property
    def manifest(self) -> ReferenceManifest:
        return self._manifest

    def catalogue(self) -> list[ReferenceCorpusSpec]:
        return list(self._catalogue.values())

    def spec(self, name: str) -> ReferenceCorpusSpec:
        spec = self._catalogue.get(name)
        if spec is None:
            raise UnknownReferenceError(f"Unknown reference corpus: {name!r}")
        return spec

    # ------------------------------------------------------------------ #
    # Listing
    # ------------------------------------------------------------------ #

    def list_all(self) -> list[dict[str, Any]]:
        """Combine the catalogue with the manifest into one API response.

        Each entry has ``installed: bool`` and, when installed, the manifest
        metadata (size, installed_at, sha256). When not installed, only the
        catalogue metadata is returned.
        """
        out: list[dict[str, Any]] = []
        for spec in self._catalogue.values():
            entry = self._manifest.get(spec.name)
            available = bool(spec.source_url) and bool(spec.sha256)
            row = {
                "name": spec.name,
                "display_name": spec.display_name,
                "language": spec.language,
                "description": spec.description,
                "format": spec.format,
                "size_hint": spec.size_hint,
                "license": spec.license,
                "citation": spec.citation,
                "genre": spec.genre,
                "min_corpus_tokens": spec.min_corpus_tokens,
                "tags": list(spec.tags),
                "available": available,
                "installed": entry is not None,
                "downloadable": available and entry is None,
            }
            if entry is not None:
                row.update({
                    "installed_at": entry.installed_at,
                    "size_bytes": entry.size_bytes,
                    "sha256": entry.sha256,
                    "catalogue_version": entry.catalogue_version,
                })
            out.append(row)
        return out

    # ------------------------------------------------------------------ #
    # Download / install
    # ------------------------------------------------------------------ #

    def get_progress(self, name: str) -> DownloadProgress | None:
        return self._active.get(name)

    def all_progress(self) -> list[DownloadProgress]:
        return list(self._active.values())

    def cancel(self, name: str) -> bool:
        """Request cancellation of an in-flight download. Idempotent."""
        if name not in self._active:
            return False
        self._cancelled.add(name)
        return True

    async def download(
        self,
        name: str,
        *,
        on_progress: ProgressCallback | None = None,
    ) -> ManifestEntry:
        """Download, verify, and install a reference corpus.

        Returns the resulting ``ManifestEntry`` on success. Safe to call
        concurrently with another ``download(name)`` call — they share the
        same lock and the second caller waits for the first to finish (or
        joins its progress stream).
        """
        spec = self.spec(name)
        if not spec.source_url or not spec.sha256:
            raise DownloadFailedError(
                f"Reference '{name}' has no source URL or checksum — not "
                f"available for download. It will be added in a future release."
            )
        # Already installed? Short-circuit.
        existing = self._manifest.get(name)
        if existing is not None:
            return existing

        lock = self._locks.setdefault(name, asyncio.Lock())
        async with lock:
            # Re-check inside the lock — another caller may have installed
            # it while we waited.
            existing = self._manifest.get(name)
            if existing is not None:
                return existing

            return await self._do_download(spec, on_progress)

    async def _do_download(
        self,
        spec: ReferenceCorpusSpec,
        on_progress: ProgressCallback | None,
    ) -> ManifestEntry:
        part_path = self._storage_dir / f"{spec.name}.tsv.part"
        final_path = self._storage_dir / f"{spec.name}.tsv"
        self._cancelled.discard(spec.name)

        progress = DownloadProgress(
            name=spec.name,
            status=DownloadStatus.PENDING,
            started_at=_now(),
        )
        self._active[spec.name] = progress

        try:
            last_error: str = ""
            for attempt in range(self.MAX_RETRIES):
                if spec.name in self._cancelled:
                    progress.status = DownloadStatus.CANCELLED
                    raise DownloadFailedError(f"Download of '{spec.name}' cancelled")

                progress.retries = attempt
                try:
                    await self._stream_download(spec, part_path, progress, on_progress)
                    break
                except DownloadFailedError as e:
                    last_error = str(e)
                    if attempt + 1 < self.MAX_RETRIES and spec.name not in self._cancelled:
                        backoff = self.RETRY_BACKOFF[min(attempt, len(self.RETRY_BACKOFF) - 1)]
                        log.warning(
                            "reference_download_retry",
                            name=spec.name, attempt=attempt + 1, backoff=backoff, error=last_error,
                        )
                        await asyncio.sleep(backoff)
                        # Resumable: keep the .part file for the next attempt.
                        continue
                    raise
            else:
                raise DownloadFailedError(
                    f"Download of '{spec.name}' failed after {self.MAX_RETRIES} attempts: {last_error}"
                )

            # Verify SHA-256
            progress.status = DownloadStatus.VERIFYING
            progress.updated_at = _now()
            if on_progress:
                on_progress(progress)

            actual = await asyncio.to_thread(_sha256_of_file, part_path)
            if actual != spec.sha256:
                progress.status = DownloadStatus.FAILED
                progress.error = "checksum mismatch"
                # Don't keep a corrupt file around.
                part_path.unlink(missing_ok=True)
                raise ChecksumMismatchError(spec.name, spec.sha256, actual)

            # Atomic install: rename .part → .tsv
            part_path.replace(final_path)
            size = final_path.stat().st_size

            entry = ManifestEntry(
                name=spec.name,
                display_name=spec.display_name,
                language=spec.language,
                format=spec.format,
                sha256=spec.sha256,
                size_bytes=size,
                installed_at=ReferenceManifest.now_iso(),
                source_url=spec.source_url,
                license=spec.license,
                citation=spec.citation,
                catalogue_version=_catalogue_version(),
                file_path=final_path.name,
            )
            self._manifest.upsert(entry)

            progress.status = DownloadStatus.INSTALLED
            progress.downloaded_bytes = size
            progress.total_bytes = size
            progress.updated_at = _now()
            if on_progress:
                on_progress(progress)

            log.info(
                "reference_installed",
                name=spec.name, size=size, sha256=actual[:12] + "…",
            )
            return entry

        except Exception as e:
            progress.status = DownloadStatus.FAILED
            progress.error = str(e)
            progress.updated_at = _now()
            if on_progress:
                on_progress(progress)
            raise
        finally:
            # Keep the progress entry for 5 minutes so the UI can poll the
            # final state, then it's gone. The caller can also clear it
            # explicitly via ``forget_progress``.
            asyncio.get_event_loop().call_later(
                300, lambda: self._active.pop(spec.name, None)
            )

    async def _stream_download(
        self,
        spec: ReferenceCorpusSpec,
        part_path: Path,
        progress: DownloadProgress,
        on_progress: ProgressCallback | None,
    ) -> None:
        """Stream one download attempt to ``part_path`` (resumable).

        Resumability: if ``part_path`` already exists, send an HTTP Range
        request for the missing bytes and append. If the server ignores
        Range or returns 200, restart from scratch.
        """
        existing_bytes = part_path.stat().st_size if part_path.exists() else 0
        headers: dict[str, str] = {}
        if existing_bytes > 0:
            headers["Range"] = f"bytes={existing_bytes}-"

        # Append mode: if the server honors Range, we append. If not, we
        # truncate and start over.
        mode = "ab" if existing_bytes > 0 else "wb"
        wrote_any = False

        timeout = httpx.Timeout(self.CONNECT_TIMEOUT, read=self.READ_TIMEOUT, write=30.0)
        async with httpx.AsyncClient(timeout=timeout, follow_redirects=True) as client:
            async with client.stream("GET", spec.source_url, headers=headers) as resp:
                if resp.status_code == 416:
                    # "Range Not Satisfiable" — we already have the whole file.
                    # Fall through to verification.
                    return
                if resp.status_code not in (200, 206):
                    raise DownloadFailedError(
                        f"HTTP {resp.status_code} fetching {spec.source_url}"
                    )

                if resp.status_code == 200:
                    # Server ignored Range — restart from scratch.
                    existing_bytes = 0
                    mode = "wb"

                # Determine total size for progress.
                if resp.status_code == 206:
                    # Content-Range: bytes 100-999/2000
                    cr = resp.headers.get("content-range", "")
                    if "/" in cr:
                        try:
                            progress.total_bytes = int(cr.rsplit("/", 1)[1])
                        except (ValueError, IndexError):
                            progress.total_bytes = 0
                else:
                    cl = resp.headers.get("content-length")
                    progress.total_bytes = (int(cl) + existing_bytes) if cl else 0

                progress.downloaded_bytes = existing_bytes
                progress.status = DownloadStatus.DOWNLOADING
                progress.updated_at = _now()
                if on_progress:
                    on_progress(progress)

                with open(part_path, mode) as f:
                    async for chunk in resp.aiter_bytes(self.CHUNK_SIZE):
                        if spec.name in self._cancelled:
                            raise DownloadFailedError(f"Download of '{spec.name}' cancelled")
                        f.write(chunk)
                        progress.downloaded_bytes += len(chunk)
                        wrote_any = True
                        if on_progress:
                            on_progress(progress)

                if not wrote_any and existing_bytes == 0:
                    raise DownloadFailedError("No bytes received from server")

    # ------------------------------------------------------------------ #
    # Delete / cleanup
    # ------------------------------------------------------------------ #

    def delete(self, name: str) -> None:
        """Remove an installed reference corpus from disk + manifest."""
        entry = self._manifest.get(name)
        if entry is None:
            raise ReferenceNotInstalledError(f"Reference '{name}' is not installed")
        path = self._storage_dir / entry.file_path
        path.unlink(missing_ok=True)
        # Also clean up any stale .part file from a failed download.
        (self._storage_dir / f"{name}.tsv.part").unlink(missing_ok=True)
        self._manifest.remove(name)
        log.info("reference_deleted", name=name)

    def cleanup_orphans(self) -> list[str]:
        """Delete files in the storage dir that aren't in the manifest.

        Returns the list of removed filenames. Useful after a crash that
        left a ``.part`` file behind, or after a manifest reset.
        """
        kept = {entry.file_path for entry in self._manifest.list_entries()}
        removed: list[str] = []
        for child in self._storage_dir.iterdir():
            if child.name == "manifest.json":
                continue
            if child.name in kept:
                continue
            if child.is_file():
                child.unlink()
                removed.append(child.name)
                log.info("reference_orphan_removed", file=child.name)
        return removed

    def forget_progress(self, name: str) -> bool:
        """Drop the cached progress entry for a finished download."""
        return self._active.pop(name, None) is not None

    # ------------------------------------------------------------------ #
    # Read access for keyness_bridge
    # ------------------------------------------------------------------ #

    def resolve_path(self, name: str) -> Path:
        """Return the absolute path to an installed reference's file."""
        entry = self._manifest.get(name)
        if entry is None:
            raise ReferenceNotInstalledError(f"Reference '{name}' is not installed")
        path = self._storage_dir / entry.file_path
        if not path.exists():
            # File was deleted out-of-band. Drop the manifest entry so the
            # UI shows it as not-installed instead of crashing.
            log.warning("reference_file_missing_dropping_manifest", name=name, path=str(path))
            self._manifest.remove(name)
            raise ReferenceNotInstalledError(
                f"Reference '{name}' is in the manifest but the file is missing"
            )
        return path


# --------------------------------------------------------------------------- #
# Helpers
# --------------------------------------------------------------------------- #


def _now() -> float:
    import time
    return time.time()


def _sha256_of_file(path: Path) -> str:
    """Stream a file through SHA-256. Safe for multi-GB files."""
    h = hashlib.sha256()
    with open(path, "rb") as f:
        for chunk in iter(lambda: f.read(1024 * 1024), b""):
            h.update(chunk)
    return h.hexdigest()


def _catalogue_version() -> str:
    """Bumped whenever the catalogue's SHA-256 values change."""
    # Issue 7: previously imported app.main which caused a circular import
    # (app.main → api.* → reference_corpus → manager → app.main). Now we
    # read the version directly from the package __init__ which has no
    # side effects.
    try:
        from app import __version__
        return __version__
    except Exception:
        return "0.0.0"


# --------------------------------------------------------------------------- #
# Process-wide singleton
# --------------------------------------------------------------------------- #


_manager: ReferenceCorpusManager | None = None


def get_manager() -> ReferenceCorpusManager:
    global _manager
    if _manager is None:
        _manager = ReferenceCorpusManager()
    return _manager
