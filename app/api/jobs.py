from fastapi import APIRouter, status
from typing import Dict, List, Union

from app.schemas.job import JobCreate
from app.services.job_service import JobService


router = APIRouter(tags=["jobs"])


@router.get("/jobs")
def list_jobs() -> List[Dict[str, Union[int, str]]]:
    return JobService().list_jobs()


@router.post("/jobs", status_code=status.HTTP_201_CREATED)
def create_job(payload: JobCreate) -> Dict[str, Union[int, str]]:
    return JobService().create_job(title=payload.title)
