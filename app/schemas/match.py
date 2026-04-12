from pydantic import BaseModel, Field


class ResumeMatchRequest(BaseModel):
    resume_id: int = Field(..., gt=0)


class JobMatch(BaseModel):
    job_title: str
    match_score: int
    matched_keywords: list[str]
    rationale: str


class ResumeMatchResponse(BaseModel):
    resume_id: int
    matches: list[JobMatch]
