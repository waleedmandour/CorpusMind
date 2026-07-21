"""Reference corpus subsystem — Issue 1.

Provides a robust download + persistence layer for bundled reference corpora
(frequency lists and full corpora) so that keyness analysis works consistently
across application restarts. The subsystem has four cooperating modules:

  - ``registry``      — declarative catalogue of all known bundled references
                        (name, language, source URL, SHA-256, format, license).
  - ``manifest``      — on-disk JSON manifest of what is currently installed,
                        with version + checksum + size + installed-at metadata.
  - ``manager``       — high-level orchestrator: download (resumable, retrying,
                        SHA-256-verified), delete, list, get-frequency-list.
  - ``keyness_bridge``— adapts a reference frequency list so it can be used
                        by ``stats.service.compute_keyness`` without requiring
                        a full ``Corpus`` row in the database.

Design principles (per the project's local-first + reproducibility pillars):
  * All files live under ``Settings.data_dir / "reference-corpora"`` so they
    survive app upgrades and are easy to back up.
  * SHA-256 verification is mandatory — a corrupted or truncated download is
    deleted and the user sees a clear error.
  * Resumable downloads use HTTP Range requests; partial files are kept under
    a ``.part`` suffix and resumed on the next attempt.
  * The manifest is the single source of truth for "what is installed". The
    API never trusts the filesystem alone.
"""
from __future__ import annotations

from .keyness_bridge import (
    compute_keyness_with_reference_list,
    invalidate_cache,
    load_frequency_list,
)
from .manager import (
    DownloadProgress,
    DownloadStatus,
    ReferenceCorpusManager,
    get_manager,
)
from .manifest import ManifestEntry, ReferenceManifest
from .registry import BUNDLED_REFERENCES, ReferenceCorpusSpec

__all__ = [
    "BUNDLED_REFERENCES",
    "DownloadProgress",
    "DownloadStatus",
    "ManifestEntry",
    "ReferenceCorpusManager",
    "ReferenceCorpusSpec",
    "ReferenceManifest",
    "compute_keyness_with_reference_list",
    "get_manager",
    "invalidate_cache",
    "load_frequency_list",
]
