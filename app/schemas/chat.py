from typing import Literal, Optional

from pydantic import BaseModel, Field

CHAT_CONTRACT_VERSION = "chat.v1"


class ChatRequest(BaseModel):
    user_id: str = Field(..., min_length=1, description="Stable user identifier")
    message: str = Field(..., min_length=1, description="User input message")


class ChatSource(BaseModel):
    type: str = Field(..., description="Evidence source category")
    title: str = Field(..., description="Short source title for display")
    snippet: str = Field(..., description="Short grounded evidence text")
    company: Optional[str] = Field(default=None, description="Hiring organization name")
    location: Optional[str] = Field(default=None, description="Job location")
    work_type: Optional[str] = Field(default=None, description="Job type such as intern or graduate")
    posted_at: Optional[str] = Field(default=None, description="Posting date")
    url: Optional[str] = Field(default=None, description="Source link")


class ChatPlan(BaseModel):
    task_type: str = Field(..., description="Machine-readable task label")
    reason: str = Field(..., description="Human-readable routing rationale")
    steps: list[str] = Field(default_factory=list)
    # Phase 1 extension: keep all new planner fields optional for
    # backward compatibility with existing router/planner outputs.
    domain: Optional[str] = None
    action: Optional[str] = None
    goal: Optional[str] = None
    subgoals: list[str] = Field(default_factory=list)
    resources: list[str] = Field(default_factory=list)
    required_context: list[str] = Field(default_factory=list)
    confidence: Optional[float] = Field(default=None, ge=0.0, le=1.0)
    plan_type: Optional[str] = None
    evidence_policy: Optional[str] = None
    stop_criteria: list[str] = Field(default_factory=list)
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
    contract_version: Literal["chat.v1"] = Field(
        default=CHAT_CONTRACT_VERSION,
        description="Stable /chat response contract version",
    )
    answer: str
    stage: str = Field(default="done", description="High-level response stage")
    memory_used: bool = False
    sources: list[ChatSource] = Field(default_factory=list)
    tool_used: Optional[str] = None
    plan: Optional[ChatPlan] = None
    tool_trace: list[str] = Field(default_factory=list)
    loop_trace: list[dict] = Field(default_factory=list)
    llm_trace: LLMTrace = Field(default_factory=LLMTrace)
