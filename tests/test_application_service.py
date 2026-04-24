from app.services.application_service import ApplicationService
from app.services.candidate_service import CandidateService


def test_application_service_creates_and_lists_by_user(isolated_runtime) -> None:
    candidate = CandidateService().create_candidate(name="Svc User", user_id="svc-user")
    service = ApplicationService()

    first = service.create_application(
        candidate_id=int(candidate["id"]),
        company="Canva",
        job_title="Data Analyst Intern",
        status="applied",
    )
    second = service.create_application(
        candidate_id=int(candidate["id"]),
        company="Google",
        job_title="Software Intern",
        status="interview",
    )
    rows = service.list_applications_by_user(user_id="svc-user", limit=10)

    assert first["id"] == 1
    assert second["id"] == 2
    assert len(rows) == 2
    assert rows[0]["company"] == "Google"
    assert rows[0]["status"] == "interview"
    assert rows[1]["company"] == "Canva"


def test_application_service_updates_status_and_note(isolated_runtime) -> None:
    candidate = CandidateService().create_candidate(name="Svc User 2", user_id="svc-user-2")
    service = ApplicationService()
    created = service.create_application(
        candidate_id=int(candidate["id"]),
        company="Atlassian",
        job_title="Grad Program",
        status="applied",
    )

    updated = service.update_application_status(
        application_id=int(created["id"]),
        status="rejected",
        note="final round feedback received",
    )

    assert updated["id"] == created["id"]
    assert updated["status"] == "rejected"
    assert updated["note"] == "final round feedback received"
