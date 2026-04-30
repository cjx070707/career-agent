import json
import time
from typing import Any, Dict, List, Optional

import httpx
from pydantic import ValidationError

from app.env import settings
from app.llm.career_event_extractor_client import CareerEventExtractorClient
from app.llm.plan_validator import PlanValidator
from app.llm.prompts import (
    DIAGNOSTIC_PLANNER_SYSTEM_PROMPT,
    JOB_SEARCH_SUMMARIZER_SYSTEM_PROMPT,
    PLANNER_SYSTEM_PROMPT,
)
from app.schemas.diagnostic_planner import DiagnosticPlannerOutput
from app.llm.react_decider_client import ReactDeciderClient
from app.schemas.chat import ChatPlan


class LLMClient:
    """LLM wrapper with a deterministic fallback path for local development."""

    ALLOWED_TASK_TYPES = {
        "candidate_profile",
        "resume_analysis",
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
    PLANNER_TIMEOUT_SECONDS = 8.0
    
    JOB_SEARCH_SUMMARY_TIMEOUT_SECONDS = 20.0
    CAREER_EVENT_EXTRACTION_TIMEOUT_SECONDS = 5.0
    OBSERVE_DECISION_TIMEOUT_SECONDS = 5.0
    DIAGNOSTIC_PLANNER_TIMEOUT_SECONDS = 12.0

    def __init__(self) -> None:
        self.model = settings.default_model
        self.last_plan_source = "not_used"
        self.last_job_search_summary_source = "not_used"
        self.last_generate_source = "not_used"
        self.last_plan_timed_out = False
        self.last_plan_elapsed_ms = 0.0
        self.plan_validator = PlanValidator(
            allowed_task_types=self.ALLOWED_TASK_TYPES,
            max_plan_steps=self.MAX_PLAN_STEPS,
        )
        self.react_decider = ReactDeciderClient(timeout_seconds=self.OBSERVE_DECISION_TIMEOUT_SECONDS)
        self.career_event_extractor = CareerEventExtractorClient()

    def is_configured(self) -> bool:
        return bool(settings.openai_api_key)

    def _planner_api_key(self) -> str:
        return settings.planner_api_key

    def _planner_base_url(self) -> str:
        return settings.planner_base_url

    def _planner_model(self) -> str:
        return settings.planner_model

    def _classifier_model(self) -> str:
        return settings.classifier_model or self._planner_model()

    def _react_decision_model(self) -> str:
        return settings.react_decision_model or self._planner_model()

    def _generator_model(self) -> str:
        return settings.generator_model or self._planner_model()

    def _diagnostic_model(self) -> str:
        return settings.diagnostic_model or self._classifier_model()

    def generate_plan(
        self,
        message: str,
        memory_context: List[str],
        profile: Dict[str, Any],
        available_tools: List[str],
        user_state: Dict[str, Any] = None,
    ) -> Dict[str, Any]:
        normalized_user_state = user_state or {}
        self.last_plan_timed_out = False
        self.last_plan_elapsed_ms = 0.0
        start = time.perf_counter()
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
            if isinstance(exc, httpx.TimeoutException):
                self.last_plan_timed_out = True
                self.last_plan_source = "fallback"
                timeout_fallback = self._fallback_plan(
                    message,
                    memory_context,
                    profile,
                    available_tools,
                    normalized_user_state,
                )
                timeout_fallback.update(
                    {
                        "task_type": "fallback",
                        "reason": "planner timeout fallback",
                        "steps": [],
                        "needs_more_context": False,
                        "missing_context": [],
                        "follow_up_question": None,
                    }
                )
                return self._validated_plan(
                    timeout_fallback,
                    planner_source="fallback",
                    available_tools=available_tools,
                )
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
        finally:
            self.last_plan_elapsed_ms = (time.perf_counter() - start) * 1000

    def generate_diagnostic_plan(
        self,
        *,
        message: str,
        plan_semantics: Dict[str, Any],
        profile: Dict[str, Any],
        context_resolution: Dict[str, Any],
        memory_context: List[str],
    ) -> Dict[str, Any]:
        try:
            payload = self._generate_diagnostic_plan_with_model(
                message=message,
                plan_semantics=plan_semantics,
                profile=profile,
                context_resolution=context_resolution,
                memory_context=memory_context,
            )
            parsed = DiagnosticPlannerOutput.model_validate(payload)
            return parsed.model_dump()
        except (
            RuntimeError,
            ValidationError,
            ValueError,
            TypeError,
            json.JSONDecodeError,
            httpx.HTTPError,
        ):
            return self._fallback_diagnostic_plan()

    def generate(
        self,
        message: str,
        memory_context: List[Dict[str, str]],
        evidence: List[str],
    ) -> str:
        if self.is_configured():
            try:
                request = self._build_generate_chat_request(
                    message=message,
                    memory_context=memory_context,
                    evidence=evidence,
                )
                payload = self._post_responses(
                    f"{self._planner_base_url().rstrip('/')}/chat/completions",
                    api_key=self._planner_api_key(),
                    payload=request,
                    timeout=self.JOB_SEARCH_SUMMARY_TIMEOUT_SECONDS,
                )
                text = self._extract_chat_completion_text(payload).strip()
                if text:
                    self.last_generate_source = "model"
                    return text
            except (RuntimeError, ValueError, TypeError, json.JSONDecodeError, httpx.HTTPError):
                pass

        self.last_generate_source = "fallback"
        # Return a user-friendly apology instead of dumping raw evidence/internals.
        return "抱歉，我暂时无法生成回答，请稍后再试。"

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
            # Build the /responses-format request to reuse schema and prompts,
            # then convert it to /chat/completions format.
            # (DashScope's /responses endpoint may hang instead of returning 404,
            # causing a 5s timeout on every career-event extraction call.)
            responses_req = self._build_career_event_extract_request(
                user_id=user_id,
                message=message,
            )
            chat_request = {
                "model": responses_req["model"],
                "messages": [
                    {"role": turn["role"], "content": turn["content"]}
                    for turn in responses_req["input"]
                ],
                "response_format": {
                    "type": "json_schema",
                    "json_schema": {
                        "name": responses_req["text"]["format"]["name"],
                        "strict": True,
                        "schema": responses_req["text"]["format"]["schema"],
                    },
                },
            }
            if settings.planner_disable_thinking:
                self._disable_thinking(chat_request)
            response_payload = self._post_responses(
                f"{self._planner_base_url().rstrip('/')}/chat/completions",
                api_key=self._planner_api_key(),
                payload=chat_request,
                timeout=self.CAREER_EVENT_EXTRACTION_TIMEOUT_SECONDS,
            )
            text = self._extract_chat_completion_text(response_payload)
            return self.career_event_extractor.normalize(json.loads(text)) if text else []
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
        return self.react_decider.decide_next_action(
            is_configured=self.is_configured(),
            request_builder=self._build_observe_decision_request,
            post_responses=self._post_responses,
            extract_chat_completion_text=self._extract_chat_completion_text,
            planner_base_url=self._planner_base_url(),
            planner_api_key=self._planner_api_key(),
            task_type=task_type,
            message=message,
            current_step=current_step,
            tool_result=tool_result,
            remaining_steps=remaining_steps,
            available_tools=available_tools,
        )

    def decide_react_action(
        self,
        *,
        task_type: str,
        message: str,
        state: Dict[str, Any],
        last_observation: Optional[Dict[str, Any]],
        available_tools: List[str],
        executor_whitelist: Optional[List[str]] = None,
    ) -> Dict[str, Any]:
        """Decide next bounded-strategy executor action.

        Actions may include Phase 4B: switch_tool | replan_strategy (see sanitization).
        """
        whitelist = executor_whitelist if executor_whitelist is not None else available_tools

        if not self.is_configured():
            return self._fallback_executor_action(
                task_type=task_type,
                last_observation=last_observation,
                available_tools=available_tools,
                reason="llm_not_configured",
                executor_whitelist=whitelist,
            )

        request = self._build_react_action_request(
            task_type=task_type,
            message=message,
            state=state,
            last_observation=last_observation,
            available_tools=available_tools,
            executor_whitelist=whitelist,
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
            return self._sanitize_executor_action(
                parsed=parsed,
                remaining_tools=list(available_tools),
                whitelist_executor_tools=list(whitelist),
            )
        except (RuntimeError, ValueError, TypeError, json.JSONDecodeError, httpx.HTTPError):
            return self._fallback_executor_action(
                task_type=task_type,
                last_observation=last_observation,
                available_tools=available_tools,
                reason="react_fallback_after_error",
                executor_whitelist=whitelist,
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

    def _generate_diagnostic_plan_with_model(
        self,
        *,
        message: str,
        plan_semantics: Dict[str, Any],
        profile: Dict[str, Any],
        context_resolution: Dict[str, Any],
        memory_context: List[str],
    ) -> Dict[str, Any]:
        if not self._planner_api_key():
            raise RuntimeError("Diagnostic planner not configured")

        # Go directly to /chat/completions — avoids the /responses endpoint which
        # may hang on DashScope (producing a 12s timeout instead of a fast 404).
        chat_request = self._build_chat_completions_diagnostic_plan_request(
            message=message,
            plan_semantics=plan_semantics,
            profile=profile,
            context_resolution=context_resolution,
            memory_context=memory_context,
        )
        chat_payload = self._post_responses(
            f"{self._planner_base_url().rstrip('/')}/chat/completions",
            api_key=self._planner_api_key(),
            payload=chat_request,
            timeout=self.DIAGNOSTIC_PLANNER_TIMEOUT_SECONDS,
        )
        return self._extract_chat_completions_diagnostic_plan_payload(chat_payload)

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

    def _build_generate_chat_request(
        self,
        *,
        message: str,
        memory_context: List[Dict[str, str]],
        evidence: List[str],
    ) -> Dict[str, Any]:
        messages: List[Dict[str, str]] = [
            {
                "role": "system",
                "content": (
                    "你是一个专业的求职辅导 agent。根据对话历史和参考数据，给出有针对性的回答。\n"
                    "回答要求：\n"
                    "- 聚焦用户当前问题，不要发散或重复上一轮内容\n"
                    "- 控制在 300 字以内，除非用户明确要求详细展开\n"
                    "- 给出结论和 1-3 个具体行动建议，不要长篇铺垫\n"
                    "- 如果信息不足，直接问最关键的一个问题"
                ),
            }
        ]
        # memory_context carries role explicitly — no guessing with i % 2
        for turn in memory_context:
            role = str(turn.get("role", "user"))
            content = str(turn.get("content", ""))
            if content:
                messages.append({"role": role, "content": content})

        user_content = message
        if evidence:
            user_content += "\n\n参考数据：" + "\n".join(evidence)
        messages.append({"role": "user", "content": user_content})

        request = {"model": self._generator_model(), "messages": messages}
        self._disable_thinking(request)
        return request

    def _build_diagnostic_plan_request(
        self,
        *,
        message: str,
        plan_semantics: Dict[str, Any],
        profile: Dict[str, Any],
        context_resolution: Dict[str, Any],
        memory_context: List[str],
    ) -> Dict[str, Any]:
        request = {
            "model": self._diagnostic_model(),
            "input": [
                {"role": "system", "content": DIAGNOSTIC_PLANNER_SYSTEM_PROMPT},
                {
                    "role": "user",
                    "content": json.dumps(
                        {
                            "message": message,
                            "plan_semantics": plan_semantics,
                            "profile": profile,
                            "context_resolution": context_resolution,
                            "memory_context": memory_context,
                        },
                        ensure_ascii=False,
                    ),
                },
            ],
            "text": {
                "format": {
                    "type": "json_schema",
                    "name": "diagnostic_planner_output",
                    "strict": True,
                    "schema": DiagnosticPlannerOutput.model_json_schema(),
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
            "model": self._generator_model(),
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

    def _build_chat_completions_diagnostic_plan_request(
        self,
        *,
        message: str,
        plan_semantics: Dict[str, Any],
        profile: Dict[str, Any],
        context_resolution: Dict[str, Any],
        memory_context: List[str],
    ) -> Dict[str, Any]:
        request = {
            "model": self._diagnostic_model(),
            "messages": [
                {"role": "system", "content": DIAGNOSTIC_PLANNER_SYSTEM_PROMPT},
                {
                    "role": "user",
                    "content": json.dumps(
                        {
                            "message": message,
                            "plan_semantics": plan_semantics,
                            "profile": profile,
                            "context_resolution": context_resolution,
                            "memory_context": memory_context,
                        },
                        ensure_ascii=False,
                    ),
                },
            ],
            "response_format": {
                "type": "json_schema",
                "json_schema": {
                    "name": "diagnostic_planner_output",
                    "strict": True,
                    "schema": DiagnosticPlannerOutput.model_json_schema(),
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

    def _extract_diagnostic_plan_payload(self, payload: Dict[str, Any]) -> Dict[str, Any]:
        text = self._extract_responses_text(payload)
        if text:
            return json.loads(text)
        raise ValueError("No structured diagnostic planner payload returned by model")

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

    def _extract_chat_completions_diagnostic_plan_payload(
        self,
        payload: Dict[str, Any],
    ) -> Dict[str, Any]:
        choices = payload.get("choices", [])
        for choice in choices:
            message = choice.get("message", {})
            content = message.get("content")
            if content:
                return json.loads(content)
        raise ValueError("No structured diagnostic planner payload returned by chat completions")

    def _validated_plan(
        self,
        plan_payload: Dict[str, Any],
        planner_source: str,
        available_tools: Optional[List[str]] = None,
    ) -> Dict[str, Any]:
        return self.plan_validator.validate_and_dump(
            plan_payload=plan_payload,
            planner_source=planner_source,
            available_tools=available_tools,
        )

    def _normalize_plan(self, plan_payload: Dict[str, Any]) -> Dict[str, Any]:
        return self.plan_validator.normalize_plan(plan_payload)

    def _validate_plan_contract(
        self,
        plan: ChatPlan,
        available_tools: Optional[List[str]] = None,
    ) -> None:
        self.plan_validator.validate_plan_contract(plan, available_tools=available_tools)

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
        # DashScope qwen3 API parameter to disable thinking/reasoning mode.
        request["enable_thinking"] = False

    def _build_career_event_extract_request(
        self,
        user_id: str,
        message: str,
    ) -> Dict[str, Any]:
        request = self.career_event_extractor.build_request(
            planner_model=self._diagnostic_model(),
            user_id=user_id,
            message=message,
        )
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
        executor_whitelist: List[str],
    ) -> Dict[str, Any]:
        schema = {
            "type": "object",
            "additionalProperties": False,
            "properties": {
                "action": {
                    "type": "string",
                    "enum": [
                        "continue",
                        "ask_for_context",
                        "finish",
                        "switch_tool",
                        "replan_strategy",
                    ],
                },
                "reason": {"type": "string"},
                "observation_summary": {"type": "string"},
                "tool_name": {"type": "string"},
                "planned_tools": {"type": "array", "items": {"type": "string"}},
            },
            "required": ["action", "reason", "observation_summary", "tool_name", "planned_tools"],
        }
        request = {
            "model": self._react_decision_model(),
            "messages": [
                {
                    "role": "system",
                    "content": (
                        "You control a bounded career-agent executor inside one task."
                        " Choose exactly one action. "
                        "continue: proceed to next tool in queue, or do nothing if queue is empty. "
                        "ask_for_context: missing evidence. "
                        "finish: stop safely. "
                        "switch_tool: call a specific tool next (set tool_name to any tool "
                        "in executor_tools_whitelist). "
                        "replan_strategy: replace the remainder with a SHORT valid tool subset "
                        "for THIS task using planned_tools (ToolResolver-aligned). "
                        "Never invent tools; only use identifiers from executor_tools_whitelist. "
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
                            "remaining_queued_tools": available_tools,
                            "all_available_tools": executor_whitelist,
                            "executor_tools_whitelist": executor_whitelist,
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

    def _sanitize_executor_action(
        self,
        *,
        parsed: Dict[str, Any],
        remaining_tools: List[str],
        whitelist_executor_tools: List[str],
    ) -> Dict[str, Any]:
        remaining_set = set(remaining_tools)
        whitelist_set = set(whitelist_executor_tools)
        allowed = remaining_set & whitelist_set

        action = str(parsed.get("action") or "continue").strip().lower()
        tool_name_raw = parsed.get("tool_name")
        tool_name = str(tool_name_raw).strip() if isinstance(tool_name_raw, str) else ""
        planned = parsed.get("planned_tools") if isinstance(parsed.get("planned_tools"), list) else []

        legacy_consume_budget = False
        # Backward compatibility for older prompts/clients.
        if action == "tool":
            action = "continue"
        elif action == "stop":
            action = "finish"
        elif action == "replan":
            action = "continue"
            legacy_consume_budget = True
        elif action == "finish":
            pass
        elif action == "switch_tool":
            if tool_name not in allowed or tool_name not in whitelist_set:
                action = "continue"
                tool_name = ""
        elif action == "replan_strategy":
            if not planned:
                action = "continue"
        elif action not in {
            "continue",
            "ask_for_context",
            "finish",
            "switch_tool",
            "replan_strategy",
        }:
            action = "continue"

        payload: Dict[str, Any] = {
            "action": action,
            "reason": str(parsed.get("reason") or "").strip(),
            "observation_summary": str(parsed.get("observation_summary") or "").strip(),
            "tool_name": tool_name if action == "switch_tool" else "",
            "planned_tools": [
                str(t).strip() for t in planned if isinstance(t, str) and str(t).strip()
            ]
            if action == "replan_strategy"
            else [],
        }
        if legacy_consume_budget:
            payload["consume_budget"] = True
        return payload

    def _fallback_executor_action(
        self,
        *,
        task_type: str,
        last_observation: Optional[Dict[str, Any]],
        available_tools: List[str],
        reason: str,
        executor_whitelist: Optional[List[str]] = None,
    ) -> Dict[str, Any]:
        _ = executor_whitelist
        fallback = self.react_decider.fallback_observe_decision(
            task_type=task_type,
            current_step=str((last_observation or {}).get("step") or ""),
            tool_result=(last_observation or {}).get("result"),
            remaining_steps=available_tools,
        )
        decision = str(fallback.get("decision") or "continue").strip().lower()
        if decision == "stop":
            action = "finish"
            return {
                "action": action,
                "reason": str(fallback.get("reason") or reason).strip() or reason,
                "observation_summary": "",
                "tool_name": "",
                "planned_tools": [],
            }
        # Legacy observer "replan" does not reorder the executor queue — it gates budget only.
        if decision == "replan":
            return {
                "action": "continue",
                "reason": str(fallback.get("reason") or reason).strip() or reason,
                "observation_summary": "",
                "tool_name": "",
                "planned_tools": [],
                "consume_budget": True,
            }
        return {
            "action": "continue",
            "reason": str(fallback.get("reason") or reason).strip() or reason,
            "observation_summary": "",
            "tool_name": "",
            "planned_tools": [],
        }

    def _sanitize_react_action(
        self,
        *,
        parsed: Dict[str, Any],
        state: Dict[str, Any],
        available_tools: List[str],
    ) -> Dict[str, Any]:
        _ = state
        return self.react_decider.sanitize_react_action(
            parsed=parsed,
            available_tools=available_tools,
        )

    def _fallback_react_action(
        self,
        *,
        state: Dict[str, Any],
        available_tools: List[str],
        reason: str,
    ) -> Dict[str, Any]:
        return self.react_decider.fallback_react_action(
            state=state,
            available_tools=available_tools,
            reason=reason,
        )

    def _fallback_observe_decision(
        self,
        *,
        task_type: str,
        current_step: str,
        tool_result: Any,
        remaining_steps: List[str],
    ) -> Dict[str, Any]:
        return self.react_decider.fallback_observe_decision(
            task_type=task_type,
            current_step=current_step,
            tool_result=tool_result,
            remaining_steps=remaining_steps,
        )

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
        return self.career_event_extractor.normalize(payload)

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

    def _fallback_diagnostic_plan(self) -> Dict[str, Any]:
        fallback = DiagnosticPlannerOutput(
            diagnostic_hypotheses=[
                {
                    "bottleneck_type": "insufficient_evidence",
                    "summary": "Current evidence is not enough for a high-confidence hypothesis.",
                    "rationale": "Need real application, interview, and feedback signals to narrow down bottlenecks.",
                    "confidence": 0.4,
                    "evidence_refs": [],
                }
            ],
            evidence_to_collect=[
                {
                    "source": "applications",
                    "reason": "Application funnel states are needed to identify conversion bottlenecks.",
                    "priority": "high",
                    "required": True,
                },
                {
                    "source": "interviews",
                    "reason": "Interview outcomes are needed to separate interview from resume bottlenecks.",
                    "priority": "high",
                    "required": True,
                },
                {
                    "source": "feedback",
                    "reason": "Concrete interview feedback is needed to detect skill-specific gaps.",
                    "priority": "high",
                    "required": True,
                },
            ],
            next_question="Could you share recent application outcomes, interview results, and feedback details?",
            confidence=0.4,
            stop_criteria=["enough evidence collected"],
        )
        return fallback.model_dump()
