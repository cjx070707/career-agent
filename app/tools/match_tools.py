from app.schemas.tool import MatchResumeToJobsToolInput
from app.services.match_service import MatchService
from app.services.resume_service import ResumeService
from app.tools.base import ToolDefinition


def build_match_tools() -> list[ToolDefinition]:
    match_service = MatchService()
    resume_service = ResumeService()

    def _match(payload: MatchResumeToJobsToolInput) -> dict:
        resume = resume_service.get_latest_resume(payload.user_id)
        if not resume or not resume.get("id"):
            return {"error": "未找到简历，请先上传简历"}
        return match_service.match_resume_to_jobs(resume["id"]).model_dump()

    return [
        ToolDefinition(
            name="match_resume_to_jobs",
            description=(
                "根据用户简历内容，从岗位库中匹配最相关的岗位，返回匹配度和关键词。"
                "当用户想了解哪些岗位适合自己时调用，传入 user_id。"
            ),
            category="job_match",
            input_model=MatchResumeToJobsToolInput,
            handler=_match,
        )
    ]
