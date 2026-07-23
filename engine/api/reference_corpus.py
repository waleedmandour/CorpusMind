"""Reference corpus API endpoints — Issue 1.

Exposes the reference-corpus subsystem over HTTP so the frontend can:

  * list available + installed references
  * download a reference (with progress polling)
  * cancel an in-flight download
  * delete an installed reference
  * run keyness directly against an installed reference frequency list
    (without requiring the user to also upload a full reference Corpus)
  * run orphan cleanup

All endpoints are prefixed with ``/api/v1/reference-corpora``.
"""
from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field
from sqlalchemy.ext.asyncio import AsyncSession

from app.logging import get_logger
from reference_corpus import (
    get_manager,
)
from reference_corpus.keyness_bridge import compute_keyness_with_reference_list
from reference_corpus.manager import (
    ChecksumMismatchError,
    DownloadFailedError,
    ReferenceCorpusError,
    ReferenceNotInstalledError,
    UnknownReferenceError,
)
from storage.models import Corpus
from storage.session import get_session

log = get_logger(__name__)
router = APIRouter()


# --------------------------------------------------------------------------- #
# Response models
# --------------------------------------------------------------------------- #


class ReferenceListResponse(BaseModel):
    references: list[dict]


class ReferenceDownloadResponse(BaseModel):
    name: str
    status: str
    installed: bool
    message: str = ""


class KeynessWithReferenceRequest(BaseModel):
    reference_name: str = Field(..., description="Name of an installed reference corpus")
    min_freq: int = Field(5, ge=1)
    measures: list[str] | None = None
    limit: int = Field(500, ge=1, le=5000)


# --------------------------------------------------------------------------- #
# Listing + status
# --------------------------------------------------------------------------- #


@router.get("/reference-corpora")
async def list_references() -> ReferenceListResponse:
    """List all catalogue entries with their install status."""
    mgr = get_manager()
    return ReferenceListResponse(references=mgr.list_all())


@router.get("/reference-corpora/{name}/status")
async def reference_status(name: str) -> dict:
    """Get the current download/install status of a single reference.

    Useful for polling a long-running download from the UI.
    """
    mgr = get_manager()
    try:
        spec = mgr.spec(name)
    except UnknownReferenceError as e:
        raise HTTPException(404, str(e)) from e

    entry = mgr.manifest.get(name)
    progress = mgr.get_progress(name)
    return {
        "name": name,
        "display_name": spec.display_name,
        "installed": entry is not None,
        "progress": progress.to_dict() if progress else None,
        **({"installed_at": entry.installed_at, "size_bytes": entry.size_bytes} if entry else {}),
    }


# --------------------------------------------------------------------------- #
# Download / cancel / delete
# --------------------------------------------------------------------------- #


@router.post("/reference-corpora/{name}/download")
async def download_reference(name: str) -> ReferenceDownloadResponse:
    """Download, verify (SHA-256), and install a reference corpus.

    Returns once the install is complete. For large references, the UI
    should poll ``GET /reference-corpora/{name}/status`` while this is
    in flight (or call this endpoint from a background task and rely on
    the per-name lock to dedupe concurrent requests).
    """
    mgr = get_manager()
    try:
        entry = await mgr.download(name)
        return ReferenceDownloadResponse(
            name=name, status="installed", installed=True,
            message=f"Installed {entry.display_name} ({entry.size_bytes} bytes)",
        )
    except ChecksumMismatchError as e:
        raise HTTPException(422, str(e)) from e
    except DownloadFailedError as e:
        raise HTTPException(502, str(e)) from e
    except ReferenceCorpusError as e:
        raise HTTPException(400, str(e)) from e


@router.post("/reference-corpora/{name}/cancel")
async def cancel_download(name: str) -> dict:
    """Request cancellation of an in-flight download. Idempotent."""
    mgr = get_manager()
    cancelled = mgr.cancel(name)
    return {"name": name, "cancel_requested": cancelled}


@router.delete("/reference-corpora/{name}")
async def delete_reference(name: str) -> dict:
    """Delete an installed reference corpus from disk + manifest."""
    mgr = get_manager()
    try:
        mgr.delete(name)
        return {"name": name, "deleted": True}
    except ReferenceNotInstalledError as e:
        raise HTTPException(404, str(e)) from e


@router.post("/reference-corpora/cleanup-orphans")
async def cleanup_orphans() -> dict:
    """Delete files in the storage dir that aren't in the manifest."""
    mgr = get_manager()
    removed = mgr.cleanup_orphans()
    return {"removed": removed, "count": len(removed)}


# --------------------------------------------------------------------------- #
# Keyness against a reference frequency list
# --------------------------------------------------------------------------- #


@router.post("/corpora/{cid}/keyness-with-reference/{ref_name}")
async def keyness_with_reference(
    cid: str,
    ref_name: str,
    body: KeynessWithReferenceRequest,
    session: AsyncSession = Depends(get_session),
) -> dict:
    """Run keyness against a bundled reference frequency list.

    This bypasses the requirement for a full Corpus row as the reference.
    The reference's per-word frequencies are loaded from disk (cached
    per-process); the target corpus's frequencies are computed live from
    the database.

    Returns the same shape as ``POST /corpora/{cid}/keyness`` so the UI
    can swap between the two endpoints transparently.
    """
    if not await session.get(Corpus, cid):
        raise HTTPException(404, "Target corpus not found")

    mgr = get_manager()
    if not mgr.manifest.has(ref_name):
        raise HTTPException(
            404,
            f"Reference '{ref_name}' is not installed. "
            f"POST /reference-corpora/{ref_name}/download first.",
        )

    # Validate language compatibility.
    spec = mgr.spec(ref_name)
    target = await session.get(Corpus, cid)
    if target.language and spec.language and target.language != spec.language:
        raise HTTPException(
            422,
            f"Language mismatch: target corpus is '{target.language}' but "
            f"reference '{ref_name}' is '{spec.language}'. Keyness across "
            f"languages is not meaningful.",
        )

    try:
        r = await compute_keyness_with_reference_list(
            session, cid, ref_name,
            min_freq=body.min_freq, measures=body.measures, limit=body.limit,
        )
    except FileNotFoundError as e:
        raise HTTPException(404, str(e)) from e
    except Exception as e:
        log.error("keyness_with_reference_failed", cid=cid, ref=ref_name, error=str(e))
        raise HTTPException(500, f"Keyness computation failed: {e}") from e

    return {
        "target_corpus_id": r.target_corpus_id,
        "reference_name": ref_name,
        "reference_corpus_id": r.reference_corpus_id,
        "measures": r.measures,
        "positive_keywords": r.positive_keywords,
        "negative_keywords": r.negative_keywords,
        "N1": r.N1,
        "N2": r.N2,
    }
