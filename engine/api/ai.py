"""AI Assistant endpoints — grounded chat (§11)."""
from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, Query, Request
from pydantic import BaseModel, Field
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

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

    # If no model is specified, auto-detect the first available model from the provider.
    if not req.model:
        try:
            available_models = await provider.list_models()
            if available_models:
                req.model = available_models[0]
                log.info("auto_selected_model", model=req.model, provider=req.provider)
        except Exception as e:
            log.warning("auto_select_model_failed", error=str(e))

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
                       "via Settings > Model Providers > Download models."
            )
        elif provider_name == "lmstudio":
            raise HTTPException(
                status_code=503,
                detail="LM Studio is not running or no model is loaded. "
                       "Please start LM Studio and enable the local server "
                       "(Developer > Start Local Server)."
            )
        else:
            raise HTTPException(
                status_code=503,
                detail=f"The {provider_name} provider is not available. "
                       f"Please check Settings > Model Providers."
            )

    # CRITICAL GREENLET FIX: Don't pass the request's session to answer().
    # The answer() method calls execute_tool() which opens its own session_scope()
    # — a second session on the same async engine. When two async sessions
    # coexist in the same event loop, SQLAlchemy's greenlet machinery throws
    # "greenlet_spawn has not been called; can't call await_only() here".
    # Fix: answer() uses its OWN session_scope() for ALL database operations.
    # The request session is only used to create the conversation row, then
    # committed and closed before answer() is called.
    # Issue 8: use selectinload for the conversation lookup too — the
    # api/ai.py chat endpoint still used session.get() which lazy-loads
    # turns and triggers the greenlet error on the next line.
    convo = None
    if req.conversation_id:
        stmt = (
            select(Conversation)
            .options(selectinload(Conversation.turns))
            .where(Conversation.id == req.conversation_id)
        )
        result = await session.execute(stmt)
        convo = result.scalar_one_or_none()
    if convo is None:
        convo = Conversation(provider=req.provider, model=req.model or "")
        session.add(convo)
        await session.flush()
    convo_id = convo.id
    # Commit the request session so it's fully done before answer() opens its own.
    await session.commit()

    assistant = Assistant(provider, model=req.model, corpus_id=req.corpus_id)
    try:
        turn = await assistant.answer(convo_id, req.message)
    except Exception as e:
        error_msg = str(e)
        log.error("chat_failed", error=error_msg)
        if "connection refused" in error_msg.lower() or "connect" in error_msg.lower():
            raise HTTPException(
                status_code=502,
                detail="Could not connect to the AI model. Please make sure "
                       "Ollama or LM Studio is running and a model is loaded."
            ) from e
        else:
            raise HTTPException(status_code=502, detail=f"Model call failed: {error_msg}") from e

    return ChatResponse(
        conversation_id=convo_id,
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
    stmt = (
        select(Conversation)
        .options(selectinload(Conversation.turns))
        .order_by(Conversation.updated_at.desc())
        .limit(50)
    )
    convos = (await session.execute(stmt)).scalars().all()
    return [{"id": c.id, "provider": c.provider, "model": c.model,
             "created_at": c.created_at.isoformat(), "updated_at": c.updated_at.isoformat(),
             "turn_count": len(c.turns)} for c in convos]


@router.get("/conversations/{cid}")
async def get_conversation(cid: str, session: AsyncSession = Depends(get_session)) -> dict:
    stmt = (
        select(Conversation)
        .options(selectinload(Conversation.turns))
        .where(Conversation.id == cid)
    )
    result = await session.execute(stmt)
    convo = result.scalar_one_or_none()
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


# --------------------------------------------------------------------------- #
# Issue 2: Query suggestions (pre-fabricated + dynamic)
# --------------------------------------------------------------------------- #


class DynamicSuggestionsRequest(BaseModel):
    provider: str = Field("ollama")
    model: str | None = Field(None)
    corpus_id: str | None = Field(None)
    language: str = Field("en", pattern="^(en|ar)$")
    recent_analysis: dict | None = Field(None, description="Optional: the user's most recent analysis result, for context-aware suggestions")


@router.get("/query-suggestions")
async def get_query_suggestions(
    language: str = Query("en", pattern="^(en|ar)$"),
    corpus_id: str | None = Query(None),
) -> dict:
    """Return the pre-fabricated query catalogue, always visible in the UI.

    Each suggestion has ``available`` set based on whether the user's
    current state (corpus loaded, reference installed) satisfies the
    suggestion's requirements. The UI uses this to grey out unavailable
    suggestions instead of hiding them — so the user always sees the
    full range of what CorpusMind can do.
    """
    from ai.query_suggestions import has_reference_for_language, list_prefabricated

    suggestions = list_prefabricated(language=language)

    # Determine availability flags.
    has_corpus = bool(corpus_id)
    # We need to know the corpus's language to check reference availability.
    # If no corpus is loaded, treat reference availability as False so the
    # UI greys out keyness suggestions.
    ref_available = False
    if corpus_id:
        try:
            c = await session_get_corpus(corpus_id)  # type: ignore[name-defined]
            if c is not None:
                ref_available = has_reference_for_language(c.language or "en")
        except Exception:
            pass
    else:
        # No corpus loaded — but the user might still want to see what
        # references are available. Check English (the default).
        ref_available = has_reference_for_language("en")

    for s in suggestions:
        s["available"] = True
        if s["requires_corpus"] and not has_corpus:
            s["available"] = False
            s["unavailable_reason"] = "Requires an active corpus"
        elif s["requires_reference"] and not ref_available:
            s["available"] = False
            s["unavailable_reason"] = "Requires an installed reference corpus for this language"

    return {"suggestions": suggestions, "has_corpus": has_corpus, "ref_available": ref_available}


@router.post("/query-suggestions/dynamic")
async def get_dynamic_suggestions(
    req: DynamicSuggestionsRequest,
    request: Request,
    session: AsyncSession = Depends(get_session),
) -> dict:
    """Generate LLM-powered follow-up research questions.

    Returns a merged list: pre-fabricated first (always), then dynamic.
    The dynamic part is empty when no corpus is loaded, no LLM is
    available, or the LLM returns unparseable output. The UI should
    treat this as "no dynamic suggestions available" rather than an error.
    """
    from ai.query_suggestions import (
        generate_dynamic_queries,
        list_prefabricated,
    )

    # Pre-fabricated (always present)
    out = list_prefabricated(language=req.language)

    # Dynamic (best-effort)
    dynamic: list[dict] = []
    try:
        provider = request.app.state.providers.get(req.provider)
        if provider is not None:
            # Auto-select first model if none specified.
            model = req.model
            if not model:
                try:
                    models = await provider.list_models()
                    if models:
                        model = models[0]
                except Exception:
                    pass
            if model:
                suggestions = await generate_dynamic_queries(
                    session,
                    corpus_id=req.corpus_id,
                    provider=provider,
                    model=model,
                    recent_analysis=req.recent_analysis,
                    language=req.language,
                )
                for s in suggestions:
                    dynamic.append({
                        "id": f"dyn_{abs(hash(s.query)) % 100000}",
                        "category": s.category,
                        "label": s.query[:80] + ("…" if len(s.query) > 80 else ""),
                        "query": s.query,
                        "rationale": s.rationale,
                        "requires_corpus": True,
                        "requires_reference": False,
                        "available": True,
                        "source": "dynamic",
                    })
    except Exception as e:
        log.warning("dynamic_suggestions_endpoint_failed", error=str(e))

    return {
        "suggestions": out + dynamic,
        "dynamic_count": len(dynamic),
        "provider_requested": req.provider,
        "model_used": req.model,
    }


# Helper for the query-suggestions endpoint — avoids a circular import
# by getting a fresh session only when needed.
async def session_get_corpus(corpus_id: str):
    from storage.models import Corpus
    from storage.session import session_scope
    async with session_scope() as s:
        return await s.get(Corpus, corpus_id)
