import json
from typing import Any, Dict, List, Optional

import httpx
from pydantic import ValidationError

from app.env import settings
from app.llm.prompts import (
    CAREER_EVENT_EXTRACTOR_SYSTEM_PROMPT,
    JOB_SEARCH_SUMMARIZER_SYSTEM_PROMPT,
    PLANNER_SYSTEM_PROMPT,
)
from app.schemas.chat import ChatPlan


class LLMClient:
    """LLM wrapper with a deterministic fallback path for local development."""

    ALLOWED_TASK_TYPES = {
        "candidate_profile",
        "job_search",
        "job_match",
        "job_match_planning",
        "interview_history",
        "career_insights",
        "fallback",
    }
    # Hard cap on planner-produced step chains. Anything longer is treated as a
    # hallucinated tool loop and falls back to the deterministic plan.
    MAX_PLAN_STEPS = 6
    PLANNER_TIMEOUT_SECONDS = 12.0
    JOB_SEARCH_SUMMARY_TIMEOUT_SECONDS = 12.0
    CAREER_EVENT_EXTRACTION_TIMEOUT_SECONDS = 5.0
    OBSERVE_DECISION_TIMEOUT_SECONDS = 10.0

    def __init__(self) -> None:
        self.model = settings.default_model
        self.last_plan_source = "not_used"
        self.last_job_search_summary_source = "not_used"
        self.last_generate_source = "not_used"

    def is_configured(self) -> bool:
        return bool(settings.openai_api_key)

    def _planner_api_key(self) -> str:
        return settings.planner_api_key

    def _planner_base_url(self) -> str:
        return settings.planner_base_url

    def _planner_model(self) -> str:
        return settings.planner_model

    def generate_plan(
        self,
        message: str,
        memory_context: List[str],
        profile: Dict[str, Any],
        available_tools: List[str],
        user_state: Dict[str, Any] = None,
    ) -> Dict[str, Any]:
        normalized_user_state = user_state or {}
        last_error: Optional[Exception] = None

        for _ in range(2):
            try:
                plan_payload = self._generate_plan_with_model(
                    message=message,
                    memory_context=memory_context,
                    profile=profile,
                    available_tools=available_tools,
                    user_state=normalized_user_state,
                )
                self.last_plan_source = "model"
                return self._validated_plan(
                    plan_payload,
                    planner_source="model",
                    available_tools=available_tools,
                )
            except (RuntimeError, ValidationError, ValueError, httpx.HTTPError) as exc:
                last_error = exc

        _ = last_error
        self.last_plan_source = "fallback"
        return self._validated_plan(
            self._fallback_plan(
                message,
                memory_context,
                profile,
                available_tools,
                normalized_user_state,
            ),
            planner_source="fallback",
            available_tools=available_tools,
        )

    def generate(
        self,
        message: str,
        memory_context: list[str],
        evidence: list[str],
    ) -> str:
        self.last_generate_source = "fallback"
        if self.is_configured():
            return (
                f"Model {self.model} is configured, but live completion is not wired yet."
            )

        if evidence:
            titles = ", ".join(evidence)
            return f"Fallback response for '{message}'. Relevant evidence: {titles}."

        if memory_context:
            return (
                f"Fallback response for '{message}'. "
                "I also used your recent conversation context."
            )

        return f"Fallback response for '{message}'."

    def summarize_job_search(
        self,
        message: str,
        memory_context: List[str],
        jobs: List[Dict[str, Any]],
    ) -> str:
        top_jobs = self._top_job_search_hits(jobs)
        if not self._job_search_summarizer_is_configured():
            self.last_job_search_summary_source = "fallback"
            return self._fallback_job_search_summary(top_jobs, bool(memory_context))
        try:
            request = self._build_job_search_summarize_chat_request(
                message=message,
                memory_context=memory_context,
                jobs=top_jobs,
            )
            chat_payload = self._post_responses(
                f"{self._planner_base_url().rstrip('/')}/chat/completions",
                api_key=self._planner_api_key(),
                payload=request,
                timeout=self.JOB_SEARCH_SUMMARY_TIMEOUT_SECONDS,
            )
            text = self._extract_chat_completion_text(chat_payload).strip()
            if not text:
                self.last_job_search_summary_source = "fallback"
                return self._fallback_job_search_summary(top_jobs, bool(memory_context))
            self.last_job_search_summary_source = "model"
            return text
        except (RuntimeError, ValueError, httpx.HTTPError):
            self.last_job_search_summary_source = "fallback"
            return self._fallback_job_search_summary(top_jobs, bool(memory_context))

    def extract_career_events(
        self,
        user_id: str,
        message: str,
    ) -> List[Dict[str, str]]:
        if not self._career_event_extractor_is_configured():
            return []
        try:
            request = self._build_career_event_extract_request(
                user_id=user_id,
                message=message,
            )
            response_payload = self._post_responses(
                f"{self._planner_base_url().rstrip('/')}/responses",
                api_key=self._planner_api_key(),
                payload=request,
                timeout=self.CAREER_EVENT_EXTRACTION_TIMEOUT_SECONDS,
            )
            text = self._extract_responses_text(response_payload)
            return self._normalize_extracted_career_events(json.loads(text))
        except (RuntimeError, ValueError, TypeError, json.JSONDecodeError, httpx.HTTPError):
            return []

    def decide_next_action(
        self,
        *,
        task_type: str,
        message: str,
        current_step: str,
        tool_result: Any,
        remaining_steps: List[str],
        available_tools: List[str],
    ) -> Dict[str, Any]:
        """Bounded observe step for executor loops.

        Returns a structured decision:
          - {"decision": "continue"|"stop"|"replan", "reason": str, "steps": list[str]}
        """
        if not self.is_configured():
            return self._fallback_observe_decision(
                task_type=task_type,
                current_step=current_step,
                tool_result=tool_result,
                remaining_steps=remaining_steps,
            )

        request = self._build_observe_decision_request(
            task_type=task_type,
            message=message,
            current_step=current_step,
            tool_result=tool_result,
            remaining_steps=remaining_steps,
            available_tools=available_tools,
        )
        try:
            payload = self._post_responses(
                f"{self._planner_base_url().rstrip('/')}/chat/completions",
                api_key=self._planner_api_key(),
                payload=request,
                timeout=self.OBSERVE_DECISION_TIMEOUT_SECONDS,
            )
            raw = self._extract_chat_completion_text(payload).strip()
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
            return {
                "decision": decision,
                "reason": str(parsed.get("reason") or "").strip(),
                "steps": sanitized_steps,
            }
        except (RuntimeError, ValueError, TypeError, json.JSONDecodeError, httpx.HTTPError):
            return self._fallback_observe_decision(
                task_type=task_type,
                current_step=current_step,
                tool_result=tool_result,
                remaining_steps=remaining_steps,
            )

    def decide_react_action(
        self,
        *,
        task_type: str,
        message: str,
        state: Dict[str, Any],
        last_observation: Optional[Dict[str, Any]],
        available_tools: List[str],
    ) -> Dict[str, Any]:
        """Decide next bounded ReAct action.

        Returns:
          {"action": "tool"|"finish", "tool_name": str|None, "reason": str, "observation_summary": str}
        """
        if not self.is_configured():
            return self._fallback_react_action(
                state=state,
                available_tools=available_tools,
                reason="llm_not_configured",
            )

        request = self._build_react_action_request(
            task_type=task_type,
            message=message,
            state=state,
            last_observation=last_observation,
            available_tools=available_tools,
        )
        try:
            payload = self._post_responses(
                f"{self._planner_base_url().rstrip('/')}/chat/completions",
                api_key=self._planner_api_key(),
                payload=request,
                timeout=self.OBSERVE_DECISION_TIMEOUT_SECONDS,
            )
            raw = self._extract_chat_completion_text(payload).strip()
            parsed = json.loads(raw) if raw else {}
            return self._sanitize_react_action(
                parsed=parsed,
                state=state,
                available_tools=available_tools,
            )
        except (RuntimeError, ValueError, TypeError, json.JSONDecodeError, httpx.HTTPError):
            return self._fallback_react_action(
                state=state,
                available_tools=available_tools,
                reason="react_fallback_after_error",
            )

    def _generate_plan_with_model(
        self,
        message: str,
        memory_context: List[str],
        profile: Dict[str, Any],
        available_tools: List[str],
        user_state: Dict[str, Any],
    ) -> Dict[str, Any]:
        if not self.is_configured():
            raise RuntimeError("LLM planner not configured")

        request = self._build_plan_request(
            message=message,
            memory_context=memory_context,
            profile=profile,
            available_tools=available_tools,
            user_state=user_state,
        )
        try:
            response_payload = self._post_responses(
                f"{self._planner_base_url().rstrip('/')}/responses",
                api_key=self._planner_api_key(),
                payload=request,
                timeout=self.PLANNER_TIMEOUT_SECONDS,
            )
            return self._extract_plan_payload(response_payload)
        except httpx.HTTPStatusError as exc:
            if exc.response.status_code != 404:
                raise

        chat_request = self._build_chat_completions_plan_request(
            message=message,
            memory_context=memory_context,
            profile=profile,
            available_tools=available_tools,
            user_state=user_state,
        )
        chat_payload = self._post_responses(
            f"{self._planner_base_url().rstrip('/')}/chat/completions",
            api_key=self._planner_api_key(),
            payload=chat_request,
            timeout=self.PLANNER_TIMEOUT_SECONDS,
        )
        return self._extract_chat_completions_plan_payload(chat_payload)

    def _build_plan_request(
        self,
        message: str,
        memory_context: List[str],
        profile: Dict[str, Any],
        available_tools: List[str],
        user_state: Dict[str, Any],
    ) -> Dict[str, Any]:
        request = {
            "model": self._planner_model(),
            "input": [
                {
                    "role": "system",
                    "content": PLANNER_SYSTEM_PROMPT,
                },
                {
                    "role": "user",
                    "content": json.dumps(
                        {
                            "message": message,
                            "memory_context": memory_context,
                            "profile": profile,
                            "available_tools": available_tools,
                            "user_state": user_state,
                        },
                        ensure_ascii=False,
                    ),
                },
            ],
            "text": {
                "format": {
                    "type": "json_schema",
                    "name": "chat_plan",
                    "strict": True,
                    "schema": ChatPlan.model_json_schema(),
                }
            },
        }
        if settings.planner_disable_thinking:
            self._disable_thinking(request)
        return request

    def _build_chat_completions_plan_request(
        self,
        message: str,
        memory_context: List[str],
        profile: Dict[str, Any],
        available_tools: List[str],
        user_state: Dict[str, Any],
    ) -> Dict[str, Any]:
        request = {
            "model": self._planner_model(),
            "messages": [
                {
                    "role": "system",
                    "content": PLANNER_SYSTEM_PROMPT,
                },
                {
                    "role": "user",
                    "content": json.dumps(
                        {
                            "message": message,
                            "memory_context": memory_context,
                            "profile": profile,
                            "available_tools": available_tools,
                            "user_state": user_state,
                        },
                        ensure_ascii=False,
                    ),
                },
            ],
            "response_format": {
                "type": "json_schema",
                "json_schema": {
                    "name": "chat_plan",
                    "strict": True,
                    "schema": ChatPlan.model_json_schema(),
                },
            },
        }
        if settings.planner_disable_thinking:
            self._disable_thinking(request)
        return request

    def _extract_plan_payload(self, payload: Dict[str, Any]) -> Dict[str, Any]:
        text = self._extract_responses_text(payload)
        if text:
            return json.loads(text)
        raise ValueError("No structured planner payload returned by model")

    def _extract_responses_text(self, payload: Dict[str, Any]) -> str:
        output = payload.get("output", [])
        for item in output:
            for content in item.get("content", []):
                text = content.get("text")
                if text:
                    return text
        return ""

    def _extract_chat_completions_plan_payload(
        self,
        payload: Dict[str, Any],
    ) -> Dict[str, Any]:
        choices = payload.get("choices", [])
        for choice in choices:
            message = choice.get("message", {})
            content = message.get("content")
            if content:
                return json.loads(content)
        raise ValueError("No structured planner payload returned by chat completions")

    def _validated_plan(
        self,
        plan_payload: Dict[str, Any],
        planner_source: str,
        available_tools: Optional[List[str]] = None,
    ) -> Dict[str, Any]:
        normalized_payload = self._normalize_plan(plan_payload)
        plan = ChatPlan.model_validate(
            {
                **normalized_payload,
                "planner_source": planner_source,
            }
        )
        self._validate_plan_contract(plan, available_tools=available_tools)
        return plan.model_dump()

    def _normalize_plan(self, plan_payload: Dict[str, Any]) -> Dict[str, Any]:
        normalized = dict(plan_payload)
        if normalized.get("task_type") != "job_search":
            return normalized
        steps = normalized.get("steps", [])
        if "search_jobs" not in steps:
            return normalized
        normalized["steps"] = ["search_jobs"]
        return normalized

    def _validate_plan_contract(
        self,
        plan: ChatPlan,
        available_tools: Optional[List[str]] = None,
    ) -> None:
        if plan.task_type not in self.ALLOWED_TASK_TYPES:
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

        if len(steps) > self.MAX_PLAN_STEPS:
            raise ValueError(
                f"plan steps exceed MAX_PLAN_STEPS={self.MAX_PLAN_STEPS}"
            )

        if available_tools is not None:
            allowed_tools = set(available_tools)
            unknown = [step for step in steps if step not in allowed_tools]
            if unknown:
                raise ValueError(
                    f"plan contains steps not in available_tools: {unknown}"
                )

        if plan.task_type == "job_match_planning" and steps:
            # For recommendation plans, we must search before matching so the
            # match step has candidate jobs to score against.
            if "search_jobs" in steps and "match_resume_to_jobs" in steps:
                if steps.index("search_jobs") > steps.index("match_resume_to_jobs"):
                    raise ValueError(
                        "job_match_planning requires search_jobs before match_resume_to_jobs"
                    )

    def _post_responses(
        self,
        url: str,
        api_key: str,
        payload: Dict[str, Any],
        timeout: float = 45.0,
    ) -> Dict[str, Any]:
        response = httpx.post(
            url,
            headers={
                "Authorization": f"Bearer {api_key}",
                "Content-Type": "application/json",
            },
            json=payload,
            timeout=timeout,
        )
        response.raise_for_status()
        return response.json()

    def _build_job_search_summarize_chat_request(
        self,
        message: str,
        memory_context: List[str],
        jobs: List[Dict[str, Any]],
    ) -> Dict[str, Any]:
        request = {
            "model": self._planner_model(),
            "messages": [
                {
                    "role": "system",
                    "content": JOB_SEARCH_SUMMARIZER_SYSTEM_PROMPT,
                },
                {
                    "role": "user",
                    "content": json.dumps(
                        {
                            "message": message,
                            "memory_context": memory_context,
                            "jobs": jobs,
                        },
                        ensure_ascii=False,
                    ),
                },
            ],
        }
        self._disable_thinking(request)
        return request

    def _disable_thinking(self, request: Dict[str, Any]) -> None:
        request["thinking"] = {"type": "disabled"}

    def _build_career_event_extract_request(
        self,
        user_id: str,
        message: str,
    ) -> Dict[str, Any]:
        request = {
            "model": self._planner_model(),
            "input": [
                {
                    "role": "system",
                    "content": CAREER_EVENT_EXTRACTOR_SYSTEM_PROMPT,
                },
                {
                    "role": "user",
                    "content": json.dumps(
                        {
                            "user_id": user_id,
                            "message": message,
                        },
                        ensure_ascii=False,
                    ),
                },
            ],
            "text": {
                "format": {
                    "type": "json_schema",
                    "name": "career_events",
                    "strict": True,
                    "schema": {
                        "type": "object",
                        "additionalProperties": False,
                        "properties": {
                            "events": {
                                "type": "array",
                                "maxItems": 3,
                                "items": {
                                    "type": "object",
                                    "additionalProperties": False,
                                    "properties": {
                                        "event_type": {
                                            "type": "string",
                                            "enum": [
                                                "application_status",
                                                "interview_feedback",
                                                "assessment_result",
                                                "career_milestone",
                                            ],
                                        },
                                        "title": {"type": "string"},
                                        "summary": {"type": "string"},
                                        "occurred_at": {
                                            "type": ["string", "null"],
                                        },
                                    },
                                    "required": [
                                        "event_type",
                                        "title",
                                        "summary",
                                        "occurred_at",
                                    ],
                                },
                            }
                        },
                        "required": ["events"],
                    },
                }
            },
        }
        self._disable_thinking(request)
        return request

    def _build_observe_decision_request(
        self,
        *,
        task_type: str,
        message: str,
        current_step: str,
        tool_result: Any,
        remaining_steps: List[str],
        available_tools: List[str],
    ) -> Dict[str, Any]:
        schema = {
            "type": "object",
            "additionalProperties": False,
            "properties": {
                "decision": {
                    "type": "string",
                    "enum": ["continue", "stop", "replan"],
                },
                "reason": {"type": "string"},
                "steps": {
                    "type": "array",
                    "items": {"type": "string"},
                },
            },
            "required": ["decision", "reason", "steps"],
        }
        request = {
            "model": self._planner_model(),
            "messages": [
                {
                    "role": "system",
                    "content": (
                        "You are an execution observer for a career agent. "
                        "Given current step result, decide one of: continue, stop, replan. "
                        "Use replan only when current result makes remaining steps clearly suboptimal."
                    ),
                },
                {
                    "role": "user",
                    "content": json.dumps(
                        {
                            "task_type": task_type,
                            "message": message,
                            "current_step": current_step,
                            "tool_result": tool_result,
                            "remaining_steps": remaining_steps,
                            "available_tools": available_tools,
                        },
                        ensure_ascii=False,
                    ),
                },
            ],
            "response_format": {
                "type": "json_schema",
                "json_schema": {
                    "name": "observe_decision",
                    "strict": True,
                    "schema": schema,
                },
            },
        }
        if settings.planner_disable_thinking:
            self._disable_thinking(request)
        return request

    def _build_react_action_request(
        self,
        *,
        task_type: str,
        message: str,
        state: Dict[str, Any],
        last_observation: Optional[Dict[str, Any]],
        available_tools: List[str],
    ) -> Dict[str, Any]:
        schema = {
            "type": "object",
            "additionalProperties": False,
            "properties": {
                "action": {"type": "string", "enum": ["tool", "finish"]},
                "tool_name": {"type": ["string", "null"]},
                "tool_input_hint": {"type": "object", "additionalProperties": True},
                "reason": {"type": "string"},
                "observation_summary": {"type": "string"},
            },
            "required": ["action", "tool_name", "tool_input_hint", "reason", "observation_summary"],
        }
        request = {
            "model": self._planner_model(),
            "messages": [
                {
                    "role": "system",
                    "content": (
                        "You are a bounded ReAct controller for a career agent. "
                        "Choose exactly one next action: call one tool or finish. "
                        "Never output chain-of-thought."
                    ),
                },
                {
                    "role": "user",
                    "content": json.dumps(
                        {
                            "task_type": task_type,
                            "message": message,
                            "state": state,
                            "last_observation": last_observation,
                            "available_tools": available_tools,
                        },
                        ensure_ascii=False,
                    ),
                },
            ],
            "response_format": {
                "type": "json_schema",
                "json_schema": {
                    "name": "react_action",
                    "strict": True,
                    "schema": schema,
                },
            },
        }
        if settings.planner_disable_thinking:
            self._disable_thinking(request)
        return request

    def _sanitize_react_action(
        self,
        *,
        parsed: Dict[str, Any],
        state: Dict[str, Any],
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
            "tool_input_hint": parsed.get("tool_input_hint")
            if isinstance(parsed.get("tool_input_hint"), dict)
            else {},
        }

    def _fallback_react_action(
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
        return {
            "action": "finish",
            "tool_name": None,
            "reason": reason,
            "observation_summary": "",
            "tool_input_hint": {},
        }

    def _fallback_observe_decision(
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

    def _extract_chat_completion_text(self, payload: Dict[str, Any]) -> str:
        choices = payload.get("choices", [])
        for choice in choices:
            message = choice.get("message", {})
            content = message.get("content")
            if isinstance(content, str) and content:
                return content
            if isinstance(content, list):
                parts: List[str] = []
                for part in content:
                    if isinstance(part, dict) and part.get("type") == "text":
                        text = part.get("text")
                        if isinstance(text, str) and text:
                            parts.append(text)
                if parts:
                    return "".join(parts)
        return ""

    def _job_search_summarizer_is_configured(self) -> bool:
        return bool(self._planner_api_key())

    def _career_event_extractor_is_configured(self) -> bool:
        return bool(self._planner_api_key())

    def _normalize_extracted_career_events(
        self,
        payload: Any,
    ) -> List[Dict[str, str]]:
        if isinstance(payload, list):
            raw_events = payload
        elif isinstance(payload, dict):
            raw_events = payload.get("events", [])
        else:
            return []

        allowed_event_types = {
            "application_status",
            "interview_feedback",
            "assessment_result",
            "career_milestone",
        }
        events: List[Dict[str, str]] = []
        for raw_event in raw_events[:3]:
            if not isinstance(raw_event, dict):
                continue
            event_type = str(raw_event.get("event_type") or "").strip()
            title = str(raw_event.get("title") or "").strip()
            summary = str(raw_event.get("summary") or "").strip()
            occurred_at = str(raw_event.get("occurred_at") or "").strip()
            if event_type not in allowed_event_types:
                continue
            if not title or not summary:
                continue
            events.append(
                {
                    "event_type": event_type,
                    "title": title,
                    "summary": summary,
                    "occurred_at": occurred_at,
                }
            )
        return events

    def _top_job_search_hits(self, jobs: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
        return jobs[:3]

    def _fallback_job_search_summary(
        self,
        jobs: List[Dict[str, Any]],
        has_memory_context: bool,
    ) -> str:
        if not jobs:
            return "暂时没有合适的岗位结果，建议换个关键词再试。"

        if has_memory_context:
            intro = (
                "结合你最近提到的偏好，系统优先在 Sydney / University of Sydney "
                "语境下为你筛选了以下岗位："
            )
        else:
            intro = (
                "根据你的提问，系统优先在 Sydney / University of Sydney "
                "语境下筛选了以下岗位："
            )

        lines: List[str] = [intro]
        for idx, job in enumerate(jobs, start=1):
            title = str(job.get("title") or "未命名岗位").strip()
            reason = str(job.get("reason") or job.get("snippet") or "").strip()
            if reason:
                lines.append(f"{idx}. {title}：{reason}")
            else:
                lines.append(f"{idx}. {title}")
        lines.append("如果需要，我可以结合你的简历再做一次精细匹配。")
        return "\n".join(lines)

    def _fallback_plan(
        self,
        message: str,
        memory_context: List[str],
        profile: Dict[str, Any],
        available_tools: List[str],
        user_state: Dict[str, Any],
    ) -> Dict[str, Any]:
        lowered_message = message.lower()
        profile_role = str(profile.get("target_role_preference", "")).strip()
        tools = set(available_tools)

        def keep_available(steps: List[str]) -> List[str]:
            return [step for step in steps if step in tools]

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
                reason = (
                    "这是推荐型问题，但当前缺少部分工具能力，先按可用工具继续执行。"
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
            }

        if any(keyword in message for keyword in ("资料", "画像", "我是谁")):
            return {
                "task_type": "candidate_profile",
                "reason": "这是资料查询问题，直接读取候选人资料即可。",
                "steps": keep_available(["get_candidate_profile"]),
                "needs_more_context": "get_candidate_profile" not in tools,
                "missing_context": ["candidate_profile"] if "get_candidate_profile" not in tools else [],
                "follow_up_question": None,
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
                }
            steps = keep_available(["match_resume_to_jobs"])
            return {
                "task_type": "job_match",
                "reason": "这是岗位匹配问题，直接用简历匹配岗位。",
                "steps": steps,
                "needs_more_context": "match_resume_to_jobs" not in tools,
                "missing_context": [],
                "follow_up_question": None,
            }

        if any(keyword in message for keyword in ("找", "岗位")) or any(
            keyword in lowered_message
            for keyword in ("job", "jobs", "backend", "frontend", "python", "fastapi")
        ):
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
            }

        return {
            "task_type": "fallback",
            "reason": "当前问题不需要工具，直接走普通回答。",
            "steps": [],
            "needs_more_context": False,
            "missing_context": [],
            "follow_up_question": None,
        }
