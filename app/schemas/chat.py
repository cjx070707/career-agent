from typing import Literal, Optional

from pydantic import BaseModel, Field

CHAT_CONTRACT_VERSION = "chat.v1"


class ChatRequest(BaseModel):
    user_id: str = Field(..., min_length=1, description="Stable user identifier")
    message: str = Field(..., min_length=1, description="User input message")
    session_id: Optional[str] = Field(default=None, description="Conversation session UUID")


class ChatSource(BaseModel):
    type: str = Field(..., description="Evidence source category")
    title: str = Field(..., description="Short source title for display")
    snippet: str = Field(..., description="Short grounded evidence text")
    company: Optional[str] = Field(default=None, description="Hiring organization name")
    location: Optional[str] = Field(default=None, description="Job location")
    work_type: Optional[str] = Field(default=None, description="Job type such as intern or graduate")
    posted_at: Optional[str] = Field(default=None, description="Posting date")
    url: Optional[str] = Field(default=None, description="Source link")


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
    tool_trace: list[str] = Field(default_factory=list)
