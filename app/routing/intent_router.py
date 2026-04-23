from typing import Any, Dict, List, Optional


# High-confidence keywords used to decide whether the router should handle a
# job search. `job_search` must be obvious enough that a planner would produce
# the same single-step plan; anything less clear is delegated to the LLM.
_JOB_SEARCH_ACTION_KEYWORDS_ZH = ("找", "搜")
_JOB_SEARCH_OBJECT_KEYWORDS_ZH = ("岗位", "招聘", "实习")
_JOB_SEARCH_KEYWORDS_EN = ("job", "jobs", "position", "positions", "vacancy", "vacancies")

# Compound-intent markers: user asks us to search AND leverage their resume in
# the same message. This needs the full 4-step plan, not a bare search.
_COMPOUND_MATCH_MARKERS = ("简历", "匹配度", "match my resume", "resume match")


class IntentRouter:
    """Rule-first router for obvious Career Hub scenarios."""

    def route(
        self,
        message: str,
        memory_context: List[str],
        profile: Dict[str, Any],
        available_tools: List[str],
        user_state: Dict[str, Any],
    ) -> Optional[Dict[str, Any]]:
        lowered_message = message.lower()
        profile_role = str(profile.get("target_role_preference", "")).strip()
        tools = set(available_tools)

        def keep_available(steps: List[str]) -> List[str]:
            return [step for step in steps if step in tools]

        has_job_search_signal = (
            any(kw in message for kw in _JOB_SEARCH_ACTION_KEYWORDS_ZH)
            or any(kw in message for kw in _JOB_SEARCH_OBJECT_KEYWORDS_ZH)
            or any(kw in lowered_message for kw in _JOB_SEARCH_KEYWORDS_EN)
        )
        has_compound_match_signal = any(
            marker in message or marker in lowered_message
            for marker in _COMPOUND_MATCH_MARKERS
        )

        # Compound intent: search + match-with-resume in one message. Fire the
        # full match planning chain before the narrower job_search branch runs.
        if has_job_search_signal and has_compound_match_signal:
            desired_steps = [
                "get_candidate_profile",
                "get_resume_by_id",
                "search_jobs",
                "match_resume_to_jobs",
            ]
            filtered_steps = keep_available(desired_steps)
            missing_tools = [step for step in desired_steps if step not in tools]
            reason = (
                "这是复合意图：用户既要搜索岗位，也要结合简历做匹配，"
                "按推荐型问题的完整链执行。"
            )
            if missing_tools:
                reason = (
                    "这是复合意图，但当前缺少部分工具能力，先按可用工具继续执行。"
                )
            return {
                "task_type": "job_match_planning",
                "reason": reason,
                "steps": filtered_steps,
                "needs_more_context": bool(missing_tools),
                "missing_context": ["tooling"] if missing_tools else [],
                "follow_up_question": (
                    "我现在缺少部分岗位匹配工具能力。要继续完整推荐的话，我需要可用的简历读取和岗位匹配能力。"
                    if missing_tools
                    else None
                ),
                "planner_source": "router",
            }

        if any(keyword in message for keyword in ("结合我的情况", "推荐适合投", "推荐适合")):
            desired_steps = [
                "get_candidate_profile",
                "get_resume_by_id",
                "search_jobs",
                "match_resume_to_jobs",
            ]
            filtered_steps = keep_available(desired_steps)
            missing_tools = [step for step in desired_steps if step not in tools]
            reason = "这是推荐型问题，需要先读画像和简历，再搜索并匹配岗位。"
            if missing_tools:
                reason = "这是推荐型问题，但当前缺少部分工具能力，先按可用工具继续执行。"
            return {
                "task_type": "job_match_planning",
                "reason": reason,
                "steps": filtered_steps,
                "needs_more_context": bool(missing_tools),
                "missing_context": ["tooling"] if missing_tools else [],
                "follow_up_question": (
                    "我现在缺少部分岗位匹配工具能力。要继续完整推荐的话，我需要可用的简历读取和岗位匹配能力。"
                    if missing_tools
                    else None
                ),
                "planner_source": "router",
            }

        if any(keyword in message for keyword in ("资料", "画像", "我是谁")):
            return {
                "task_type": "candidate_profile",
                "reason": "这是资料查询问题，直接读取候选人资料即可。",
                "steps": keep_available(["get_candidate_profile"]),
                "needs_more_context": "get_candidate_profile" not in tools,
                "missing_context": (
                    ["candidate_profile"] if "get_candidate_profile" not in tools else []
                ),
                "follow_up_question": None,
                "planner_source": "router",
            }

        if any(keyword in lowered_message for keyword in ("适合投", "适合哪些岗位")):
            if not user_state.get("has_resume", False):
                return {
                    "task_type": "job_match",
                    "reason": "这是岗位匹配问题，但当前缺少简历信息，应该先向用户追问。",
                    "steps": [],
                    "needs_more_context": True,
                    "missing_context": ["resume"],
                    "follow_up_question": "要先帮你做岗位匹配的话，我需要一份简历。你可以先上传或录入你的简历内容吗？",
                    "planner_source": "router",
                }
            return {
                "task_type": "job_match",
                "reason": "这是岗位匹配问题，直接用简历匹配岗位。",
                "steps": keep_available(["match_resume_to_jobs"]),
                "needs_more_context": "match_resume_to_jobs" not in tools,
                "missing_context": [],
                "follow_up_question": None,
                "planner_source": "router",
            }

        if has_job_search_signal:
            reason_parts = ["这是岗位搜索问题"]
            if profile_role:
                reason_parts.append(f"并结合长期偏好 {profile_role}")
            if memory_context:
                reason_parts.append("并参考最近对话")
            reason_parts.append("来搜索岗位。")
            return {
                "task_type": "job_search",
                "reason": "".join(reason_parts),
                "steps": keep_available(["search_jobs"]),
                "needs_more_context": "search_jobs" not in tools,
                "missing_context": [],
                "follow_up_question": None,
                "planner_source": "router",
            }

        return None
