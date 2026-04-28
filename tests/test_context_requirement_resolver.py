from app.resolvers.context_requirement_resolver import ContextRequirementResolver
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


def test_resume_summary_without_resume_needs_more_context() -> None:
    plan = make_plan(task_type="resume_analysis", domain="resume_analysis", action="summarize")

    result = ContextRequirementResolver().resolve(
        plan=plan,
        message="总结我的简历",
        user_state={"has_resume": False},
        profile={},
        memory_context=[],
    )

    assert result.needs_more_context is True
    assert result.required_context == ["resume"]
    assert result.missing_context == ["resume"]
    assert "简历" in str(result.follow_up_question)
    assert result.resolver_trace


def test_job_match_compare_without_job_detail_needs_more_context() -> None:
    plan = make_plan(task_type="job_match", domain="job_match", action="compare")

    result = ContextRequirementResolver().resolve(
        plan=plan,
        message="这个岗位我匹配吗",
        user_state={"has_resume": True, "has_job_detail": False},
        profile={},
        memory_context=[],
    )

    assert result.needs_more_context is True
    assert result.required_context == ["resume", "job_detail"]
    assert result.missing_context == ["job_detail"]
    assert "岗位" in str(result.follow_up_question)


def test_job_match_compare_with_resume_and_job_detail_can_continue() -> None:
    plan = make_plan(task_type="job_match", domain="job_match", action="compare")

    result = ContextRequirementResolver().resolve(
        plan=plan,
        message="JD: Python backend engineer, FastAPI, SQL. 这个岗位我匹配吗",
        user_state={"has_resume": True, "has_job_detail": True},
        profile={},
        memory_context=[],
    )

    assert result.needs_more_context is False
    assert result.missing_context == []


def test_interview_prep_with_target_role_can_continue() -> None:
    plan = make_plan(task_type="interview_prep", domain="interview_prep", action="plan")

    result = ContextRequirementResolver().resolve(
        plan=plan,
        message="帮我准备 data analyst 面试",
        user_state={},
        profile={},
        memory_context=[],
    )

    assert result.needs_more_context is False
    assert result.required_context == ["target_role"]


def test_interview_prep_without_target_role_needs_more_context() -> None:
    plan = make_plan(task_type="interview_prep", domain="interview_prep", action="plan")

    result = ContextRequirementResolver().resolve(
        plan=plan,
        message="帮我准备面试",
        user_state={},
        profile={"target_role_preference": ""},
        memory_context=[],
    )

    assert result.needs_more_context is True
    assert result.missing_context == ["target_role"]
    assert "目标岗位" in str(result.follow_up_question)


def test_third_party_advice_does_not_require_current_user_profile() -> None:
    plan = make_plan(
        task_type="fallback",
        domain="career_advice",
        action="advise",
        plan_type="third_party_advice",
        required_context=["profile"],
    )

    result = ContextRequirementResolver().resolve(
        plan=plan,
        message="我朋友想找后端实习，该怎么准备",
        user_state={"has_resume": False},
        profile={},
        memory_context=[],
    )

    assert result.required_context == []
    assert result.missing_context == []
    assert result.needs_more_context is False


def test_required_context_merges_plan_fields() -> None:
    plan = make_plan(
        task_type="job_search",
        domain="job_search",
        action="search",
        required_context=["location"],
    )

    result = ContextRequirementResolver().resolve(
        plan=plan,
        message="帮我找 Sydney 的 backend 岗位",
        user_state={},
        profile={},
        memory_context=[],
    )

    assert result.required_context == ["location", "job_query"]
    assert result.needs_more_context is False

