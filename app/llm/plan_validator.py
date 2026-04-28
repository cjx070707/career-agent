from typing import Any, Dict, List, Optional, Set

from app.schemas.chat import ChatPlan


class PlanValidator:
    def __init__(self, *, allowed_task_types: Set[str], max_plan_steps: int) -> None:
        self.allowed_task_types = allowed_task_types
        self.max_plan_steps = max_plan_steps

    def validate_and_dump(
        self,
        *,
        plan_payload: Dict[str, Any],
        planner_source: str,
        available_tools: Optional[List[str]] = None,
    ) -> Dict[str, Any]:
        normalized_payload = self.normalize_plan(plan_payload)
        plan = ChatPlan.model_validate({**normalized_payload, "planner_source": planner_source})
        self.validate_plan_contract(plan, available_tools=available_tools)
        return plan.model_dump()

    def normalize_plan(self, plan_payload: Dict[str, Any]) -> Dict[str, Any]:
        normalized = dict(plan_payload)
        if normalized.get("task_type") != "job_search":
            return normalized
        steps = normalized.get("steps", [])
        if "search_jobs" not in steps:
            return normalized
        normalized["steps"] = ["search_jobs"]
        return normalized

    def validate_plan_contract(
        self,
        plan: ChatPlan,
        available_tools: Optional[List[str]] = None,
    ) -> None:
        if plan.task_type not in self.allowed_task_types:
            raise ValueError(f"Invalid task_type: {plan.task_type}")

        if plan.needs_more_context:
            if not plan.missing_context:
                raise ValueError("missing_context is required when more context is needed")
            if not plan.follow_up_question:
                raise ValueError("follow_up_question is required when more context is needed")

        if plan.confidence is not None and not (0.0 <= plan.confidence <= 1.0):
            raise ValueError("confidence must be between 0 and 1")

        if str(plan.plan_type or "").strip().lower() == "diagnostic":
            if not str(plan.goal or "").strip():
                raise ValueError("diagnostic plan_type requires goal")
            if not list(plan.subgoals or []):
                raise ValueError("diagnostic plan_type requires subgoals")
            if not list(plan.resources or []):
                raise ValueError("diagnostic plan_type requires resources")
            if not list(plan.stop_criteria or []):
                raise ValueError("diagnostic plan_type requires stop_criteria")

        action = str(plan.action or "").strip().lower()
        if action in {"match", "compare", "rank", "explain_gap", "recommend"}:
            resources = {item.strip().lower() for item in (plan.resources or []) if str(item).strip()}
            if "resume" not in resources and "latest_resume" not in resources:
                raise ValueError("matching actions require resume resource")
            if not ({"job_detail", "job_query", "target_jobs"} & resources):
                raise ValueError("matching actions require job_detail/job_query/target_jobs resource")

        steps = list(plan.steps or [])
        if len(steps) > self.max_plan_steps:
            raise ValueError(f"plan steps exceed MAX_PLAN_STEPS={self.max_plan_steps}")

        if available_tools is not None:
            allowed_tools = set(available_tools)
            unknown = [step for step in steps if step not in allowed_tools]
            if unknown:
                raise ValueError(f"plan contains steps not in available_tools: {unknown}")

        if plan.task_type == "job_match_planning" and steps:
            if "search_jobs" in steps and "match_resume_to_jobs" in steps:
                if steps.index("search_jobs") > steps.index("match_resume_to_jobs"):
                    raise ValueError("job_match_planning requires search_jobs before match_resume_to_jobs")
