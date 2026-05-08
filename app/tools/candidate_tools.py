from app.schemas.tool import CandidateProfileToolInput
from app.services.candidate_service import CandidateService
from app.tools.base import ToolDefinition


def build_candidate_tools() -> list[ToolDefinition]:
    candidate_service = CandidateService()
    return [
        ToolDefinition(
            name="get_candidate_profile",
            description=(
                "获取当前用户的候选人基本信息（姓名、注册信息）。"
                "当需要了解用户基本资料时调用，传入 user_id。"
            ),
            category="candidate_profile",
            input_model=CandidateProfileToolInput,
            handler=lambda payload: candidate_service.get_latest_candidate(
                payload.user_id
            ),
        )
    ]
