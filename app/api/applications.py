from typing import Dict, List, Union

from fastapi import APIRouter, HTTPException, Query, status

from app.schemas.application import ApplicationCreate, ApplicationStatusUpdate
from app.services.application_service import ApplicationService


router = APIRouter(tags=["applications"])
application_service = ApplicationService()


@router.get("/applications")
def list_applications(
    user_id: str = Query(..., min_length=1),
    limit: int = Query(10, ge=1, le=50),
) -> List[Dict[str, Union[int, str]]]:
    return application_service.list_applications_by_user(user_id=user_id, limit=limit)


@router.post("/applications", status_code=status.HTTP_201_CREATED)
def create_application(payload: ApplicationCreate) -> Dict[str, Union[int, str]]:
    try:
        return application_service.create_application(
            candidate_id=payload.candidate_id,
            company=payload.company,
            job_title=payload.job_title,
            status=payload.status,
            note=payload.note,
        )
    except ValueError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc


@router.patch("/applications/{application_id}")
def update_application_status(
    application_id: int,
    payload: ApplicationStatusUpdate,
) -> Dict[str, Union[int, str]]:
    try:
        return application_service.update_application_status(
            application_id=application_id,
            status=payload.status,
            note=payload.note,
        )
    except ValueError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
