"""AI Assistant endpoints — grounded chat (§11)."""
from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, Request
from fastapi.responses import StreamingResponse
from pydantic import BaseModel, Field
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from ai import Assistant
from ai.tools import list_tools
from app.logging import get_logger
from storage.models import Conversation
from storage.session import get_session, session_scope

log = get_logger(__name__)
router = APIRouter()


class ChatRequest(BaseModel):
    message: str = Field(..., min_length=1)
    provider: str = Field("ollama")
    model: str | None = Field(None)
    conversation_id: str | None = Field(None)
    corpus_id: str | None = Field(None)


class ChatResponse(BaseModel):
    conversation_id: str
    content: str
    grounded: bool
    tool_calls: list[dict]
    evidence: list[dict]
    elapsed_ms: int
    provider: str
    model: str


@router.post("/chat", response_model=ChatResponse)
async def chat(req: ChatRequest, request: Request, session: AsyncSession = Depends(get_session)) -> ChatResponse:
    try:
        provider = request.app.state.providers.get(req.provider)
    except Exception as e:
        raise HTTPException(status_code=400, detail=f"Provider error: {e}")

    # Load or create conversation
    convo = None
    if req.conversation_id:
        convo = await session.get(Conversation, req.conversation_id)
    if convo is None:
        convo = Conversation(provider=req.provider, model=req.model or "")
        session.add(convo)
        await session.flush()

    assistant = Assistant(provider, model=req.model, corpus_id=req.corpus_id)
    try:
        turn = await assistant.answer(session, convo, req.message)
    except Exception as e:
        log.error("chat_failed", error=str(e))
        raise HTTPException(status_code=502, detail=f"Model call failed: {e}")

    return ChatResponse(
        conversation_id=convo.id,
        content=turn.content,
        grounded=turn.grounded,
        tool_calls=turn.tool_calls,
        evidence=[{"kind": e.kind, "ref": e.ref, "snippet": e.snippet} for e in turn.evidence],
        elapsed_ms=turn.elapsed_ms,
        provider=req.provider,
        model=req.model or getattr(provider, "default_model", ""),
    )


@router.get("/conversations")
async def list_conversations(session: AsyncSession = Depends(get_session)) -> list[dict]:
    stmt = select(Conversation).order_by(Conversation.updated_at.desc()).limit(50)
    convos = (await session.execute(stmt)).scalars().all()
    return [{"id": c.id, "provider": c.provider, "model": c.model,
             "created_at": c.created_at.isoformat(), "updated_at": c.updated_at.isoformat(),
             "turn_count": len(c.turns)} for c in convos]


@router.get("/conversations/{cid}")
async def get_conversation(cid: str, session: AsyncSession = Depends(get_session)) -> dict:
    convo = await session.get(Conversation, cid)
    if not convo:
        raise HTTPException(404, "Conversation not found")
    return {
        "id": convo.id,
        "provider": convo.provider,
        "model": convo.model,
        "created_at": convo.created_at.isoformat(),
        "updated_at": convo.updated_at.isoformat(),
        "turns": [
            {
                "idx": t.idx,
                "role": t.role,
                "content": t.content,
                "grounded": t.grounded,
                "tool_calls": t.tool_calls,
                "evidence": t.evidence,
                "elapsed_ms": t.elapsed_ms,
            }
            for t in convo.turns
        ],
    }


@router.get("/tools")
async def tools() -> dict:
    return {"tools": list_tools()}


@router.delete("/conversations/{cid}")
async def delete_conversation(cid: str, session: AsyncSession = Depends(get_session)) -> dict:
    convo = await session.get(Conversation, cid)
    if not convo:
        raise HTTPException(404, "Conversation not found")
    await session.delete(convo)
    return {"deleted": cid}
