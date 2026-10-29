"""Fixed snapshot corpus: paths, hash verification, and engine corpus setup.

The snapshot is the ground truth fixture of the grounding harness. Both
``build_gold`` and ``run_grounding`` recreate the SAME corpus layout through
:func:`prepare_corpora`, so the frozen gold tool outputs remain valid across
runs. Any change to the snapshot texts (or to this layout) invalidates the
gold and must go through a full rebuild + review.
"""

from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass
from pathlib import Path
from typing import Any

_SNAPSHOT_DIR = Path(__file__).parent / "data" / "snapshot"
_MANIFEST_PATH = _SNAPSHOT_DIR / "manifest.json"

# Symbolic corpus layout shared by build_gold and run_grounding.
# symbol -> (name, language, files)
CORPUS_LAYOUT: dict[str, tuple[str, str, list[str]]] = {
    "C1": ("EN-all", "en", ["en_news.txt", "en_academic.txt", "en_learner.txt"]),
    "C2": ("EN-learner", "en", ["en_learner.txt"]),
    "C3": ("EN-press", "en", ["en_news.txt", "en_academic.txt"]),
    "C4": ("AR-all", "ar", [
        "ar_msa.txt", "ar_classical.txt", "ar_dialect.txt", "ar_nopunct.txt",
    ]),
    "C5": ("AR-parallel", "ar", ["ar_parallel.txt"]),
    "C6": ("EN-parallel", "en", ["en_parallel.txt"]),
}


class SnapshotIntegrityError(RuntimeError):
    """Raised when a snapshot file does not match its frozen manifest hash."""


@dataclass(frozen=True)
class SnapshotDoc:
    file: str
    language: str
    role: str
    text: str
    sha256: str


def load_manifest() -> dict[str, Any]:
    data: dict[str, Any] = json.loads(_MANIFEST_PATH.read_text(encoding="utf-8"))
    return data


def verify_snapshot() -> list[SnapshotDoc]:
    """Verify every snapshot file against the frozen manifest and return docs.

    Raises :class:`SnapshotIntegrityError` on any hash mismatch — the gold is
    only valid for the exact bytes it was frozen against.
    """
    manifest = load_manifest()
    docs: list[SnapshotDoc] = []
    for entry in manifest["documents"]:
        path = _SNAPSHOT_DIR / entry["file"]
        raw = path.read_bytes()
        digest = hashlib.sha256(raw).hexdigest()
        if digest != entry["sha256"]:
            raise SnapshotIntegrityError(
                f"snapshot file {entry['file']} changed since the gold was "
                f"frozen ({entry['sha256']} -> {digest}). Rebuild the gold and "
                "review the diff before scoring anything against it."
            )
        docs.append(SnapshotDoc(
            file=entry["file"],
            language=entry["language"],
            role=entry["role"],
            text=raw.decode("utf-8"),
            sha256=digest,
        ))
    return docs


def snapshot_text(file: str) -> str:
    """Return one snapshot text by file name (hash-verified)."""
    for doc in verify_snapshot():
        if doc.file == file:
            return doc.text
    raise KeyError(f"unknown snapshot file: {file}")


async def prepare_corpora(client: Any) -> dict[str, str]:
    """Create the project + corpora layout via the ASGI API and ingest texts.

    Returns the symbol -> corpus_id map (C1..C6) that build_gold freezes and
    run_grounding re-creates. ``client`` is an httpx.AsyncClient bound to the
    engine app with its lifespan active.
    """
    r = await client.post("/api/v1/projects", json={"name": "eval", "language": "en"})
    r.raise_for_status()
    pid = r.json()["id"]
    corpus_ids: dict[str, str] = {}
    docs = {d.file: d for d in verify_snapshot()}
    for symbol, (name, language, files) in CORPUS_LAYOUT.items():
        r = await client.post(
            f"/api/v1/projects/{pid}/corpora", json={"name": name, "language": language}
        )
        r.raise_for_status()
        cid = r.json()["id"]
        corpus_ids[symbol] = cid
        # multipart: one request per file keeps field construction simple
        for fname in files:
            raw = docs[fname].text.encode("utf-8")
            r = await client.post(
                f"/api/v1/corpora/{cid}/documents",
                files={"files": (fname, raw, "text/plain")},
            )
            if r.status_code >= 400:
                raise RuntimeError(
                    f"upload failed for {fname} -> {symbol}: "
                    f"HTTP {r.status_code}: {r.text[:400]}"
                )
    return corpus_ids
