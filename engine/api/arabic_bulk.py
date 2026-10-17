"""Bulk Arabic analysis routes (v1.2.11 follow-up; r4 adds corpus-driven start).

Chunked, cancellable, progress-reporting analysis for corpus-sized input
(500K-1M+ tokens). See app/arabic_bulk.py for the design and the measured
numbers that motivate it.

  POST /api/v1/arabic/analyze/job          start — pass EITHER raw `text`
                                           OR `corpus_id` (r4: the engine
                                           loads the corpus's stored cleaned
                                           text server-side, so the browser
                                           never round-trips megabytes; 409
                                           when one is running)
  GET  /api/v1/arabic/analyze/job/status   chunks/tokens progress + ETA
  POST /api/v1/arabic/analyze/job/cancel   cooperative, between chunks
  GET  /api/v1/arabic/analyze/job/result   JSON download (aggregated)
"""

from __future__ import annotations

from typing import Any

from fastapi import APIRouter, Depends, HTTPException
from fastapi.responses import FileResponse
from pydantic import BaseModel, Field
from sqlalchemy import select
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.ext.asyncio import AsyncSession

from app.arabic_bulk import BulkBusyError, get_bulk_job
from app.logging import get_logger
from nlp.arabic.pipeline import ArabicDataMissingError
from storage.models import Corpus, Document
from storage.session import get_session

log = get_logger(__name__)

router = APIRouter()


class BulkAnalyzeRequest(BaseModel):
    # Exactly one of the two sources must be provided (validated in the route:
    # pydantic cannot express "exactly one of these two optionals" without
    # model_validator noise, and the route turns violations into a 422 with an
    # actionable message either way).
    text: str | None = Field(default=None, min_length=1, description="Corpus-sized Arabic text")
    corpus_id: str | None = Field(
        default=None,
        description="r4: analyze a corpus uploaded via 'Your Corpus' — its stored "
        "cleaned text is loaded server-side in ingestion order.",
    )


async def _corpus_text(session: AsyncSession, corpus_id: str) -> tuple[str, str]:
    """(corpus_name, joined_text) for a 'Your Corpus' corpus.

    Documents are read in ingestion order (created_at) and blank documents are
    skipped; 404 for an unknown corpus, 422 when the corpus holds no text.
    """
    corpus = await session.get(Corpus, corpus_id)
    if corpus is None:
        raise HTTPException(404, "Corpus not found")
    res = await session.execute(
        select(Document.cleaned_text)
        .where(Document.corpus_id == corpus_id)
        .order_by(Document.created_at)
    )
    parts = [t for t in res.scalars().all() if t and t.strip()]
    if not parts:
        raise HTTPException(422, f"Corpus '{corpus.name}' has no text content to analyze.")
    return corpus.name, "\n\n".join(parts)


@router.post("/arabic/analyze/job")
async def start_bulk(
    body: BulkAnalyzeRequest, session: AsyncSession = Depends(get_session)
) -> dict[str, Any]:
    if bool(body.text) == bool(body.corpus_id):
        raise HTTPException(422, "Provide exactly one of `text` or `corpus_id`.")
    # r5: nothing below may escape as a BARE 500. The corpus read and the job
    # start touch the local DB, the filesystem and the analyzer stack — on a
    # real desktop machine any of these can fail for environment reasons
    # (antivirus holding the DB file, disk pressure, a lock from a long
    # ingestion commit). Every failure class gets an actionable detail and a
    # server-side traceback in the log, mirroring the interactive route's
    # contract (api/arabic.py): known-recoverable -> 503, unknown -> a LABELED
    # 500 ("<ErrClass>: <msg>"), never a detail-less Internal Server Error.
    job = get_bulk_job()
    try:
        source: str | None = None
        if body.corpus_id is not None:
            source, text = await _corpus_text(session, body.corpus_id)
        else:
            text = body.text or ""
        return job.start(text, source=source)
    except HTTPException:
        raise
    except BulkBusyError as e:
        raise HTTPException(status_code=409, detail=str(e)) from e
    except ValueError as e:
        raise HTTPException(status_code=422, detail=str(e)) from e
    except ArabicDataMissingError as e:
        # Same contract as the interactive route; the current start path is
        # data-free, but the chunking stack must be allowed to adopt the
        # pre-flight without silently changing the wire behavior.
        raise HTTPException(status_code=503, detail=str(e)) from e
    except SQLAlchemyError as e:
        log.exception("arabic_bulk_start_db_error", corpus_id=body.corpus_id)
        raise HTTPException(
            status_code=503,
            detail=(
                "The corpus could not be read from the local database "
                f"({type(e).__name__}). Another long operation (for example a "
                "large upload still processing) may be holding it — wait a "
                "moment and start the analysis again."
            ),
        ) from e
    except (MemoryError, OSError) as e:
        log.exception("arabic_bulk_start_load_error", corpus_id=body.corpus_id)
        raise HTTPException(
            status_code=503,
            detail=(
                "The corpus text could not be loaded for analysis "
                f"({type(e).__name__}: {e}). Free some memory/disk space and "
                "try again; if it persists, analyze the corpus in parts."
            ),
        ) from e
    except Exception as e:
        log.exception("arabic_bulk_start_unexpected", corpus_id=body.corpus_id)
        raise HTTPException(
            status_code=500,
            detail=f"Bulk Arabic analysis could not be started: {type(e).__name__}: {e}",
        ) from e


@router.get("/arabic/analyze/job/status")
async def bulk_status() -> dict[str, Any]:
    return get_bulk_job().status()


@router.post("/arabic/analyze/job/cancel")
async def bulk_cancel() -> dict[str, Any]:
    job = get_bulk_job()
    s = job.cancel()
    if not s.get("busy"):
        raise HTTPException(
            status_code=409, detail="No bulk Arabic analysis is currently running."
        )
    return s


@router.get("/arabic/analyze/job/result")
async def bulk_result() -> FileResponse:
    job = get_bulk_job()
    path = job.result_path()
    if path is None or not path.is_file():
        s = job.status()
        state = s.get("state")
        if state == "running":
            raise HTTPException(
                status_code=409,
                detail=f"Bulk analysis still running ({s.get('tokens_done', 0)}/"
                f"{s.get('tokens_total', 0)} tokens). Poll /status.",
            )
        raise HTTPException(
            status_code=404,
            detail=f"No bulk analysis result available (job state: {state}). "
            "Start one with POST /api/v1/arabic/analyze/job.",
        )
    return FileResponse(
        path,
        media_type="application/json",
        filename="corpusmind-arabic-bulk-analysis.json",
    )
