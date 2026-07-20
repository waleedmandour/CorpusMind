"""AI Assistant endpoints — grounded chat (§11)."""
from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, Request
from pydantic import BaseModel, Field
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from ai import Assistant
from ai.tools import list_tools
from app.logging import get_logger
from storage.models import Conversation
from storage.session import get_session

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
    # Confidence layer (deterministic interpretation)
    confidence: float = 1.0
    confidence_reasoning: str = ""
    needs_validation: bool = False
    mcqs: list[dict] = []


@router.post("/chat", response_model=ChatResponse)
async def chat(req: ChatRequest, request: Request, session: AsyncSession = Depends(get_session)) -> ChatResponse:
    try:
        provider = request.app.state.providers.get(req.provider)
    except Exception as e:
        raise HTTPException(status_code=400, detail=f"Provider error: {e}") from e

    if provider is None:
        raise HTTPException(
            status_code=400,
            detail=f"AI provider '{req.provider}' is not available. "
                   f"Make sure Ollama or LM Studio is running, or configure a cloud provider in Settings."
        )

    # Check if the provider is healthy before attempting the chat
    try:
        is_healthy = await provider.health()
    except Exception:
        is_healthy = False
    if not is_healthy:
        provider_name = getattr(provider, "name", req.provider)
        if provider_name == "ollama":
            raise HTTPException(
                status_code=503,
                detail="Ollama is not running or no model is loaded. "
                       "Please start Ollama and pull a model (e.g. llama3.2:3b) "
                       "via Settings → Model Providers → Download models."
            )
        elif provider_name == "lmstudio":
            raise HTTPException(
                status_code=503,
                detail="LM Studio is not running or no model is loaded. "
                       "Please start LM Studio and enable the local server "
                       "(Developer → Start Local Server)."
            )
        else:
            raise HTTPException(
                status_code=503,
                detail=f"The {provider_name} provider is not available. "
                       f"Please check Settings → Model Providers."
            )

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
        error_msg = str(e)
        log.error("chat_failed", error=error_msg)
        # Provide a user-friendly error message for common failures
        if "greenlet" in error_msg.lower():
            raise HTTPException(
                status_code=502,
                detail="The AI model encountered a database synchronization issue. "
                       "This is a known issue with async SQLAlchemy + sync LLM calls. "
                       "Please try again — if it persists, restart the engine."
            ) from e
        elif "connection refused" in error_msg.lower() or "connect" in error_msg.lower():
            raise HTTPException(
                status_code=502,
                detail="Could not connect to the AI model. Please make sure "
                       "Ollama or LM Studio is running and a model is loaded."
            ) from e
        else:
            raise HTTPException(status_code=502, detail=f"Model call failed: {error_msg}") from e

    return ChatResponse(
        conversation_id=convo.id,
        content=turn.content,
        grounded=turn.grounded,
        tool_calls=turn.tool_calls,
        evidence=[{"kind": e.kind, "ref": e.ref, "snippet": e.snippet} for e in turn.evidence],
        elapsed_ms=turn.elapsed_ms,
        provider=req.provider,
        model=req.model or getattr(provider, "default_model", ""),
        confidence=turn.confidence,
        confidence_reasoning=turn.confidence_reasoning,
        needs_validation=turn.needs_validation,
        mcqs=turn.mcqs,
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
