import asyncio
import json
import queue as _queue_module
from typing import AsyncGenerator

from fastapi import APIRouter
from fastapi.responses import StreamingResponse

from app.schemas.chat import ChatRequest, ChatResponse
from app.services.agent_service import AgentService
from app.services.autonomous_agent_service import AutonomousAgentService


router = APIRouter(tags=["chat"])

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
async def chat(payload: ChatRequest) -> StreamingResponse:
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
        # Thread-safe bridge: worker thread → async queue → SSE
        status_q: asyncio.Queue[str] = asyncio.Queue()
        _DONE = object()  # sentinel

        def on_status(text: str) -> None:
            # Called from the thread-pool thread; forward to the async loop.
            loop.call_soon_threadsafe(status_q.put_nowait, text)

        svc = AutonomousAgentService()

        # Run respond() in a thread so the event loop stays free to flush SSE.
        async def _run() -> None:
            try:
                return await loop.run_in_executor(
                    None,
                    lambda: svc.respond(payload.user_id, payload.message, on_status=on_status),
                )
            finally:
                loop.call_soon_threadsafe(status_q.put_nowait, _DONE)

        task = asyncio.ensure_future(_run())

        # Stream status events until the sentinel arrives
        while True:
            item = await status_q.get()
            if item is _DONE:
                break
            yield _sse("status", text=item)

        # Collect the final result (or surface the exception)
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
