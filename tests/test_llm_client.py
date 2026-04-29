import json
import time

import httpx

from app.llm.client import LLMClient
from app.env import settings
from app.llm.prompts import (
    DIAGNOSTIC_PLANNER_SYSTEM_PROMPT,
    JOB_SEARCH_SUMMARIZER_SYSTEM_PROMPT,
)
from app.schemas.diagnostic_planner import DiagnosticPlannerOutput


CAREER_EVENT_RESPONSE_TEXT = json.dumps(
    {
        "events": [
            {
                "event_type": "interview_feedback",
                "title": "Canva backend interview feedback",
                "summary": "Rejected after Canva backend interview; prepare system design fundamentals.",
                "occurred_at": "2026-04-20",
            }
        ]
    }
)


class ModelFirstLLMClient(LLMClient):
    def __init__(self, model_result=None, model_error=None) -> None:
        super().__init__()
        self.model_result = model_result
        self.model_error = model_error
        self.model_calls = 0
        self.fallback_calls = 0

    def _generate_plan_with_model(self, **kwargs):
        self.model_calls += 1
        if self.model_error is not None:
            raise self.model_error
        return self.model_result

    def _fallback_plan(self, *args, **kwargs):
        self.fallback_calls += 1
        return super()._fallback_plan(*args, **kwargs)


class ConfigAwareLLMClient(LLMClient):
    def __init__(self) -> None:
        super().__init__()
        self.request_url = None

    def is_configured(self) -> bool:
        return True

    def _post_responses(self, url, payload=None, api_key=None, **kwargs):
        self.request_url = url
        return {
            "output": [
                {
                    "content": [
                        {
                            "text": "{\"task_type\":\"job_search\",\"reason\":\"ok\",\"steps\":[\"search_jobs\"],\"needs_more_context\":false,\"missing_context\":[],\"follow_up_question\":null}"
                        }
                    ]
                }
            ]
        }


class ChatCompletionsFallbackLLMClient(LLMClient):
    def __init__(self) -> None:
        super().__init__()
        self.called_urls = []

    def is_configured(self) -> bool:
        return True

    def _post_responses(self, url, payload=None, api_key=None, **kwargs):
        self.called_urls.append(url)
        if url.endswith("/responses"):
            request = httpx.Request("POST", url)
            response = httpx.Response(404, request=request)
            raise httpx.HTTPStatusError("not found", request=request, response=response)
        if url.endswith("/chat/completions"):
            return {
                "choices": [
                    {
                        "message": {
                            "content": "{\"task_type\":\"job_search\",\"reason\":\"planned via chat completions\",\"steps\":[\"search_jobs\"],\"needs_more_context\":false,\"missing_context\":[],\"follow_up_question\":null}"
                        }
                    }
                ]
            }
        raise AssertionError(f"Unexpected URL: {url}")


class JobSearchSummarizeChatClient(LLMClient):
    def __init__(self) -> None:
        super().__init__()
        self.summarize_chat_calls = []

    def _post_responses(self, url, payload=None, api_key=None, **kwargs):
        self.summarize_chat_calls.append((url, payload, kwargs))
        return {"choices": [{"message": {"content": "Model job-search summary."}}]}


class GenerateChatClient(LLMClient):
    def __init__(self, response_text: str, error=None) -> None:
        super().__init__()
        self.response_text = response_text
        self.error = error
        self.calls = []

    def is_configured(self) -> bool:
        return True

    def _post_responses(self, url, payload=None, api_key=None, **kwargs):
        self.calls.append((url, payload, kwargs))
        if self.error is not None:
            raise self.error
        return {"choices": [{"message": {"content": self.response_text}}]}


class TimeoutCaptureLLMClient(LLMClient):
    def __init__(self) -> None:
        super().__init__()
        self.calls = []

    def is_configured(self) -> bool:
        return True

    def _post_responses(self, url, payload=None, api_key=None, **kwargs):
        self.calls.append((url, kwargs))
        if url.endswith("/responses"):
            return {
                "output": [
                    {
                        "content": [
                            {
                                "text": "{\"task_type\":\"job_search\",\"reason\":\"ok\",\"steps\":[\"search_jobs\"],\"needs_more_context\":false,\"missing_context\":[],\"follow_up_question\":null}"
                            }
                        ]
                    }
                ]
            }
        return {"choices": [{"message": {"content": "Model job-search summary."}}]}


class CareerEventExtractionClient(LLMClient):
    def __init__(self, response_text=CAREER_EVENT_RESPONSE_TEXT, error=None) -> None:
        super().__init__()
        self.response_text = response_text
        self.error = error
        self.calls = []

    def is_configured(self) -> bool:
        return True

    def _post_responses(self, url, payload=None, api_key=None, **kwargs):
        self.calls.append((url, payload, kwargs))
        if self.error is not None:
            raise self.error
        return {"output": [{"content": [{"text": self.response_text}]}]}


class ObserveDecisionClient(LLMClient):
    def __init__(self, response_json: str) -> None:
        super().__init__()
        self.response_json = response_json
        self.calls = []

    def is_configured(self) -> bool:
        return True

    def _post_responses(self, url, payload=None, api_key=None, **kwargs):
        self.calls.append((url, payload, kwargs))
        return {"choices": [{"message": {"content": self.response_json}}]}


class DiagnosticModelFirstLLMClient(LLMClient):
    def __init__(self, model_result=None, model_error=None) -> None:
        super().__init__()
        self.model_result = model_result
        self.model_error = model_error
        self.model_calls = 0
        self.fallback_calls = 0

    def _generate_diagnostic_plan_with_model(self, **kwargs):
        self.model_calls += 1
        if self.model_error is not None:
            raise self.model_error
        return self.model_result

    def _fallback_diagnostic_plan(self):
        self.fallback_calls += 1
        return super()._fallback_diagnostic_plan()


def test_generate_plan_uses_profile_and_memory_for_job_search() -> None:
    client = LLMClient()
    original_openai_api_key = settings.openai_api_key
    original_planner_api_key = settings.planner_api_key

    settings.openai_api_key = ""
    settings.planner_api_key = ""
    try:
        plan = client.generate_plan(
            message="帮我找一些岗位",
            memory_context=["我们刚刚聊过后端实习方向"],
            profile={
                "user_id": "u1",
                "target_role_preference": "backend",
                "skill_keywords": ["python", "fastapi"],
                "career_focus_notes": "User currently prefers backend roles.",
            },
            available_tools=["search_jobs", "match_resume_to_jobs"],
        )
    finally:
        settings.openai_api_key = original_openai_api_key
        settings.planner_api_key = original_planner_api_key

    assert plan["task_type"] == "job_search"
    assert plan["steps"] == ["search_jobs"]
    assert "backend" in plan["reason"].lower()
    assert "最近对话" in plan["reason"]


def test_generate_plan_respects_available_tools_for_matching() -> None:
    client = LLMClient()
    original_openai_api_key = settings.openai_api_key
    original_planner_api_key = settings.planner_api_key

    settings.openai_api_key = ""
    settings.planner_api_key = ""
    try:
        plan = client.generate_plan(
            message="结合我的情况推荐适合投的岗位",
            memory_context=[],
            profile={
                "user_id": "u1",
                "target_role_preference": "",
                "skill_keywords": [],
                "career_focus_notes": "",
            },
            available_tools=["get_candidate_profile", "search_jobs"],
        )
    finally:
        settings.openai_api_key = original_openai_api_key
        settings.planner_api_key = original_planner_api_key

    assert plan["task_type"] == "job_match_planning"
    assert plan["steps"] == ["get_candidate_profile", "search_jobs"]
    assert plan["needs_more_context"] is True
    assert "工具" in plan["reason"]


def test_generate_plan_asks_for_resume_when_matching_context_is_missing() -> None:
    client = LLMClient()
    original_openai_api_key = settings.openai_api_key
    original_planner_api_key = settings.planner_api_key

    settings.openai_api_key = ""
    settings.planner_api_key = ""
    try:
        plan = client.generate_plan(
            message="我适合投哪些岗位",
            memory_context=[],
            profile={
                "user_id": "u1",
                "target_role_preference": "",
                "skill_keywords": [],
                "career_focus_notes": "",
            },
            available_tools=["match_resume_to_jobs"],
            user_state={"has_candidate": True, "has_resume": False},
        )
    finally:
        settings.openai_api_key = original_openai_api_key
        settings.planner_api_key = original_planner_api_key

    assert plan["task_type"] == "job_match"
    assert plan["steps"] == []
    assert plan["needs_more_context"] is True
    assert plan["missing_context"] == ["resume"]
    assert "简历" in plan["follow_up_question"]


def test_generate_plan_tries_model_first_and_skips_fallback_on_success() -> None:
    client = ModelFirstLLMClient(
        model_result={
            "task_type": "job_search",
            "reason": "planned by model",
            "steps": ["search_jobs"],
            "needs_more_context": False,
            "missing_context": [],
            "follow_up_question": None,
        }
    )

    plan = client.generate_plan(
        message="帮我找一些岗位",
        memory_context=[],
        profile={},
        available_tools=["search_jobs"],
    )

    assert client.model_calls == 1
    assert client.fallback_calls == 0
    assert plan["reason"] == "planned by model"
    assert plan["planner_source"] == "model"


def test_generate_plan_falls_back_after_model_failure() -> None:
    client = ModelFirstLLMClient(model_error=RuntimeError("model failed"))

    plan = client.generate_plan(
        message="帮我找一些岗位",
        memory_context=[],
        profile={
            "target_role_preference": "backend",
        },
        available_tools=["search_jobs"],
    )

    assert client.model_calls >= 1
    assert client.fallback_calls == 1
    assert plan["task_type"] == "job_search"
    assert plan["planner_source"] == "fallback"
    assert client.model_calls == 1


def test_generate_plan_timeout_falls_back_quickly_single_attempt() -> None:
    client = ModelFirstLLMClient(
        model_error=httpx.ReadTimeout("planner timeout"),
    )
    started = time.perf_counter()
    plan = client.generate_plan(
        message="你到底有什么用啊",
        memory_context=[],
        profile={},
        available_tools=[],
    )
    elapsed = time.perf_counter() - started

    assert client.model_calls == 1
    assert client.fallback_calls == 1
    assert plan["planner_source"] == "fallback"
    assert elapsed < 1.0


def test_generate_plan_falls_back_after_schema_failure() -> None:
    client = ModelFirstLLMClient(
        model_result={
            "reason": "broken payload",
            "steps": ["search_jobs"],
        }
    )

    plan = client.generate_plan(
        message="帮我找一些岗位",
        memory_context=[],
        profile={},
        available_tools=["search_jobs"],
    )

    assert client.model_calls >= 1
    assert client.fallback_calls == 1
    assert plan["task_type"] == "job_search"
    assert plan["planner_source"] == "fallback"


def test_build_plan_request_uses_dedicated_planner_prompt() -> None:
    client = LLMClient()

    request = client._build_plan_request(
        message="帮我找一些岗位",
        memory_context=["我们刚刚聊过后端方向"],
        profile={"target_role_preference": "backend"},
        available_tools=["search_jobs"],
        user_state={"has_candidate": True, "has_resume": False},
    )

    system_content = request["input"][0]["content"]
    user_content = request["input"][1]["content"]

    assert "planner for a career agent" in system_content.lower()
    assert "Do not invent unavailable tools." in system_content
    assert "\"available_tools\": [\"search_jobs\"]" in user_content


def test_build_plan_request_uses_hardened_planner_prompt() -> None:
    client = LLMClient()

    request = client._build_plan_request(
        message="我适合投哪些岗位",
        memory_context=[],
        profile={},
        available_tools=["match_resume_to_jobs"],
        user_state={"has_candidate": True, "has_resume": False},
    )

    system_content = request["input"][0]["content"]

    assert "University of Sydney Career Hub" in system_content
    assert "search first" in system_content
    assert "location_preference, experience_level, and work_type_preference" in system_content
    assert "If required user context is missing" in system_content
    assert "follow_up_question" in system_content
    assert "Do not use unavailable tools" in system_content


def test_build_plan_request_lists_allowed_task_types_and_short_label_rule() -> None:
    client = LLMClient()

    request = client._build_plan_request(
        message="我适合投哪些岗位",
        memory_context=[],
        profile={},
        available_tools=["match_resume_to_jobs"],
        user_state={"has_candidate": True, "has_resume": True},
    )

    system_content = request["input"][0]["content"]

    assert "Allowed task_type values" in system_content
    assert "candidate_profile" in system_content
    assert "job_search" in system_content
    assert "job_match" in system_content
    assert "interview_history" in system_content
    assert "career_insights" in system_content
    assert "Do not output descriptive titles" in system_content


def test_generate_plan_uses_configured_base_url() -> None:
    client = ConfigAwareLLMClient()
    original_base_url = settings.planner_base_url
    settings.planner_base_url = "https://example.com/v1"

    try:
        client.generate_plan(
            message="帮我找一些岗位",
            memory_context=[],
            profile={},
            available_tools=["search_jobs"],
        )
    finally:
        settings.planner_base_url = original_base_url

    assert client.request_url == "https://example.com/v1/responses"


def test_generate_plan_uses_chat_completions_when_responses_is_unavailable() -> None:
    client = ChatCompletionsFallbackLLMClient()
    planner_base_url = settings.planner_base_url.rstrip("/")

    plan = client.generate_plan(
        message="帮我找一些岗位",
        memory_context=[],
        profile={},
        available_tools=["search_jobs"],
    )

    assert client.called_urls == [
        f"{planner_base_url}/responses",
        f"{planner_base_url}/chat/completions",
    ]
    assert plan["planner_source"] == "model"
    assert plan["reason"] == "planned via chat completions"


def test_build_chat_completions_request_disables_thinking_when_configured() -> None:
    client = LLMClient()
    original_disable_thinking = settings.planner_disable_thinking
    settings.planner_disable_thinking = True

    try:
        request = client._build_chat_completions_plan_request(
            message="我适合投哪些岗位",
            memory_context=[],
            profile={},
            available_tools=["match_resume_to_jobs"],
            user_state={"has_candidate": True, "has_resume": True},
        )
    finally:
        settings.planner_disable_thinking = original_disable_thinking

    assert request["thinking"] == {"type": "disabled"}


def test_build_plan_request_uses_planner_model_override_when_configured() -> None:
    client = LLMClient()
    original_planner_model = settings.planner_model
    settings.planner_model = "planner-only-model"

    try:
        request = client._build_plan_request(
            message="帮我找一些岗位",
            memory_context=[],
            profile={},
            available_tools=["search_jobs"],
            user_state={"has_candidate": True, "has_resume": True},
        )
    finally:
        settings.planner_model = original_planner_model

    assert request["model"] == "planner-only-model"


def test_planner_requests_use_planner_specific_provider_settings() -> None:
    client = LLMClient()
    original_planner_model = settings.planner_model
    original_planner_base_url = settings.planner_base_url
    original_planner_api_key = settings.planner_api_key

    settings.planner_model = "planner-only-model"
    settings.planner_base_url = "https://planner.example/v1"
    settings.planner_api_key = "planner-only-key"

    try:
        assert client._planner_model() == "planner-only-model"
        assert client._planner_base_url() == "https://planner.example/v1"
        assert client._planner_api_key() == "planner-only-key"
    finally:
        settings.planner_model = original_planner_model
        settings.planner_base_url = original_planner_base_url
        settings.planner_api_key = original_planner_api_key


def test_generate_plan_falls_back_when_task_type_is_not_allowed_label() -> None:
    client = ModelFirstLLMClient(
        model_result={
            "task_type": "profile_analysis_and_job_matching",
            "reason": "bad label",
            "steps": [],
            "needs_more_context": False,
            "missing_context": [],
            "follow_up_question": None,
        }
    )

    plan = client.generate_plan(
        message="我适合投哪些岗位",
        memory_context=[],
        profile={},
        available_tools=["match_resume_to_jobs"],
        user_state={"has_candidate": True, "has_resume": True},
    )

    assert client.fallback_calls == 1
    assert plan["planner_source"] == "fallback"
    assert plan["task_type"] == "job_match"


def test_generate_plan_accepts_interview_history_task_type() -> None:
    client = ModelFirstLLMClient(
        model_result={
            "task_type": "interview_history",
            "reason": "list interview feedback",
            "steps": ["get_interview_feedback"],
            "needs_more_context": False,
            "missing_context": [],
            "follow_up_question": None,
        }
    )

    plan = client.generate_plan(
        message="what interview feedback do I have?",
        memory_context=[],
        profile={},
        available_tools=["get_interview_feedback"],
        user_state={"has_candidate": True, "has_resume": True},
    )

    assert client.fallback_calls == 0
    assert plan["planner_source"] == "model"
    assert plan["task_type"] == "interview_history"
    assert plan["steps"] == ["get_interview_feedback"]


def test_generate_plan_accepts_career_insights_task_type() -> None:
    client = ModelFirstLLMClient(
        model_result={
            "task_type": "career_insights",
            "reason": "summarize career signals",
            "steps": ["get_career_insights"],
            "needs_more_context": False,
            "missing_context": [],
            "follow_up_question": None,
        }
    )

    plan = client.generate_plan(
        message="what should I prepare next based on applications and interviews?",
        memory_context=[],
        profile={},
        available_tools=["get_career_insights"],
        user_state={"has_candidate": True, "has_resume": True},
    )

    assert client.fallback_calls == 0
    assert plan["planner_source"] == "model"
    assert plan["task_type"] == "career_insights"
    assert plan["steps"] == ["get_career_insights"]


def test_generate_plan_falls_back_when_step_is_not_in_available_tools() -> None:
    client = ModelFirstLLMClient(
        model_result={
            "task_type": "job_match_planning",
            "reason": "hallucinated tool",
            "steps": ["search_jobs", "imaginary_tool"],
            "needs_more_context": False,
            "missing_context": [],
            "follow_up_question": None,
        }
    )

    plan = client.generate_plan(
        message="结合我的情况推荐适合投的岗位",
        memory_context=[],
        profile={},
        available_tools=["search_jobs", "match_resume_to_jobs"],
        user_state={"has_candidate": True, "has_resume": True},
    )

    assert client.fallback_calls == 1
    assert plan["planner_source"] == "fallback"
    for step in plan["steps"]:
        assert step in {"search_jobs", "match_resume_to_jobs"}


def test_generate_plan_falls_back_when_job_match_planning_step_order_is_wrong() -> None:
    client = ModelFirstLLMClient(
        model_result={
            "task_type": "job_match_planning",
            "reason": "match before search is invalid",
            "steps": ["match_resume_to_jobs", "search_jobs"],
            "needs_more_context": False,
            "missing_context": [],
            "follow_up_question": None,
        }
    )

    plan = client.generate_plan(
        message="结合我的情况推荐适合投的岗位",
        memory_context=[],
        profile={},
        available_tools=[
            "get_candidate_profile",
            "get_resume_by_id",
            "search_jobs",
            "match_resume_to_jobs",
        ],
        user_state={"has_candidate": True, "has_resume": True},
    )

    assert client.fallback_calls == 1
    assert plan["planner_source"] == "fallback"


def test_generate_plan_falls_back_when_steps_exceed_length_cap() -> None:
    client = ModelFirstLLMClient(
        model_result={
            "task_type": "job_match_planning",
            "reason": "too many steps",
            "steps": [
                "get_candidate_profile",
                "get_resume_by_id",
                "search_jobs",
                "match_resume_to_jobs",
                "search_jobs",
                "match_resume_to_jobs",
                "search_jobs",
            ],
            "needs_more_context": False,
            "missing_context": [],
            "follow_up_question": None,
        }
    )

    plan = client.generate_plan(
        message="结合我的情况推荐适合投的岗位",
        memory_context=[],
        profile={},
        available_tools=[
            "get_candidate_profile",
            "get_resume_by_id",
            "search_jobs",
            "match_resume_to_jobs",
        ],
        user_state={"has_candidate": True, "has_resume": True},
    )

    assert client.fallback_calls == 1
    assert plan["planner_source"] == "fallback"


def test_generate_plan_falls_back_when_missing_context_contract_is_broken() -> None:
    client = ModelFirstLLMClient(
        model_result={
            "task_type": "job_match",
            "reason": "asks for more context but does not provide details",
            "steps": [],
            "needs_more_context": True,
            "missing_context": [],
            "follow_up_question": None,
        }
    )

    plan = client.generate_plan(
        message="我适合投哪些岗位",
        memory_context=[],
        profile={},
        available_tools=["match_resume_to_jobs"],
        user_state={"has_candidate": True, "has_resume": False},
    )

    assert client.fallback_calls == 1
    assert plan["planner_source"] == "fallback"
    assert plan["missing_context"] == ["resume"]


def test_summarize_job_search_uses_chat_completions_when_configured() -> None:
    client = JobSearchSummarizeChatClient()
    planner_base = settings.planner_base_url.rstrip("/")
    original_openai_api_key = settings.openai_api_key
    original_planner_api_key = settings.planner_api_key

    settings.openai_api_key = ""
    settings.planner_api_key = "planner-only-key"
    try:
        text = client.summarize_job_search(
            message="找后端实习",
            memory_context=["我们聊过偏好 Python"],
            jobs=[
                {"title": "Backend Intern", "snippet": "Python team"},
                {"title": "Platform Intern", "snippet": "Infra team"},
                {"title": "API Intern", "snippet": "Service APIs"},
                {"title": "Extra Intern", "snippet": "Should not be sent"},
            ],
        )
    finally:
        settings.openai_api_key = original_openai_api_key
        settings.planner_api_key = original_planner_api_key

    assert text == "Model job-search summary."
    assert len(client.summarize_chat_calls) == 1
    url, payload, kwargs = client.summarize_chat_calls[0]
    assert url == f"{planner_base}/chat/completions"
    assert kwargs["timeout"] == 12.0
    assert payload["model"] == settings.planner_model
    assert payload["thinking"] == {"type": "disabled"}
    assert payload["messages"][0]["content"] == JOB_SEARCH_SUMMARIZER_SYSTEM_PROMPT
    user_blob = json.loads(payload["messages"][1]["content"])
    assert user_blob["message"] == "找后端实习"
    assert user_blob["memory_context"] == ["我们聊过偏好 Python"]
    assert [job["title"] for job in user_blob["jobs"]] == [
        "Backend Intern",
        "Platform Intern",
        "API Intern",
    ]


def test_summarize_job_search_disables_thinking_even_when_planner_keeps_it() -> None:
    client = JobSearchSummarizeChatClient()
    original_disable_thinking = settings.planner_disable_thinking
    original_planner_api_key = settings.planner_api_key

    settings.planner_disable_thinking = False
    settings.planner_api_key = "planner-only-key"
    try:
        client.summarize_job_search(
            message="找后端实习",
            memory_context=[],
            jobs=[{"title": "Backend Intern", "snippet": "Python team"}],
        )
    finally:
        settings.planner_disable_thinking = original_disable_thinking
        settings.planner_api_key = original_planner_api_key

    payload = client.summarize_chat_calls[0][1]
    assert payload["thinking"] == {"type": "disabled"}


def test_planner_uses_full_timeout_and_summarizer_uses_short_timeout() -> None:
    client = TimeoutCaptureLLMClient()

    client.generate_plan(
        message="帮我找一些岗位",
        memory_context=[],
        profile={},
        available_tools=["search_jobs"],
    )
    client.summarize_job_search(
        message="找后端实习",
        memory_context=[],
        jobs=[{"title": "Backend Intern", "snippet": "Python team"}],
    )

    assert client.calls[0][1]["timeout"] == client.PLANNER_TIMEOUT_SECONDS
    assert client.calls[1][1]["timeout"] == client.JOB_SEARCH_SUMMARY_TIMEOUT_SECONDS


def test_extract_career_events_uses_structured_responses_payload() -> None:
    client = CareerEventExtractionClient()

    events = client.extract_career_events(
        user_id="event-user",
        message="Canva backend 面试没过，反馈是 system design fundamentals。",
    )

    assert events == [
        {
            "event_type": "interview_feedback",
            "title": "Canva backend interview feedback",
            "summary": "Rejected after Canva backend interview; prepare system design fundamentals.",
            "occurred_at": "2026-04-20",
        }
    ]
    assert client.calls
    _, payload, kwargs = client.calls[0]
    assert kwargs["timeout"] == 5.0
    assert payload["thinking"] == {"type": "disabled"}
    user_blob = json.loads(payload["input"][1]["content"])
    assert user_blob["user_id"] == "event-user"
    assert "Canva backend" in user_blob["message"]


def test_extract_career_events_returns_empty_when_model_payload_is_invalid() -> None:
    client = CareerEventExtractionClient(response_text="{not-json")

    assert client.extract_career_events(
        user_id="event-user",
        message="Canva backend 面试没过。",
    ) == []


def test_decide_next_action_returns_replan_with_sanitized_steps() -> None:
    client = ObserveDecisionClient(
        response_json='{"decision":"replan","reason":"adjust","steps":["search_jobs","imaginary_tool"]}'
    )

    result = client.decide_next_action(
        task_type="job_match_planning",
        message="结合我的情况推荐适合投的岗位",
        current_step="search_jobs",
        tool_result=[{"title": "Python FastAPI Backend Engineer"}],
        remaining_steps=["match_resume_to_jobs"],
        available_tools=["search_jobs", "match_resume_to_jobs"],
    )

    assert result["decision"] == "replan"
    assert result["steps"] == ["search_jobs"]
    assert client.calls


def test_decide_react_action_returns_continue_for_valid_action() -> None:
    client = ObserveDecisionClient(
        response_json='{"action":"continue","reason":"need jobs","observation_summary":"found candidates"}'
    )
    result = client.decide_react_action(
        task_type="job_match_planning",
        message="结合我的情况推荐适合投的岗位",
        state={"_last_step": "get_resume_by_id"},
        last_observation={"step": "get_resume_by_id", "result": {"id": 1}},
        available_tools=["search_jobs", "match_resume_to_jobs"],
    )
    assert result["action"] == "continue"
    assert result["reason"] == "need jobs"
    assert result["observation_summary"] == "found candidates"


def test_decide_react_action_maps_legacy_tool_action_to_continue() -> None:
    client = ObserveDecisionClient(
        response_json='{"action":"tool","tool_name":"imaginary_tool","tool_input_hint":{},"reason":"legacy","observation_summary":""}'
    )
    result = client.decide_react_action(
        task_type="job_match_planning",
        message="结合我的情况推荐适合投的岗位",
        state={"_last_step": "search_jobs"},
        last_observation={"step": "search_jobs", "result": []},
        available_tools=["search_jobs", "match_resume_to_jobs"],
    )
    assert result["action"] == "continue"
    assert result["reason"] == "legacy"


def test_decide_react_action_sanitizes_unknown_action_to_continue() -> None:
    client = ObserveDecisionClient(
        response_json='{"action":"switch_tool","reason":"bad","observation_summary":""}'
    )
    result = client.decide_react_action(
        task_type="job_match_planning",
        message="结合我的情况推荐适合投的岗位",
        state={"_last_step": "search_jobs"},
        last_observation={"step": "search_jobs", "result": []},
        available_tools=["search_jobs", "match_resume_to_jobs"],
    )
    assert result["action"] == "continue"


def test_decide_react_action_accepts_switch_tool_with_whitelist() -> None:
    client = ObserveDecisionClient(
        response_json='{"action":"switch_tool","tool_name":"match_resume_to_jobs","reason":"resume already loaded","observation_summary":"switch to scoring"}'
    )
    result = client.decide_react_action(
        task_type="job_match_planning",
        message="结合我的情况推荐适合投的岗位",
        state={"_last_step": "search_jobs"},
        last_observation={"step": "search_jobs", "result": [{"title": "Backend Engineer"}]},
        available_tools=["search_jobs", "match_resume_to_jobs"],
        executor_whitelist=["search_jobs", "match_resume_to_jobs"],
    )
    assert result["action"] == "switch_tool"
    assert result["tool_name"] == "match_resume_to_jobs"
    assert result["planned_tools"] == []
    assert result["reason"] == "resume already loaded"


def test_decide_react_action_accepts_replan_strategy_chain() -> None:
    client = ObserveDecisionClient(
        response_json='{"action":"replan_strategy","planned_tools":["match_resume_to_jobs","search_jobs"],"reason":"skip low-value repetition","observation_summary":"rewrite remaining chain"}'
    )
    result = client.decide_react_action(
        task_type="job_match_planning",
        message="结合我的情况推荐适合投的岗位",
        state={"_last_step": "get_resume_by_id"},
        last_observation={"step": "get_resume_by_id", "result": {"id": 1}},
        available_tools=["search_jobs", "match_resume_to_jobs"],
        executor_whitelist=["search_jobs", "match_resume_to_jobs"],
    )
    assert result["action"] == "replan_strategy"
    assert result["tool_name"] == ""
    assert result["planned_tools"] == ["match_resume_to_jobs", "search_jobs"]
    assert result["reason"] == "skip low-value repetition"


def test_generate_plan_accepts_optional_extended_schema_fields() -> None:
    client = ModelFirstLLMClient(
        model_result={
            "task_type": "career_insights",
            "reason": "diagnose with structured plan metadata",
            "steps": ["get_career_insights"],
            "domain": "career",
            "action": "diagnose_bottleneck",
            "goal": "Find main bottleneck",
            "subgoals": ["check interview feedback"],
            "resources": ["candidate_profile", "latest_resume", "target_jobs"],
            "required_context": ["target_role"],
            "confidence": 0.86,
            "plan_type": "diagnostic",
            "evidence_policy": "use_existing",
            "stop_criteria": ["main bottleneck identified"],
            "needs_more_context": False,
            "missing_context": [],
            "follow_up_question": None,
        }
    )

    plan = client.generate_plan(
        message="我为什么一直投递没回音？",
        memory_context=[],
        profile={},
        available_tools=["get_career_insights"],
        user_state={"has_candidate": True, "has_resume": True},
    )

    assert plan["planner_source"] == "model"
    assert plan["domain"] == "career"
    assert plan["action"] == "diagnose_bottleneck"
    assert plan["confidence"] == 0.86
    assert plan["plan_type"] == "diagnostic"


def test_generate_plan_falls_back_when_diagnostic_plan_missing_goal() -> None:
    client = ModelFirstLLMClient(
        model_result={
            "task_type": "career_insights",
            "reason": "diagnostic metadata missing required fields",
            "steps": ["get_career_insights"],
            "plan_type": "diagnostic",
            "subgoals": ["check interview feedback"],
            "resources": ["candidate_profile"],
            "stop_criteria": ["done"],
            "needs_more_context": False,
            "missing_context": [],
            "follow_up_question": None,
        }
    )

    plan = client.generate_plan(
        message="我为什么一直投递没回音？",
        memory_context=[],
        profile={},
        available_tools=["get_career_insights"],
        user_state={"has_candidate": True, "has_resume": True},
    )

    assert client.fallback_calls == 1
    assert plan["planner_source"] == "fallback"


def test_generate_diagnostic_plan_accepts_valid_payload() -> None:
    client = DiagnosticModelFirstLLMClient(
        model_result={
            "diagnostic_hypotheses": [
                {
                    "bottleneck_type": "resume_positioning",
                    "summary": "Likely conversion bottleneck before interviews.",
                    "rationale": "Applications remain in early statuses.",
                    "confidence": 0.7,
                    "evidence_refs": ["applications.status_counts"],
                }
            ],
            "evidence_to_collect": [
                {
                    "source": "applications",
                    "reason": "Need status funnel breakdown.",
                    "priority": "high",
                    "required": True,
                }
            ],
            "next_question": "Could you share your last 10 application statuses?",
            "confidence": 0.7,
            "stop_criteria": ["main bottleneck hypothesis selected"],
        }
    )

    result = client.generate_diagnostic_plan(
        message="为什么我一直没回音？",
        plan_semantics={"task_type": "career_insights"},
        profile={},
        context_resolution={"needs_more_context": False},
        memory_context=[],
    )

    parsed = DiagnosticPlannerOutput.model_validate(result)
    assert parsed.confidence == 0.7
    assert client.model_calls == 1
    assert client.fallback_calls == 0


def test_generate_diagnostic_plan_falls_back_on_invalid_json_error() -> None:
    client = DiagnosticModelFirstLLMClient(model_error=json.JSONDecodeError("bad", "x", 0))

    result = client.generate_diagnostic_plan(
        message="为什么我一直没回音？",
        plan_semantics={"task_type": "career_insights"},
        profile={},
        context_resolution={"needs_more_context": False},
        memory_context=[],
    )

    assert client.model_calls == 1
    assert client.fallback_calls == 1
    assert result["diagnostic_hypotheses"][0]["bottleneck_type"] == "insufficient_evidence"


def test_generate_diagnostic_plan_falls_back_on_schema_mismatch() -> None:
    client = DiagnosticModelFirstLLMClient(
        model_result={
            "diagnostic_hypotheses": "bad",
            "evidence_to_collect": [],
            "next_question": None,
            "confidence": 0.5,
            "stop_criteria": [],
        }
    )

    result = client.generate_diagnostic_plan(
        message="为什么我一直没回音？",
        plan_semantics={"task_type": "career_insights"},
        profile={},
        context_resolution={"needs_more_context": False},
        memory_context=[],
    )

    assert client.fallback_calls == 1
    assert result["confidence"] <= 0.4


def test_generate_diagnostic_plan_falls_back_on_unknown_enum() -> None:
    client = DiagnosticModelFirstLLMClient(
        model_result={
            "diagnostic_hypotheses": [
                {
                    "bottleneck_type": "unknown_type",
                    "summary": "x",
                    "rationale": "y",
                    "confidence": 0.9,
                    "evidence_refs": ["foo"],
                }
            ],
            "evidence_to_collect": [],
            "next_question": None,
            "confidence": 0.9,
            "stop_criteria": [],
        }
    )

    result = client.generate_diagnostic_plan(
        message="为什么我一直没回音？",
        plan_semantics={"task_type": "career_insights"},
        profile={},
        context_resolution={"needs_more_context": False},
        memory_context=[],
    )

    assert client.fallback_calls == 1
    assert result["diagnostic_hypotheses"][0]["bottleneck_type"] == "insufficient_evidence"


def test_generate_diagnostic_plan_falls_back_on_extra_keys_and_tool_fields() -> None:
    client = DiagnosticModelFirstLLMClient(
        model_result={
            "diagnostic_hypotheses": [
                {
                    "bottleneck_type": "skill_gap",
                    "summary": "x",
                    "rationale": "y",
                    "confidence": 0.8,
                    "evidence_refs": ["feedback.0"],
                    "tool_name": "search_jobs",
                }
            ],
            "evidence_to_collect": [
                {
                    "source": "feedback",
                    "reason": "need interview feedback",
                    "priority": "high",
                    "required": True,
                    "tool_chain": ["search_jobs"],
                }
            ],
            "next_question": None,
            "confidence": 0.8,
            "stop_criteria": [],
            "steps": ["search_jobs"],
        }
    )

    result = client.generate_diagnostic_plan(
        message="为什么我一直没回音？",
        plan_semantics={"task_type": "career_insights"},
        profile={},
        context_resolution={"needs_more_context": False},
        memory_context=[],
    )

    assert client.fallback_calls == 1
    assert "tool_name" not in result
    assert "steps" not in result


def test_build_diagnostic_plan_request_uses_dedicated_prompt_and_schema() -> None:
    client = LLMClient()

    request = client._build_diagnostic_plan_request(
        message="为什么我一直没回音？",
        plan_semantics={"task_type": "career_insights"},
        profile={"target_role_preference": "backend"},
        context_resolution={"needs_more_context": False},
        memory_context=["最近收到两次拒信"],
    )

    assert request["input"][0]["content"] == DIAGNOSTIC_PLANNER_SYSTEM_PROMPT
    schema = request["text"]["format"]["schema"]
    assert schema == DiagnosticPlannerOutput.model_json_schema()
    assert request["text"]["format"]["strict"] is True


def test_generate_uses_chat_completions_when_configured() -> None:
    client = GenerateChatClient(response_text="Model generated answer.")

    answer = client.generate(
        message="我该如何准备面试？",
        memory_context=["用户偏向后端岗位"],
        evidence=["Backend Intern at Canva"],
    )

    assert answer == "Model generated answer."
    assert client.last_generate_source == "model"
    assert len(client.calls) == 1
    url, payload, kwargs = client.calls[0]
    assert url.endswith("/chat/completions")
    assert payload["model"] == client.model
    assert kwargs["timeout"] == 12.0


def test_generate_falls_back_when_model_call_fails() -> None:
    client = GenerateChatClient(response_text="", error=httpx.HTTPError("boom"))

    answer = client.generate(
        message="帮我看下一步",
        memory_context=[],
        evidence=["e1"],
    )

    assert "Fallback response for '帮我看下一步'" in answer
    assert client.last_generate_source == "fallback"


def test_fallback_plan_defaults_to_safe_no_tool_execution() -> None:
    client = LLMClient()
    plan = client._fallback_plan(
        message="any unknown message",
        memory_context=["ctx"],
        profile={"target_role_preference": "backend"},
        available_tools=["search_jobs", "match_resume_to_jobs"],
        user_state={"has_resume": True},
    )

    assert plan["task_type"] == "fallback"
    assert plan["steps"] == []
    assert plan["needs_more_context"] is False
