from app.routing.intent_gateway import IntentGateway


def test_gateway_route_resume_analysis() -> None:
    gateway = IntentGateway()
    decision = gateway.resolve_after_router_miss(
        message="总结一下我的简历",
        profile={},
        user_state={"has_resume": True, "has_job_detail": False, "has_candidate": True},
        memory_context=[],
        available_tools=[],
    )

    assert decision.domain == "career"
    assert decision.intent_cluster == "resume_analysis"
    assert decision.action == "route"
    assert decision.fallback_type != "true"
    assert decision.local_plan_payload is not None
    assert decision.local_plan_payload["task_type"] == "resume_analysis"


def test_gateway_clarify_job_match_missing_job_detail() -> None:
    gateway = IntentGateway()
    decision = gateway.resolve_after_router_miss(
        message="这个岗位适合我吗",
        profile={},
        user_state={"has_resume": True, "has_job_detail": False, "has_candidate": True},
        memory_context=[],
        available_tools=[],
    )

    assert decision.domain == "career"
    assert decision.intent_cluster == "job_match"
    assert decision.action == "clarify"
    assert decision.fallback_type == "recoverable"


def test_gateway_application_diag_not_true_fallback() -> None:
    gateway = IntentGateway()
    decision = gateway.resolve_after_router_miss(
        message="我投递没进展怎么办",
        profile={},
        user_state={"has_resume": False, "has_job_detail": False, "has_candidate": True},
        memory_context=[],
        available_tools=[],
    )

    assert decision.domain == "career"
    assert decision.intent_cluster == "application_diag"
    assert decision.action in {"route", "clarify"}
    assert decision.fallback_type != "true"


def test_gateway_route_interview_prep() -> None:
    gateway = IntentGateway()
    decision = gateway.resolve_after_router_miss(
        message="准备数据分析岗面试你要看返回 plan",
        profile={},
        user_state={"has_resume": False, "has_job_detail": False, "has_candidate": True},
        memory_context=[],
        available_tools=[],
    )

    assert decision.domain == "career"
    assert decision.intent_cluster == "interview_prep"
    assert decision.action == "route"
    assert decision.local_plan_payload is not None
    assert decision.local_plan_payload["task_type"] == "interview_prep"


def test_gateway_true_fallback_non_career() -> None:
    gateway = IntentGateway()
    decision = gateway.resolve_after_router_miss(
        message="天气怎么样",
        profile={},
        user_state={"has_resume": False, "has_job_detail": False, "has_candidate": True},
        memory_context=[],
        available_tools=[],
    )

    assert decision.domain == "non_career"
    assert decision.action == "true_fallback"
    assert decision.fallback_type == "true"

