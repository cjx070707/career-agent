from typing import Any, Dict, List, Optional

from app.llm.client import LLMClient
from app.schemas.diagnostic_planner import (
    DiagnosticPlannerInput,
    DiagnosticPlannerOutput,
)


class CareerDiagnosticPlanner:
    def __init__(self, llm_client: Optional[LLMClient] = None) -> None:
        self.llm_client = llm_client or LLMClient()

    def plan(
        self,
        *,
        message: str,
        plan_semantics: Dict[str, Any],
        profile: Dict[str, Any],
        context_resolution: Dict[str, Any],
        memory_context: List[str],
    ) -> DiagnosticPlannerOutput:
        normalized_plan = dict(plan_semantics or {})
        normalized_profile = dict(profile or {})
        normalized_context = dict(context_resolution or {})
        normalized_memory = [str(item) for item in (memory_context or []) if str(item).strip()]

        if not self._is_applicable(normalized_plan):
            return self._not_applicable_output()

        if bool(normalized_context.get("needs_more_context")):
            return self._context_blocked_output(
                follow_up_question=str(normalized_context.get("follow_up_question") or "").strip() or None
            )

        safe_input = self._build_safe_input(
            message=message,
            plan_semantics=normalized_plan,
            profile=normalized_profile,
            context_resolution=normalized_context,
            memory_context=normalized_memory,
        )

        try:
            payload = self.llm_client.generate_diagnostic_plan(
                message=safe_input.message,
                plan_semantics=safe_input.plan_semantics,
                profile=safe_input.profile,
                context_resolution=safe_input.context_resolution,
                memory_context=safe_input.memory_context,
            )
            return self._sanitize_output(payload)
        except Exception:
            return self._fallback_output()

    def _is_applicable(self, plan_semantics: Dict[str, Any]) -> bool:
        task_type = str(plan_semantics.get("task_type") or "").strip().lower()
        domain = str(plan_semantics.get("domain") or "").strip().lower()
        action = str(plan_semantics.get("action") or "").strip().lower()
        if task_type == "career_insights":
            return True
        return domain == "career_strategy" and action == "diagnose"

    def _build_safe_input(
        self,
        *,
        message: str,
        plan_semantics: Dict[str, Any],
        profile: Dict[str, Any],
        context_resolution: Dict[str, Any],
        memory_context: List[str],
    ) -> DiagnosticPlannerInput:
        profile_summary = {
            "target_role_preference": profile.get("target_role_preference"),
            "skill_keywords": profile.get("skill_keywords", []),
            "career_focus_notes": profile.get("career_focus_notes"),
            "application_patterns": profile.get("application_patterns"),
            "interview_weaknesses": profile.get("interview_weaknesses"),
            "next_focus_areas": profile.get("next_focus_areas"),
        }
        context_summary = {
            "required_context": context_resolution.get("required_context", []),
            "missing_context": context_resolution.get("missing_context", []),
            "needs_more_context": bool(context_resolution.get("needs_more_context")),
            "follow_up_question": context_resolution.get("follow_up_question"),
        }
        semantics_summary = {
            "task_type": plan_semantics.get("task_type"),
            "domain": plan_semantics.get("domain"),
            "action": plan_semantics.get("action"),
            "plan_type": plan_semantics.get("plan_type"),
            "goal": plan_semantics.get("goal"),
            "subgoals": plan_semantics.get("subgoals", []),
        }
        return DiagnosticPlannerInput(
            message=message,
            plan_semantics=semantics_summary,
            profile=profile_summary,
            context_resolution=context_summary,
            memory_context=memory_context,
        )

    def _sanitize_output(self, payload: Dict[str, Any]) -> DiagnosticPlannerOutput:
        normalized = DiagnosticPlannerOutput.model_validate(payload)
        sanitized_payload = normalized.model_dump()
        banned_keys = {"tool_name", "steps", "tool_chain", "tool_input", "tool_input_hint", "tool"}
        for hypothesis in sanitized_payload.get("diagnostic_hypotheses", []):
            for banned in banned_keys:
                hypothesis.pop(banned, None)
        for evidence in sanitized_payload.get("evidence_to_collect", []):
            for banned in banned_keys:
                evidence.pop(banned, None)
        return DiagnosticPlannerOutput.model_validate(sanitized_payload)

    def _not_applicable_output(self) -> DiagnosticPlannerOutput:
        return DiagnosticPlannerOutput(
            diagnostic_hypotheses=[],
            evidence_to_collect=[],
            next_question=None,
            confidence=0.0,
            stop_criteria=["not applicable"],
        )

    def _context_blocked_output(self, *, follow_up_question: Optional[str]) -> DiagnosticPlannerOutput:
        return DiagnosticPlannerOutput(
            diagnostic_hypotheses=[],
            evidence_to_collect=[],
            next_question=follow_up_question,
            confidence=0.2,
            stop_criteria=["required context collected"],
        )

    def _fallback_output(self) -> DiagnosticPlannerOutput:
        return DiagnosticPlannerOutput(
            diagnostic_hypotheses=[
                {
                    "bottleneck_type": "insufficient_evidence",
                    "summary": "当前证据不足，先补齐关键求职过程信息。",
                    "rationale": "缺少足够的可验证证据来形成高置信诊断假设。",
                    "confidence": 0.4,
                    "evidence_refs": [],
                }
            ],
            evidence_to_collect=[
                {
                    "source": "applications",
                    "reason": "需要投递漏斗数据来判断转化阶段瓶颈。",
                    "priority": "high",
                    "required": True,
                },
                {
                    "source": "interviews",
                    "reason": "需要面试结果来区分投递问题和面试问题。",
                    "priority": "high",
                    "required": True,
                },
                {
                    "source": "feedback",
                    "reason": "需要具体反馈来判断是否存在技能短板。",
                    "priority": "high",
                    "required": True,
                },
            ],
            next_question="你可以先补充最近的投递记录、面试结果和反馈吗？",
            confidence=0.4,
            stop_criteria=["enough evidence collected"],
        )
