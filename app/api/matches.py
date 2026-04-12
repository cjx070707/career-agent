from fastapi import APIRouter

from app.schemas.match import ResumeMatchRequest, ResumeMatchResponse
from app.services.match_service import MatchService


router = APIRouter(tags=["matches"])


@router.post("/matches/resume", response_model=ResumeMatchResponse)
def match_resume(payload: ResumeMatchRequest) -> ResumeMatchResponse:
    return MatchService().match_resume_to_jobs(payload.resume_id)
