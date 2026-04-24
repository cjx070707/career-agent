from typing import Optional

from pydantic import BaseModel, Field


class InterviewCreate(BaseModel):
    candidate_id: int = Field(..., gt=0)
    company: str = Field(..., min_length=1)
    job_title: str = Field(..., min_length=1)
    interview_round: str = Field(..., min_length=1)
    result: str = Field(..., min_length=1)
    feedback: Optional[str] = None


class InterviewUpdate(BaseModel):
    result: str = Field(..., min_length=1)
    feedback: Optional[str] = None
