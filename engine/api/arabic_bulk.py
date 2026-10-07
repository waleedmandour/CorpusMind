"""Bulk Arabic analysis routes (v1.2.11 follow-up).

Chunked, cancellable, progress-reporting analysis for corpus-sized input
(500K-1M+ tokens). See app/arabic_bulk.py for the design and the measured
numbers that motivate it.

  POST /api/v1/arabic/analyze/job          start (409 when one is running)
  GET  /api/v1/arabic/analyze/job/status   chunks/tokens progress + ETA
  POST /api/v1/arabic/analyze/job/cancel   cooperative, between chunks
  GET  /api/v1/arabic/analyze/job/result   JSON download (aggregated)
"""

from __future__ import annotations

from typing import Any

from fastapi import APIRouter, HTTPException
from fastapi.responses import FileResponse
from pydantic import BaseModel, Field

from app.arabic_bulk import BulkBusyError, get_bulk_job
from app.logging import get_logger

log = get_logger(__name__)

router = APIRouter()


class BulkAnalyzeRequest(BaseModel):
    text: str = Field(..., min_length=1, description="Corpus-sized Arabic text")


@router.post("/arabic/analyze/job")
async def start_bulk(body: BulkAnalyzeRequest) -> dict[str, Any]:
    job = get_bulk_job()
    try:
        return job.start(body.text)
    except BulkBusyError as e:
        raise HTTPException(status_code=409, detail=str(e)) from e
    except ValueError as e:
        raise HTTPException(status_code=422, detail=str(e)) from e


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
