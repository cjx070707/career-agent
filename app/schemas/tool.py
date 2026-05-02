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


class CareerInsightsToolInput(BaseModel):
    user_id: str = Field(..., min_length=1)
    limit: int = Field(default=10, ge=1, le=50)


class SearchJobsToolInput(BaseModel):
    query: str = Field(..., min_length=1)
    location: Optional[str] = Field(None, description="Filter by city, e.g. 'Sydney'")
    work_type: Optional[str] = Field(None, description="Filter by work type, e.g. 'intern', 'full-time'")


class MatchResumeToJobsToolInput(BaseModel):
    resume_id: int = Field(..., gt=0)
