from typing import Optional

from pydantic import BaseModel, Field


class ResumeCreate(BaseModel):
    candidate_id: int
    title: str = Field(..., min_length=1)
    content: str = Field(..., min_length=1)
    version: str = Field(..., min_length=1)


class Resume(BaseModel):
    id: Optional[int] = None
    candidate_id: int
    title: str
    content: str
    version: str
