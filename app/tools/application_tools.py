from app.schemas.tool import ApplicationsByUserToolInput, LogApplicationToolInput
from app.services.application_service import ApplicationService
from app.services.candidate_service import CandidateService
from app.tools.base import ToolDefinition


def build_application_tools() -> list[ToolDefinition]:
    application_service = ApplicationService()
    candidate_service = CandidateService()

    def _log_application(payload: LogApplicationToolInput) -> dict:
        try:
            candidate = candidate_service.get_latest_candidate(payload.user_id)
        except ValueError:
            return {"error": "未找到用户信息，无法记录投递"}
        record = application_service.create_application(
            candidate_id=int(candidate["id"]),
            company=payload.company,
            job_title=payload.job_title,
            status=payload.status,
            note=payload.note,
        )
        return {"ok": True, "application_id": record["id"], "message": f"已记录投递：{payload.company} — {payload.job_title}（{payload.status}）"}

    return [
        ToolDefinition(
            name="get_applications",
            description="查询用户最近的求职投递记录，传入 user_id。",
            category="application_history",
            input_model=ApplicationsByUserToolInput,
            handler=lambda payload: application_service.list_applications_by_user(
                user_id=payload.user_id,
                limit=payload.limit,
            ),
        ),
        ToolDefinition(
            name="log_application",
            description=(
                "记录一条求职投递记录到数据库。"
                "当用户提到'我投了某公司'/'已经投递了'/'刚申请了'/'投了简历'等时调用。"
                "status 可选值：applied（已投）/ interview（进入面试）/ offer（拿到 offer）/ rejected（被拒）。"
                "调用后告知用户已记录成功，并可询问是否有其他投递要记录。"
            ),
            category="application_history",
            input_model=LogApplicationToolInput,
            handler=_log_application,
        ),
    ]
