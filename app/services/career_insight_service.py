from collections import Counter
from typing import Dict, List, Optional, Union

from app.services.application_service import ApplicationService
from app.services.career_event_service import CareerEventService
from app.services.interview_service import InterviewService
from app.services.profile_service import ProfileService
from app.services.retrieval_service import RetrievalService


class CareerInsightService:
    def __init__(
        self,
        profile_service: Optional[ProfileService] = None,
        application_service: Optional[ApplicationService] = None,
        interview_service: Optional[InterviewService] = None,
        retrieval_service: Optional[RetrievalService] = None,
        career_event_service: Optional[CareerEventService] = None,
    ) -> None:
        self.profile_service = profile_service or ProfileService()
        self.application_service = application_service or ApplicationService()
        self.interview_service = interview_service or InterviewService()
        self.retrieval_service = retrieval_service or RetrievalService()
        self.career_event_service = career_event_service or CareerEventService(
            retrieval_service=self.retrieval_service,
        )

    def get_career_insights(
        self,
        user_id: str,
        limit: int = 10,
    ) -> Dict[str, Union[Dict, List[str]]]:
        safe_limit = max(1, min(int(limit), 50))
        profile = self.profile_service.refresh_from_career_records(user_id)
        self.retrieval_service.upsert_career_profile(user_id=user_id, profile=profile)
        self.career_event_service.sync_from_career_records(user_id)
        applications = self.application_service.list_applications_by_user(
            user_id=user_id,
            limit=safe_limit,
        )
        interviews = self.interview_service.list_interviews_by_user(
            user_id=user_id,
            limit=safe_limit,
        )

        feedback_highlights = [
            str(item.get("feedback", "")).strip()
            for item in interviews
            if str(item.get("feedback", "")).strip()
        ][:3]

        strengths = self._build_strengths(profile=profile, applications=applications)
        risk_areas = self._build_risk_areas(
            applications=applications,
            interviews=interviews,
            feedback_highlights=feedback_highlights,
        )
        next_actions = self._build_suggestions(
            profile=profile,
            applications=applications,
            interviews=interviews,
            feedback_highlights=feedback_highlights,
        )

        return {
            "profile": profile,
            "application_summary": {
                "total": len(applications),
                "status_counts": self._sorted_counts(
                    str(item.get("status", "")).strip() for item in applications
                ),
                "recent": applications,
            },
            "interview_summary": {
                "total": len(interviews),
                "result_counts": self._sorted_counts(
                    str(item.get("result", "")).strip() for item in interviews
                ),
                "feedback_highlights": feedback_highlights,
                "recent": interviews,
            },
            "strengths": strengths,
            "risk_areas": risk_areas,
            "next_actions": next_actions,
            "source_summary": self._build_source_summary(applications, interviews),
            "suggestions": next_actions,
        }

    def _sorted_counts(self, values) -> Dict[str, int]:
        counts = Counter(value for value in values if value)
        return {key: counts[key] for key in sorted(counts)}

    def _build_suggestions(
        self,
        profile: Dict[str, object],
        applications: List[Dict[str, Union[int, str]]],
        interviews: List[Dict[str, Union[int, str]]],
        feedback_highlights: List[str],
    ) -> List[str]:
        suggestions: List[str] = []
        if not profile.get("target_role_preference"):
            suggestions.append("先明确目标方向，方便后续投递和准备更聚焦。")

        if not applications and not interviews:
            suggestions.append("先补充投递记录和面试反馈，我才能更准确地判断求职状态。")

        application_statuses = {
            str(item.get("status", "")).strip().lower() for item in applications
        }
        progressed_statuses = {"interview", "interviewing", "offered", "offer"}
        if applications and not (application_statuses & progressed_statuses):
            suggestions.append("目前投递进展偏早期，可以检查简历命中度并优先跟进高匹配岗位。")

        if feedback_highlights:
            suggestions.append(f"围绕 {feedback_highlights[0]} 继续准备。")

        rejected_interviews = [
            item for item in interviews if str(item.get("result", "")).lower() == "rejected"
        ]
        if rejected_interviews and not feedback_highlights:
            suggestions.append("复盘未通过轮次，补充具体反馈后可以定位共性短板。")

        return suggestions[:3]

    def _build_strengths(
        self,
        profile: Dict[str, object],
        applications: List[Dict[str, Union[int, str]]],
    ) -> List[str]:
        strengths: List[str] = []
        role = str(profile.get("target_role_preference") or "").strip()
        skills = [
            str(item).strip()
            for item in profile.get("skill_keywords", [])
            if str(item).strip()
        ]
        if role:
            strengths.append(f"目标方向已聚焦在 {role}。")
        if skills:
            strengths.append(f"已沉淀技能关键词：{', '.join(skills[:4])}。")
        progressed = [
            item for item in applications
            if str(item.get("status", "")).strip().lower()
            in {"interview", "interviewing", "offered", "offer"}
        ]
        if progressed:
            strengths.append("已有投递进入面试或后续阶段，可以复用相关申请素材。")
        return strengths[:3]

    def _build_risk_areas(
        self,
        applications: List[Dict[str, Union[int, str]]],
        interviews: List[Dict[str, Union[int, str]]],
        feedback_highlights: List[str],
    ) -> List[str]:
        risk_areas: List[str] = []
        if feedback_highlights:
            risk_areas.append(f"面试反馈暴露短板：{feedback_highlights[0]}。")

        rejected_interviews = [
            item for item in interviews
            if str(item.get("result", "")).strip().lower() == "rejected"
        ]
        if rejected_interviews:
            risk_areas.append("存在未通过面试记录，需要复盘共性原因。")

        application_statuses = {
            str(item.get("status", "")).strip().lower() for item in applications
        }
        if applications and application_statuses <= {"applied", "submitted"}:
            risk_areas.append("投递主要停留在早期状态，需要提升简历命中和跟进策略。")

        return risk_areas[:3]

    def _build_source_summary(
        self,
        applications: List[Dict[str, Union[int, str]]],
        interviews: List[Dict[str, Union[int, str]]],
    ) -> List[Dict[str, str]]:
        sources: List[Dict[str, str]] = []
        for item in applications[:3]:
            sources.append(
                {
                    "type": "application",
                    "title": f"{item.get('company', '')} - {item.get('job_title', '')}".strip(" -"),
                    "snippet": f"状态：{item.get('status', '')}；备注：{item.get('note', '')}".strip(),
                }
            )
        for item in interviews[:3]:
            sources.append(
                {
                    "type": "interview_feedback",
                    "title": f"{item.get('company', '')} - {item.get('job_title', '')}".strip(" -"),
                    "snippet": (
                        f"轮次：{item.get('interview_round', '')}；"
                        f"结果：{item.get('result', '')}；"
                        f"反馈：{item.get('feedback', '')}"
                    ).strip(),
                }
            )
        return sources
