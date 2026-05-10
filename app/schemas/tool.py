from typing import Optional

from pydantic import BaseModel, Field


class CandidateProfileToolInput(BaseModel):
    user_id: str = Field(..., min_length=1, description="The user_id of the candidate")


class ResumeByIdToolInput(BaseModel):
    user_id: str = Field(..., min_length=1, description="The user_id whose latest resume to fetch")


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
    user_id: str = Field(..., min_length=1, description="The user_id whose resume to match against jobs")


class LogApplicationToolInput(BaseModel):
    user_id: str = Field(..., min_length=1)
    company: str = Field(..., min_length=1, description="公司名称，e.g. 'Canva'")
    job_title: str = Field(..., min_length=1, description="岗位名称，e.g. '后端实习'")
    status: str = Field(..., description="投递状态：applied / interview / offer / rejected")
    note: Optional[str] = Field(None, description="备注，e.g. '通过 LinkedIn 投递'")


class LogInterviewToolInput(BaseModel):
    user_id: str = Field(..., min_length=1)
    company: str = Field(..., min_length=1, description="公司名称")
    job_title: str = Field(..., min_length=1, description="岗位名称")
    interview_round: str = Field(..., description="面试轮次，e.g. '一面' / 'HR面' / '终面'")
    result: str = Field(..., description="面试结果：passed / failed / pending")
    feedback: Optional[str] = Field(None, description="面试反馈或个人复盘")
