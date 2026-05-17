import asyncio
import json
from typing import AsyncGenerator, List, Optional

from fastapi import APIRouter, Request
from fastapi.responses import StreamingResponse
from pydantic import BaseModel

from app.middleware.rate_limit import CHAT_LIMIT, limiter
from app.schemas.chat import ChatRequest, ChatResponse
from app.services.autonomous_agent_service import AutonomousAgentService
from app.services.memory_service import MemoryService


router = APIRouter(tags=["chat"])


# ---------------------------------------------------------------------------
# Session / History endpoints
# ---------------------------------------------------------------------------

class SessionSummary(BaseModel):
    session_id: str
    title: str
    created_at: str
    turn_count: int


class HistoryMessage(BaseModel):
    id: int
    role: str
    content: str
    session_id: Optional[str] = None


@router.get("/conversations/{user_id}/sessions", response_model=List[SessionSummary])
def list_sessions(user_id: str) -> List[SessionSummary]:
    """Return all sessions for a user, newest first."""
    sessions = MemoryService().list_sessions(user_id)
    return [
        SessionSummary(
            session_id=s.session_id,
            title=s.title,
            created_at=s.created_at,
            turn_count=s.turn_count,
        )
        for s in sessions
    ]


@router.get("/conversations/{user_id}/sessions/{session_id}", response_model=List[HistoryMessage])
def get_session_messages(user_id: str, session_id: str) -> List[HistoryMessage]:
    """Return all messages in a specific session."""
    turns = MemoryService().load_session_messages(user_id, session_id)
    return [
        HistoryMessage(id=t.id, role=t.role, content=t.content, session_id=t.session_id)
        for t in turns
    ]


class SaveMessageRequest(BaseModel):
    role: str
    content: str
    session_id: Optional[str] = None


@router.post("/conversations/{user_id}/message", response_model=HistoryMessage)
def save_message(user_id: str, payload: SaveMessageRequest) -> HistoryMessage:
    """Persist a single message turn (e.g. a system-generated agent note)."""
    row_id = MemoryService().save_single_turn(
        user_id=user_id,
        role=payload.role,
        content=payload.content,
        session_id=payload.session_id,
    )
    return HistoryMessage(
        id=row_id,
        role=payload.role,
        content=payload.content,
        session_id=payload.session_id,
    )


@router.get("/conversations/{user_id}", response_model=List[HistoryMessage])
def get_conversation_history(user_id: str) -> List[HistoryMessage]:
    """Return the most recent conversation turns for a user (up to 12).
    Legacy endpoint — used as fallback when no session_id available."""
    turns = MemoryService().load_recent_messages(user_id)
    return [
        HistoryMessage(id=t.id, role=t.role, content=t.content, session_id=t.session_id)
        for t in turns
    ]


# ---------------------------------------------------------------------------
# SSE helper
# ---------------------------------------------------------------------------

def _sse(event_type: str, **payload) -> str:
    """Format a single Server-Sent Event line."""
    data = json.dumps({"type": event_type, **payload}, ensure_ascii=False)
    return f"data: {data}\n\n"


# ---------------------------------------------------------------------------
# Streaming endpoint  —  autonomous agent (primary)
# ---------------------------------------------------------------------------

@router.post("/chat")
@limiter.limit(CHAT_LIMIT)
async def chat(request: Request, payload: ChatRequest) -> StreamingResponse:
    """
    SSE streaming chat endpoint backed by AutonomousAgentService.

    Event sequence:
      {"type": "status", "text": "..."}   — immediate + per-tool progress
      {"type": "answer",  "text": "...", "stage": "...",
       "tool_used": "...", "memory_used": bool, "sources": [...]}
      {"type": "done"}

    Tool-call status events arrive in real time while the agent loop runs,
    so the browser stays live even when the LLM takes 20+ seconds.
    """

    async def event_stream() -> AsyncGenerator[str, None]:
        # ── Acknowledge immediately ──────────────────────────────────
        yield _sse("status", text="🔍 正在分析请求...")

        loop = asyncio.get_event_loop()
        event_q: asyncio.Queue = asyncio.Queue()
        _DONE = object()

        def on_status(text: str) -> None:
            loop.call_soon_threadsafe(event_q.put_nowait, ("status", text))

        def on_token(text: str) -> None:
            loop.call_soon_threadsafe(event_q.put_nowait, ("token", text))

        svc = AutonomousAgentService()

        async def _run() -> None:
            try:
                return await loop.run_in_executor(
                    None,
                    lambda: svc.respond(
                        payload.user_id, payload.message,
                        on_status=on_status, on_token=on_token,
                        session_id=payload.session_id,
                    ),
                )
            finally:
                loop.call_soon_threadsafe(event_q.put_nowait, _DONE)

        task = asyncio.ensure_future(_run())

        while True:
            item = await event_q.get()
            if item is _DONE:
                break
            kind, text = item
            if kind == "status":
                yield _sse("status", text=text)
            else:
                yield _sse("token", text=text)

        try:
            result = await task
        except Exception as exc:
            yield _sse("error", text=f"服务器错误：{exc}")
            yield _sse("done")
            return

        sources_data = [s.model_dump() for s in (result.sources or [])]
        yield _sse(
            "answer",
            text=result.answer,
            stage=result.stage,
            memory_used=result.memory_used,
            tool_used=result.tool_used,
            sources=sources_data,
            tool_trace=result.tool_trace,
        )
        yield _sse("done")

    return StreamingResponse(
        event_stream(),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "X-Accel-Buffering": "no",
        },
    )


# ---------------------------------------------------------------------------
# Non-streaming fallback  (backward-compat for evals / curl testing)
# ---------------------------------------------------------------------------

@router.post("/chat/sync", response_model=ChatResponse)
@limiter.limit(CHAT_LIMIT)
def chat_sync(request: Request, payload: ChatRequest) -> ChatResponse:
    """Synchronous endpoint kept for evals and direct API testing."""
    result = AutonomousAgentService().respond(
        payload.user_id, payload.message, session_id=payload.session_id
    )
    return ChatResponse(
        answer=result.answer,
        stage=result.stage,
        memory_used=result.memory_used,
        sources=result.sources,
        tool_used=result.tool_used,
        tool_trace=result.tool_trace,
    )
