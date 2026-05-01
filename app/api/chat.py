import asyncio
import json
from typing import AsyncGenerator

from fastapi import APIRouter
from fastapi.responses import StreamingResponse

from app.schemas.chat import ChatRequest, ChatResponse
from app.services.agent_service import AgentService


router = APIRouter(tags=["chat"])

# ---------------------------------------------------------------------------
# SSE helper
# ---------------------------------------------------------------------------

def _sse(event_type: str, **payload) -> str:
    """Format a single Server-Sent Event line."""
    data = json.dumps({"type": event_type, **payload}, ensure_ascii=False)
    return f"data: {data}\n\n"


# ---------------------------------------------------------------------------
# Streaming endpoint  (primary)
# ---------------------------------------------------------------------------

@router.post("/chat")
async def chat(payload: ChatRequest) -> StreamingResponse:
    """
    SSE streaming chat endpoint.

    Event sequence:
      {"type": "status", "text": "..."}   — progress updates (arrive immediately)
      {"type": "answer",  "text": "...", "stage": "...", "sources": [...],
       "tool_used": "...", "memory_used": bool}  — final answer
      {"type": "done"}                    — stream closed

    Clients should use EventSource / fetch with ReadableStream.
    The first status event arrives within ~1 s so the browser connection
    stays alive regardless of how long the LLM calls take.
    """

    async def event_stream() -> AsyncGenerator[str, None]:
        # ── 1. Acknowledge immediately so the browser knows we're alive ──
        yield _sse("status", text="🔍 正在分析请求...")

        svc = AgentService()

        # ── 2. Run the blocking respond() in a thread pool ──────────────
        # This keeps the async event loop free to flush SSE frames.
        loop = asyncio.get_event_loop()
        try:
            result = await loop.run_in_executor(
                None, svc.respond, payload.user_id, payload.message
            )
        except Exception as exc:
            yield _sse("error", text=f"服务器错误：{exc}")
            yield _sse("done")
            return

        # ── 3. Emit the answer with the same fields as ChatResponse ─────
        sources_data = [s.model_dump() for s in (result.sources or [])]
        yield _sse(
            "answer",
            text=result.answer,
            stage=result.stage,
            memory_used=result.memory_used,
            tool_used=result.tool_used,
            sources=sources_data,
        )
        yield _sse("done")

    return StreamingResponse(
        event_stream(),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "X-Accel-Buffering": "no",   # disable nginx buffering
        },
    )


# ---------------------------------------------------------------------------
# Non-streaming fallback  (backward-compat for evals / curl testing)
# ---------------------------------------------------------------------------

@router.post("/chat/sync", response_model=ChatResponse)
def chat_sync(payload: ChatRequest) -> ChatResponse:
    """Synchronous endpoint kept for evals and direct API testing."""
    result = AgentService().respond(payload.user_id, payload.message)
    return ChatResponse(
        answer=result.answer,
        stage=result.stage,
        memory_used=result.memory_used,
        sources=result.sources,
        tool_used=result.tool_used,
        plan=result.plan,
        tool_trace=result.tool_trace,
        loop_trace=result.loop_trace,
        llm_trace=result.llm_trace,
    )
