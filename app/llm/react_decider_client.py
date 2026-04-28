import json
from typing import Any, Dict, List, Optional

import httpx


class ReactDeciderClient:
    def __init__(self, *, timeout_seconds: float) -> None:
        self.timeout_seconds = timeout_seconds

    def decide_next_action(
        self,
        *,
        is_configured: bool,
        request_builder: Any,
        post_responses: Any,
        extract_chat_completion_text: Any,
        planner_base_url: str,
        planner_api_key: str,
        task_type: str,
        message: str,
        current_step: str,
        tool_result: Any,
        remaining_steps: List[str],
        available_tools: List[str],
    ) -> Dict[str, Any]:
        if not is_configured:
            return self.fallback_observe_decision(
                task_type=task_type,
                current_step=current_step,
                tool_result=tool_result,
                remaining_steps=remaining_steps,
            )
        request = request_builder(
            task_type=task_type,
            message=message,
            current_step=current_step,
            tool_result=tool_result,
            remaining_steps=remaining_steps,
            available_tools=available_tools,
        )
        try:
            payload = post_responses(
                f"{planner_base_url.rstrip('/')}/chat/completions",
                api_key=planner_api_key,
                payload=request,
                timeout=self.timeout_seconds,
            )
            raw = extract_chat_completion_text(payload).strip()
            parsed = json.loads(raw) if raw else {}
            decision = str(parsed.get("decision") or "continue").strip().lower()
            if decision not in {"continue", "stop", "replan"}:
                decision = "continue"
            steps = parsed.get("steps") if isinstance(parsed.get("steps"), list) else []
            sanitized_steps = [
                str(step).strip()
                for step in steps
                if isinstance(step, str) and str(step).strip() in set(available_tools)
            ]
            return {"decision": decision, "reason": str(parsed.get("reason") or "").strip(), "steps": sanitized_steps}
        except (RuntimeError, ValueError, TypeError, json.JSONDecodeError, httpx.HTTPError):
            return self.fallback_observe_decision(
                task_type=task_type,
                current_step=current_step,
                tool_result=tool_result,
                remaining_steps=remaining_steps,
            )

    def sanitize_react_action(
        self,
        *,
        parsed: Dict[str, Any],
        available_tools: List[str],
    ) -> Dict[str, Any]:
        action = str(parsed.get("action") or "finish").strip().lower()
        if action not in {"tool", "finish"}:
            action = "finish"
        tool_name_raw = parsed.get("tool_name")
        tool_name = str(tool_name_raw).strip() if isinstance(tool_name_raw, str) else ""
        if action == "tool" and tool_name not in set(available_tools):
            action = "finish"
            tool_name = ""
        return {
            "action": action,
            "tool_name": tool_name or None,
            "reason": str(parsed.get("reason") or "").strip(),
            "observation_summary": str(parsed.get("observation_summary") or "").strip(),
            "tool_input_hint": parsed.get("tool_input_hint") if isinstance(parsed.get("tool_input_hint"), dict) else {},
        }

    def fallback_react_action(
        self,
        *,
        state: Dict[str, Any],
        available_tools: List[str],
        reason: str,
    ) -> Dict[str, Any]:
        if available_tools:
            return {
                "action": "tool",
                "tool_name": available_tools[0],
                "reason": reason,
                "observation_summary": "",
                "tool_input_hint": {},
            }
        last_step = str(state.get("_last_step") or "")
        if last_step:
            idx = available_tools.index(last_step) if last_step in available_tools else -1
            if idx >= 0 and idx + 1 < len(available_tools):
                return {
                    "action": "tool",
                    "tool_name": available_tools[idx + 1],
                    "reason": reason,
                    "observation_summary": "",
                    "tool_input_hint": {},
                }
        return {"action": "finish", "tool_name": None, "reason": reason, "observation_summary": "", "tool_input_hint": {}}

    def fallback_observe_decision(
        self,
        *,
        task_type: str,
        current_step: str,
        tool_result: Any,
        remaining_steps: List[str],
    ) -> Dict[str, Any]:
        if task_type == "job_match_planning" and current_step == "search_jobs":
            hits = tool_result if isinstance(tool_result, list) else []
            if not hits:
                return {"decision": "stop", "reason": "search returned no jobs", "steps": []}
            if "match_resume_to_jobs" not in remaining_steps:
                return {
                    "decision": "replan",
                    "reason": "search returned jobs; append matching step",
                    "steps": ["match_resume_to_jobs"],
                }
        return {"decision": "continue", "reason": "default continue", "steps": []}
