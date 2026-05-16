from typing import Dict, List, Optional, Union

from fastapi import APIRouter, Query, status

from app.schemas.resume import ResumeCreate
from app.services.resume_service import ResumeService


router = APIRouter(tags=["resumes"])
resume_service = ResumeService()


@router.get("/resumes")
def list_resumes(user_id: Optional[str] = Query(None)) -> List[Dict[str, Union[int, str]]]:
    if user_id:
        try:
            return [resume_service.get_latest_resume(user_id)]
        except ValueError:
            return []
    return resume_service.list_resumes()


@router.post("/resumes", status_code=status.HTTP_201_CREATED)
def create_resume(payload: ResumeCreate) -> Dict[str, Union[int, str]]:
    return resume_service.create_resume(
        candidate_id=payload.candidate_id,
        title=payload.title,
        content=payload.content,
        version=payload.version,
    )
