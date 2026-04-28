"""Unit tests for IntentRouter narrowing + compound detection.

Stage C boundary: router owns high-confidence rules; ambiguous queries must
fall through to `None` so the LLM planner can take over.
"""

from app.routing.intent_router import IntentRouter


ALL_TOOLS = [
    "get_candidate_profile",
    "get_resume_by_id",
    "get_applications",
    "get_interview_feedback",
    "get_career_insights",
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

    # Single object words should not trigger job_search.
    assert _route(router, "我想实习") is None
    assert _route(router, "job") is None


def test_job_search_still_catches_clear_search_phrasing() -> None:
    router = IntentRouter()

    plan = _route(router, "帮我找一些 Python backend 岗位")
    assert plan is not None
    assert plan["task_type"] == "job_search"

    plan = _route(router, "我想找一份 data analyst 实习")
    assert plan is not None
    assert plan["task_type"] == "job_search"

    plan = _route(router, "any junior data jobs?")
    assert plan is None


def test_greeting_routes_to_local_fallback_without_planner() -> None:
    router = IntentRouter()

    plan = _route(router, "你好")

    assert plan is not None
    assert plan["task_type"] == "fallback"
    assert plan["steps"] == []
    assert plan["planner_source"] == "router"


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

    assert _route(router, "有 Atlassian 的 grad program 吗") is None


def test_career_preparation_question_routes_to_career_insights() -> None:
    router = IntentRouter()

    plan = _route(router, "我 USYD CS 大三想进 AI 方向，现在该怎么准备")

    assert plan is not None
    assert plan["task_type"] == "career_insights"
    assert plan["steps"] == ["get_career_insights"]
    assert plan["planner_source"] == "router"


def test_application_history_routes_to_get_applications() -> None:
    router = IntentRouter()

    plan = _route(router, "我最近投了哪些岗位？")
    assert plan is not None
    assert plan["task_type"] == "application_history"
    assert plan["steps"] == ["get_applications"]
    assert plan["planner_source"] == "router"


def test_interview_history_routes_to_get_interview_feedback() -> None:
    router = IntentRouter()

    plan = _route(router, "我最近面试反馈怎么样？")
    assert plan is not None
    assert plan["task_type"] == "interview_history"
    assert plan["steps"] == ["get_interview_feedback"]
    assert plan["planner_source"] == "router"


def test_career_insights_routes_to_get_career_insights() -> None:
    router = IntentRouter()

    plan = _route(router, "结合我的投递和面试反馈，我下一步该准备什么？")

    assert plan is not None
    assert plan["task_type"] == "career_insights"
    assert plan["steps"] == ["get_career_insights"]
    assert plan["planner_source"] == "router"


def test_career_direction_routes_to_get_career_insights() -> None:
    router = IntentRouter()

    plan = _route(router, "你觉得我下一步职业方向应该怎么考虑？")

    assert plan is not None
    assert plan["task_type"] == "career_insights"
    assert plan["steps"] == ["get_career_insights"]
    assert plan["planner_source"] == "router"


def test_general_next_step_question_routes_to_career_insights() -> None:
    router = IntentRouter()

    plan = _route(router, "我下一步该做什么？")

    assert plan is not None
    assert plan["task_type"] == "career_insights"
    assert plan["steps"] == ["get_career_insights"]
    assert plan["planner_source"] == "router"


def test_router_resume_summary_extended_plan_fields() -> None:
    router = IntentRouter()

    plan = _route(
        router,
        "总结一下我的简历",
        user_state={"has_candidate": True, "has_resume": False},
    )

    assert plan is not None
    assert plan["domain"] == "resume_analysis"
    assert plan["action"] == "summarize"
    assert "resume" in plan["resources"]
    assert "resume" in plan["required_context"]
    assert plan["needs_more_context"] is True
    assert "resume" in plan["missing_context"]


def test_router_job_match_requires_job_detail() -> None:
    router = IntentRouter()

    plan = _route(
        router,
        "帮我看看这个岗位适不适合我",
        user_state={"has_candidate": True, "has_resume": True, "has_job_detail": False},
    )

    assert plan is not None
    assert plan["task_type"] == "job_match"
    assert plan["domain"] in ("job_match", "job_application")
    assert plan["action"] == "compare"
    assert "resume" in plan["resources"]
    assert "job_detail" in plan["resources"]
    assert "resume" in plan["required_context"]
    assert "job_detail" in plan["required_context"]
    assert plan["needs_more_context"] is True
    assert "job_detail" in plan["missing_context"]
    assert plan["follow_up_question"] is not None


def test_router_third_party_job_advice_not_career_insights() -> None:
    router = IntentRouter()

    plan = _route(
        router,
        "我朋友想找 Java 后端岗位，你觉得他该怎么准备？",
    )

    assert plan is not None
    assert plan["task_type"] != "career_insights"
    assert plan["plan_type"] == "third_party_advice"
    assert plan["domain"] == "career_advice"
    assert plan["action"] == "advise"
    assert "profile" not in plan["resources"]


def test_router_career_stagnation_to_career_insights() -> None:
    router = IntentRouter()

    plan = _route(router, "我最近投递没进展，下一步应该怎么办？")

    assert plan is not None
    assert plan["task_type"] == "career_insights"
    assert plan["domain"] == "career_strategy"
    assert plan["action"] == "diagnose"
    assert "profile" in plan["resources"]
    assert "投递" in plan["goal"] or "瓶颈" in plan["goal"]


def test_router_interview_prep_data_analyst() -> None:
    router = IntentRouter()

    plan = _route(router, "我想准备数据分析岗面试")

    assert plan is not None
    assert plan["task_type"] == "interview_prep"
    assert plan["domain"] == "interview_prep"
    assert plan["action"] == "plan"
    assert "profile" in plan["resources"]
    assert "target_role" in plan["resources"]
    assert "target_role" in plan["required_context"]
    assert "面试准备" in plan["goal"] or "计划" in plan["goal"]


def test_router_outputs_required_context_and_resources() -> None:
    router = IntentRouter()

    plan = _route(
        router,
        "帮我看看这个岗位适不适合我",
        user_state={"has_candidate": True, "has_resume": False, "has_job_detail": False},
    )

    assert plan is not None
    assert sorted(plan["required_context"]) == sorted(["resume", "job_detail"])
    assert sorted(plan["resources"]) == sorted(["resume", "job_detail"])
    assert sorted(plan["missing_context"]) == sorted(["resume", "job_detail"])


def test_router_resume_summary_phrase_conceptual() -> None:
    router = IntentRouter()
    plan = _route(router, "帮我概括一下我的简历")
    assert plan is not None
    assert plan["task_type"] == "candidate_profile"
    assert plan["domain"] == "resume_analysis"
    assert plan["action"] == "summarize"
    assert plan["resources"] == ["resume"]
    assert plan["required_context"] == ["resume"]
    assert plan["plan_type"] == "analysis"


def test_router_resume_summary_cv_focus() -> None:
    router = IntentRouter()
    plan = _route(router, "看一下我的 CV，总结重点")
    assert plan is not None
    assert plan["task_type"] == "candidate_profile"
    assert plan["domain"] == "resume_analysis"
    assert plan["action"] == "summarize"
    assert plan["resources"] == ["resume"]
    assert plan["required_context"] == ["resume"]
    assert plan["plan_type"] == "analysis"


def test_router_job_match_jd_phrase() -> None:
    router = IntentRouter()
    plan = _route(router, "这个 JD 和我匹配吗")
    assert plan is not None
    assert plan["task_type"] == "job_match"
    assert plan["domain"] == "job_match"
    assert plan["action"] == "compare"
    assert sorted(plan["resources"]) == sorted(["resume", "job_detail"])
    assert sorted(plan["required_context"]) == sorted(["resume", "job_detail"])
    assert plan["plan_type"] == "matching"


def test_router_job_match_can_apply_phrase() -> None:
    router = IntentRouter()
    plan = _route(router, "这个岗位我能投吗")
    assert plan is not None
    assert plan["task_type"] == "job_match"
    assert plan["domain"] == "job_match"
    assert plan["action"] == "compare"
    assert sorted(plan["resources"]) == sorted(["resume", "job_detail"])
    assert sorted(plan["required_context"]) == sorted(["resume", "job_detail"])
    assert plan["plan_type"] == "matching"


def test_router_job_match_compare_this_job_resume() -> None:
    router = IntentRouter()
    plan = _route(router, "compare this job with my resume")
    assert plan is not None
    assert plan["task_type"] == "job_match"
    assert plan["domain"] == "job_match"
    assert plan["action"] == "compare"
    assert sorted(plan["resources"]) == sorted(["resume", "job_detail"])
    assert sorted(plan["required_context"]) == sorted(["resume", "job_detail"])
    assert plan["plan_type"] == "matching"


def test_router_job_search_data_analyst_phrase() -> None:
    router = IntentRouter()
    plan = _route(router, "帮我找几个数据分析岗位")
    assert plan is not None
    assert plan["task_type"] == "job_search"
    assert plan["domain"] == "job_search"
    assert plan["action"] == "search"
    assert plan["resources"] == ["jobs"]
    assert plan["required_context"] == ["job_query"]
    assert plan["plan_type"] == "search"


def test_router_job_search_recommend_backend_phrase() -> None:
    router = IntentRouter()
    plan = _route(router, "推荐几个后端开发岗位")
    assert plan is not None
    assert plan["task_type"] == "job_search"
    assert plan["domain"] == "job_search"
    assert plan["action"] == "search"
    assert plan["resources"] == ["jobs"]
    assert plan["required_context"] == ["job_query"]
    assert plan["plan_type"] == "search"


def test_router_interview_prep_data_analyst_phrase() -> None:
    router = IntentRouter()
    plan = _route(router, "数据分析面试怎么准备")
    assert plan is not None
    assert plan["task_type"] == "interview_prep"
    assert plan["domain"] == "interview_prep"
    assert plan["action"] == "plan"
    assert sorted(plan["resources"]) == sorted(["profile", "target_role"])
    assert plan["required_context"] == ["target_role"]
    assert plan["plan_type"] == "planning"


def test_router_interview_prep_backend_internship_phrase() -> None:
    router = IntentRouter()
    plan = _route(router, "如何准备 backend internship 面试")
    assert plan is not None
    assert plan["task_type"] == "interview_prep"
    assert plan["domain"] == "interview_prep"
    assert plan["action"] == "plan"
    assert sorted(plan["resources"]) == sorted(["profile", "target_role"])
    assert plan["required_context"] == ["target_role"]
    assert plan["plan_type"] == "planning"


def test_router_interview_prep_english_prepare_phrase() -> None:
    router = IntentRouter()
    plan = _route(router, "what should I prepare for a python interview")
    assert plan is not None
    assert plan["task_type"] == "interview_prep"
    assert plan["domain"] == "interview_prep"
    assert plan["action"] == "plan"
    assert sorted(plan["resources"]) == sorted(["profile", "target_role"])
    assert plan["required_context"] == ["target_role"]
    assert plan["plan_type"] == "planning"


def test_router_third_party_roommate_advice() -> None:
    router = IntentRouter()
    plan = _route(router, "我室友想找 Java 岗位")
    assert plan is not None
    assert plan["task_type"] == "fallback"
    assert plan["domain"] == "career_advice"
    assert plan["action"] == "advise"
    assert plan["resources"] == ["general_job_market_knowledge"]
    assert plan["required_context"] == []
    assert plan["plan_type"] == "third_party_advice"
