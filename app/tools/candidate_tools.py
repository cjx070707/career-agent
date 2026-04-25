from app.schemas.tool import CandidateProfileToolInput
from app.services.candidate_service import CandidateService
from app.tools.base import ToolDefinition


def build_candidate_tools() -> list[ToolDefinition]:
    candidate_service = CandidateService()
    return [
        ToolDefinition(
            name="get_candidate_profile",
            description="Fetch a candidate profile by candidate id.",
            category="candidate_profile",
            input_model=CandidateProfileToolInput,
            handler=lambda payload: candidate_service.get_candidate_by_id(
                payload.candidate_id
            ),
        )
    ]
