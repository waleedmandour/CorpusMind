"""AI Assistant endpoints — grounded chat round-trip (§11)."""
from __future__ import annotations

from fastapi import APIRouter, HTTPException, Request
from fastapi.responses import StreamingResponse
from pydantic import BaseModel, Field

from ai import Assistant, Conversation

router = APIRouter()


# In-memory conversation store for Phase 0.
# Phase 1+ persists to SQLite (storage/) and surfaces a proper session API.
_CONVERSATIONS: dict[str, Conversation] = {}


class ChatRequest(BaseModel):
    message: str = Field(..., min_length=1, description="User's question to the Assistant.")
    provider: str = Field("ollama", description="Model provider: ollama | lmstudio | cloud")
    model: str | None = Field(None, description="Specific model name. Falls back to provider default.")
    conversation_id: str | None = Field(None, description="Continue an existing conversation.")


class ChatResponse(BaseModel):
    conversation_id: str
    content: str
    grounded: bool
    tool_calls: list[dict]
    elapsed_ms: int
    provider: str
    model: str


@router.post("/chat", response_model=ChatResponse)
async def chat(req: ChatRequest, request: Request) -> ChatResponse:
    """Grounded chat round-trip.

    The response carries `grounded: bool`. The UI MUST render ungrounded answers
    with a visible badge — this is the load-bearing implementation of §11.1.
    """
    try:
        provider = request.app.state.providers.get(req.provider)
    except Exception as e:
        raise HTTPException(status_code=400, detail=f"Provider error: {e}")

    convo = _CONVERSATIONS.get(req.conversation_id) if req.conversation_id else None
    if convo is None:
        convo = Conversation(provider=req.provider, model=req.model or "")
        _CONVERSATIONS[convo.id] = convo
    elif req.model and not convo.model:
        convo.model = req.model

    assistant = Assistant(provider, request.app.state.tools, model=req.model)
    try:
        turn = await assistant.answer(convo, req.message)
    except Exception as e:
        raise HTTPException(status_code=502, detail=f"Model call failed: {e}")

    return ChatResponse(
        conversation_id=convo.id,
        content=turn.content,
        grounded=turn.grounded,
        tool_calls=turn.tool_calls,
        elapsed_ms=turn.elapsed_ms,
        provider=req.provider,
        model=req.model or getattr(provider, "default_model", ""),
    )


class StreamRequest(BaseModel):
    message: str
    provider: str = "ollama"
    model: str | None = None


@router.post("/chat/stream")
async def chat_stream(req: StreamRequest, request: Request) -> StreamingResponse:
    """Minimal SSE streaming endpoint — full grounded-streaming lands in Phase 1
    alongside tool-calling loop. Phase 0 returns plain text chunks from the model
    for UI plumbing validation only."""
    try:
        provider = request.app.state.providers.get(req.provider)
    except Exception as e:
        raise HTTPException(status_code=400, detail=f"Provider error: {e}")

    from ai.providers import Message

    msgs = [
        Message(role="system", content="You are the CorpusMind AI Assistant. Reply concisely."),
        Message(role="user", content=req.message),
    ]

    async def gen():
        try:
            async for chunk in provider.stream(msgs, model=req.model):
                # SSE framing
                yield f"data: {chunk}\n\n"
            yield "data: [DONE]\n\n"
        except Exception as e:
            yield f"data: [ERROR] {e}\n\n"

    return StreamingResponse(gen(), media_type="text/event-stream")


@router.get("/conversations/{cid}")
async def get_conversation(cid: str) -> dict:
    convo = _CONVERSATIONS.get(cid)
    if convo is None:
        raise HTTPException(status_code=404, detail="Conversation not found")
    return convo.to_export()


@router.get("/tools")
async def list_tools(request: Request) -> dict:
    """List the deterministic tools the Assistant is allowed to call (§11.2)."""
    tools = request.app.state.tools
    return {"tools": [{"name": s.name, "description": s.description} for s in tools._tools.values()]}
