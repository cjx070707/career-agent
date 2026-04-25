from app.schemas.tool import ResumeByIdToolInput
from app.services.resume_service import ResumeService
from app.tools.base import ToolDefinition


def build_resume_tools() -> list[ToolDefinition]:
    resume_service = ResumeService()
    return [
        ToolDefinition(
            name="get_resume_by_id",
            description="Fetch a resume by resume id.",
            category="resume",
            input_model=ResumeByIdToolInput,
            handler=lambda payload: resume_service.get_resume_by_id(payload.resume_id),
        )
    ]
