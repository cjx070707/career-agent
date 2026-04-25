from app.schemas.tool import InterviewsByUserToolInput
from app.services.interview_service import InterviewService
from app.tools.base import ToolDefinition


def build_interview_tools() -> list[ToolDefinition]:
    interview_service = InterviewService()
    return [
        ToolDefinition(
            name="get_interview_feedback",
            description="List recent interview feedback for a user.",
            category="interview_history",
            input_model=InterviewsByUserToolInput,
            handler=lambda payload: interview_service.list_interviews_by_user(
                user_id=payload.user_id,
                limit=payload.limit,
            ),
        )
    ]
