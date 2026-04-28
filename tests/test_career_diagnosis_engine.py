from app.services.career_diagnosis_engine import CareerDiagnosisEngine


ALLOWED_BOTTLENECKS = {
    "insufficient_evidence",
    "application_volume",
    "resume_positioning",
    "interview_performance",
    "skill_gap",
    "job_targeting",
}


def test_insufficient_evidence_when_no_role_and_no_records() -> None:
    diagnosis = CareerDiagnosisEngine().diagnose(
        profile={"target_role_preference": ""},
        applications=[],
        interviews=[],
        feedback_highlights=[],
    )

    assert diagnosis["bottleneck_type"] == "insufficient_evidence"
    assert diagnosis["confidence"] <= 0.4
    assert diagnosis["evidence"]


def test_application_volume_with_role_but_no_records() -> None:
    diagnosis = CareerDiagnosisEngine().diagnose(
        profile={"target_role_preference": "backend"},
        applications=[],
        interviews=[],
        feedback_highlights=[],
    )

    assert diagnosis["bottleneck_type"] == "application_volume"
    assert 0.45 <= diagnosis["confidence"] <= 0.6


def test_resume_positioning_for_applied_submitted_without_interviews() -> None:
    diagnosis = CareerDiagnosisEngine().diagnose(
        profile={"target_role_preference": "backend"},
        applications=[
            {"status": "applied", "company": "Canva", "job_title": "Backend Intern"},
            {"status": "submitted", "company": "Atlassian", "job_title": "Backend Grad"},
        ],
        interviews=[],
        feedback_highlights=[],
    )

    assert diagnosis["bottleneck_type"] == "resume_positioning"
    assert 0.6 <= diagnosis["confidence"] <= 0.75


def test_interview_performance_for_rejected_interviews() -> None:
    diagnosis = CareerDiagnosisEngine().diagnose(
        profile={"target_role_preference": "backend"},
        applications=[{"status": "interview", "company": "Canva", "job_title": "Backend Intern"}],
        interviews=[
            {"result": "rejected", "feedback": "", "company": "Canva", "job_title": "Backend Intern"}
        ],
        feedback_highlights=[],
    )

    assert diagnosis["bottleneck_type"] == "interview_performance"
    assert 0.75 <= diagnosis["confidence"] <= 0.9


def test_skill_gap_wins_over_interview_performance() -> None:
    diagnosis = CareerDiagnosisEngine().diagnose(
        profile={"target_role_preference": "backend"},
        applications=[{"status": "interview", "company": "Canva", "job_title": "Backend Intern"}],
        interviews=[
            {
                "result": "rejected",
                "feedback": "need stronger system design and SQL fundamentals",
                "company": "Canva",
                "job_title": "Backend Intern",
            }
        ],
        feedback_highlights=["need stronger system design and SQL fundamentals"],
    )

    assert diagnosis["bottleneck_type"] == "skill_gap"
    assert diagnosis["confidence"] >= 0.8


def test_job_targeting_only_with_explicit_alignment_signals() -> None:
    diagnosis = CareerDiagnosisEngine().diagnose(
        profile={"target_role_preference": "backend"},
        applications=[
            {
                "status": "applied",
                "note": "方向太散, not relevant and too broad",
                "company": "A",
                "job_title": "Mixed Role",
            }
        ],
        interviews=[],
        feedback_highlights=[],
    )

    assert diagnosis["bottleneck_type"] == "job_targeting"


def test_no_evidence_never_high_confidence() -> None:
    diagnosis = CareerDiagnosisEngine().diagnose(
        profile={"target_role_preference": ""},
        applications=[],
        interviews=[],
        feedback_highlights=[],
    )

    assert diagnosis["confidence"] < 0.8


def test_evidence_item_shape_and_enum_guards() -> None:
    diagnosis = CareerDiagnosisEngine().diagnose(
        profile={"target_role_preference": "backend"},
        applications=[{"status": "applied", "company": "Canva", "job_title": "Backend Intern"}],
        interviews=[],
        feedback_highlights=[],
    )

    assert diagnosis["bottleneck_type"] in ALLOWED_BOTTLENECKS
    for item in diagnosis["evidence"]:
        assert set(item.keys()) == {"source", "signal", "detail"}
        assert item["source"] in {"profile", "applications", "interviews", "feedback"}
        assert isinstance(item["signal"], str) and item["signal"]
        assert isinstance(item["detail"], str) and item["detail"]
