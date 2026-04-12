from app.schemas.tool import MatchResumeToJobsToolInput
from app.services.match_service import MatchService
from app.tools.base import ToolDefinition


def build_match_tools() -> list[ToolDefinition]:
    match_service = MatchService()
    return [
        ToolDefinition(
            name="match_resume_to_jobs",
            description="Match a resume against jobs and return structured matches.",
            input_model=MatchResumeToJobsToolInput,
            handler=lambda payload: match_service.match_resume_to_jobs(
                payload.resume_id
            ).model_dump(),
        )
    ]
