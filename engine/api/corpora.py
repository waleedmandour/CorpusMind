"""Corpus management API routes (§8.1, §8.2)."""

from __future__ import annotations

from datetime import datetime

from fastapi import APIRouter, Depends, File, Form, HTTPException, UploadFile
from pydantic import BaseModel, Field
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.logging import get_logger
from ingestion.service import ingest_document
from storage.models import Corpus, Document, Project, Subcorpus
from storage.session import get_session

log = get_logger(__name__)
router = APIRouter()


class TagsetRequest(BaseModel):
    tagset: str = Field(..., min_length=2, max_length=32)


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
async def create_project(
    body: ProjectCreate, session: AsyncSession = Depends(get_session)
) -> ProjectOut:
    p = Project(
        name=body.name,
        description=body.description,
        language=body.language,
        visibility=body.visibility,
    )
    session.add(p)
    await session.flush()
    return ProjectOut(
        id=p.id,
        name=p.name,
        description=p.description,
        language=p.language,
        visibility=p.visibility,
        created_at=p.created_at,
        corpus_count=0,
    )


@router.get("/projects", response_model=list[ProjectOut])
async def list_projects(session: AsyncSession = Depends(get_session)) -> list[ProjectOut]:
    stmt = select(Project).order_by(Project.created_at.desc())
    projects = (await session.execute(stmt)).scalars().all()
    out = []
    for p in projects:
        n = (
            await session.scalar(select(func.count(Corpus.id)).where(Corpus.project_id == p.id))
            or 0
        )
        out.append(
            ProjectOut(
                id=p.id,
                name=p.name,
                description=p.description,
                language=p.language,
                visibility=p.visibility,
                created_at=p.created_at,
                corpus_count=n,
            )
        )
    return out


@router.get("/projects/{pid}", response_model=ProjectOut)
async def get_project(pid: str, session: AsyncSession = Depends(get_session)) -> ProjectOut:
    p = await session.get(Project, pid)
    if not p:
        raise HTTPException(404, "Project not found")
    n = await session.scalar(select(func.count(Corpus.id)).where(Corpus.project_id == pid)) or 0
    return ProjectOut(
        id=p.id,
        name=p.name,
        description=p.description,
        language=p.language,
        visibility=p.visibility,
        created_at=p.created_at,
        corpus_count=n,
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
    genre: str = "mixed"  # academic, news, spoken, fiction, blog, legal, medical, mixed, etc.


class CorpusOut(BaseModel):
    id: str
    project_id: str
    name: str
    language: str
    genre: str = "mixed"
    pipeline_recipe: dict
    stats: dict
    created_at: datetime
    document_count: int = 0


@router.post("/projects/{pid}/corpora", response_model=CorpusOut)
async def create_corpus(
    pid: str, body: CorpusCreate, session: AsyncSession = Depends(get_session)
) -> CorpusOut:
    p = await session.get(Project, pid)
    if not p:
        raise HTTPException(404, "Project not found")
    c = Corpus(
        project_id=pid, name=body.name, language=body.language or p.language, genre=body.genre
    )
    session.add(c)
    await session.flush()
    return CorpusOut(
        id=c.id,
        project_id=c.project_id,
        name=c.name,
        language=c.language,
        genre=c.genre,
        pipeline_recipe=c.pipeline_recipe,
        stats=c.stats,
        created_at=c.created_at,
        document_count=0,
    )


@router.get("/projects/{pid}/corpora", response_model=list[CorpusOut])
async def list_corpora(pid: str, session: AsyncSession = Depends(get_session)) -> list[CorpusOut]:
    stmt = select(Corpus).where(Corpus.project_id == pid).order_by(Corpus.created_at.desc())
    corpora = (await session.execute(stmt)).scalars().all()
    out = []
    for c in corpora:
        n = (
            await session.scalar(select(func.count(Document.id)).where(Document.corpus_id == c.id))
            or 0
        )
        out.append(
            CorpusOut(
                id=c.id,
                project_id=c.project_id,
                name=c.name,
                language=c.language,
                genre=c.genre,
                pipeline_recipe=c.pipeline_recipe,
                stats=c.stats,
                created_at=c.created_at,
                document_count=n,
            )
        )
    return out


@router.get("/corpora/{cid}", response_model=CorpusOut)
async def get_corpus(cid: str, session: AsyncSession = Depends(get_session)) -> CorpusOut:
    c = await session.get(Corpus, cid)
    if not c:
        raise HTTPException(404, "Corpus not found")
    n = await session.scalar(select(func.count(Document.id)).where(Document.corpus_id == cid)) or 0
    return CorpusOut(
        id=c.id,
        project_id=c.project_id,
        name=c.name,
        language=c.language,
        genre=c.genre,
        pipeline_recipe=c.pipeline_recipe,
        stats=c.stats,
        created_at=c.created_at,
        document_count=n,
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
        # Fix #6: Enforce a maximum upload size (50 MB per file)
        MAX_UPLOAD_SIZE = 50 * 1024 * 1024  # 50 MB
        raw = await f.read()
        if not raw:
            log.warning("upload_empty", filename=f.filename)
            continue
        if len(raw) > MAX_UPLOAD_SIZE:
            raise HTTPException(
                413,
                f"File '{f.filename}' is {len(raw) // 1024 // 1024} MB. "
                f"Maximum upload size is {MAX_UPLOAD_SIZE // 1024 // 1024} MB.",
            )
        # Fix #7: Sanitize filename to prevent path traversal and log injection
        import os

        safe_filename = os.path.basename(f.filename or "untitled.txt")
        try:
            doc = await ingest_document(session, c, safe_filename, raw, language=language)
            out.append(
                DocumentOut(
                    id=doc.id,
                    corpus_id=doc.corpus_id,
                    filename=doc.filename,
                    format=doc.format,
                    encoding=doc.encoding,
                    detected_language=doc.detected_language,
                    raw_size_bytes=doc.raw_size_bytes,
                    meta=doc.meta,
                    created_at=doc.created_at,
                )
            )
        except Exception as e:
            log.error("ingest_failed", filename=safe_filename, error=str(e))
            raise HTTPException(400, f"Failed to ingest '{safe_filename}': {e}") from e
    return out


@router.get("/corpora/{cid}/documents", response_model=list[DocumentOut])
async def list_documents(
    cid: str, session: AsyncSession = Depends(get_session)
) -> list[DocumentOut]:
    stmt = select(Document).where(Document.corpus_id == cid).order_by(Document.created_at.desc())
    docs = (await session.execute(stmt)).scalars().all()
    return [
        DocumentOut(
            id=d.id,
            corpus_id=d.corpus_id,
            filename=d.filename,
            format=d.format,
            encoding=d.encoding,
            detected_language=d.detected_language,
            raw_size_bytes=d.raw_size_bytes,
            meta=d.meta,
            created_at=d.created_at,
        )
        for d in docs
    ]


@router.delete("/corpora/{cid}/documents/{did}")
async def delete_document(cid: str, did: str, session: AsyncSession = Depends(get_session)) -> dict:
    """Delete a document from a corpus and recompute corpus stats.

    v0.1.17: This endpoint was missing — users couldn't remove individual
    files from a corpus. Now they can.
    """
    doc = await session.get(Document, did)
    if not doc or doc.corpus_id != cid:
        raise HTTPException(404, "Document not found in this corpus")

    # Get the corpus for stats recompute
    corpus = await session.get(Corpus, cid)
    if not corpus:
        raise HTTPException(404, "Corpus not found")

    # Delete the document (cascades to its tokens via the annotation version)
    filename = doc.filename
    await session.delete(doc)
    await session.flush()

    # Recompute corpus stats
    from storage.models import AnnotationVersion, Token

    latest_version = await session.scalar(
        select(AnnotationVersion)
        .where(AnnotationVersion.corpus_id == cid)
        .order_by(AnnotationVersion.created_at.desc())
        .limit(1)
    )
    token_count = 0
    type_count = 0
    if latest_version:
        token_count = (
            await session.scalar(
                select(func.count(Token.id)).where(Token.version_id == latest_version.id)
            )
            or 0
        )
        type_count = (
            await session.scalar(
                select(func.count(Token.text.distinct())).where(
                    Token.version_id == latest_version.id
                )
            )
            or 0
        )

    doc_count = (
        await session.scalar(select(func.count(Document.id)).where(Document.corpus_id == cid)) or 0
    )

    # Fix: SQLAlchemy JSON columns don't detect in-place mutations. Must
    # reassign the dict to trigger the UPDATE.
    new_stats = dict(corpus.stats or {})
    new_stats.update(
        {
            "document_count": doc_count,
            "token_count": token_count,
            "type_count": type_count,
        }
    )
    corpus.stats = new_stats  # reassign triggers SQLAlchemy change detection

    await session.commit()
    log.info("document_deleted", cid=cid, did=did, filename=filename, remaining_docs=doc_count)
    return {"deleted": did, "filename": filename, "remaining_documents": doc_count}


@router.patch("/corpora/{cid}/tagset")
async def set_corpus_tagset(
    cid: str, body: TagsetRequest, session: AsyncSession = Depends(get_session)
) -> dict:
    """v1.2.0 (Issue 4): persist the user's tagset choice per corpus.

    Stored inside ``corpus.pipeline_recipe`` (JSON) under ``tagset`` so no
    schema migration is needed. The POS panel reads this as the default
    tagset for the corpus.
    """
    corpus = await session.get(Corpus, cid)
    if not corpus:
        raise HTTPException(404, "Corpus not found")

    from nlp.tagsets import is_valid_tagset, valid_tagsets_for_language

    language = corpus.language or "en"
    if not is_valid_tagset(body.tagset, language):
        raise HTTPException(
            422,
            f"Tagset '{body.tagset}' is not valid for a '{language}' corpus. "
            f"Valid tagsets: {', '.join(valid_tagsets_for_language(language))}.",
        )

    new_recipe = dict(corpus.pipeline_recipe or {})
    new_recipe["tagset"] = body.tagset
    corpus.pipeline_recipe = new_recipe  # reassign triggers SQLAlchemy change detection
    await session.commit()
    log.info("corpus_tagset_set", cid=cid, tagset=body.tagset)
    return {"ok": True, "corpus_id": cid, "tagset": body.tagset}


@router.post("/corpora/{cid}/recompile")
async def recompile_corpus(cid: str, session: AsyncSession = Depends(get_session)) -> dict:
    """Re-run the full NLP pipeline on all documents in a corpus.

    v0.1.17: This re-cleans and re-tags every document, creating a new
    annotation version. Useful after changing cleaning options or after
    adding/removing documents.
    """
    corpus = await session.get(Corpus, cid)
    if not corpus:
        raise HTTPException(404, "Corpus not found")

    # Get all documents
    stmt = select(Document).where(Document.corpus_id == cid).order_by(Document.created_at)
    docs = (await session.execute(stmt)).scalars().all()
    if not docs:
        raise HTTPException(400, "No documents to recompile")

    # Re-ingest every document into ONE new annotation version.
    # Issue 1 fix — three stacked bugs hid behind the old per-document
    # try/except (which returned HTTP 200 with "recompiled": 0):
    #   1. `parsed.tokens` — ParsedDocument has no such attribute (tokens
    #      live on each sentence; indexes come from enumeration).
    #   2. Invalid AnnotationVersion kwargs (`backend=`, `spacy_version=`)
    #      — the model has neither column; the backend folds into model_name.
    #   3. A new version was created PER DOCUMENT, so the latest version only
    #      ever contained the last document's tokens. A recompile is a single
    #      pipeline re-run over the whole corpus → one version row, tokens
    #      from every successfully re-parsed document.
    from nlp.general.pipeline import get_pipeline
    from storage.models import AnnotationVersion, Token

    pipeline = get_pipeline(backend="spacy", language=corpus.language or "en")
    info = pipeline.info()

    existing = await session.scalar(
        select(AnnotationVersion)
        .where(AnnotationVersion.corpus_id == cid)
        .order_by(AnnotationVersion.created_at.desc())
        .limit(1)
    )
    version_n = 1
    if existing and existing.version_label.startswith("v"):
        try:
            version_n = int(existing.version_label[1:]) + 1
        except ValueError:
            pass

    av = AnnotationVersion(
        corpus_id=cid,
        version_label=f"v{version_n}",
        # Mirror ingestion/service.py's column mapping exactly.
        model_name=f"{info.backend}:{info.model_name}",
        model_version=info.model_version,
        tokenizer=info.backend,
        tagger=info.backend,
        parser=info.backend,
        token_count=0,
        type_count=0,
    )
    session.add(av)
    await session.flush()

    recompiled = 0
    failed: list[dict] = []
    total_tokens = 0
    all_texts: set[str] = set()
    for doc in docs:
        try:
            # Re-parse from the stored cleaned text
            parsed = pipeline.parse_document(doc.cleaned_text)
            for sent_idx, sent in enumerate(parsed.sentences):
                for tok_idx, tok in enumerate(sent.tokens):
                    session.add(
                        Token(
                            version_id=av.id,
                            document_id=doc.id,
                            sentence_idx=sent_idx,
                            token_idx=tok_idx,
                            text=tok.text,
                            lemma=tok.lemma,
                            pos=tok.pos,
                            # v1.2.0: persist the FULL annotation — recompile
                            # previously dropped pos_fine/morph/dep_*, which
                            # silently broke the PTB/CLAWS-7/Calima tagsets
                            # for any corpus the user re-tagged.
                            pos_fine=tok.pos_fine,
                            morph=tok.morph,
                            dep_head=tok.dep_head,
                            dep_rel=tok.dep_rel,
                            is_punct=tok.is_punct,
                        )
                    )
                    all_texts.add(tok.text)
                    total_tokens += 1
            recompiled += 1
        except Exception as e:
            log.error("recompile_doc_failed", doc=doc.filename, error=str(e))
            # Issue 1 fix: report per-document failures in the response body
            # instead of silently claiming success.
            failed.append({"document_id": doc.id, "filename": doc.filename, "error": str(e)})

    av.token_count = total_tokens
    av.type_count = len(all_texts)
    await session.flush()
    latest = av
    if latest:
        new_stats = dict(corpus.stats or {})
        new_stats.update(
            {
                "token_count": latest.token_count,
                "type_count": latest.type_count,
                "document_count": len(docs),
            }
        )
        corpus.stats = new_stats  # reassign triggers SQLAlchemy change detection

    # Update pipeline recipe — same pattern
    new_recipe = dict(corpus.pipeline_recipe or {})
    new_recipe.update(
        {
            "backend": info.backend,
            "model_name": info.model_name,
            "model_version": info.model_version,
            "spacy_version": info.spacy_version,
        }
    )
    corpus.pipeline_recipe = new_recipe  # reassign triggers SQLAlchemy change detection

    await session.commit()
    log.info("corpus_recompiled", cid=cid, docs=recompiled, total=len(docs))
    return {
        "recompiled": recompiled,
        "total_documents": len(docs),
        "failed": failed,
        "success": recompiled == len(docs),
        "token_count": latest.token_count if latest else 0,
        "type_count": latest.type_count if latest else 0,
    }


# --------------------------------------------------------------------------- #
# v0.1.19: Document metadata + Subcorpus management
# --------------------------------------------------------------------------- #


class DocumentMetadataUpdate(BaseModel):
    """Update a document's metadata (genre, register, year, etc.)."""

    meta: dict = Field(default_factory=dict)


@router.patch("/corpora/{cid}/documents/{did}/meta")
async def update_document_metadata(
    cid: str, did: str, body: DocumentMetadataUpdate, session: AsyncSession = Depends(get_session)
) -> dict:
    """Update a document's metadata (genre, register, year, author, etc.).

    v0.1.19: This metadata is used for subcorpus filtering — e.g., creating
    a subcorpus that only includes documents where genre="news".
    """
    doc = await session.get(Document, did)
    if not doc or doc.corpus_id != cid:
        raise HTTPException(404, "Document not found in this corpus")
    # Reassign (not in-place mutation) for SQLAlchemy change detection
    new_meta = dict(doc.meta or {})
    new_meta.update(body.meta)
    doc.meta = new_meta
    await session.commit()
    return {"ok": True, "document_id": did, "meta": new_meta}


class SubcorpusCreate(BaseModel):
    name: str = Field(..., min_length=1, max_length=128)
    description: str = ""
    filter_criteria: dict = Field(default_factory=dict)


class SubcorpusOut(BaseModel):
    id: str
    corpus_id: str
    name: str
    description: str
    filter_criteria: dict
    created_at: datetime


@router.post("/corpora/{cid}/subcorpora", response_model=SubcorpusOut)
async def create_subcorpus(
    cid: str, body: SubcorpusCreate, session: AsyncSession = Depends(get_session)
) -> SubcorpusOut:
    """Create a named subcorpus (saved filter) for a corpus.

    v0.1.19: A subcorpus is a saved filter over document metadata, e.g.:
        filter_criteria = {"genre": "news", "year_min": 2010}

    Analysis endpoints can optionally accept a subcorpus_id to restrict
    results to only matching documents.
    """
    if not await session.get(Corpus, cid):
        raise HTTPException(404, "Corpus not found")
    sc = Subcorpus(
        corpus_id=cid,
        name=body.name,
        description=body.description,
        filter_criteria=body.filter_criteria,
    )
    session.add(sc)
    await session.flush()
    return SubcorpusOut(
        id=sc.id,
        corpus_id=sc.corpus_id,
        name=sc.name,
        description=sc.description,
        filter_criteria=sc.filter_criteria,
        created_at=sc.created_at,
    )


@router.get("/corpora/{cid}/subcorpora", response_model=list[SubcorpusOut])
async def list_subcorpora(
    cid: str, session: AsyncSession = Depends(get_session)
) -> list[SubcorpusOut]:
    """List all subcorpora (saved filters) for a corpus."""
    stmt = select(Subcorpus).where(Subcorpus.corpus_id == cid).order_by(Subcorpus.created_at.desc())
    subs = (await session.execute(stmt)).scalars().all()
    return [
        SubcorpusOut(
            id=s.id,
            corpus_id=s.corpus_id,
            name=s.name,
            description=s.description,
            filter_criteria=s.filter_criteria,
            created_at=s.created_at,
        )
        for s in subs
    ]


@router.delete("/corpora/{cid}/subcorpora/{sid}")
async def delete_subcorpus(
    cid: str, sid: str, session: AsyncSession = Depends(get_session)
) -> dict:
    """Delete a subcorpus (saved filter). Does NOT delete documents."""
    sc = await session.get(Subcorpus, sid)
    if not sc or sc.corpus_id != cid:
        raise HTTPException(404, "Subcorpus not found")
    await session.delete(sc)
    await session.commit()
    return {"deleted": sid}


async def resolve_subcorpus_document_ids(session: AsyncSession, subcorpus_id: str) -> list[str]:
    """Resolve a saved subcorpus (named filter) to its matching document IDs.

    Issue 2 fix: the previous helper (``apply_subcorpus_filter``) called
    ``session.get_sync()``, which does not exist on AsyncSession, and was not
    called from anywhere — so subcorpora could be created but never used for
    analysis. The analysis handlers (concordance / frequency / collocations /
    keyness) now accept an optional ``subcorpus_id``, resolve it through this
    function, and restrict their token queries to the returned documents.

    Raises HTTPException(404) if the subcorpus does not exist. Returns the
    (possibly empty) list of matching document IDs.
    """
    sc = await session.get(Subcorpus, subcorpus_id)
    if not sc:
        raise HTTPException(404, "Subcorpus not found")
    if not sc.filter_criteria:
        return []
    # Find documents whose meta matches the filter criteria
    doc_stmt = select(Document.id).where(Document.corpus_id == sc.corpus_id)
    # Apply each filter criterion as a JSON match
    # For simple key-value pairs: meta->>'key' = 'value'
    # For year_min/year_max: meta->>'year' >= year_min
    for key, value in sc.filter_criteria.items():
        if key == "year_min":
            doc_stmt = doc_stmt.where(Document.meta["year"].as_string() >= str(value))
        elif key == "year_max":
            doc_stmt = doc_stmt.where(Document.meta["year"].as_string() <= str(value))
        else:
            doc_stmt = doc_stmt.where(Document.meta[key].as_string() == str(value))
    rows = (await session.execute(doc_stmt)).scalars().all()
    return list(rows)
