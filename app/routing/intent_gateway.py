from __future__ import annotations

from typing import Any, Dict, List

from app.routing.intent_signals import collect_intent_signals
from app.routing.router_plan_factory import build_router_plan
from app.schemas.intent_gateway import IntentCluster, IntentGatewayDecision


_NON_CAREER_MARKERS = ("天气", "天气怎么样", "诗歌", "诗", "笑话", "翻译", "数学", "计算", "故事")

_APPLICATION_DIAG_STAGNATION_MARKERS = (
    "没回音",
    "没有回复",
    "无回复",
    "没回复",
    "无消息",
    "没消息",
    "没进展",
    "无进展",
    "进展",
    "卡住",
    "stuck",
    "no response",
    "ghosted",
)

_JOB_DISCOVERY_MARKERS = ("grad", "grad program", "program", "实习", "internship", "岗位", "职位", "招聘", "job", "jobs", "role")

_RESUME_IMPROVE_MARKERS = ("优化", "改进", "修改", "润色", "提升", "完善", "tailor", "optimize")
_RESUME_DIAG_MARKERS = ("问题", "缺点", "不足", "哪里不好", "怎么改", "不匹配", "不合适", "diagnose", "weakness")
_RESUME_SUMMARY_MARKERS = ("总结", "概括", "亮点", "summary", "summarize", "highlight", "总结一下", "summary my resume")


class IntentGateway:
    """Intent disambiguation between router-first and planner escalation."""

    def resolve_after_router_miss(
        self,
        *,
        message: str,
        profile: Dict[str, Any],
        user_state: Dict[str, Any],
        memory_context: List[str],
        available_tools: List[str],
    ) -> IntentGatewayDecision:
        lowered = message.lower().strip()
        stripped = message.strip()

        # Non-career hard rule: if it looks obviously unrelated.
        if any(marker in message for marker in _NON_CAREER_MARKERS):
            return IntentGatewayDecision(
                domain="non_career",
                intent_cluster="unknown",
                confidence=0.99,
                action="true_fallback",
                required_context=[],
                missing_context=[],
                reason="non-career request detected",
                fallback_type="true",
                local_plan_payload=self._build_true_fallback_plan(),
            )

        # Career domain detection (be conservative: treat unclear job-market chat
        # as career-domain to avoid accidental true-fallback).
        career_markers = any(
            mk in lowered
            for mk in (
                "简历",
                "resume",
                "cv",
                "岗位",
                "职位",
                "招聘",
                "投递",
                "申请",
                "面试",
                "interview",
                "求职",
                "career",
                "投递",
                "市场",
                "job",
                "jobs",
                "grad",
                "program",
                "internship",
                "intern",
                "实习",
            )
        ) or any(mk in lowered for mk in _JOB_DISCOVERY_MARKERS)
        if not career_markers:
            # When user is already inside Career Hub flow (candidate/resume
            # exists, or we have prior memory), treat "evidence-only" queries
            # as career-domain even if the message itself lacks explicit job
            # keywords; otherwise we'd incorrectly return true-fallback.
            if bool(user_state.get("has_candidate")) or bool(user_state.get("has_resume")) or bool(memory_context):
                return IntentGatewayDecision(
                    domain="career",
                    intent_cluster="unknown",
                    confidence=0.45,
                    action="escalate_to_planner",
                    required_context=[],
                    missing_context=[],
                    reason="no explicit job markers, but career hub evidence exists -> planner arbitration",
                    fallback_type="none",
                    local_plan_payload=None,
                )
            return IntentGatewayDecision(
                domain="non_career",
                intent_cluster="unknown",
                confidence=0.6,
                action="true_fallback",
                required_context=[],
                missing_context=[],
                reason="no career marker detected",
                fallback_type="true",
                local_plan_payload=self._build_true_fallback_plan(),
            )

        # Use existing high-signal detection to derive clusters.
        signals = collect_intent_signals(message, lowered, stripped)

        has_resume = bool(user_state.get("has_resume", False))
        has_job_detail = bool(user_state.get("has_job_detail", False))

        # Fast-path: English "jobs fit me" / "backend jobs for me" discovery
        # should use local job_search instead of planner escalation,
        # otherwise tests run without API keys may fall back and return no sources.
        if self._looks_like_english_job_discovery_fit(message=message, lowered=lowered):
            local = self._build_job_search_route_plan()
            return IntentGatewayDecision(
                domain="career",
                intent_cluster="job_match",
                confidence=0.7,
                action="route",
                required_context=[],
                missing_context=[],
                reason="english job discovery ('fit me') -> local job_search",
                fallback_type="none",
                local_plan_payload=local,
            )

        # 1) resume_analysis
        if self._looks_like_resume_analysis(message, lowered):
            intent_cluster: IntentCluster = "resume_analysis"
            if has_resume:
                local = self._build_resume_analysis_route_plan(intent_cluster=intent_cluster)
                return IntentGatewayDecision(
                    domain="career",
                    intent_cluster=intent_cluster,
                    confidence=0.9,
                    action="route",
                    required_context=["resume"],
                    missing_context=[],
                    reason="resume analysis request (local route)",
                    fallback_type="none",
                    local_plan_payload=local,
                )
            # Clarify when resume missing.
            local = self._build_resume_analysis_clarify_plan()
            return IntentGatewayDecision(
                domain="career",
                intent_cluster=intent_cluster,
                confidence=0.85,
                action="clarify",
                required_context=["resume"],
                missing_context=["resume"],
                reason="resume missing -> clarify",
                fallback_type="recoverable",
                local_plan_payload=local,
            )

        # 2) job_match (job fit compare)
        if signals.has_job_fit or self._looks_like_job_fit(message, lowered):
            intent_cluster = "job_match"
            if has_resume and has_job_detail:
                local = self._build_job_match_route_plan()
                return IntentGatewayDecision(
                    domain="career",
                    intent_cluster=intent_cluster,
                    confidence=0.9,
                    action="route",
                    required_context=["resume", "job_detail"],
                    missing_context=[],
                    reason="job fit compare request (local route)",
                    fallback_type="none",
                    local_plan_payload=local,
                )
            local = self._build_job_match_clarify_plan(
                missing=["resume" if not has_resume else "job_detail" if not has_job_detail else ""]
            )
            missing = []
            if not has_resume:
                missing.append("resume")
            if not has_job_detail:
                missing.append("job_detail")
            return IntentGatewayDecision(
                domain="career",
                intent_cluster=intent_cluster,
                confidence=0.88,
                action="clarify",
                required_context=["resume", "job_detail"],
                missing_context=missing,
                reason="job fit compare needs resume and job detail",
                fallback_type="recoverable",
                local_plan_payload=local,
            )

        # 3) job_recommend
        if signals.has_recommend_match or self._looks_like_job_recommend(message, lowered):
            intent_cluster = "job_recommend"
            if has_resume:
                local = self._build_job_recommend_route_plan()
                return IntentGatewayDecision(
                    domain="career",
                    intent_cluster=intent_cluster,
                    confidence=0.85,
                    action="route",
                    required_context=["resume"],
                    missing_context=[],
                    reason="job recommend request (local route)",
                    fallback_type="none",
                    local_plan_payload=local,
                )
            local = self._build_job_recommend_clarify_plan()
            return IntentGatewayDecision(
                domain="career",
                intent_cluster=intent_cluster,
                confidence=0.8,
                action="clarify",
                required_context=["resume"],
                missing_context=["resume"],
                reason="job recommend needs resume",
                fallback_type="recoverable",
                local_plan_payload=local,
            )

        # 4) application_diag
        if self._looks_like_application_diag(message, lowered):
            # Ambiguous but career-related: clarify first to avoid true-fallback.
            intent_cluster = "application_diag"
            local = self._build_application_diag_clarify_plan()
            return IntentGatewayDecision(
                domain="career",
                intent_cluster=intent_cluster,
                confidence=0.78,
                action="clarify",
                required_context=["target_role"],
                missing_context=["target_role"],
                reason="application stagnation detected -> clarify target role first",
                fallback_type="recoverable",
                local_plan_payload=local,
            )

        # 5) interview_prep
        if signals.has_interview_prep or self._looks_like_interview_prep(message, lowered):
            intent_cluster = "interview_prep"
            local = self._build_interview_prep_route_plan()
            # Let ContextRequirementResolver decide whether target_role is missing.
            return IntentGatewayDecision(
                domain="career",
                intent_cluster=intent_cluster,
                confidence=0.82,
                action="route",
                required_context=["target_role"],
                missing_context=[],
                reason="interview prep request (local route)",
                fallback_type="none",
                local_plan_payload=local,
            )

        # Unknown career but still job-market related: escalate to planner for
        # bounded arbitration unless we can clarify missing goal.
        if any(mk in lowered for mk in _JOB_DISCOVERY_MARKERS):
            intent_cluster = "unknown"
            return IntentGatewayDecision(
                domain="career",
                intent_cluster=intent_cluster,
                confidence=0.55,
                action="escalate_to_planner",
                required_context=[],
                missing_context=[],
                reason="job discovery / grad program-like request -> planner arbitration",
                fallback_type="none",
                local_plan_payload=None,
            )

        # Career-domain uncertain => clarify by default.
        if self._looks_like_complex_cross_goal_query(lowered):
            return IntentGatewayDecision(
                domain="career",
                intent_cluster="unknown",
                confidence=0.5,
                action="escalate_to_planner",
                required_context=[],
                missing_context=[],
                reason="complex cross-goal strategy query -> planner arbitration",
                fallback_type="none",
                local_plan_payload=None,
            )
        return IntentGatewayDecision(
            domain="career",
            intent_cluster="unknown",
            confidence=0.45,
            action="clarify",
            required_context=["target_role"],
            missing_context=["target_role"],
            reason="uncertain career intent -> clarify",
            fallback_type="recoverable",
            local_plan_payload=self._build_unknown_career_clarify_plan(),
        )

    def _build_true_fallback_plan(self) -> dict:
        return {
            "task_type": "fallback",
            "reason": "true_fallback: non-career request",
            "steps": [],
            "needs_more_context": False,
            "missing_context": [],
            "follow_up_question": None,
            "planner_source": "gateway",
            "domain": "conversation",
            "action": "true_fallback",
            "confidence": 0.99,
            "plan_type": "direct",
            "evidence_policy": "none",
            "stop_criteria": ["non-career fallback returned"],
        }

    def _build_resume_analysis_route_plan(self, *, intent_cluster: IntentCluster) -> dict:
        plan = build_router_plan(
            task_type="resume_analysis",
            reason="这是简历总结请求，需要先读取简历。",
            steps=["get_resume_by_id"],
            needs_more_context=False,
            missing_context=[],
            follow_up_question=None,
            domain="resume_analysis",
            action="summarize",
            goal="Summarize the user's resume highlights and positioning.",
            resources=["resume"],
            required_context=["resume"],
            confidence=0.94,
            plan_type="analysis",
            evidence_policy="use_existing",
            stop_criteria=["resume summary completed"],
        )
        plan["planner_source"] = "gateway"
        plan["resolver_trace"] = []
        return plan

    def _build_resume_analysis_clarify_plan(self) -> dict:
        plan = build_router_plan(
            task_type="resume_analysis",
            reason="简历总结需要简历内容，当前缺少简历。",
            steps=[],
            needs_more_context=True,
            missing_context=["resume"],
            follow_up_question="我还没有读取到你的简历。请上传简历文件，或直接粘贴简历文本。",
            domain="resume_analysis",
            action="summarize",
            goal="Summarize the user's resume highlights and positioning.",
            resources=["resume"],
            required_context=["resume"],
            confidence=0.85,
            plan_type="analysis",
            evidence_policy="use_existing",
            stop_criteria=["resume missing confirmed"],
        )
        plan["planner_source"] = "gateway"
        return plan

    def _build_job_match_route_plan(self) -> dict:
        plan = build_router_plan(
            task_type="job_match",
            reason="岗位适配判断请求：使用简历对比岗位详情。",
            steps=["match_resume_to_jobs"],
            needs_more_context=False,
            missing_context=[],
            follow_up_question=None,
            domain="job_match",
            action="compare",
            goal="Compare resume evidence with job requirements and estimate fit.",
            subgoals=["collect resume evidence", "collect job requirements", "output fit judgement"],
            resources=["resume", "job_detail"],
            required_context=["resume", "job_detail"],
            confidence=0.9,
            plan_type="matching",
            evidence_policy="use_existing",
            stop_criteria=["fit judgement produced"],
        )
        plan["planner_source"] = "gateway"
        return plan

    def _build_job_match_clarify_plan(self, *, missing: List[str]) -> dict:
        follow_up = "请提供岗位 JD / 招聘链接 / 岗位描述，我才能评估你是否匹配。"
        if "resume" in missing and "job_detail" not in missing:
            follow_up = "我还需要你的简历才能做岗位匹配，请先上传或粘贴简历内容。"
        plan = build_router_plan(
            task_type="job_match",
            reason="岗位适配判断缺少关键上下文。",
            steps=[],
            needs_more_context=True,
            missing_context=[m for m in missing if m],
            follow_up_question=follow_up,
            domain="job_match",
            action="compare",
            goal="Compare resume evidence with job requirements and estimate fit.",
            resources=["resume", "job_detail"],
            required_context=["resume", "job_detail"],
            confidence=0.82,
            plan_type="matching",
            evidence_policy="use_existing",
            stop_criteria=["critical context missing"],
        )
        plan["planner_source"] = "gateway"
        return plan

    def _build_job_recommend_route_plan(self) -> dict:
        plan = build_router_plan(
            task_type="job_match_planning",
            reason="这是推荐型问题，需要先读画像和简历，再搜索并匹配岗位。",
            steps=["get_candidate_profile", "get_resume_by_id", "search_jobs", "match_resume_to_jobs"],
            needs_more_context=False,
            missing_context=[],
            follow_up_question=None,
            domain="job_match",
            action="recommend",
            goal="Find suitable jobs and score them against the user resume.",
            subgoals=["load profile", "load resume", "search jobs", "match jobs"],
            resources=["profile", "resume", "jobs"],
            required_context=["resume", "job_query"],
            confidence=0.86,
            plan_type="matching",
            evidence_policy="use_existing",
            stop_criteria=["recommended jobs returned"],
        )
        plan["planner_source"] = "gateway"
        return plan

    def _build_job_recommend_clarify_plan(self) -> dict:
        plan = build_router_plan(
            task_type="job_match",
            reason="岗位推荐需要简历信息。",
            steps=[],
            needs_more_context=True,
            missing_context=["resume"],
            follow_up_question="要给你做岗位推荐，我需要先读取你的简历。请上传或粘贴简历内容。",
            domain="job_match",
            action="compare",
            goal="Compare resume evidence with job requirements and estimate fit.",
            resources=["resume", "job_detail"],
            required_context=["resume", "job_detail"],
            confidence=0.78,
            plan_type="matching",
            evidence_policy="use_existing",
            stop_criteria=["resume missing confirmed"],
        )
        plan["planner_source"] = "gateway"
        return plan

    def _build_application_diag_clarify_plan(self) -> dict:
        plan = build_router_plan(
            task_type="career_insights",
            reason="投递没进展：需要先确认你的目标岗位方向以便诊断。",
            steps=[],
            needs_more_context=True,
            missing_context=["target_role"],
            follow_up_question="你想准备哪个目标岗位？请告诉我岗位名称或方向（例如 backend / data analyst）。",
            domain="career_strategy",
            action="diagnose",
            goal="Analyze application stagnation and propose next steps.",
            resources=["profile"],
            required_context=["target_role"],
            confidence=0.7,
            plan_type="diagnostic",
            evidence_policy="use_existing",
            stop_criteria=["need target role"],
        )
        plan["planner_source"] = "gateway"
        return plan

    def _build_interview_prep_route_plan(self) -> dict:
        plan = build_router_plan(
            task_type="interview_prep",
            reason="这是面试准备请求：生成目标岗位导向的准备计划。",
            steps=["get_candidate_profile"],
            needs_more_context=False,
            missing_context=[],
            follow_up_question=None,
            domain="interview_prep",
            action="plan",
            goal="为目标岗位生成面试准备计划。",
            subgoals=["identify target role", "prioritize topics", "suggest practice tasks"],
            resources=["profile", "target_role"],
            required_context=["target_role"],
            confidence=0.86,
            plan_type="planning",
            evidence_policy="use_existing",
            stop_criteria=["interview prep plan produced"],
        )
        plan["planner_source"] = "gateway"
        return plan

    def _build_unknown_career_clarify_plan(self) -> dict:
        plan = build_router_plan(
            task_type="job_match",
            reason="不确定你的具体求职目标，需要你澄清后才能继续。",
            steps=[],
            needs_more_context=True,
            missing_context=["target_role"],
            follow_up_question="你希望我帮你做哪一类事情：岗位匹配 / 投递诊断 / 面试准备？并告诉我目标岗位名称或方向。",
            domain="job_match",
            action="compare",
            goal="Clarify user goal and requested career task.",
            resources=["resume", "job_detail"],
            required_context=["target_role"],
            confidence=0.4,
            plan_type="matching",
            evidence_policy="use_existing",
            stop_criteria=["goal clarified"],
        )
        plan["planner_source"] = "gateway"
        return plan

    def _looks_like_resume_analysis(self, message: str, lowered: str) -> bool:
        has_resume = any(mk in message for mk in ("简历", "resume", "cv"))
        has_summary = any(mk in message for mk in _RESUME_SUMMARY_MARKERS) or any(mk in lowered for mk in _RESUME_SUMMARY_MARKERS)
        has_diag = any(mk in message for mk in _RESUME_DIAG_MARKERS) or any(mk in lowered for mk in _RESUME_DIAG_MARKERS)
        has_improve = any(mk in message for mk in _RESUME_IMPROVE_MARKERS) or any(mk in lowered for mk in _RESUME_IMPROVE_MARKERS)
        # Only summarize/diagnose/improve; otherwise keep the router/planner.
        return has_resume and (has_summary or has_diag or has_improve)

    def _looks_like_job_fit(self, message: str, lowered: str) -> bool:
        return (
            ("岗位" in message or "职位" in message or "jd" in lowered or "岗位描述" in message)
            and any(mk in lowered for mk in ("适合", "匹配", "能投", "值得投", "值得我投", "compare", "不匹配", "值不值得"))
        )

    def _looks_like_job_recommend(self, message: str, lowered: str) -> bool:
        return (
            any(mk in lowered for mk in ("推荐", "按我背景", "根据我的情况"))
            and any(mk in lowered for mk in ("岗位", "职位", "实习", "intern", "job", "jobs", "role"))
            and any(mk in lowered for mk in ("简历", "背景", "我", "my"))
        )

    def _looks_like_application_diag(self, message: str, lowered: str) -> bool:
        has_application = any(mk in lowered for mk in ("投递", "申请", "application", "applications", "applied"))
        has_stagnation = any(mk in lowered for mk in _APPLICATION_DIAG_STAGNATION_MARKERS)
        return has_application and has_stagnation

    def _looks_like_interview_prep(self, message: str, lowered: str) -> bool:
        has_interview = any(mk in lowered for mk in ("面试", "interview"))
        has_prepare = any(mk in lowered for mk in ("准备", "prepare", "prep", "plan"))
        return has_interview and has_prepare

    def _looks_like_english_job_discovery_fit(self, *, message: str, lowered: str) -> bool:
        has_job_keywords = any(mk in lowered for mk in ("job", "jobs", "role", "position", "internship"))
        has_fit_intent = any(mk in lowered for mk in ("fit me", "fits me", "fit for me", "am i a fit", "suitable", "match me"))
        # If the user explicitly asks for resume-based matching, don't treat as
        # pure discovery.
        has_resume = any(mk in lowered for mk in ("简历", "resume", "cv"))
        return has_job_keywords and has_fit_intent and not has_resume

    def _looks_like_complex_cross_goal_query(self, lowered: str) -> bool:
        # Allow planner only for multi-objective / tradeoff style queries.
        has_tradeoff = any(mk in lowered for mk in ("取舍", "tradeoff", "权衡", "vs", "还是", "优先"))
        has_multi_goal = sum(
            1
            for group in (
                ("简历", "resume", "cv"),
                ("岗位", "job", "jobs", "role", "职位"),
                ("投递", "application", "申请"),
                ("面试", "interview"),
                ("学习计划", "learning plan", "timeline"),
            )
            if any(mk in lowered for mk in group)
        ) >= 2
        has_constraints = any(mk in lowered for mk in ("一周", "两周", "time budget", "约束", "constraint"))
        return (has_tradeoff and has_multi_goal) or (has_multi_goal and has_constraints)

    def _build_job_search_route_plan(self) -> dict:
        plan = build_router_plan(
            task_type="job_search",
            reason="这是岗位发现请求，直接用本地 job_search 检索适合的岗位。",
            steps=["search_jobs"],
            needs_more_context=False,
            missing_context=[],
            follow_up_question=None,
            domain="job_search",
            action="search",
            goal="Search relevant jobs by user request and fit intent.",
            resources=["jobs"],
            required_context=[],
            confidence=0.75,
            plan_type="search",
            evidence_policy="use_existing",
            stop_criteria=["job list returned"],
        )
        plan["planner_source"] = "gateway"
        plan["resolver_trace"] = []
        return plan

