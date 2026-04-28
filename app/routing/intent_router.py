from typing import Any, Dict, List, Optional

from app.routing.intent_signals import collect_intent_signals
from app.routing.router_plan_factory import build_router_plan


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
        stripped_message = message.strip()
        profile_role = str(profile.get("target_role_preference", "")).strip()
        tools = set(available_tools)

        def keep_available(steps: List[str]) -> List[str]:
            return [step for step in steps if step in tools]

        signals = collect_intent_signals(message, lowered_message, stripped_message)

        if signals.is_greeting:
            return build_router_plan(
                task_type="fallback",
                reason="这是简单寒暄，不需要调用 Planner 或工具。",
                steps=[],
                needs_more_context=False,
                missing_context=[],
                follow_up_question=None,
                domain="conversation",
                action="greeting",
                goal="Respond with a brief greeting and ask how to help.",
                confidence=0.99,
                plan_type="direct",
                evidence_policy="none",
                stop_criteria=["greeting completed"],
            )

        if signals.has_capability_help:
            return build_router_plan(
                task_type="fallback",
                reason="这是能力说明请求，直接返回本地能力说明，无需调用 Planner 或工具。",
                steps=[],
                needs_more_context=False,
                missing_context=[],
                follow_up_question=None,
                domain="conversation",
                action="capability_help",
                goal="Explain core capabilities in a concise local response.",
                confidence=0.99,
                plan_type="direct",
                evidence_policy="none",
                stop_criteria=["capability help provided"],
            )

        if signals.has_resume_presence_query:
            has_resume = bool(user_state.get("has_resume", False))
            return build_router_plan(
                task_type="resume_analysis",
                reason="这是简历是否存在的查询，优先本地读取简历状态。",
                steps=keep_available(["get_resume_by_id"]) if has_resume else [],
                needs_more_context=not has_resume,
                missing_context=["resume"] if not has_resume else [],
                follow_up_question=(
                    "我还没有读取到你的简历。请上传简历文件，或直接粘贴简历文本。"
                    if not has_resume
                    else None
                ),
                domain="resume_analysis",
                action="summarize",
                goal="Check whether resume exists and summarize when available.",
                resources=["resume"],
                required_context=["resume"],
                confidence=0.97,
                plan_type="analysis",
                evidence_policy="use_existing",
                stop_criteria=["resume presence confirmed", "missing resume confirmed"],
            )

        if signals.is_third_party:
            return build_router_plan(
                task_type="fallback",
                reason="这是第三方求职建议，不应读取或更新当前用户画像。",
                steps=[],
                needs_more_context=False,
                missing_context=[],
                follow_up_question=None,
                domain="career_advice",
                action="advise",
                goal="Give general preparation advice for the third-party target role.",
                subgoals=[
                    "identify target role from message",
                    "provide practical preparation checklist",
                ],
                resources=["general_job_market_knowledge"],
                required_context=[],
                confidence=0.95,
                plan_type="third_party_advice",
                evidence_policy="general_advice_only",
                stop_criteria=["actionable checklist provided"],
            )

        if signals.has_resume_summary:
            has_resume = bool(user_state.get("has_resume", False))
            return build_router_plan(
                task_type="resume_analysis",
                reason="这是简历总结请求，需要先读取简历。",
                steps=keep_available(["get_resume_by_id"]) if has_resume else [],
                needs_more_context=not has_resume,
                missing_context=["resume"] if not has_resume else [],
                follow_up_question=(
                    "我需要你的简历内容才能总结。请上传简历文件，或粘贴简历文本。"
                    if not has_resume
                    else None
                ),
                domain="resume_analysis",
                action="summarize",
                goal="Summarize the user's resume highlights and positioning.",
                subgoals=["load resume", "extract strengths", "summarize positioning"],
                resources=["resume"],
                required_context=["resume"],
                confidence=0.94,
                plan_type="analysis",
                evidence_policy="use_existing",
                stop_criteria=["resume summary completed", "missing resume confirmed"],
            )

        if signals.has_job_fit and not (signals.has_job_search and signals.has_compound_match):
            has_resume = bool(user_state.get("has_resume", False))
            has_job_detail = bool(user_state.get("has_job_detail", False))
            missing_context = []
            if not has_resume:
                missing_context.append("resume")
            if not has_job_detail:
                missing_context.append("job_detail")
            return build_router_plan(
                task_type="job_match",
                reason="这是岗位适配判断请求，需要简历与岗位详情进行对比。",
                steps=keep_available(["match_resume_to_jobs"]) if not missing_context else [],
                needs_more_context=bool(missing_context),
                missing_context=missing_context,
                follow_up_question=(
                    "请提供岗位 JD / 招聘链接 / 岗位描述，我才能评估你是否匹配。"
                    if "job_detail" in missing_context
                    else (
                        "我还需要你的简历才能做岗位匹配，请先上传或粘贴简历内容。"
                        if "resume" in missing_context
                        else None
                    )
                ),
                domain="job_match",
                action="compare",
                goal="Compare resume evidence with job requirements and estimate fit.",
                subgoals=["collect resume evidence", "collect job requirements", "output fit judgement"],
                resources=["resume", "job_detail"],
                required_context=["resume", "job_detail"],
                confidence=0.93,
                plan_type="matching",
                evidence_policy="use_existing",
                stop_criteria=["fit judgement produced", "critical context missing"],
            )

        # Compound intent: search + match-with-resume in one message. Fire the
        # full match planning chain before the narrower job_search branch runs.
        if signals.has_job_search and signals.has_compound_match:
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
            return build_router_plan(
                task_type="job_match_planning",
                reason=reason,
                steps=filtered_steps,
                needs_more_context=bool(missing_tools),
                missing_context=["tooling"] if missing_tools else [],
                follow_up_question=(
                    "我现在缺少部分岗位匹配工具能力。要继续完整推荐的话，我需要可用的简历读取和岗位匹配能力。"
                    if missing_tools
                    else None
                ),
                domain="job_match",
                action="recommend",
                goal="Find suitable jobs and score them against the user resume.",
                subgoals=["load profile", "load resume", "search jobs", "match jobs"],
                resources=["profile", "resume", "jobs"],
                required_context=["resume", "job_query"],
                confidence=0.92,
                plan_type="matching",
                evidence_policy="use_existing",
                stop_criteria=["recommended jobs returned", "tooling missing"],
            )

        if signals.has_recommend_match:
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
            return build_router_plan(
                task_type="job_match_planning",
                reason=reason,
                steps=filtered_steps,
                needs_more_context=bool(missing_tools),
                missing_context=["tooling"] if missing_tools else [],
                follow_up_question=(
                    "我现在缺少部分岗位匹配工具能力。要继续完整推荐的话，我需要可用的简历读取和岗位匹配能力。"
                    if missing_tools
                    else None
                ),
                domain="job_match",
                action="recommend",
                goal="Recommend suitable jobs based on user profile and resume.",
                subgoals=["read profile", "read resume", "search jobs", "rank by match"],
                resources=["profile", "resume", "jobs"],
                required_context=["resume"],
                confidence=0.9,
                plan_type="matching",
                evidence_policy="use_existing",
                stop_criteria=["recommendations generated", "tooling missing"],
            )

        if signals.has_profile_query:
            return build_router_plan(
                task_type="candidate_profile",
                reason="这是资料查询问题，直接读取候选人资料即可。",
                steps=keep_available(["get_candidate_profile"]),
                needs_more_context="get_candidate_profile" not in tools,
                missing_context=(
                    ["candidate_profile"] if "get_candidate_profile" not in tools else []
                ),
                follow_up_question=None,
                domain="profile",
                action="query",
                goal="Retrieve the user's saved career profile.",
                resources=["profile"],
                required_context=[],
                confidence=0.96,
                plan_type="lookup",
                evidence_policy="use_existing",
                stop_criteria=["profile retrieved"],
            )

        if signals.has_simple_job_match:
            if not user_state.get("has_resume", False):
                return build_router_plan(
                    task_type="job_match",
                    reason="这是岗位匹配问题，但当前缺少简历信息，应该先向用户追问。",
                    steps=[],
                    needs_more_context=True,
                    missing_context=["resume"],
                    follow_up_question="要先帮你做岗位匹配的话，我需要一份简历。你可以先上传或录入你的简历内容吗？",
                    domain="job_match",
                    action="match",
                    goal="Match the resume against available jobs.",
                    resources=["resume", "jobs"],
                    required_context=["resume"],
                    confidence=0.92,
                    plan_type="matching",
                    evidence_policy="use_existing",
                    stop_criteria=["resume missing confirmed"],
                )
            return build_router_plan(
                task_type="job_match",
                reason="这是岗位匹配问题，直接用简历匹配岗位。",
                steps=keep_available(["match_resume_to_jobs"]),
                needs_more_context="match_resume_to_jobs" not in tools,
                missing_context=[],
                follow_up_question=None,
                domain="job_match",
                action="match",
                goal="Match the resume against available jobs.",
                resources=["resume", "jobs"],
                required_context=["resume"],
                confidence=0.92,
                plan_type="matching",
                evidence_policy="use_existing",
                stop_criteria=["match completed", "tool missing"],
            )

        if signals.has_interview_prep:
            return build_router_plan(
                task_type="interview_prep",
                reason="这是面试准备请求，需要给出目标岗位导向的准备计划。",
                steps=keep_available(["get_candidate_profile"]),
                needs_more_context=False,
                missing_context=[],
                follow_up_question=None,
                domain="interview_prep",
                action="plan",
                goal="为目标岗位生成面试准备计划。",
                subgoals=["identify target role", "prioritize topics", "suggest practice tasks"],
                resources=["profile", "target_role"],
                required_context=["target_role"],
                confidence=0.9,
                plan_type="planning",
                evidence_policy="use_existing",
                stop_criteria=["interview prep plan produced"],
            )

        if (
            signals.has_career_diagnosis
            or signals.has_career_next_step
            or signals.has_general_next_step
        ):
            return build_router_plan(
                task_type="career_insights",
                reason="这是求职画像和状态诊断问题，需要聚合画像、投递和面试反馈。",
                steps=keep_available(["get_career_insights"]),
                needs_more_context="get_career_insights" not in tools,
                missing_context=[],
                follow_up_question=None,
                domain="career_strategy",
                action="diagnose",
                goal="分析当前投递/面试瓶颈，并给出下一步行动计划。",
                subgoals=[
                    "read profile status",
                    "inspect application/interview patterns",
                    "propose prioritized next actions",
                ],
                resources=["profile", "applications", "interviews"],
                required_context=["profile"],
                confidence=0.89,
                plan_type="diagnostic",
                evidence_policy="use_existing",
                stop_criteria=["bottleneck identified", "next actions produced"],
            )

        if signals.has_application_history:
            return build_router_plan(
                task_type="application_history",
                reason="这是投递记录查询问题，直接读取最近投递历史即可。",
                steps=keep_available(["get_applications"]),
                needs_more_context="get_applications" not in tools,
                missing_context=[],
                follow_up_question=None,
                domain="records",
                action="list_applications",
                goal="Fetch recent application history.",
                resources=["applications"],
                required_context=[],
                confidence=0.96,
                plan_type="lookup",
                evidence_policy="use_existing",
                stop_criteria=["history listed"],
            )

        if signals.has_interview_history or signals.has_interview_feedback_history:
            return build_router_plan(
                task_type="interview_history",
                reason="这是面试反馈查询问题，直接读取最近面试反馈即可。",
                steps=keep_available(["get_interview_feedback"]),
                needs_more_context="get_interview_feedback" not in tools,
                missing_context=[],
                follow_up_question=None,
                domain="records",
                action="list_interviews",
                goal="Fetch recent interview feedback history.",
                resources=["interviews"],
                required_context=[],
                confidence=0.96,
                plan_type="lookup",
                evidence_policy="use_existing",
                stop_criteria=["feedback listed"],
            )

        if signals.has_job_search:
            reason_parts = ["这是岗位搜索问题"]
            if profile_role:
                reason_parts.append(f"并结合长期偏好 {profile_role}")
            if memory_context:
                reason_parts.append("并参考最近对话")
            reason_parts.append("来搜索岗位。")
            return build_router_plan(
                task_type="job_search",
                reason="".join(reason_parts),
                steps=keep_available(["search_jobs"]),
                needs_more_context="search_jobs" not in tools,
                missing_context=[],
                follow_up_question=None,
                domain="job_search",
                action="search",
                goal="Search relevant jobs by user request and profile preference.",
                resources=["jobs"],
                required_context=["job_query"],
                confidence=0.95,
                plan_type="search",
                evidence_policy="use_existing",
                stop_criteria=["job list returned"],
            )

        return None
