import re
import time
from typing import Any, Callable, Dict, List, Optional, Sequence, Tuple

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
        replan_budget: int = 2,
        whitelist_executor_tools: Optional[List[str]] = None,
        validate_replan_chain: Optional[
            Callable[[Sequence[str], List[str]], Tuple[List[str], str]]
        ] = None,
    ) -> tuple[List[str], Dict[str, Any], List[Dict[str, Any]]]:
        trace: List[str] = []
        state: Dict[str, Any] = {}
        loop_trace: List[Dict[str, Any]] = []
        queue: List[str] = [step for step in initial_steps if step in self.tool_registry.list_tool_names()]
        strategy_replans_used = 0
        switch_count = 0
        step_repeat_count = 0
        last_step = ""
        loop_started = time.perf_counter()
        terminated_by = "plan_exhausted"

        whitelist = whitelist_executor_tools or list(self.tool_registry.list_tool_names())
        registry_names = self.tool_registry.list_tool_names()

        def validator(proposed: Sequence[str], exec_trace: List[str]) -> tuple[List[str], str]:
            if validate_replan_chain is None:
                return [], "rejected"
            return validate_replan_chain(proposed, exec_trace)

        while queue and len(trace) < self.max_loop_steps:
            iteration = len(trace) + 1
            step = queue.pop(0)
            if step == last_step:
                step_repeat_count += 1
            else:
                step_repeat_count = 1
            last_step = step
            if step_repeat_count > self.max_step_repeat:
                terminated_by = "max_repeat_guard"
                loop_trace.append(
                    {
                        "iteration": iteration,
                        "current_step": step,
                        "tool_result_summary": "step repeated over guard threshold",
                        "decider_action": "finish",
                        "decider_reason": "max_repeat_guard",
                        "strategy_replans_used": strategy_replans_used,
                        "budget_remaining": max(replan_budget - strategy_replans_used, 0),
                        "elapsed_ms": round((time.perf_counter() - loop_started) * 1000, 2),
                    }
                )
                break
            try:
                payload = build_payload(user_id, message, step, state)
                tool_result = self.tool_registry.run(step, payload)
            except ValueError:
                terminated_by = "finish"
                break

            observation_summary = self._summarize_observation(step, tool_result.get("data"))
            state["last_observation"] = {
                "step": step,
                "result": tool_result.get("data"),
                "summary": observation_summary,
            }
            if not bool(tool_result.get("ok", False)):
                terminated_by = "finish"
                loop_trace.append(
                    {
                        "iteration": iteration,
                        "current_step": step,
                        "tool_result_summary": observation_summary,
                        "decider_action": "finish",
                        "decider_reason": "tool_error",
                        "strategy_replans_used": strategy_replans_used,
                        "budget_remaining": max(replan_budget - strategy_replans_used, 0),
                        "elapsed_ms": round((time.perf_counter() - loop_started) * 1000, 2),
                    }
                )
                break

            trace.append(step)
            state[step] = tool_result["data"]
            state["last_result"] = tool_result["data"]
            state["_last_step"] = step

            if not should_continue_after_step(step, tool_result["data"], state):
                terminated_by = "finish"
                loop_trace.append(
                    {
                        "iteration": iteration,
                        "current_step": step,
                        "tool_result_summary": observation_summary,
                        "decider_action": "finish",
                        "decider_reason": "rule_stop_after_step",
                        "strategy_replans_used": strategy_replans_used,
                        "budget_remaining": max(replan_budget - strategy_replans_used, 0),
                        "elapsed_ms": round((time.perf_counter() - loop_started) * 1000, 2),
                    }
                )
                break
            if self._is_no_progress(step, tool_result["data"], state):
                terminated_by = "finish"
                loop_trace.append(
                    {
                        "iteration": iteration,
                        "current_step": step,
                        "tool_result_summary": observation_summary,
                        "decider_action": "finish",
                        "decider_reason": "no_progress",
                        "strategy_replans_used": strategy_replans_used,
                        "budget_remaining": max(replan_budget - strategy_replans_used, 0),
                        "elapsed_ms": round((time.perf_counter() - loop_started) * 1000, 2),
                    }
                )
                break

            if not queue:
                terminated_by = "finish"
                loop_trace.append(
                    {
                        "iteration": iteration,
                        "current_step": step,
                        "tool_result_summary": observation_summary,
                        "decider_action": "finish",
                        "decider_reason": "plan_exhausted",
                        "strategy_replans_used": strategy_replans_used,
                        "budget_remaining": max(replan_budget - strategy_replans_used, 0),
                        "elapsed_ms": round((time.perf_counter() - loop_started) * 1000, 2),
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
                whitelist_executor_tools=list(whitelist),
            )
            action_before = str(react_action.get("action") or "continue").strip().lower()
            reason = str(react_action.get("reason") or "")
            consume_budget = bool(react_action.get("consume_budget", False))
            inferred_context = self._infer_missing_context(step=step, tool_result=tool_result["data"])

            def _budget_meta() -> Dict[str, Any]:
                return {
                    "strategy_replans_used": strategy_replans_used,
                    "switch_count": switch_count,
                    "budget_remaining": max(replan_budget - strategy_replans_used, 0),
                }

            if inferred_context["missing_context"] and action_before != "ask_for_context":
                action_before = "ask_for_context"

            if action_before == "ask_for_context" or inferred_context["missing_context"]:
                terminated_by = "ask_for_context"
                state["_missing_context"] = inferred_context["missing_context"]
                state["_follow_up_question"] = inferred_context["follow_up_question"]
                loop_trace.append(
                    {
                        "iteration": iteration,
                        "current_step": step,
                        "tool_result_summary": observation_summary,
                        "decider_action": "ask_for_context",
                        "decider_reason": reason or inferred_context["reason"],
                        "action_before": action_before,
                        "action_after": "ask_for_context",
                        "replan_reason": "",
                        "candidate_tools": list(queue),
                        "selected_tool": None,
                        "replanned_chain": [],
                        "guardrail_decision": "accepted",
                        **_budget_meta(),
                        "elapsed_ms": round((time.perf_counter() - loop_started) * 1000, 2),
                    }
                )
                break

            if action_before == "finish":
                terminated_by = "finish"
                loop_trace.append(
                    {
                        "iteration": iteration,
                        "current_step": step,
                        "tool_result_summary": observation_summary,
                        "decider_action": "finish",
                        "decider_reason": reason or "observer_finish",
                        "action_before": action_before,
                        "action_after": "finish",
                        "candidate_tools": list(queue),
                        "selected_tool": None,
                        "replanned_chain": [],
                        "guardrail_decision": "accepted",
                        **_budget_meta(),
                        "elapsed_ms": round((time.perf_counter() - loop_started) * 1000, 2),
                    }
                )
                break

            if action_before == "switch_tool":
                tool_name = str(react_action.get("tool_name") or "").strip()
                prior_queue = list(queue)
                remaining_tool_set = set(prior_queue)
                switch_ok = (
                    tool_name
                    and tool_name in remaining_tool_set
                    and tool_name in set(whitelist)
                    and tool_name in set(registry_names)
                )
                replanned_chain_snapshot: List[str] = []
                if switch_ok:
                    remainder_after = [tool_name] + [s for s in prior_queue if s != tool_name]
                    queue[:] = remainder_after
                    switch_count += 1
                    strategy_replans_used += 1
                    rr_guardrail = "accepted"
                    action_after = "switch_tool"
                else:
                    rr_guardrail = "rejected"
                    action_after = "continue"

                loop_trace.append(
                    {
                        "iteration": iteration,
                        "current_step": step,
                        "tool_result_summary": observation_summary,
                        "decider_action": action_before if rr_guardrail == "accepted" else "continue",
                        "decider_reason": reason or "switch_tool",
                        "action_before": action_before,
                        "action_after": action_after,
                        "replan_reason": reason or "",
                        "candidate_tools": prior_queue,
                        "selected_tool": tool_name if rr_guardrail == "accepted" else None,
                        "replanned_chain": replanned_chain_snapshot,
                        "guardrail_decision": rr_guardrail,
                        **_budget_meta(),
                        "elapsed_ms": round((time.perf_counter() - loop_started) * 1000, 2),
                    }
                )

                spend = 1 if rr_guardrail == "accepted" else 0
                if spend and strategy_replans_used > replan_budget:
                    terminated_by = "budget_exhausted"
                    loop_trace.append(
                        {
                            "iteration": iteration,
                            "current_step": step,
                            "tool_result_summary": observation_summary,
                            "decider_action": "finish",
                            "decider_reason": "budget_exhausted",
                            "action_before": action_before,
                            "action_after": "finish",
                            "guardrail_decision": "fallback",
                            **_budget_meta(),
                            "elapsed_ms": round((time.perf_counter() - loop_started) * 1000, 2),
                        }
                    )
                    break

                continue

            if action_before == "replan_strategy":
                proposed = react_action.get("planned_tools") or []
                if not isinstance(proposed, list):
                    proposed = []
                normalized, gd = validator(proposed, trace)
                normalized_chain = list(normalized)
                replaced = ""
                action_after_rs = action_before
                if gd != "accepted" or not normalized_chain:
                    normalized_chain_out: List[str] = []
                    replan_gr = "rejected"
                    action_after_rs = "continue"
                else:
                    queue[:] = normalized_chain
                    strategy_replans_used += 1
                    replan_gr = "accepted"
                    replaced = "queue_replaced"
                    normalized_chain_out = normalized_chain

                loop_trace.append(
                    {
                        "iteration": iteration,
                        "current_step": step,
                        "tool_result_summary": observation_summary,
                        "decider_action": action_before if replan_gr == "accepted" else "continue",
                        "decider_reason": reason or "replan_strategy",
                        "action_before": action_before,
                        "action_after": action_after_rs,
                        "replan_reason": replaced,
                        "candidate_tools": list(proposed),
                        "selected_tool": None,
                        "replanned_chain": normalized_chain_out if replan_gr == "accepted" else [],
                        "guardrail_decision": replan_gr,
                        **_budget_meta(),
                        "elapsed_ms": round((time.perf_counter() - loop_started) * 1000, 2),
                    }
                )

                if replan_gr == "accepted" and strategy_replans_used > replan_budget:
                    terminated_by = "budget_exhausted"
                    loop_trace.append(
                        {
                            "iteration": iteration,
                            "current_step": step,
                            "tool_result_summary": observation_summary,
                            "decider_action": "finish",
                            "decider_reason": "budget_exhausted",
                            "guardrail_decision": "fallback",
                            **_budget_meta(),
                            "elapsed_ms": round((time.perf_counter() - loop_started) * 1000, 2),
                        }
                    )
                    break

                continue

            if consume_budget:
                strategy_replans_used += 1
                if strategy_replans_used > replan_budget:
                    terminated_by = "budget_exhausted"
                    loop_trace.append(
                        {
                            "iteration": iteration,
                            "current_step": step,
                            "tool_result_summary": observation_summary,
                            "decider_action": "finish",
                            "decider_reason": "budget_exhausted",
                            "guardrail_decision": "fallback",
                            **_budget_meta(),
                            "elapsed_ms": round((time.perf_counter() - loop_started) * 1000, 2),
                        }
                    )
                    break

            loop_trace.append(
                {
                    "iteration": iteration,
                    "current_step": step,
                    "tool_result_summary": str(react_action.get("observation_summary") or observation_summary),
                    "decider_action": "continue",
                    "decider_reason": reason or "observer_continue",
                    "action_before": action_before,
                    "action_after": "continue",
                    "candidate_tools": list(queue),
                    "selected_tool": None,
                    "replanned_chain": [],
                    "guardrail_decision": "accepted",
                    **_budget_meta(),
                    "elapsed_ms": round((time.perf_counter() - loop_started) * 1000, 2),
                }
            )
            continue

        state["_loop_control"] = {
            "executor_mode": "react_strategy",
            "replan_budget": replan_budget,
            "strategy_replans_used": strategy_replans_used,
            "switch_count": switch_count,
            "replan_count": strategy_replans_used,
            "step_repeat_count": step_repeat_count,
            "terminated_by": terminated_by,
            "last_observation": state.get("last_observation"),
        }
        return trace, state, loop_trace

    def _decide_react_action(
        self,
        *,
        task_type: str,
        message: str,
        state: Dict[str, Any],
        last_observation: Optional[Dict[str, Any]],
        remaining_steps: List[str],
        whitelist_executor_tools: List[str],
    ) -> Dict[str, Any]:
        decider = getattr(self.llm_client, "decide_react_action", None)
        if callable(decider):
            result = decider(
                task_type=task_type,
                message=message,
                state=state,
                last_observation=last_observation,
                available_tools=remaining_steps or self.tool_registry.list_tool_names(),
                executor_whitelist=whitelist_executor_tools,
            )
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
                return {"action": "finish", "reason": "legacy_stop"}
            if decision == "replan":
                return {
                    "action": "continue",
                    "reason": str(fallback.get("reason") or "legacy_replan"),
                    "consume_budget": True,
                }
            return {
                "action": "continue" if remaining_steps else "finish",
                "reason": str(fallback.get("reason") or "legacy_continue"),
                "consume_budget": False,
            }
        return {"action": "finish", "reason": "no_decider"}

    def _infer_missing_context(self, *, step: str, tool_result: Any) -> Dict[str, Any]:
        if isinstance(tool_result, dict):
            missing = tool_result.get("missing_context")
            if isinstance(missing, list) and missing:
                return {
                    "missing_context": [str(item) for item in missing if str(item).strip()],
                    "follow_up_question": str(tool_result.get("follow_up_question") or "").strip() or None,
                    "reason": "missing_context_from_tool",
                }
        if step == "search_jobs" and isinstance(tool_result, list) and not tool_result:
            return {
                "missing_context": ["job_detail"],
                "follow_up_question": "我还缺少明确岗位信息。请提供岗位 JD、岗位链接，或粘贴岗位描述。",
                "reason": "missing_job_detail",
            }
        return {"missing_context": [], "follow_up_question": None, "reason": ""}

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
