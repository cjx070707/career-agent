from app.services.candidate_service import CandidateService
from app.services.interview_service import InterviewService


def test_interview_service_creates_and_lists_by_user(isolated_runtime) -> None:
    candidate = CandidateService().create_candidate(name="Interview User", user_id="iv-user")
    service = InterviewService()

    first = service.create_interview(
        candidate_id=int(candidate["id"]),
        company="Canva",
        job_title="Data Analyst Intern",
        interview_round="hr",
        result="pending",
    )
    second = service.create_interview(
        candidate_id=int(candidate["id"]),
        company="Atlassian",
        job_title="Backend Intern",
        interview_round="tech1",
        result="passed",
    )
    rows = service.list_interviews_by_user(user_id="iv-user", limit=10)

    assert first["id"] == 1
    assert second["id"] == 2
    assert len(rows) == 2
    assert rows[0]["company"] == "Atlassian"
    assert rows[0]["interview_round"] == "tech1"
    assert rows[1]["company"] == "Canva"


def test_interview_service_updates_result_and_feedback(isolated_runtime) -> None:
    candidate = CandidateService().create_candidate(name="Interview User 2", user_id="iv-user-2")
    service = InterviewService()
    created = service.create_interview(
        candidate_id=int(candidate["id"]),
        company="Google",
        job_title="Software Intern",
        interview_round="oa",
        result="pending",
    )

    updated = service.update_interview(
        interview_id=int(created["id"]),
        result="rejected",
        feedback="need stronger system design examples",
    )

    assert updated["id"] == created["id"]
    assert updated["result"] == "rejected"
    assert updated["feedback"] == "need stronger system design examples"
