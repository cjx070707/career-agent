from typing import Dict, List, Union

from fastapi import APIRouter, HTTPException, Query, status

from app.schemas.interview import InterviewCreate, InterviewUpdate
from app.services.interview_service import InterviewService


router = APIRouter(tags=["interviews"])
interview_service = InterviewService()


@router.get("/interviews")
def list_interviews(
    user_id: str = Query(..., min_length=1),
    limit: int = Query(10, ge=1, le=50),
) -> List[Dict[str, Union[int, str]]]:
    return interview_service.list_interviews_by_user(user_id=user_id, limit=limit)


@router.post("/interviews", status_code=status.HTTP_201_CREATED)
def create_interview(payload: InterviewCreate) -> Dict[str, Union[int, str]]:
    try:
        return interview_service.create_interview(
            candidate_id=payload.candidate_id,
            company=payload.company,
            job_title=payload.job_title,
            interview_round=payload.interview_round,
            result=payload.result,
            feedback=payload.feedback,
        )
    except ValueError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc


@router.patch("/interviews/{interview_id}")
def update_interview(
    interview_id: int,
    payload: InterviewUpdate,
) -> Dict[str, Union[int, str]]:
    try:
        return interview_service.update_interview(
            interview_id=interview_id,
            result=payload.result,
            feedback=payload.feedback,
        )
    except ValueError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
