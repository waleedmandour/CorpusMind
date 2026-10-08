"""In-app Arabic data pack installer routes (v1.2.11 follow-up).

One background job, one status endpoint, one cancel endpoint. All three are
cheap to answer: the status lives in a small lock-protected dict, and the
job itself runs in its own thread - none of these routes ever touch the
event loop's budget for analysis work.

  POST /arabic/data/install          start (409 when a job is already
                                     running or nothing is missing -
                                     pass force=true to reinstall anyway)
  GET  /arabic/data/install/status   live progress (bytes, stage, packages)
  POST /arabic/data/install/cancel   cooperative cancel between chunks

The status payload also reports what WILL be downloaded (pinned versions,
sizes, licences) when idle, so the UI can show an honest preview before the
user commits to a ~254MB download (MSA + the three dialect morphology DBs +
the dialect-ID model; v1.2.11 added the dialect DBs so the Arabic Tools
dialect dropdown is fully provisionable in-app).
"""

from __future__ import annotations

from typing import Any

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, Field

from app.arabic_installer import (
    ArabicInstallerError,
    _package_state,
    _resolve_target_dir,
    catalog_packages,
    get_arabic_installer,
)
from app.logging import get_logger
from nlp.arabic.pipeline import camel_data_status

log = get_logger(__name__)

router = APIRouter()


class InstallRequest(BaseModel):
    include_dialect_id: bool = Field(
        True,
        description="Also download the dialect-ID model (adds ~122MB). "
        "Dialect ID stays unavailable without it; morphology alone needs only "
        "the ~39MB calima-msa-r13 pack.",
    )
    include_dialects: bool = Field(
        True,
        description="Also download the Egyptian / Gulf / Levantine dialect "
        "morphology DBs (adds ~82MB). Without them the dialect dropdown's "
        "egy/glf/lev options answer 503; v1.2.11 teaches the installer to "
        "fetch them so the dropdown is fully provisionable in-app.",
    )
    force: bool = Field(
        False,
        description="Re-install (repair), v1.2.12: re-download EVERY wanted "
        "package and replace whatever is on disk, even when the pack already "
        "counts as installed. The way out of a partial or corrupted install "
        "(app reinstall, cancelled job, crashed extraction).",
    )


@router.post("/arabic/data/install")
async def start_install(body: InstallRequest) -> dict[str, Any]:
    """Start the background download+install of the Arabic data pack."""
    installer = get_arabic_installer()
    try:
        return installer.start(
            include_dialect_id=body.include_dialect_id,
            include_dialects=body.include_dialects,
            force=body.force,
        )
    except ArabicInstallerError as e:
        # "Already running" / "already installed" / "target not writable":
        # a client-visible conflict, not a server fault.
        raise HTTPException(status_code=409, detail=str(e)) from e


@router.get("/arabic/data/install/status")
async def install_status() -> dict[str, Any]:
    """Live status of the install job + an honest preview of what an
    install would download when nothing is running."""
    installer = get_arabic_installer()
    s = installer.status()
    if s.get("state") == "idle":
        # Nothing has ever run in this process: offer the pinned preview.
        try:
            target = _resolve_target_dir()
            preview = []
            for pkg in catalog_packages():
                preview.append(
                    {
                        "name": pkg["name"],
                        "version": pkg["version"],
                        "size": pkg["size"],
                        "sha256": pkg["sha256"],
                        "license": pkg["license"],
                        "state": _package_state(target, pkg),
                    }
                )
            s["offer"] = {
                "target_dir": str(target),
                "packages": preview,
                "total_bytes": sum(p["size"] for p in preview if p["state"] == "missing"),
            }
        except Exception as e:
            log.warning("arabic_installer_preview_failed", error=str(e))
    # Complement with the filesystem truth the analysis path uses, so the UI
    # can flip its buttons the moment the pack becomes usable.
    s["camel_tools"] = camel_data_status()
    return s


@router.post("/arabic/data/install/cancel")
async def cancel_install() -> dict[str, Any]:
    """Request cooperative cancellation of a running install."""
    installer = get_arabic_installer()
    s = installer.cancel()
    if not s.get("busy"):
        raise HTTPException(
            status_code=409,
            detail="No Arabic data pack install is currently running.",
        )
    return s
