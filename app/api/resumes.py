from typing import Dict, List, Union

from fastapi import APIRouter, status

from app.schemas.resume import ResumeCreate
from app.services.resume_service import ResumeService


router = APIRouter(tags=["resumes"])
resume_service = ResumeService()


@router.get("/resumes")
def list_resumes() -> List[Dict[str, Union[int, str]]]:
    return resume_service.list_resumes()


@router.post("/resumes", status_code=status.HTTP_201_CREATED)
def create_resume(payload: ResumeCreate) -> Dict[str, Union[int, str]]:
    return resume_service.create_resume(
        candidate_id=payload.candidate_id,
        title=payload.title,
        content=payload.content,
        version=payload.version,
    )
