from typing import Optional

from pydantic import BaseModel, Field


class ChatRequest(BaseModel):
    user_id: str = Field(..., min_length=1, description="Stable user identifier")
    message: str = Field(..., min_length=1, description="User input message")


class ChatSource(BaseModel):
    type: str
    title: str
    snippet: str


class ChatPlan(BaseModel):
    task_type: str
    reason: str
    steps: list[str] = Field(default_factory=list)
    needs_more_context: bool = False
    missing_context: list[str] = Field(default_factory=list)
    follow_up_question: Optional[str] = None
    planner_source: Optional[str] = None


class LLMTrace(BaseModel):
    planner_source: str = "not_used"
    job_search_summary_source: str = "not_used"
    generate_source: str = "not_used"


class ChatResponse(BaseModel):
    answer: str
    memory_used: bool = False
    sources: list[ChatSource] = Field(default_factory=list)
    tool_used: Optional[str] = None
    plan: Optional[ChatPlan] = None
    tool_trace: list[str] = Field(default_factory=list)
    llm_trace: LLMTrace = Field(default_factory=LLMTrace)
