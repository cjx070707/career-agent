import re
from typing import Any, Callable, Dict, List, Optional

from app.tools.registry import ToolRegistry


class PlanExecutor:
    def __init__(
        self,
        *,
        tool_registry: ToolRegistry,
        llm_client: Any,
        max_loop_steps: int,
        max_step_repeat: int,
    ) -> None:
        self.tool_registry = tool_registry
        self.llm_client = llm_client
        self.max_loop_steps = max_loop_steps
        self.max_step_repeat = max_step_repeat

    def execute_plan(
        self,
        *,
        user_id: str,
        message: str,
        steps: List[str],
        build_payload: Callable[[str, str, str, Dict[str, Any]], Dict[str, Any]],
        should_continue_after_step: Callable[[str, Any, Dict[str, Any]], bool],
    ) -> tuple[List[str], Dict[str, Any], List[Dict[str, Any]]]:
        trace: List[str] = []
        state: Dict[str, Any] = {}
        queue: List[str] = [step for step in steps if step in self.tool_registry.list_tool_names()]
        while queue:
            step = queue.pop(0)
            try:
                payload = build_payload(user_id, message, step, state)
                tool_result = self.tool_registry.run(step, payload)
            except ValueError:
                break
            if not bool(tool_result.get("ok", False)):
                break
            trace.append(step)
            state[step] = tool_result["data"]
            state["last_result"] = tool_result["data"]
            if not should_continue_after_step(step, tool_result["data"], state):
                break
        return trace, state, []

    def execute_react_loop(
        self,
        *,
        user_id: str,
        message: str,
        initial_steps: List[str],
        task_type: str,
        build_payload: Callable[[str, str, str, Dict[str, Any]], Dict[str, Any]],
        should_continue_after_step: Callable[[str, Any, Dict[str, Any]], bool],
    ) -> tuple[List[str], Dict[str, Any], List[Dict[str, Any]]]:
        trace: List[str] = []
        state: Dict[str, Any] = {}
        loop_trace: List[Dict[str, Any]] = []
        queue: List[str] = [step for step in initial_steps if step in self.tool_registry.list_tool_names()]

        while queue and len(trace) < self.max_loop_steps:
            step = queue.pop(0)
            try:
                payload = build_payload(user_id, message, step, state)
                tool_result = self.tool_registry.run(step, payload)
            except ValueError:
                break

            observation_summary = self._summarize_observation(step, tool_result.get("data"))
            if not bool(tool_result.get("ok", False)):
                loop_trace.append(
                    {
                        "step": step,
                        "action": "finish",
                        "decision": "stop",
                        "reason": "tool_error",
                        "observation_summary": observation_summary,
                    }
                )
                break

            trace.append(step)
            state[step] = tool_result["data"]
            state["last_result"] = tool_result["data"]
            state["_last_step"] = step

            if not should_continue_after_step(step, tool_result["data"], state):
                loop_trace.append(
                    {
                        "step": step,
                        "action": "finish",
                        "decision": "stop",
                        "reason": "rule_stop_after_step",
                        "observation_summary": observation_summary,
                    }
                )
                break
            if self._is_no_progress(step, tool_result["data"], state):
                loop_trace.append(
                    {
                        "step": step,
                        "action": "finish",
                        "decision": "stop",
                        "reason": "no_progress",
                        "observation_summary": observation_summary,
                    }
                )
                break

            if not queue:
                loop_trace.append(
                    {
                        "step": step,
                        "action": "finish",
                        "decision": "finish",
                        "reason": "plan_exhausted",
                        "observation_summary": observation_summary,
                    }
                )
                break

            react_action = self._decide_react_action(
                task_type=task_type,
                message=message,
                state=state,
                last_observation={
                    "step": step,
                    "result": tool_result["data"],
                    "summary": observation_summary,
                },
                remaining_steps=list(queue),
            )
            action = str(react_action.get("action") or "finish").strip().lower()
            if action != "tool":
                loop_trace.append(
                    {
                        "step": step,
                        "action": "finish",
                        "decision": "finish",
                        "reason": str(react_action.get("reason") or "observer_finish"),
                        "observation_summary": observation_summary,
                    }
                )
                break

            next_tool = str(react_action.get("tool_name") or "").strip()
            if not next_tool:
                loop_trace.append(
                    {
                        "step": step,
                        "action": "finish",
                        "decision": "finish",
                        "reason": "missing_tool_name",
                        "observation_summary": observation_summary,
                    }
                )
                break

            executed_counts: Dict[str, int] = {}
            for executed_step in trace:
                executed_counts[executed_step] = executed_counts.get(executed_step, 0) + 1
            if executed_counts.get(next_tool, 0) >= self.max_step_repeat:
                loop_trace.append(
                    {
                        "step": step,
                        "action": "finish",
                        "decision": "stop",
                        "reason": "max_step_repeat_reached",
                        "observation_summary": observation_summary,
                    }
                )
                break

            if not queue or queue[0] != next_tool:
                queue.insert(0, next_tool)
            queue = self._dedupe_over_repeated_steps(queue, trace)
            loop_trace.append(
                {
                    "step": step,
                    "action": "tool",
                    "decision": str(react_action.get("decision") or "continue"),
                    "reason": str(react_action.get("reason") or ""),
                    "next_tool": next_tool,
                    "observation_summary": str(react_action.get("observation_summary") or observation_summary),
                }
            )

        return trace, state, loop_trace

    def _decide_react_action(
        self,
        *,
        task_type: str,
        message: str,
        state: Dict[str, Any],
        last_observation: Optional[Dict[str, Any]],
        remaining_steps: List[str],
    ) -> Dict[str, Any]:
        decider = getattr(self.llm_client, "decide_react_action", None)
        if callable(decider):
            result = decider(
                task_type=task_type,
                message=message,
                state=state,
                last_observation=last_observation,
                available_tools=remaining_steps or self.tool_registry.list_tool_names(),
            )
            if "decision" not in result:
                result["decision"] = "continue" if result.get("action") == "tool" else "stop"
            return result
        fallback_decider = getattr(self.llm_client, "decide_next_action", None)
        if callable(fallback_decider):
            fallback = fallback_decider(
                task_type=task_type,
                message=message,
                current_step=str((last_observation or {}).get("step") or ""),
                tool_result=(last_observation or {}).get("result"),
                remaining_steps=remaining_steps,
                available_tools=self.tool_registry.list_tool_names(),
            )
            decision = str(fallback.get("decision") or "continue").strip().lower()
            if decision == "stop":
                return {"action": "finish", "tool_name": None, "reason": "legacy_stop", "decision": "stop"}
            if decision == "replan":
                steps = fallback.get("steps") if isinstance(fallback.get("steps"), list) else []
                next_tool = str(steps[0]).strip() if steps else None
                return {
                    "action": "tool" if next_tool else "finish",
                    "tool_name": next_tool,
                    "reason": str(fallback.get("reason") or "legacy_replan"),
                    "decision": "replan" if next_tool else "stop",
                }
            next_tool = remaining_steps[0] if remaining_steps else None
            return {
                "action": "tool" if next_tool else "finish",
                "tool_name": next_tool,
                "reason": str(fallback.get("reason") or "legacy_continue"),
                "decision": "continue" if next_tool else "stop",
            }
        return {"action": "finish", "tool_name": None, "reason": "no_decider", "decision": "stop"}

    def _dedupe_over_repeated_steps(self, queue: List[str], trace: List[str]) -> List[str]:
        if not queue:
            return queue
        executed_counts: Dict[str, int] = {}
        for step in trace:
            executed_counts[step] = executed_counts.get(step, 0) + 1
        return [step for step in queue if executed_counts.get(step, 0) < self.max_step_repeat]

    def _summarize_observation(self, step: str, tool_result: Any) -> str:
        if step == "search_jobs" and isinstance(tool_result, list):
            return f"found {len(tool_result)} job candidates"
        if step == "match_resume_to_jobs" and isinstance(tool_result, dict):
            matches = tool_result.get("matches", [])
            if isinstance(matches, list):
                return f"matched resume against {len(matches)} jobs"
        if step == "get_career_insights" and isinstance(tool_result, dict):
            return "generated career insight summary"
        return "tool executed"

    def _is_no_progress(self, step: str, tool_result: Any, state: Dict[str, Any]) -> bool:
        signature = self._progress_signature(step, tool_result)
        previous = state.get("_last_progress_signature")
        state["_last_progress_signature"] = signature
        if previous is None:
            return False
        return previous == signature

    def _progress_signature(self, step: str, tool_result: Any) -> Any:
        if step == "search_jobs" and isinstance(tool_result, list):
            return (
                step,
                tuple(
                    str(item.get("title", "")).strip().lower()
                    for item in tool_result[:3]
                    if isinstance(item, dict)
                ),
            )
        if step == "match_resume_to_jobs" and isinstance(tool_result, dict):
            matches = tool_result.get("matches", [])
            if isinstance(matches, list):
                return (
                    step,
                    tuple(
                        (str(match.get("job_title", "")).strip().lower(), str(match.get("match_score", "")))
                        for match in matches[:3]
                        if isinstance(match, dict)
                    ),
                )
        return (step, str(tool_result)[:400])

    def should_continue_after_search(
        self,
        *,
        step: str,
        tool_result: Any,
        state: Dict[str, Any],
    ) -> bool:
        if step != "search_jobs":
            return True

        if not tool_result:
            state["last_result"] = []
            return False

        resume_data = state.get("get_resume_by_id")
        if not resume_data:
            return True

        resume_tokens = self._tokenize(str(resume_data.get("content", "")))
        if not resume_tokens:
            return True

        search_tokens: set[str] = set()
        for item in tool_result:
            search_tokens |= self._tokenize(f"{item.get('title', '')} {item.get('snippet', '')}")

        meaningful_overlap = (resume_tokens - self._low_signal_tokens()) & (
            search_tokens - self._low_signal_tokens()
        )
        if meaningful_overlap:
            return True

        state["last_result"] = []
        return False

    def _tokenize(self, text: str) -> set[str]:
        return set(re.findall(r"[a-zA-Z0-9]+", text.lower()))

    def _low_signal_tokens(self) -> set[str]:
        return {"engineer", "intern", "platform", "systems", "system", "role", "job", "jobs"}
