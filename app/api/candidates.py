from fastapi import APIRouter, Query, status
from typing import Dict, List, Optional, Union

from app.schemas.candidate import CandidateCreate
from app.services.candidate_service import CandidateService


router = APIRouter(tags=["candidates"])
candidate_service = CandidateService()


@router.get("/candidates")
def list_candidates(user_id: Optional[str] = Query(None)) -> List[Dict[str, Union[int, str]]]:
    if user_id:
        try:
            return [candidate_service.get_latest_candidate(user_id)]
        except ValueError:
            return []
    return candidate_service.list_candidates()


@router.post("/candidates", status_code=status.HTTP_201_CREATED)
def create_candidate(payload: CandidateCreate) -> Dict[str, Union[int, str]]:
    return candidate_service.create_candidate(
        name=payload.name,
        user_id=payload.user_id,
    )
