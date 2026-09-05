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

import asyncio
import os
import tarfile
import tempfile
import time
import zipfile
from pathlib import Path, PurePosixPath

import httpx
from fastapi import APIRouter, Depends, File, HTTPException, UploadFile
from pydantic import BaseModel, Field
from sqlalchemy.ext.asyncio import AsyncSession

from app.logging import get_logger
from app.settings import get_settings
from ingestion.service import ingest_document
from reference_corpus import get_manager
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
            name=name,
            status="installed",
            installed=True,
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
            session,
            cid,
            ref_name,
            min_freq=body.min_freq,
            measures=body.measures,
            limit=body.limit,
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


# --------------------------------------------------------------------------- #
# Full reference corpus download → extract → ingest
#
# v1.2.0 rewrite (user-reported OTA 504):
#   The Oxford Text Archive gateway routinely fails large bitstream requests
#   (HTTP 504 / hang) — reproduced for both BAWE (108 MB) and BNC Baby
#   (22 MB). The old pipeline downloaded the ENTIRE archive into RAM in a
#   single GET with no retries and no fallback, so any OTA hiccup failed the
#   whole job with a raw httpx error string. The new pipeline:
#
#     1. Tries every URL in ``spec.source_urls`` (mirror fallback) in order.
#     2. Per URL: streams to disk in 64 KB chunks with HTTP Range resume,
#        retrying with backoff on transient failures.
#     3. Reports REAL byte-level progress (0-49%) in the job status.
#     4. Supports cancellation (POST .../download-full/cancel).
#     5. Fails with an actionable message; the user can always download the
#        archive manually in a browser and install it offline via
#        POST .../import-archive (works even when every remote URL fails).
# --------------------------------------------------------------------------- #

# Job registry (Fix #11) + strong task references (Fix #12)
_full_corpus_jobs: dict[str, dict] = {}
_full_corpus_tasks: set = set()
# Names for which the user requested cancellation (download-full path).
_full_corpus_cancels: set[str] = set()

# Download tuning. Module-level so tests can shrink the backoff.
DOWNLOAD_ATTEMPTS_PER_URL = 2
DOWNLOAD_RETRY_BACKOFF_S = (2.0, 4.0)
DOWNLOAD_CHUNK_SIZE = 64 * 1024
DOWNLOAD_CONNECT_TIMEOUT_S = 15.0
DOWNLOAD_READ_TIMEOUT_S = 240.0
DOWNLOAD_DEADLINE_S = 12 * 60.0  # overall cap across all URLs and attempts
MAX_IMPORT_BYTES = 400 * 1024 * 1024  # safety cap for offline imports

# Statuses that mean a job is still running.
_ACTIVE_STATUSES = ("downloading", "extracting", "ingesting")


class _DownloadCancelledError(Exception):
    """Raised internally when the user cancels a full-corpus download."""


class _NonArchiveContentError(Exception):
    """The source returned 200 with non-archive bytes (HTML error page,
    login page, …). Not retryable — the response would be identical."""


def _set_job(job_id: str, **fields) -> None:
    """Update a job dict in one call (keeps status transitions readable)."""
    _full_corpus_jobs[job_id].update(fields)


def _archive_dir() -> Path:
    d = get_settings().data_dir / "reference-corpora" / "_archives"
    d.mkdir(parents=True, exist_ok=True)
    return d


def _sniff_archive(path: Path) -> str:
    """Detect archive type by magic bytes → ``'zip'`` | ``'gzip'`` | ``'unknown'``.

    Fix #12 (v0.1.25): detection is by CONTENT, not URL suffix — the OTA
    hosts archives at URLs ending in ``isAllowed=y``, so
    ``endswith('.zip')`` never matched.
    """
    with open(path, "rb") as fh:
        magic = fh.read(2)
    if magic == b"PK":
        return "zip"
    if magic == b"\x1f\x8b":
        return "gzip"
    return "unknown"


async def _download_archive(name: str, spec, job_id: str) -> tuple[Path, list[str]]:
    """Download the archive for ``spec`` to disk, trying every source URL.

    Returns ``(archive_path, tried_urls)``. Raises ``RuntimeError`` with an
    actionable message once every source is exhausted. Partial downloads are
    kept in a ``.part`` file and resumed (HTTP Range) on the next attempt,
    so a flaky source costs bandwidth only once.
    """
    urls = (
        list(spec.source_urls)
        if spec.source_urls
        else ([spec.source_url] if spec.source_url else [])
    )
    if not urls:
        raise RuntimeError(f"Reference '{name}' has no download URL.")

    part_path = _archive_dir() / f"{name}.part"
    deadline = time.monotonic() + DOWNLOAD_DEADLINE_S
    tried: list[str] = []
    errors: list[str] = []

    async with httpx.AsyncClient(
        timeout=httpx.Timeout(DOWNLOAD_READ_TIMEOUT_S, connect=DOWNLOAD_CONNECT_TIMEOUT_S),
        follow_redirects=True,
    ) as client:
        for url_index, url in enumerate(urls, start=1):
            for attempt in range(DOWNLOAD_ATTEMPTS_PER_URL):
                if name in _full_corpus_cancels:
                    raise _DownloadCancelledError(name)
                if time.monotonic() > deadline:
                    break  # deadline hit — no point starting another attempt
                tried.append(url)
                existing = part_path.stat().st_size if part_path.exists() else 0
                headers = {"Range": f"bytes={existing}-"} if existing > 0 else {}
                label = (
                    f"Downloading {name} "
                    f"(source {url_index}/{len(urls)}, "
                    f"attempt {attempt + 1}/{DOWNLOAD_ATTEMPTS_PER_URL})"
                    f"{' — resuming' if existing > 0 else ''}"
                )
                _set_job(job_id, status="downloading", message=label + "…")
                try:
                    async with client.stream("GET", url, headers=headers) as resp:
                        if resp.status_code == 416:
                            # Range not satisfiable → the .part file already
                            # holds the complete bytes (same convention as
                            # reference_corpus.manager).
                            pass
                        elif resp.status_code >= 400:
                            raise RuntimeError(f"HTTP {resp.status_code} fetching {url}")
                        else:
                            resume = resp.status_code == 206 and existing > 0
                            done = existing if resume else 0
                            total = None
                            cl = resp.headers.get("content-length")
                            if cl is not None and cl.isdigit():
                                total = int(cl) + (existing if resume else 0)
                            with open(part_path, "ab" if resume else "wb") as fh:
                                async for chunk in resp.aiter_bytes():
                                    if name in _full_corpus_cancels:
                                        raise _DownloadCancelledError(name)
                                    fh.write(chunk)
                                    done += len(chunk)
                                    if total:
                                        _set_job(
                                            job_id,
                                            progress=min(int(50 * done / total), 49),
                                            message=(
                                                f"Downloading {name}: "
                                                f"{done // (1024 * 1024)} MB / "
                                                f"{max(total // (1024 * 1024), 1)} MB"
                                            ),
                                        )
                                    else:
                                        _set_job(
                                            job_id,
                                            message=f"Downloading {name}: {done // 1024} KB…",
                                        )
                    fmt = _sniff_archive(part_path)
                    if fmt == "unknown":
                        part_path.unlink(missing_ok=True)
                        raise _NonArchiveContentError(
                            "The server returned a non-archive response "
                            "(expected ZIP or tar.gz magic bytes, got "
                            f"{url})."
                        )
                    final_path = part_path.with_suffix(".zip" if fmt == "zip" else ".tar.gz")
                    part_path.replace(final_path)
                    return final_path, tried
                except (_DownloadCancelledError, _NonArchiveContentError):
                    raise
                except Exception as e:
                    # transient error must never kill the whole job.
                    errors.append(f"{url} → {e}")
                    log.warning(
                        "download_full_attempt_failed",
                        name=name,
                        url=url,
                        attempt=attempt + 1,
                        error=str(e),
                    )
                    if attempt < DOWNLOAD_ATTEMPTS_PER_URL - 1:
                        await asyncio.sleep(
                            DOWNLOAD_RETRY_BACKOFF_S[
                                min(attempt, len(DOWNLOAD_RETRY_BACKOFF_S) - 1)
                            ]
                        )

    if part_path.exists():
        log.info("download_full_partial_kept", name=name, bytes=part_path.stat().st_size)
    raise RuntimeError(
        "All download sources failed ("
        + "; ".join(errors[-4:])
        + f"). The source server may be down or overloaded — try again "
        f"later, or download the archive manually in your browser and "
        f"install it via 'Import archive' "
        f"(POST /reference-corpora/{name}/import-archive)."
    )


def _validate_zip_members(zf: zipfile.ZipFile, dest: str) -> None:
    """Issue 9 fix: reject zip members that would extract outside `dest`.

    Mirrors the guarantees of tarfile's filter="data" for the zip branch:
    rejects absolute paths, ".." traversal components, and (on extraction)
    symlinks cannot occur in zf.namelist form but path escape can.
    """
    dest_abs = Path(dest).resolve()
    for name in zf.namelist():
        p = PurePosixPath(name)
        if p.is_absolute() or ".." in p.parts:
            raise ValueError(f"Unsafe archive member path: {name!r}")
        target = (Path(dest) / name).resolve()
        if not target.is_relative_to(dest_abs):
            raise ValueError(f"Unsafe archive member path escapes destination: {name!r}")


def _extract_text_files(archive_path: Path, spec, job_id: str) -> list[tuple[str, bytes, dict]]:
    """Extract text documents from a downloaded/uploaded archive.

    ZIP branch (BNC Baby, BAWE, mirror ZIPs): every ``.txt``/``.xml`` file
    becomes a document; XML is parsed with BeautifulSoup restricted to
    ``<text>``. tar.gz branch (Leipzig): ``*-sentences.txt`` TSVs become one
    document per sentence.
    """
    text_files: list[tuple[str, bytes, dict]] = []
    fmt = _sniff_archive(archive_path)

    _set_job(job_id, status="extracting", progress=50, message="Extracting archive…")

    if fmt == "gzip":
        with tempfile.TemporaryDirectory() as tmpdir:
            with tarfile.open(archive_path, mode="r:gz") as tar:
                # Issue 9 fix: "data" filter (Python 3.12+) rejects absolute
                # paths, ".." traversal, symlinks and device files.
                tar.extractall(tmpdir, filter="data")
            for root, _d, files in os.walk(tmpdir):
                for fname in files:
                    if fname.endswith("-sentences.txt"):
                        filepath = os.path.join(root, fname)
                        with open(filepath, encoding="utf-8") as f:
                            for line_num, line in enumerate(f):
                                parts = line.strip().split("\t")
                                if len(parts) >= 2:
                                    text_files.append(
                                        (
                                            f"{fname}_{line_num}.txt",
                                            parts[1].encode("utf-8"),
                                            {"source": "leipzig", "genre": spec.genre},
                                        )
                                    )
                        break
    elif fmt == "zip":
        with tempfile.TemporaryDirectory() as tmpdir:
            with zipfile.ZipFile(archive_path) as zf:
                # Issue 9 fix: validate every member path before extraction —
                # zipfile has no built-in "data" filter.
                _validate_zip_members(zf, tmpdir)
                zf.extractall(tmpdir)
            for root, _d, files in os.walk(tmpdir):
                dir_name = os.path.basename(root) if root != tmpdir else ""
                genre = ""
                if dir_name.lower() in ("aca", "academic"):
                    genre = "academic"
                elif dir_name.lower() in ("fic", "fiction"):
                    genre = "fiction"
                elif dir_name.lower() in ("news", "newspaper"):
                    genre = "news"
                elif dir_name.lower() in ("dem", "spoken", "conv"):
                    genre = "spoken"
                for fname in sorted(files):
                    if fname.endswith((".txt", ".xml")):
                        filepath = os.path.join(root, fname)
                        try:
                            with open(filepath, encoding="utf-8", errors="replace") as f:
                                content = f.read()
                            if fname.endswith(".xml"):
                                from bs4 import BeautifulSoup

                                soup = BeautifulSoup(content, "xml")
                                # Restrict to <text> so <teiHeader>
                                # bibliographic metadata isn't pulled into
                                # the body. get_text() walks nested tags
                                # correctly and visits each leaf text node
                                # exactly once, in document order (Fix #13).
                                # NOTE: named xml_root, NOT root — the outer
                                # os.walk() loop above already uses `root`
                                # for the current directory path.
                                xml_root = soup.find("text") or soup
                                content = xml_root.get_text(separator=" ")
                                # BNC <w>/<c> tags are tightly packed with
                                # irregular whitespace; collapse runs of
                                # whitespace to single spaces.
                                content = " ".join(content.split())
                            if content.strip():
                                text_files.append(
                                    (
                                        fname,
                                        content.encode("utf-8"),
                                        {"source": spec.name, "genre": genre or spec.genre},
                                    )
                                )
                        except Exception as e:
                            log.warning("extract_file_failed", file=fname, error=str(e))
    else:
        raise _NonArchiveContentError(
            f"Archive {archive_path.name} is neither a valid ZIP (expected "
            f"magic bytes b'PK') nor a valid tar.gz (expected magic bytes "
            f"b'\\x1f\\x8b'). Got {_sniff_archive(archive_path)!r}."
        )
    return text_files


async def _ingest_and_install(
    name: str, spec, text_files: list[tuple[str, bytes, dict]], job_id: str
) -> None:
    """Create the Corpus row and ingest extracted documents (shared by the
    download and offline-import paths)."""
    from storage.models import Corpus as CorpusModel
    from storage.models import Project
    from storage.session import session_scope

    _set_job(
        job_id,
        status="ingesting",
        progress=60,
        message=f"Ingesting {len(text_files)} documents…",
    )

    async with session_scope() as session:
        from sqlalchemy import select as sa_select

        stmt = sa_select(Project).where(Project.name == "Reference Corpora")
        project = (await session.execute(stmt)).scalar_one_or_none()
        if project is None:
            project = Project(name="Reference Corpora")
            session.add(project)
            await session.flush()

        stmt = sa_select(CorpusModel).where(
            CorpusModel.project_id == project.id,
            CorpusModel.name == spec.display_name,
        )
        existing = (await session.execute(stmt)).scalar_one_or_none()
        if existing is not None:
            _set_job(
                job_id,
                status="installed",
                progress=100,
                corpus_id=existing.id,
                message="Already installed.",
            )
            return

        corpus = CorpusModel(
            project_id=project.id,
            name=spec.display_name,
            language=spec.language,
            genre=spec.genre,
        )
        session.add(corpus)
        await session.flush()

        # v1.2.0: cap is a registry field now (was a hardcoded 500).
        cap = max(1, int(getattr(spec, "max_files", 500)))
        total = min(len(text_files), cap)
        ingested = 0
        for filename, content, meta in text_files[:cap]:
            try:
                await ingest_document(
                    session,
                    corpus,
                    filename,
                    content,
                    metadata=meta,
                    language=spec.language,
                )
                ingested += 1
                if ingested % 10 == 0 or ingested == total:
                    _set_job(
                        job_id,
                        progress=60 + int(39 * ingested / max(total, 1)),
                        message=f"Ingesting {ingested}/{total}…",
                    )
            except Exception as e:
                log.warning("ingest_reference_doc_failed", file=filename, error=str(e))

        new_stats = dict(corpus.stats or {})
        new_stats.update(
            {
                "document_count": ingested,
                "reference_name": name,
                "reference_license": spec.license,
            }
        )
        corpus.stats = new_stats
        await session.commit()

        _set_job(
            job_id,
            status="installed",
            progress=100,
            corpus_id=corpus.id,
            document_count=ingested,
            message=f"Installed {ingested} documents.",
        )
        log.info(
            "download_full_reference_complete",
            name=name,
            corpus_id=corpus.id,
            ingested=ingested,
        )


async def _process_full_reference(name: str, spec, job_id: str) -> None:
    """Background task: download → extract → ingest."""
    try:
        archive_path, _tried = await _download_archive(name, spec, job_id)
        try:
            text_files = await asyncio.to_thread(_extract_text_files, archive_path, spec, job_id)
        finally:
            # The archive is no longer needed once extraction has been
            # attempted — remove it to avoid doubling disk usage.
            archive_path.unlink(missing_ok=True)
        if not text_files:
            _set_job(
                job_id,
                status="failed",
                message=(
                    "Archive extracted successfully but contained no .txt or .xml files to ingest."
                ),
            )
            return
        await _ingest_and_install(name, spec, text_files, job_id)
    except _DownloadCancelledError:
        _full_corpus_cancels.discard(name)
        _set_job(job_id, status="failed", message="Download cancelled.")
        log.info("download_full_reference_cancelled", name=name)
    except Exception as e:
        _set_job(job_id, status="failed", message=str(e))
        log.error("download_full_reference_failed", name=name, error=str(e))


@router.post("/reference-corpora/{name}/download-full")
async def download_full_reference(name: str) -> dict:
    """Download a full reference corpus (ZIP/tar.gz), extract text files,
    create a Corpus row, and ingest through the full NLP pipeline.

    v1.2.0: robust download pipeline — tries every source URL in
    ``spec.source_urls`` (mirror fallback) with per-URL retries, backoff and
    HTTP Range resume, streams to disk (no more 108 MB in RAM), reports
    real byte-level progress, and supports cancellation. If every remote
    source fails (e.g. the Oxford Text Archive gateway 504s), the message
    explains the offline 'Import archive' path.

    The job runs in the background; poll
    ``GET /reference-corpora/{name}/download-full/status``.
    """
    mgr = get_manager()
    try:
        spec = mgr.spec(name)
    except UnknownReferenceError as e:
        raise HTTPException(404, str(e)) from e

    if spec.format != "full_corpus":
        raise HTTPException(
            400,
            f"Reference '{name}' is a {spec.format} reference, not a full_corpus. "
            f"Use POST /reference-corpora/{name}/download instead.",
        )

    if not (spec.source_urls or spec.source_url):
        raise HTTPException(400, f"Reference '{name}' has no download URL.")

    # Fix #11: Return a job ID immediately and process in background
    # to avoid HTTP timeouts on large downloads (BAWE is 108 MB + ingestion)
    job_id = f"fullref_{name}"
    existing_job = _full_corpus_jobs.get(job_id)
    if existing_job and existing_job.get("status") in _ACTIVE_STATUSES:
        return {
            "name": name,
            "status": "started",
            "job_id": job_id,
            "message": (
                f"An install for '{spec.display_name}' is already in "
                f"progress — polling the existing job."
            ),
        }

    _full_corpus_cancels.discard(name)
    _full_corpus_jobs[job_id] = {
        "name": name,
        "status": "downloading",
        "progress": 0,
        "message": "Starting download…",
        "corpus_id": None,
        "document_count": 0,
    }

    # Fix #12: hold a strong reference so asyncio doesn't GC the task
    # mid-download. Discard from the set once complete so we don't leak.
    task = asyncio.create_task(_process_full_reference(name, spec, job_id))
    _full_corpus_tasks.add(task)
    task.add_done_callback(_full_corpus_tasks.discard)

    return {
        "name": name,
        "status": "started",
        "job_id": job_id,
        "message": f"Download started for '{spec.display_name}'. Poll GET /reference-corpora/{name}/download-full/status for progress.",
    }


@router.post("/reference-corpora/{name}/download-full/cancel")
async def cancel_full_reference(name: str) -> dict:
    """Request cancellation of an in-flight full-corpus install. Idempotent."""
    job = _full_corpus_jobs.get(f"fullref_{name}")
    active = bool(job and job.get("status") in _ACTIVE_STATUSES)
    if active:
        _full_corpus_cancels.add(name)
    return {"name": name, "cancel_requested": active}


@router.post("/reference-corpora/{name}/import-archive")
async def import_full_reference(
    name: str,
    file: UploadFile = File(...),
) -> dict:
    """Offline import: install a full reference corpus from a manually
    downloaded archive (ZIP or tar.gz).

    This is the guaranteed path when every remote source fails (the Oxford
    Text Archive gateway routinely 504s on large bitstream responses, while
    browsers cope much better). The user downloads the archive in their
    browser, then uploads it here; extraction + ingestion run in the same
    background job used by ``download-full`` (same status endpoint).

    The upload is streamed to disk in chunks and rejected early if it is
    not a real archive (magic-byte sniff) or exceeds the size cap.
    """
    mgr = get_manager()
    try:
        spec = mgr.spec(name)
    except UnknownReferenceError as e:
        raise HTTPException(404, str(e)) from e

    if spec.format != "full_corpus":
        raise HTTPException(
            400,
            f"Reference '{name}' is a {spec.format} reference; offline "
            f"import applies to full_corpus references.",
        )

    job_id = f"fullref_{name}"
    existing_job = _full_corpus_jobs.get(job_id)
    if existing_job and existing_job.get("status") in _ACTIVE_STATUSES:
        raise HTTPException(409, f"An install for '{name}' is already in progress.")

    part_path = _archive_dir() / f"{name}.import.part"
    size = 0
    try:
        with open(part_path, "wb") as fh:
            while True:
                chunk = await file.read(DOWNLOAD_CHUNK_SIZE)
                if not chunk:
                    break
                size += len(chunk)
                if size > MAX_IMPORT_BYTES:
                    raise HTTPException(
                        413,
                        f"Archive exceeds the {MAX_IMPORT_BYTES // (1024 * 1024)} MB "
                        f"offline-import limit.",
                    )
                fh.write(chunk)
    finally:
        await file.close()

    fmt = _sniff_archive(part_path) if size >= 2 else "unknown"
    if fmt == "unknown":
        part_path.unlink(missing_ok=True)
        raise HTTPException(
            400,
            "The uploaded file is neither a valid ZIP nor a tar.gz archive "
            "(magic bytes mismatch). Re-download the archive from the "
            "source page and try again.",
        )

    final_path = part_path.with_suffix(".zip" if fmt == "zip" else ".tar.gz")
    part_path.replace(final_path)

    _full_corpus_jobs[job_id] = {
        "name": name,
        "status": "extracting",
        "progress": 50,
        "message": f"Imported archive ({size // (1024 * 1024)} MB). Extracting…",
        "corpus_id": None,
        "document_count": 0,
    }

    async def _process_import() -> None:
        try:
            try:
                text_files = await asyncio.to_thread(_extract_text_files, final_path, spec, job_id)
            finally:
                final_path.unlink(missing_ok=True)
            if not text_files:
                _set_job(
                    job_id,
                    status="failed",
                    message=("Archive contained no .txt or .xml files to ingest."),
                )
                return
            await _ingest_and_install(name, spec, text_files, job_id)
        except Exception as e:
            _set_job(job_id, status="failed", message=str(e))
            log.error("import_full_reference_failed", name=name, error=str(e))

    task = asyncio.create_task(_process_import())
    _full_corpus_tasks.add(task)
    task.add_done_callback(_full_corpus_tasks.discard)

    return {
        "name": name,
        "status": "started",
        "job_id": job_id,
        "message": (
            f"Archive accepted for '{spec.display_name}'. Poll "
            f"GET /reference-corpora/{name}/download-full/status for progress."
        ),
    }


@router.get("/reference-corpora/{name}/download-full/status")
async def download_full_status(name: str) -> dict:
    """Poll the status of a full-corpus download/import job."""
    job_id = f"fullref_{name}"
    job = _full_corpus_jobs.get(job_id)
    if not job:
        return {"name": name, "status": "not_started", "message": "No download job found."}
    return job
