from typing import Optional

from pydantic import BaseModel, Field


class ApplicationCreate(BaseModel):
    candidate_id: int = Field(..., gt=0)
    company: str = Field(..., min_length=1)
    job_title: str = Field(..., min_length=1)
    status: str = Field(..., min_length=1)
    note: Optional[str] = None


class ApplicationStatusUpdate(BaseModel):
    status: str = Field(..., min_length=1)
    note: Optional[str] = None
