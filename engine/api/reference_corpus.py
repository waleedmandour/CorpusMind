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


@router.post("/reference-corpora/{name}/download-full")
async def download_full_reference(
    name: str,
    session: AsyncSession = Depends(get_session),
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

    log.info("download_full_reference_start", name=name, url=spec.source_url)

    # 1. Download the archive
    try:
        async with httpx.AsyncClient(timeout=httpx.Timeout(300.0, connect=30.0)) as client:
            resp = await client.get(spec.source_url, follow_redirects=True)
            resp.raise_for_status()
    except httpx.HTTPError as e:
        raise HTTPException(502, f"Download failed: {e}") from e

    archive_bytes = resp.content
    log.info("download_full_reference_done", name=name, size=len(archive_bytes))

    # 2. Extract text files from the archive
    text_files: list[tuple[str, bytes, dict]] = []  # (filename, content, metadata)

    if spec.source_url.endswith(".tar.gz") or spec.source_url.endswith(".tgz"):
        # Leipzig corpus: tar.gz containing sentences.txt + words.txt
        with tempfile.TemporaryDirectory() as tmpdir:
            with tarfile.open(fileobj=io.BytesIO(archive_bytes), mode="r:gz") as tar:
                tar.extractall(tmpdir)

            # Find the sentences file
            for root, _dirs, files in os.walk(tmpdir):
                for fname in files:
                    if fname.endswith("-sentences.txt"):
                        filepath = os.path.join(root, fname)
                        with open(filepath, encoding="utf-8") as f:
                            for line_num, line in enumerate(f):
                                parts = line.strip().split("\t")
                                if len(parts) >= 2:
                                    sentence = parts[1]
                                    text_files.append((
                                        f"{fname}_{line_num}.txt",
                                        sentence.encode("utf-8"),
                                        {"source": "leipzig", "genre": spec.genre},
                                    ))
                        break  # Only process the first sentences file

    elif spec.source_url.endswith(".zip"):
        # BNC Baby / BAWE: ZIP containing XML or text files
        with tempfile.TemporaryDirectory() as tmpdir:
            with zipfile.ZipFile(io.BytesIO(archive_bytes)) as zf:
                zf.extractall(tmpdir)

            # Walk and find text/XML files, organized by subdirectory (genre)
            for root, _dirs, files in os.walk(tmpdir):
                # Determine genre from directory name
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
                            # For XML files, extract text content
                            if fname.endswith(".xml"):
                                from bs4 import BeautifulSoup
                                soup = BeautifulSoup(content, "xml")
                                # Try common XML text containers
                                text_parts = []
                                for tag in soup.find_all(["w", "c", "s", "p", "text", "body"]):
                                    if tag.name in ("w", "c"):
                                        text_parts.append(tag.get_text())
                                    elif tag.name in ("s", "p"):
                                        text_parts.append(tag.get_text() + " ")
                                content = " ".join(text_parts).strip()
                                if not content:
                                    # Fallback: strip all tags
                                    content = soup.get_text(separator=" ")
                            if content.strip():
                                meta = {"source": name, "genre": genre or spec.genre}
                                text_files.append((fname, content.encode("utf-8"), meta))
                        except Exception as e:
                            log.warning("extract_file_failed", file=fname, error=str(e))

    if not text_files:
        raise HTTPException(500, f"No text files found in the downloaded archive for '{name}'.")

    # 3. Find or create a project for reference corpora
    from sqlalchemy import select as sa_select
    stmt = sa_select(Project).where(Project.name == "Reference Corpora")
    project = (await session.execute(stmt)).scalar_one_or_none()
    if project is None:
        project = Project(name="Reference Corpora")
        session.add(project)
        await session.flush()

    # 4. Create a Corpus row
    # Check if a corpus with this name already exists
    stmt = sa_select(CorpusModel).where(
        CorpusModel.project_id == project.id,
        CorpusModel.name == spec.display_name,
    )
    existing_corpus = (await session.execute(stmt)).scalar_one_or_none()
    if existing_corpus is not None:
        # Already ingested — return the existing corpus
        await session.commit()
        return {
            "name": name,
            "status": "already_installed",
            "corpus_id": existing_corpus.id,
            "document_count": len(text_files),
            "message": f"Reference corpus '{spec.display_name}' is already installed.",
        }

    corpus = CorpusModel(
        project_id=project.id,
        name=spec.display_name,
        language=spec.language,
        genre=spec.genre,
    )
    session.add(corpus)
    await session.flush()

    # 5. Ingest each text file through the NLP pipeline
    ingested = 0
    for filename, content, meta in text_files[:500]:  # Cap at 500 docs for performance
        try:
            await ingest_document(
                session, corpus, filename, content,
                metadata=meta, language=spec.language,
            )
            ingested += 1
        except Exception as e:
            log.warning("ingest_reference_doc_failed", file=filename, error=str(e))

    # 6. Update corpus stats (reassign dict for SQLAlchemy)
    new_stats = dict(corpus.stats or {})
    new_stats.update({
        "document_count": ingested,
        "reference_name": name,
        "reference_license": spec.license,
    })
    corpus.stats = new_stats

    await session.commit()

    log.info(
        "download_full_reference_complete",
        name=name, corpus_id=corpus.id, ingested=ingested, total=len(text_files),
    )

    return {
        "name": name,
        "status": "installed",
        "corpus_id": corpus.id,
        "document_count": ingested,
        "total_files": len(text_files),
        "message": f"Downloaded and ingested {ingested} documents from '{spec.display_name}'.",
    }
