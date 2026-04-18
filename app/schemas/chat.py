from typing import Optional

from pydantic import BaseModel, Field


class ChatRequest(BaseModel):
    user_id: str = Field(..., min_length=1, description="Stable user identifier")
    message: str = Field(..., min_length=1, description="User input message")


class ChatSource(BaseModel):
    type: str = Field(..., description="Evidence source category")
    title: str = Field(..., description="Short source title for display")
    snippet: str = Field(..., description="Short grounded evidence text")


class ChatPlan(BaseModel):
    task_type: str = Field(..., description="Machine-readable task label")
    reason: str = Field(..., description="Human-readable routing rationale")
    steps: list[str] = Field(default_factory=list)
    needs_more_context: bool = False
    missing_context: list[str] = Field(default_factory=list)
    follow_up_question: Optional[str] = None
    planner_source: Optional[str] = Field(
        default=None,
        description="Where the plan came from: router, model, or fallback",
    )


class LLMTrace(BaseModel):
    planner_source: str = Field(default="not_used")
    job_search_summary_source: str = Field(default="not_used")
    generate_source: str = Field(default="not_used")


class ChatResponse(BaseModel):
    answer: str
    memory_used: bool = False
    sources: list[ChatSource] = Field(default_factory=list)
    tool_used: Optional[str] = None
    plan: Optional[ChatPlan] = None
    tool_trace: list[str] = Field(default_factory=list)
    llm_trace: LLMTrace = Field(default_factory=LLMTrace)
