from fastapi import APIRouter, status
from typing import Dict, List, Union

from app.schemas.candidate import CandidateCreate
from app.services.candidate_service import CandidateService


router = APIRouter(tags=["candidates"])
candidate_service = CandidateService()


@router.get("/candidates")
def list_candidates() -> List[Dict[str, Union[int, str]]]:
    return candidate_service.list_candidates()


@router.post("/candidates", status_code=status.HTTP_201_CREATED)
def create_candidate(payload: CandidateCreate) -> Dict[str, Union[int, str]]:
    return candidate_service.create_candidate(
        name=payload.name,
        user_id=payload.user_id,
    )
