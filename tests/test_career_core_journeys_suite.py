import json
from pathlib import Path

from app.services.agent_service import AgentService


def _load_cases() -> list[dict]:
    dataset = Path("evals/career_core_replay_30.jsonl")
    return [json.loads(line) for line in dataset.read_text(encoding="utf-8").splitlines() if line.strip()]


def test_career_core_journey_stability_gate(isolated_runtime) -> None:
    service = AgentService()
    rows = _load_cases()

    career_total = 0
    career_true_fallback = 0
    core_total = 0
    core_planner_called = 0
    clarify_total = 0
    clarify_with_followup = 0
    empty_talk_count = 0

    core_clusters = {
        "job_recommend",
        "job_match",
        "resume_analysis",
        "application_diag",
        "interview_prep",
    }

    for idx, row in enumerate(rows):
        result = service.respond(f"suite-user-{idx:03d}", row["message"])
        plan = result.plan.model_dump() if result.plan else {}
        resolver_trace = plan.get("resolver_trace") or []
        gateway = {}
        for item in resolver_trace:
            if item.get("resolver") == "intent_gateway":
                gateway = item
                break
        fallback_type = str(gateway.get("fallback_type") or "none")
        planner_called = bool(gateway.get("planner_called", False))
        action = str(gateway.get("gateway_action") or "")

        if row["expected_domain"] == "career":
            career_total += 1
            if fallback_type == "true":
                career_true_fallback += 1

        if row["expected_intent_cluster"] in core_clusters:
            core_total += 1
            if planner_called:
                core_planner_called += 1

        if action == "clarify":
            clarify_total += 1
            if bool(plan.get("follow_up_question")):
                clarify_with_followup += 1

        pattern = str(row.get("must_not_answer_pattern") or "")
        if pattern and pattern in str(result.answer or ""):
            empty_talk_count += 1

    true_fallback_rate = (career_true_fallback / career_total) if career_total else 0.0
    planner_dependency_rate = (core_planner_called / core_total) if core_total else 0.0
    clarify_followup_rate = (clarify_with_followup / clarify_total) if clarify_total else 1.0
    empty_talk_rate = empty_talk_count / len(rows)

    assert true_fallback_rate < 0.10
    assert planner_dependency_rate < 0.15
    assert clarify_followup_rate > 0.80
    assert empty_talk_rate <= 0.01

