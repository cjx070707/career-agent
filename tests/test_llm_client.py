import json

import httpx

from app.llm.client import LLMClient
from app.env import settings
from app.llm.prompts import JOB_SEARCH_SUMMARIZER_SYSTEM_PROMPT


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
    assert kwargs["timeout"] == 45.0
    assert payload["model"] == settings.planner_model
    assert payload["messages"][0]["content"] == JOB_SEARCH_SUMMARIZER_SYSTEM_PROMPT
    user_blob = json.loads(payload["messages"][1]["content"])
    assert user_blob["message"] == "找后端实习"
    assert user_blob["memory_context"] == ["我们聊过偏好 Python"]
    assert [job["title"] for job in user_blob["jobs"]] == [
        "Backend Intern",
        "Platform Intern",
        "API Intern",
    ]


def test_planner_and_summarizer_requests_use_45_second_timeout() -> None:
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

    assert client.calls[0][1]["timeout"] == 45.0
    assert client.calls[1][1]["timeout"] == 45.0
