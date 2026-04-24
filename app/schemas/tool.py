from typing import Optional

from pydantic import BaseModel, Field


class CandidateProfileToolInput(BaseModel):
    candidate_id: int = Field(..., gt=0)


class ResumeByIdToolInput(BaseModel):
    resume_id: int = Field(..., gt=0)


class ApplicationsByUserToolInput(BaseModel):
    user_id: str = Field(..., min_length=1)
    limit: int = Field(default=10, ge=1, le=50)


class InterviewsByUserToolInput(BaseModel):
    user_id: str = Field(..., min_length=1)
    limit: int = Field(default=10, ge=1, le=50)


class SearchJobsFilters(BaseModel):
    """Structured slots forwarded to the retrieval layer.

    Both fields are optional so callers can request a loose search, a
    location-only filter, a work_type-only filter, or both together. Values
    are compared against job metadata case-insensitively as substrings.
    """

    location: Optional[str] = None
    work_type: Optional[str] = None


class SearchJobsToolInput(BaseModel):
    query: str = Field(..., min_length=1)
    filters: Optional[SearchJobsFilters] = None


class MatchResumeToJobsToolInput(BaseModel):
    resume_id: int = Field(..., gt=0)
