"""Unit tests for IntentRouter narrowing + compound detection.

Stage C boundary: router owns high-confidence rules; ambiguous queries must
fall through to `None` so the LLM planner can take over.
"""

from app.routing.intent_router import IntentRouter


ALL_TOOLS = [
    "get_candidate_profile",
    "get_resume_by_id",
    "get_applications",
    "search_jobs",
    "match_resume_to_jobs",
]


def _route(router: IntentRouter, message: str, **kwargs):
    defaults = {
        "memory_context": [],
        "profile": {},
        "available_tools": ALL_TOOLS,
        "user_state": {"has_candidate": True, "has_resume": True},
    }
    defaults.update(kwargs)
    return router.route(message=message, **defaults)


def test_job_search_requires_explicit_action_or_object_keyword() -> None:
    router = IntentRouter()

    # Pure tech-name query should no longer fire job_search; previously `backend`
    # alone routed to search, now it falls through so the planner can decide.
    assert _route(router, "如何准备 backend internship 面试") is None
    assert _route(router, "what should I prepare for a python backend role") is None


def test_job_search_still_catches_clear_search_phrasing() -> None:
    router = IntentRouter()

    plan = _route(router, "帮我找一些 Python backend 岗位")
    assert plan is not None
    assert plan["task_type"] == "job_search"

    plan = _route(router, "我想找一份 data analyst 实习")
    assert plan is not None
    assert plan["task_type"] == "job_search"

    plan = _route(router, "any junior data jobs?")
    assert plan is not None
    assert plan["task_type"] == "job_search"


def test_compound_search_plus_resume_match_routes_to_job_match_planning() -> None:
    router = IntentRouter()

    plan = _route(
        router,
        "帮我找 data 岗并用我的简历看看匹配度",
    )
    assert plan is not None
    assert plan["task_type"] == "job_match_planning"
    assert plan["steps"] == [
        "get_candidate_profile",
        "get_resume_by_id",
        "search_jobs",
        "match_resume_to_jobs",
    ]
    assert plan["planner_source"] == "router"


def test_career_planning_question_falls_through_to_planner() -> None:
    router = IntentRouter()

    assert _route(router, "我 USYD CS 大三想进 AI 方向，现在该怎么准备") is None
    assert _route(router, "有 Atlassian 的 grad program 吗") is None


def test_application_history_routes_to_get_applications() -> None:
    router = IntentRouter()

    plan = _route(router, "我最近投了哪些岗位？")
    assert plan is not None
    assert plan["task_type"] == "application_history"
    assert plan["steps"] == ["get_applications"]
    assert plan["planner_source"] == "router"
