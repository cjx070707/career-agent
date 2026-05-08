from app.schemas.tool import ResumeByIdToolInput
from app.services.resume_service import ResumeService
from app.tools.base import ToolDefinition


def build_resume_tools() -> list[ToolDefinition]:
    resume_service = ResumeService()
    return [
        ToolDefinition(
            name="get_resume_by_id",
            description=(
                "获取用户最新简历的完整内容。"
                "当需要查看用户简历、或用户询问自己简历内容时调用，传入 user_id。"
            ),
            category="resume",
            input_model=ResumeByIdToolInput,
            handler=lambda payload: resume_service.get_latest_resume(payload.user_id),
        )
    ]
