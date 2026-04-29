from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional, Sequence, Set, Tuple, Union

from app.resolvers.context_requirement_resolver import ContextRequirementResolution
from app.schemas.chat import ChatPlan

# Upper bound on executor-visible replanned chains (align with planner/tool chain caps).
EXECUTOR_MAX_REPLANNED_STEPS = 6


@dataclass
class ToolResolution:
    tool_chain: List[Dict[str, Any]]
    resolver_trace: List[Dict[str, Any]] = field(default_factory=list)
    executable: bool = True
    blocking_reason: Optional[str] = None

    def model_dump(self) -> Dict[str, Any]:
        return {
            "tool_chain": list(self.tool_chain),
            "resolver_trace": list(self.resolver_trace),
            "executable": self.executable,
            "blocking_reason": self.blocking_reason,
        }


class ToolResolver:
    OPTIONAL_TOOLS = {"summarize_resume", "generate_interview_plan", "get_job_detail"}

    def resolve(
        self,
        *,
        plan: Union[ChatPlan, Dict[str, Any]],
        resolved_context: ContextRequirementResolution,
        available_tools: List[str],
    ) -> ToolResolution:
        plan_data = self._plan_data(plan)
        task_type = str(plan_data.get("task_type") or "")
        domain = str(plan_data.get("domain") or "")
        action = str(plan_data.get("action") or "")
        plan_type = str(plan_data.get("plan_type") or "")
        available = set(available_tools)
        trace: List[Dict[str, Any]] = []

        if resolved_context.needs_more_context:
            reason = f"missing required context: {', '.join(resolved_context.missing_context)}"
            trace.append(self._trace("block", None, reason))
            return ToolResolution(
                tool_chain=[],
                resolver_trace=trace,
                executable=False,
                blocking_reason=reason,
            )

        if plan_type == "third_party_advice":
            trace.append(
                self._trace(
                    "skip_all",
                    None,
                    "third-party advice must not call current user profile tools",
                )
            )
            return ToolResolution(tool_chain=[], resolver_trace=trace, executable=True)

        desired, critical = self._desired_tools(task_type, domain, action)
        tool_chain: List[Dict[str, Any]] = []
        missing_critical: List[str] = []

        for tool_name in desired:
            is_critical = tool_name in critical
            if tool_name in available:
                tool_chain.append(
                    {
                        "tool_name": tool_name,
                        "critical": is_critical,
                        "source": "tool_resolver",
                    }
                )
                trace.append(self._trace("select", tool_name, "tool is available"))
                continue
            if is_critical:
                missing_critical.append(tool_name)
                trace.append(self._trace("missing_critical", tool_name, "critical tool is unavailable"))
            else:
                trace.append(self._trace("skip_optional", tool_name, "optional tool is unavailable"))

        if missing_critical:
            reason = f"missing critical tools: {', '.join(missing_critical)}"
            return ToolResolution(
                tool_chain=[],
                resolver_trace=trace,
                executable=False,
                blocking_reason=reason,
            )

        return ToolResolution(
            tool_chain=tool_chain,
            resolver_trace=trace,
            executable=True,
            blocking_reason=None,
        )

    def _plan_data(self, plan: Union[ChatPlan, Dict[str, Any]]) -> Dict[str, Any]:
        if isinstance(plan, ChatPlan):
            return plan.model_dump()
        return dict(plan)

    def _desired_tools(self, task_type: str, domain: str, action: str) -> tuple[List[str], Set[str]]:
        if task_type == "resume_analysis" and domain in {"", "resume_analysis"} and action in {"", "summarize"}:
            return ["get_resume_by_id", "summarize_resume"], {"get_resume_by_id"}

        if (task_type == "job_match" or domain == "job_match") and action == "match":
            return ["match_resume_to_jobs"], {"match_resume_to_jobs"}

        if task_type in {"job_match", "job_match_planning"} or domain == "job_match":
            desired = ["get_candidate_profile", "get_resume_by_id"]
            if action == "compare":
                desired.append("get_job_detail")
            if action in {"recommend", "rank"} or task_type == "job_match_planning":
                desired.append("search_jobs")
            desired.append("match_resume_to_jobs")
            return desired, {"get_resume_by_id", "match_resume_to_jobs"}

        if task_type == "job_search" or (domain == "job_search" and action == "search"):
            return ["search_jobs"], {"search_jobs"}

        if task_type == "interview_prep" or (domain == "interview_prep" and action == "plan"):
            return ["get_candidate_profile", "get_resume_by_id", "generate_interview_plan"], {
                "get_candidate_profile"
            }

        if task_type == "career_insights" or (domain == "career_strategy" and action == "diagnose"):
            return ["get_career_insights"], {"get_career_insights"}

        return [], set()

    def executor_allowed_tool_order(
        self,
        *,
        plan: Union[ChatPlan, Dict[str, Any]],
        available_tools: List[str],
    ) -> List[str]:
        """Canonically ordered tool names permitted for bounded switch/replan in the executor."""
        plan_data = self._plan_data(plan)
        task_type = str(plan_data.get("task_type") or "")
        domain = str(plan_data.get("domain") or "")
        action = str(plan_data.get("action") or "")
        desired, _critical = self._desired_tools(task_type, domain, action)
        available_set = set(available_tools)
        return [name for name in desired if name in available_set]

    def normalize_executor_replan_chain(
        self,
        *,
        plan: Union[ChatPlan, Dict[str, Any]],
        proposed_tools: Sequence[str],
        available_tools: List[str],
        executed_trace: List[str],
    ) -> Tuple[List[str], str]:
        """Validate + sort `replan_strategy.planned_tools` within current task semantics.

        Returns `(replanned_chain, guardrail_decision)` where guardrail_decision is
        `accepted` | `rejected`.
        """
        allowed_order = self.executor_allowed_tool_order(plan=plan, available_tools=available_tools)
        if not allowed_order:
            return [], "rejected"
        idx = {tool: position for position, tool in enumerate(allowed_order)}
        allowed_set = set(idx)

        uniq: List[str] = []
        seen: Set[str] = set()
        for raw in proposed_tools:
            if not isinstance(raw, str):
                continue
            step = raw.strip()
            if not step or step not in allowed_set or step in seen:
                continue
            seen.add(step)
            uniq.append(step)
        uniq.sort(key=lambda tool: idx[tool])

        uniq = uniq[:EXECUTOR_MAX_REPLANNED_STEPS]
        executed = set(executed_trace)

        remainder = [tool for tool in uniq if tool not in executed]

        if not remainder:
            return [], "rejected"
        return remainder, "accepted"

    def _trace(self, decision: str, tool_name: Optional[str], reason: str) -> Dict[str, Any]:
        return {
            "resolver": "tool",
            "decision": decision,
            "tool_name": tool_name,
            "reason": reason,
        }
