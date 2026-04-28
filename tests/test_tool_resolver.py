from app.resolvers.context_requirement_resolver import ContextRequirementResolution
from app.resolvers.tool_resolver import ToolResolver
from app.schemas.chat import ChatPlan


def make_plan(**overrides) -> ChatPlan:
    payload = {
        "task_type": "fallback",
        "reason": "test plan",
        "steps": [],
        "planner_source": "router",
    }
    payload.update(overrides)
    return ChatPlan.model_validate(payload)


def resolved_context(*, missing_context=None, needs_more_context=False):
    return ContextRequirementResolution(
        required_context=[],
        missing_context=list(missing_context or []),
        needs_more_context=needs_more_context,
        follow_up_question=None,
        resolver_trace=[],
    )


def names(result):
    return [step["tool_name"] for step in result.tool_chain]


def test_resume_summary_maps_to_get_resume_by_id() -> None:
    plan = make_plan(task_type="resume_analysis", domain="resume_analysis", action="summarize")

    result = ToolResolver().resolve(
        plan=plan,
        resolved_context=resolved_context(),
        available_tools=["get_resume_by_id"],
    )

    assert result.executable is True
    assert names(result) == ["get_resume_by_id"]
    assert result.resolver_trace


def test_job_match_maps_to_profile_resume_and_match_tools() -> None:
    plan = make_plan(task_type="job_match", domain="job_match", action="compare")

    result = ToolResolver().resolve(
        plan=plan,
        resolved_context=resolved_context(),
        available_tools=[
            "get_candidate_profile",
            "get_resume_by_id",
            "match_resume_to_jobs",
        ],
    )

    assert result.executable is True
    assert names(result) == [
        "get_candidate_profile",
        "get_resume_by_id",
        "match_resume_to_jobs",
    ]


def test_job_search_maps_to_search_jobs() -> None:
    plan = make_plan(task_type="job_search", domain="job_search", action="search")

    result = ToolResolver().resolve(
        plan=plan,
        resolved_context=resolved_context(),
        available_tools=["search_jobs"],
    )

    assert result.executable is True
    assert names(result) == ["search_jobs"]


def test_career_strategy_maps_to_career_insights() -> None:
    plan = make_plan(task_type="career_insights", domain="career_strategy", action="diagnose")

    result = ToolResolver().resolve(
        plan=plan,
        resolved_context=resolved_context(),
        available_tools=["get_career_insights"],
    )

    assert result.executable is True
    assert names(result) == ["get_career_insights"]


def test_third_party_advice_does_not_call_current_user_profile() -> None:
    plan = make_plan(
        task_type="fallback",
        domain="career_advice",
        action="advise",
        plan_type="third_party_advice",
    )

    result = ToolResolver().resolve(
        plan=plan,
        resolved_context=resolved_context(),
        available_tools=["get_candidate_profile", "get_resume_by_id"],
    )

    assert result.executable is True
    assert names(result) == []
    assert all(step.get("tool_name") != "get_candidate_profile" for step in result.tool_chain)


def test_missing_critical_context_does_not_build_tool_chain() -> None:
    plan = make_plan(task_type="job_match", domain="job_match", action="compare")

    result = ToolResolver().resolve(
        plan=plan,
        resolved_context=resolved_context(missing_context=["job_detail"], needs_more_context=True),
        available_tools=["get_candidate_profile", "get_resume_by_id", "match_resume_to_jobs"],
    )

    assert result.executable is False
    assert result.tool_chain == []
    assert "job_detail" in str(result.blocking_reason)


def test_missing_critical_tool_blocks_execution_with_readable_reason() -> None:
    plan = make_plan(task_type="job_search", domain="job_search", action="search")

    result = ToolResolver().resolve(
        plan=plan,
        resolved_context=resolved_context(),
        available_tools=[],
    )

    assert result.executable is False
    assert result.tool_chain == []
    assert "search_jobs" in str(result.blocking_reason)

