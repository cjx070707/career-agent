from app.schemas.tool import InterviewsByUserToolInput, LogInterviewToolInput
from app.services.candidate_service import CandidateService
from app.services.interview_service import InterviewService
from app.tools.base import ToolDefinition


def build_interview_tools() -> list[ToolDefinition]:
    interview_service = InterviewService()
    candidate_service = CandidateService()

    def _log_interview(payload: LogInterviewToolInput) -> dict:
        try:
            candidate = candidate_service.get_latest_candidate(payload.user_id)
        except ValueError:
            return {"error": "未找到用户信息，无法记录面试"}
        record = interview_service.create_interview(
            candidate_id=int(candidate["id"]),
            company=payload.company,
            job_title=payload.job_title,
            interview_round=payload.interview_round,
            result=payload.result,
            feedback=payload.feedback,
        )
        return {"ok": True, "interview_id": record["id"], "message": f"已记录面试：{payload.company} {payload.interview_round}（{payload.result}）"}

    return [
        ToolDefinition(
            name="get_interview_feedback",
            description="查询用户最近的面试记录和反馈，传入 user_id。",
            category="interview_history",
            input_model=InterviewsByUserToolInput,
            handler=lambda payload: interview_service.list_interviews_by_user(
                user_id=payload.user_id,
                limit=payload.limit,
            ),
        ),
        ToolDefinition(
            name="log_interview",
            description=(
                "记录一条面试经历到数据库。"
                "当用户提到'我面了某公司'/'一面通过了'/'被拒了'/'面试反馈是'等时调用。"
                "interview_round 示例：'一面' / 'HR面' / '技术面' / '终面'。"
                "result 可选值：passed（通过）/ failed（未通过）/ pending（等待结果）。"
                "调用后告知用户已记录，并可追问面试反馈细节。"
            ),
            category="interview_history",
            input_model=LogInterviewToolInput,
            handler=_log_interview,
        ),
    ]
