import json
from typing import Any, Dict, List, Optional

import httpx
from pydantic import ValidationError

from app.env import settings
from app.llm.prompts import JOB_SEARCH_SUMMARIZER_SYSTEM_PROMPT, PLANNER_SYSTEM_PROMPT
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
                timeout=45.0,
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
                timeout=45.0,
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
            timeout=45.0,
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
        return {
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
            request["thinking"] = {"type": "disabled"}
        return request

    def _extract_plan_payload(self, payload: Dict[str, Any]) -> Dict[str, Any]:
        output = payload.get("output", [])
        for item in output:
            for content in item.get("content", []):
                text = content.get("text")
                if text:
                    return json.loads(text)
        raise ValueError("No structured planner payload returned by model")

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
        return {
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
