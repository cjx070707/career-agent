from typing import Optional

from pydantic import BaseModel, Field


class CandidateCreate(BaseModel):
    name: str = Field(..., min_length=1)
    user_id: Optional[str] = None


class Candidate(BaseModel):
    id: Optional[int] = None
    name: str
    user_id: Optional[str] = None
