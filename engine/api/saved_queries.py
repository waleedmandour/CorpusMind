"""Saved analysis queries, per project (v1.2.13-2).

Teacher-only CRUD — deliberately OFF the student allowlist (see
app/server_mode.py): saved queries are shared project resources under the
teacher token, and student saves would clutter the shared class space.

CQL queries are validated at save time so a broken pattern can never be
stored; the response echoes the parsed canonical form.
"""
from __future__ import annotations

from datetime import UTC, datetime

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from stats.cql import ast_to_str, parse_cql
from storage.models import Corpus, Project, SavedQuery
from storage.session import get_session

router = APIRouter()


class SavedQueryIn(BaseModel):
    project_id: str
    corpus_id: str | None = None
    name: str = Field(..., min_length=1, max_length=128)
    query: str = Field(..., min_length=1)
    mode: str = Field("cql", pattern="^(cql|simple)$")
    note: str = ""


class SavedQueryOut(BaseModel):
    id: str
    project_id: str
    corpus_id: str | None
    name: str
    query: str
    parsed: str | None = None
    mode: str
    note: str
    created_at: datetime


def _out(q: SavedQuery) -> SavedQueryOut:
    parsed = None
    if q.mode == "cql":
        try:
            parsed = ast_to_str(parse_cql(q.query))
        except Exception:
            parsed = None  # stored queries re-validate lazily on render
    return SavedQueryOut(
        id=q.id,
        project_id=q.project_id,
        corpus_id=q.corpus_id,
        name=q.name,
        query=q.query,
        parsed=parsed,
        mode=q.mode,
        note=q.note,
        created_at=q.created_at,
    )


@router.post("/projects/{pid}/saved-queries", response_model=SavedQueryOut)
async def create_saved_query(pid: str, body: SavedQueryIn, session: AsyncSession = Depends(get_session)) -> SavedQueryOut:
    if not await session.get(Project, pid):
        raise HTTPException(404, "Project not found")
    if body.corpus_id and not await session.get(Corpus, body.corpus_id):
        raise HTTPException(404, "Corpus not found")
    if body.mode == "cql":
        try:
            parse_cql(body.query)
        except Exception as exc:  # CqlSyntaxError
            raise HTTPException(422, detail=f"Invalid CQL query: {exc}") from exc
    q = SavedQuery(
        project_id=pid,
        corpus_id=body.corpus_id,
        name=body.name,
        query=body.query,
        mode=body.mode,
        note=body.note,
    )
    session.add(q)
    await session.flush()
    return _out(q)


@router.get("/projects/{pid}/saved-queries", response_model=list[SavedQueryOut])
async def list_saved_queries(pid: str, corpus_id: str | None = None, session: AsyncSession = Depends(get_session)) -> list[SavedQueryOut]:
    if not await session.get(Project, pid):
        raise HTTPException(404, "Project not found")
    stmt = select(SavedQuery).where(SavedQuery.project_id == pid).order_by(SavedQuery.created_at.desc())
    if corpus_id:
        stmt = stmt.where(SavedQuery.corpus_id == corpus_id)
    return [_out(q) for q in (await session.execute(stmt)).scalars().all()]


@router.delete("/projects/{pid}/saved-queries/{qid}")
async def delete_saved_query(pid: str, qid: str, session: AsyncSession = Depends(get_session)) -> dict:
    q = await session.get(SavedQuery, qid)
    if not q or q.project_id != pid:
        raise HTTPException(404, "Saved query not found")
    await session.delete(q)
    await session.commit()
    return {"deleted": qid}
