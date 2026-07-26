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


# --------------------------------------------------------------------------- #
# v0.1.20: Full reference corpus download → extract → ingest
# --------------------------------------------------------------------------- #


# Fix #11: Track full-corpus download jobs so the UI can poll status
_full_corpus_jobs: dict[str, dict] = {}

# Fix #12: Keep strong references to background download tasks so asyncio
# doesn't garbage-collect them mid-download. Python's own asyncio docs warn
# about exactly this — create_task() returns a Task that may be GC'd if no
# reference is held. See: https://docs.python.org/3/library/asyncio-task.html#asyncio.create_task
_full_corpus_tasks: set = set()


@router.post("/reference-corpora/{name}/download-full")
async def download_full_reference(
    name: str,
) -> dict:
    """Download a full reference corpus (ZIP/tar.gz), extract text files,
    create a Corpus row, and ingest through the full NLP pipeline.

    v0.1.20: This is the Phase 2 endpoint for full reference corpora
    (BNC Baby, BAWE, Leipzig). Unlike the frequency-list download endpoint
    (which just saves a TSV file), this endpoint:

    1. Downloads the archive (ZIP or tar.gz)
    2. Extracts text files from the archive
    3. Creates a new Corpus row (genre="reference")
    4. Ingests each text file through the NLP pipeline
    5. Tags documents with metadata (genre, register) for subcorpus support

    The resulting Corpus row can be used with the standard keyness endpoint
    (POST /corpora/{cid}/keyness) AND supports subcorpus filtering.
    """
    import io
    import os
    import tarfile
    import tempfile
    import zipfile

    import httpx

    from ingestion.service import ingest_document
    from storage.models import Corpus as CorpusModel
    from storage.models import Project

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

    if not spec.source_url:
        raise HTTPException(400, f"Reference '{name}' has no download URL.")

    # Fix #11: Return a job ID immediately and process in background
    # to avoid HTTP timeouts on large downloads (BAWE is 108 MB + ingestion)
    job_id = f"fullref_{name}"
    _full_corpus_jobs[job_id] = {
        "name": name,
        "status": "downloading",
        "progress": 0,
        "message": "Starting download…",
        "corpus_id": None,
        "document_count": 0,
    }

    async def _process_full_reference():
        """Background task: download → extract → ingest."""

        from storage.session import session_scope

        try:
            _full_corpus_jobs[job_id]["status"] = "downloading"
            _full_corpus_jobs[job_id]["message"] = f"Downloading {name}…"
            log.info("download_full_reference_start", name=name, url=spec.source_url)

            async with httpx.AsyncClient(timeout=httpx.Timeout(300.0, connect=30.0)) as client:
                resp = await client.get(spec.source_url, follow_redirects=True)
                resp.raise_for_status()

            archive_bytes = resp.content
            _full_corpus_jobs[job_id]["message"] = f"Downloaded {len(archive_bytes) // 1024} KB. Extracting…"
            _full_corpus_jobs[job_id]["status"] = "extracting"
            log.info("download_full_reference_done", name=name, size=len(archive_bytes))

            # Extract text files.
            #
            # Fix #12: Detect archive type by magic bytes (content sniffing),
            # NOT by URL suffix. The OTA (Oxford Text Archive) hosts BNC Baby
            # and BAWE at URLs like:
            #     https://ota.bodleian.ox.ac.uk/.../2553.zip?sequence=3&isAllowed=y
            # — the URL ends in "isAllowed=y", not ".zip", so the old
            # `spec.source_url.endswith(".zip")` check never matched and the
            # code silently skipped extraction ("No text files found in
            # archive."). Magic-byte detection works regardless of URL.
            text_files: list[tuple[str, bytes, dict]] = []

            if len(archive_bytes) < 2:
                _full_corpus_jobs[job_id]["status"] = "failed"
                _full_corpus_jobs[job_id]["message"] = (
                    f"Downloaded archive is only {len(archive_bytes)} bytes — "
                    f"too small to be a valid ZIP or tar.gz."
                )
                return

            # ZIP files start with b"PK", gzip files start with b"\x1f\x8b".
            is_gzip = archive_bytes[:2] == b"\x1f\x8b"
            is_zip = archive_bytes[:2] == b"PK"

            if is_gzip:
                with tempfile.TemporaryDirectory() as tmpdir:
                    with tarfile.open(fileobj=io.BytesIO(archive_bytes), mode="r:gz") as tar:
                        tar.extractall(tmpdir)
                    for root, _d, files in os.walk(tmpdir):
                        for fname in files:
                            if fname.endswith("-sentences.txt"):
                                filepath = os.path.join(root, fname)
                                with open(filepath, encoding="utf-8") as f:
                                    for line_num, line in enumerate(f):
                                        parts = line.strip().split("\t")
                                        if len(parts) >= 2:
                                            text_files.append((
                                                f"{fname}_{line_num}.txt",
                                                parts[1].encode("utf-8"),
                                                {"source": "leipzig", "genre": spec.genre},
                                            ))
                                break
            elif is_zip:
                with tempfile.TemporaryDirectory() as tmpdir:
                    with zipfile.ZipFile(io.BytesIO(archive_bytes)) as zf:
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
                                        # BNC/TEI-XML nests <w>/<c> inside <s>,
                                        # inside <p>, inside <div>/<text>/<body>.
                                        # A parent tag's get_text() already
                                        # includes all descendant text, so
                                        # walking w/c/s/p/text/body and
                                        # concatenating get_text() from each
                                        # (the old code) appended every word's
                                        # text once per ancestor level matched
                                        # -- 3-4x duplicated, out-of-order text
                                        # in every ingested document.
                                        # BeautifulSoup's own get_text() already
                                        # walks nested tags correctly and visits
                                        # each leaf text node exactly once, in
                                        # document order -- no manual
                                        # accumulation needed. Restrict to
                                        # <text> so <teiHeader> bibliographic
                                        # metadata isn't pulled into the body.
                                        root = soup.find("text") or soup
                                        content = root.get_text(separator=" ")
                                        # BNC <w>/<c> tags are tightly packed
                                        # with irregular whitespace; collapse
                                        # runs of whitespace to single spaces.
                                        content = " ".join(content.split())
                                    if content.strip():
                                        text_files.append((fname, content.encode("utf-8"), {"source": name, "genre": genre or spec.genre}))
                                except Exception as e:
                                    log.warning("extract_file_failed", file=fname, error=str(e))
            else:
                # Genuinely unrecognized format — give the user a useful
                # error rather than the misleading "No text files found".
                _full_corpus_jobs[job_id]["status"] = "failed"
                _full_corpus_jobs[job_id]["message"] = (
                    f"Downloaded archive from {spec.source_url} is neither a "
                    f"valid ZIP (expected magic bytes b'PK') nor a valid "
                    f"tar.gz (expected magic bytes b'\\x1f\\x8b'). Got "
                    f"{archive_bytes[:2]!r} ({len(archive_bytes)} bytes)."
                )
                return

            if not text_files:
                _full_corpus_jobs[job_id]["status"] = "failed"
                _full_corpus_jobs[job_id]["message"] = (
                    f"Archive extracted successfully but contained no .txt or "
                    f".xml files. Inspected format: "
                    f"{'tar.gz' if is_gzip else 'zip'}."
                )
                return

            _full_corpus_jobs[job_id]["status"] = "ingesting"
            _full_corpus_jobs[job_id]["message"] = f"Ingesting {len(text_files)} documents…"

            # Create corpus + ingest in its own session
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
                    _full_corpus_jobs[job_id]["status"] = "installed"
                    _full_corpus_jobs[job_id]["corpus_id"] = existing.id
                    _full_corpus_jobs[job_id]["message"] = "Already installed."
                    return

                corpus = CorpusModel(
                    project_id=project.id, name=spec.display_name,
                    language=spec.language, genre=spec.genre,
                )
                session.add(corpus)
                await session.flush()

                ingested = 0
                for filename, content, meta in text_files[:500]:
                    try:
                        await ingest_document(session, corpus, filename, content, metadata=meta, language=spec.language)
                        ingested += 1
                        if ingested % 10 == 0:
                            _full_corpus_jobs[job_id]["message"] = f"Ingesting {ingested}/{len(text_files)}…"
                    except Exception as e:
                        log.warning("ingest_reference_doc_failed", file=filename, error=str(e))

                new_stats = dict(corpus.stats or {})
                new_stats.update({"document_count": ingested, "reference_name": name, "reference_license": spec.license})
                corpus.stats = new_stats
                await session.commit()

                _full_corpus_jobs[job_id]["status"] = "installed"
                _full_corpus_jobs[job_id]["corpus_id"] = corpus.id
                _full_corpus_jobs[job_id]["document_count"] = ingested
                _full_corpus_jobs[job_id]["message"] = f"Installed {ingested} documents."
                log.info("download_full_reference_complete", name=name, corpus_id=corpus.id, ingested=ingested)

        except Exception as e:
            _full_corpus_jobs[job_id]["status"] = "failed"
            _full_corpus_jobs[job_id]["message"] = str(e)
            log.error("download_full_reference_failed", name=name, error=str(e))

    import asyncio
    # Fix #12: hold a strong reference so asyncio doesn't GC the task
    # mid-download. Discard from the set once complete so we don't leak.
    task = asyncio.create_task(_process_full_reference())
    _full_corpus_tasks.add(task)
    task.add_done_callback(_full_corpus_tasks.discard)

    return {
        "name": name,
        "status": "started",
        "job_id": job_id,
        "message": f"Download started for '{spec.display_name}'. Poll GET /reference-corpora/{name}/download-full/status for progress.",
    }


@router.get("/reference-corpora/{name}/download-full/status")
async def download_full_status(name: str) -> dict:
    """Poll the status of a full-corpus download job."""
    job_id = f"fullref_{name}"
    job = _full_corpus_jobs.get(job_id)
    if not job:
        return {"name": name, "status": "not_started", "message": "No download job found."}
    return job
