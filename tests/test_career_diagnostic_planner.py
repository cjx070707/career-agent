from app.services.career_diagnostic_planner import CareerDiagnosticPlanner


class FakeDiagnosticLLMClient:
    def __init__(self, payload=None, error=None) -> None:
        self.payload = payload
        self.error = error
        self.calls = []

    def generate_diagnostic_plan(self, **kwargs):
        self.calls.append(kwargs)
        if self.error is not None:
            raise self.error
        return self.payload


def _valid_payload():
    return {
        "diagnostic_hypotheses": [
            {
                "bottleneck_type": "resume_positioning",
                "summary": "Likely weak application-to-interview conversion.",
                "rationale": "Most applications are stuck in applied/submitted.",
                "confidence": 0.7,
                "evidence_refs": ["applications.status_counts"],
            }
        ],
        "evidence_to_collect": [
            {
                "source": "applications",
                "reason": "Need detailed funnel states.",
                "priority": "high",
                "required": True,
            }
        ],
        "next_question": "Can you share the statuses of your latest applications?",
        "confidence": 0.7,
        "stop_criteria": ["main bottleneck hypothesis selected"],
    }


def test_career_diagnosis_task_calls_llm_and_returns_controlled_output() -> None:
    fake_llm = FakeDiagnosticLLMClient(payload=_valid_payload())
    planner = CareerDiagnosticPlanner(llm_client=fake_llm)

    result = planner.plan(
        message="为什么我一直没回音？",
        plan_semantics={"task_type": "career_insights", "domain": "career_strategy", "action": "diagnose"},
        profile={"target_role_preference": "backend", "skill_keywords": ["python"]},
        context_resolution={"needs_more_context": False},
        memory_context=["最近收到两次拒信"],
    )

    assert len(fake_llm.calls) == 1
    assert result.confidence == 0.7
    assert len(result.diagnostic_hypotheses) == 1
    assert len(result.evidence_to_collect) == 1


def test_non_career_task_returns_not_applicable_without_llm_call() -> None:
    fake_llm = FakeDiagnosticLLMClient(payload=_valid_payload())
    planner = CareerDiagnosticPlanner(llm_client=fake_llm)

    result = planner.plan(
        message="帮我找岗位",
        plan_semantics={"task_type": "job_search", "domain": "job_search", "action": "search"},
        profile={},
        context_resolution={"needs_more_context": False},
        memory_context=[],
    )

    assert len(fake_llm.calls) == 0
    assert result.diagnostic_hypotheses == []
    assert result.evidence_to_collect == []
    assert result.confidence == 0.0
    assert result.stop_criteria == ["not applicable"]


def test_needs_more_context_skips_llm_and_uses_follow_up_question() -> None:
    fake_llm = FakeDiagnosticLLMClient(payload=_valid_payload())
    planner = CareerDiagnosticPlanner(llm_client=fake_llm)

    result = planner.plan(
        message="帮我诊断",
        plan_semantics={"task_type": "career_insights"},
        profile={},
        context_resolution={
            "needs_more_context": True,
            "follow_up_question": "请先提供目标岗位和最近面试反馈。",
        },
        memory_context=[],
    )

    assert len(fake_llm.calls) == 0
    assert result.confidence <= 0.3
    assert result.next_question == "请先提供目标岗位和最近面试反馈。"
    assert result.stop_criteria == ["required context collected"]


def test_llm_failure_returns_deterministic_fallback() -> None:
    fake_llm = FakeDiagnosticLLMClient(error=RuntimeError("llm failed"))
    planner = CareerDiagnosticPlanner(llm_client=fake_llm)

    result = planner.plan(
        message="为什么我一直没回音？",
        plan_semantics={"task_type": "career_insights"},
        profile={},
        context_resolution={"needs_more_context": False},
        memory_context=[],
    )

    assert len(fake_llm.calls) == 1
    assert result.confidence <= 0.4
    assert result.diagnostic_hypotheses[0].bottleneck_type == "insufficient_evidence"


def test_invalid_enum_payload_falls_back() -> None:
    fake_llm = FakeDiagnosticLLMClient(
        payload={
            "diagnostic_hypotheses": [
                {
                    "bottleneck_type": "bad_enum",
                    "summary": "x",
                    "rationale": "y",
                    "confidence": 0.9,
                    "evidence_refs": ["a"],
                }
            ],
            "evidence_to_collect": [],
            "next_question": None,
            "confidence": 0.9,
            "stop_criteria": [],
        }
    )
    planner = CareerDiagnosticPlanner(llm_client=fake_llm)

    result = planner.plan(
        message="为什么我一直没回音？",
        plan_semantics={"task_type": "career_insights"},
        profile={},
        context_resolution={"needs_more_context": False},
        memory_context=[],
    )

    assert result.diagnostic_hypotheses[0].bottleneck_type == "insufficient_evidence"
    assert result.confidence <= 0.4


def test_confidence_is_downgraded_when_no_evidence_refs() -> None:
    fake_llm = FakeDiagnosticLLMClient(
        payload={
            "diagnostic_hypotheses": [
                {
                    "bottleneck_type": "resume_positioning",
                    "summary": "x",
                    "rationale": "y",
                    "confidence": 0.9,
                    "evidence_refs": [],
                }
            ],
            "evidence_to_collect": [],
            "next_question": None,
            "confidence": 0.95,
            "stop_criteria": [],
        }
    )
    planner = CareerDiagnosticPlanner(llm_client=fake_llm)
    result = planner.plan(
        message="为什么我一直没回音？",
        plan_semantics={"task_type": "career_insights"},
        profile={},
        context_resolution={"needs_more_context": False},
        memory_context=[],
    )

    assert result.diagnostic_hypotheses[0].confidence <= 0.55
    assert result.confidence <= 0.6


def test_limits_are_enforced_for_hypotheses_and_evidence() -> None:
    hypotheses = []
    for i in range(4):
        hypotheses.append(
            {
                "bottleneck_type": "application_volume",
                "summary": f"s{i}",
                "rationale": "r",
                "confidence": 0.5,
                "evidence_refs": [f"ref{i}"],
            }
        )
    evidence = []
    for i in range(6):
        evidence.append(
            {
                "source": "applications",
                "reason": f"need {i}",
                "priority": "medium",
                "required": True,
            }
        )
    fake_llm = FakeDiagnosticLLMClient(
        payload={
            "diagnostic_hypotheses": hypotheses,
            "evidence_to_collect": evidence,
            "next_question": None,
            "confidence": 0.7,
            "stop_criteria": [],
        }
    )
    planner = CareerDiagnosticPlanner(llm_client=fake_llm)
    result = planner.plan(
        message="为什么我一直没回音？",
        plan_semantics={"task_type": "career_insights"},
        profile={},
        context_resolution={"needs_more_context": False},
        memory_context=[],
    )

    assert len(result.diagnostic_hypotheses) == 1
    assert result.diagnostic_hypotheses[0].bottleneck_type == "insufficient_evidence"
    assert len(result.evidence_to_collect) == 3


def test_output_shape_is_fixed_and_contains_no_tool_fields() -> None:
    fake_llm = FakeDiagnosticLLMClient(payload=_valid_payload())
    planner = CareerDiagnosticPlanner(llm_client=fake_llm)
    result = planner.plan(
        message="为什么我一直没回音？",
        plan_semantics={"task_type": "career_insights"},
        profile={},
        context_resolution={"needs_more_context": False},
        memory_context=[],
    )

    dump = result.model_dump()
    assert set(dump.keys()) == {
        "diagnostic_hypotheses",
        "evidence_to_collect",
        "next_question",
        "confidence",
        "stop_criteria",
    }
    assert "steps" not in dump
    assert "tool_chain" not in dump
    for hypothesis in dump["diagnostic_hypotheses"]:
        assert "tool_name" not in hypothesis
