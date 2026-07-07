"""Corpus management API routes (§8.1, §8.2)."""
from __future__ import annotations

from datetime import datetime

from fastapi import APIRouter, Depends, File, Form, HTTPException, UploadFile
from pydantic import BaseModel, Field
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.logging import get_logger
from ingestion.service import ingest_document
from storage.models import Corpus, Document, Project
from storage.session import get_session

log = get_logger(__name__)
router = APIRouter()


# --------------------------------------------------------------------------- #
# Projects
# --------------------------------------------------------------------------- #


class ProjectCreate(BaseModel):
    name: str = Field(..., min_length=1, max_length=255)
    description: str = ""
    language: str = "en"
    visibility: str = "private"


class ProjectOut(BaseModel):
    id: str
    name: str
    description: str
    language: str
    visibility: str
    created_at: datetime
    corpus_count: int = 0


@router.post("/projects", response_model=ProjectOut)
async def create_project(body: ProjectCreate, session: AsyncSession = Depends(get_session)) -> ProjectOut:
    p = Project(name=body.name, description=body.description, language=body.language, visibility=body.visibility)
    session.add(p)
    await session.flush()
    return ProjectOut(
        id=p.id, name=p.name, description=p.description, language=p.language,
        visibility=p.visibility, created_at=p.created_at, corpus_count=0,
    )


@router.get("/projects", response_model=list[ProjectOut])
async def list_projects(session: AsyncSession = Depends(get_session)) -> list[ProjectOut]:
    stmt = select(Project).order_by(Project.created_at.desc())
    projects = (await session.execute(stmt)).scalars().all()
    out = []
    for p in projects:
        n = await session.scalar(select(func.count(Corpus.id)).where(Corpus.project_id == p.id)) or 0
        out.append(ProjectOut(
            id=p.id, name=p.name, description=p.description, language=p.language,
            visibility=p.visibility, created_at=p.created_at, corpus_count=n,
        ))
    return out


@router.get("/projects/{pid}", response_model=ProjectOut)
async def get_project(pid: str, session: AsyncSession = Depends(get_session)) -> ProjectOut:
    p = await session.get(Project, pid)
    if not p:
        raise HTTPException(404, "Project not found")
    n = await session.scalar(select(func.count(Corpus.id)).where(Corpus.project_id == pid)) or 0
    return ProjectOut(
        id=p.id, name=p.name, description=p.description, language=p.language,
        visibility=p.visibility, created_at=p.created_at, corpus_count=n,
    )


@router.delete("/projects/{pid}")
async def delete_project(pid: str, session: AsyncSession = Depends(get_session)) -> dict:
    p = await session.get(Project, pid)
    if not p:
        raise HTTPException(404, "Project not found")
    await session.delete(p)
    return {"deleted": pid}


# --------------------------------------------------------------------------- #
# Corpora
# --------------------------------------------------------------------------- #


class CorpusCreate(BaseModel):
    name: str = Field(..., min_length=1, max_length=255)
    language: str = "en"


class CorpusOut(BaseModel):
    id: str
    project_id: str
    name: str
    language: str
    pipeline_recipe: dict
    stats: dict
    created_at: datetime
    document_count: int = 0


@router.post("/projects/{pid}/corpora", response_model=CorpusOut)
async def create_corpus(pid: str, body: CorpusCreate, session: AsyncSession = Depends(get_session)) -> CorpusOut:
    p = await session.get(Project, pid)
    if not p:
        raise HTTPException(404, "Project not found")
    c = Corpus(project_id=pid, name=body.name, language=body.language or p.language)
    session.add(c)
    await session.flush()
    return CorpusOut(
        id=c.id, project_id=c.project_id, name=c.name, language=c.language,
        pipeline_recipe=c.pipeline_recipe, stats=c.stats, created_at=c.created_at, document_count=0,
    )


@router.get("/projects/{pid}/corpora", response_model=list[CorpusOut])
async def list_corpora(pid: str, session: AsyncSession = Depends(get_session)) -> list[CorpusOut]:
    stmt = select(Corpus).where(Corpus.project_id == pid).order_by(Corpus.created_at.desc())
    corpora = (await session.execute(stmt)).scalars().all()
    out = []
    for c in corpora:
        n = await session.scalar(select(func.count(Document.id)).where(Document.corpus_id == c.id)) or 0
        out.append(CorpusOut(
            id=c.id, project_id=c.project_id, name=c.name, language=c.language,
            pipeline_recipe=c.pipeline_recipe, stats=c.stats, created_at=c.created_at, document_count=n,
        ))
    return out


@router.get("/corpora/{cid}", response_model=CorpusOut)
async def get_corpus(cid: str, session: AsyncSession = Depends(get_session)) -> CorpusOut:
    c = await session.get(Corpus, cid)
    if not c:
        raise HTTPException(404, "Corpus not found")
    n = await session.scalar(select(func.count(Document.id)).where(Document.corpus_id == cid)) or 0
    return CorpusOut(
        id=c.id, project_id=c.project_id, name=c.name, language=c.language,
        pipeline_recipe=c.pipeline_recipe, stats=c.stats, created_at=c.created_at, document_count=n,
    )


@router.delete("/corpora/{cid}")
async def delete_corpus(cid: str, session: AsyncSession = Depends(get_session)) -> dict:
    c = await session.get(Corpus, cid)
    if not c:
        raise HTTPException(404, "Corpus not found")
    await session.delete(c)
    return {"deleted": cid}


# --------------------------------------------------------------------------- #
# Document upload + ingestion (§8.1)
# --------------------------------------------------------------------------- #


class DocumentOut(BaseModel):
    id: str
    corpus_id: str
    filename: str
    format: str
    encoding: str
    detected_language: str | None
    raw_size_bytes: int
    meta: dict
    created_at: datetime


@router.post("/corpora/{cid}/documents", response_model=list[DocumentOut])
async def upload_documents(
    cid: str,
    files: list[UploadFile] = File(...),
    language: str | None = Form(None),
    session: AsyncSession = Depends(get_session),
) -> list[DocumentOut]:
    """Upload one or more files into the corpus. Each is parsed, cleaned,
    tokenized, tagged, and persisted as a new annotation version (§4.8)."""
    c = await session.get(Corpus, cid)
    if not c:
        raise HTTPException(404, "Corpus not found")

    out: list[DocumentOut] = []
    for f in files:
        raw = await f.read()
        if not raw:
            log.warning("upload_empty", filename=f.filename)
            continue
        try:
            doc = await ingest_document(session, c, f.filename or "untitled.txt", raw, language=language)
            out.append(DocumentOut(
                id=doc.id, corpus_id=doc.corpus_id, filename=doc.filename,
                format=doc.format, encoding=doc.encoding,
                detected_language=doc.detected_language, raw_size_bytes=doc.raw_size_bytes,
                meta=doc.meta, created_at=doc.created_at,
            ))
        except Exception as e:
            log.error("ingest_failed", filename=f.filename, error=str(e))
            raise HTTPException(400, f"Failed to ingest '{f.filename}': {e}") from e
    return out


@router.get("/corpora/{cid}/documents", response_model=list[DocumentOut])
async def list_documents(cid: str, session: AsyncSession = Depends(get_session)) -> list[DocumentOut]:
    stmt = select(Document).where(Document.corpus_id == cid).order_by(Document.created_at.desc())
    docs = (await session.execute(stmt)).scalars().all()
    return [DocumentOut(
        id=d.id, corpus_id=d.corpus_id, filename=d.filename, format=d.format,
        encoding=d.encoding, detected_language=d.detected_language,
        raw_size_bytes=d.raw_size_bytes, meta=d.meta, created_at=d.created_at,
    ) for d in docs]
