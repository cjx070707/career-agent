from app.schemas.tool import ApplicationsByUserToolInput
from app.services.application_service import ApplicationService
from app.tools.base import ToolDefinition


def build_application_tools() -> list[ToolDefinition]:
    application_service = ApplicationService()
    return [
        ToolDefinition(
            name="get_applications",
            description="List recent job applications for a user.",
            input_model=ApplicationsByUserToolInput,
            handler=lambda payload: application_service.list_applications_by_user(
                user_id=payload.user_id,
                limit=payload.limit,
            ),
        )
    ]
