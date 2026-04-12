from pydantic import BaseModel, Field


class CandidateProfileToolInput(BaseModel):
    candidate_id: int = Field(..., gt=0)


class ResumeByIdToolInput(BaseModel):
    resume_id: int = Field(..., gt=0)


class SearchJobsToolInput(BaseModel):
    query: str = Field(..., min_length=1)


class MatchResumeToJobsToolInput(BaseModel):
    resume_id: int = Field(..., gt=0)
