from fastapi import APIRouter

from app.schemas.chat import ChatRequest, ChatResponse
from app.services.agent_service import AgentService


router = APIRouter(tags=["chat"])


@router.post("/chat", response_model=ChatResponse)
def chat(payload: ChatRequest) -> ChatResponse:
    result = AgentService().respond(payload.user_id, payload.message)
    return ChatResponse(
        answer=result.answer,
        memory_used=result.memory_used,
        sources=result.sources,
        tool_used=result.tool_used,
        plan=result.plan,
        tool_trace=result.tool_trace,
        llm_trace=result.llm_trace,
    )
