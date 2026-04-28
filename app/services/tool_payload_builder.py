from typing import Any, Dict

from app.routing.filter_extractor import extract_filters
from app.services.candidate_service import CandidateService
from app.services.profile_service import ProfileService
from app.services.resume_service import ResumeService


class ToolPayloadBuilder:
    def __init__(
        self,
        *,
        candidate_service: CandidateService,
        resume_service: ResumeService,
        profile_service: ProfileService,
    ) -> None:
        self.candidate_service = candidate_service
        self.resume_service = resume_service
        self.profile_service = profile_service

    def build(
        self,
        *,
        user_id: str,
        message: str,
        tool_name: str,
        state: Dict[str, Any],
    ) -> Dict[str, Any]:
        if tool_name == "get_candidate_profile":
            candidate = self.candidate_service.get_latest_candidate(user_id)
            return {"candidate_id": candidate["id"]}

        if tool_name == "get_resume_by_id":
            resume = self.resume_service.get_latest_resume(user_id)
            state["latest_resume_id"] = resume["id"]
            return {"resume_id": resume["id"]}

        if tool_name == "match_resume_to_jobs":
            resume_id = state.get("latest_resume_id")
            if resume_id is None:
                resume = self.resume_service.get_latest_resume(user_id)
                resume_id = resume["id"]
                state["latest_resume_id"] = resume_id
            return {"resume_id": resume_id}

        if tool_name == "search_jobs":
            resume_data = state.get("get_resume_by_id")
            query_parts = [message]
            if resume_data is not None:
                query_parts.append(str(resume_data.get("content", "")))
            query = self.profile_service.augment_job_query(user_id, " ".join(query_parts))
            payload: Dict[str, Any] = {"query": query}
            slot_filters = extract_filters(message)
            if slot_filters:
                payload["filters"] = slot_filters
            return payload

        if tool_name in {"get_applications", "get_interview_feedback", "get_career_insights"}:
            return {"user_id": user_id, "limit": 10}

        return {}
