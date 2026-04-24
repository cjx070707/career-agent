from app.services.application_service import ApplicationService
from app.services.candidate_service import CandidateService
from app.services.career_event_service import CareerEventService
from app.services.interview_service import InterviewService
from app.services.retrieval_service import RetrievalService


def test_career_event_service_syncs_events_from_applications_and_interviews(
    isolated_runtime,
) -> None:
    candidate = CandidateService().create_candidate(
        name="Event User",
        user_id="event-user",
    )
    application = ApplicationService().create_application(
        candidate_id=int(candidate["id"]),
        company="Canva",
        job_title="Backend Intern",
        status="interview",
        note="HR screen scheduled",
    )
    interview = InterviewService().create_interview(
        candidate_id=int(candidate["id"]),
        company="Canva",
        job_title="Backend Intern",
        interview_round="tech1",
        result="rejected",
        feedback="system design fundamentals",
    )
    service = CareerEventService()

    events = service.sync_from_career_records("event-user")
    repeated = service.sync_from_career_records("event-user")

    assert len(events) == 2
    assert len(repeated) == 2
    assert {event["event_type"] for event in events} == {
        "application_status",
        "interview_feedback",
    }
    application_event = [
        event for event in events if event["source_type"] == "application"
    ][0]
    interview_event = [
        event for event in events if event["source_type"] == "interview"
    ][0]
    assert application_event["source_id"] == application["id"]
    assert "HR screen scheduled" in application_event["summary"]
    assert interview_event["source_id"] == interview["id"]
    assert "system design fundamentals" in interview_event["summary"]


def test_career_event_service_indexes_events_for_retrieval(
    isolated_runtime,
) -> None:
    candidate = CandidateService().create_candidate(
        name="Indexed Event User",
        user_id="indexed-event-user",
    )
    InterviewService().create_interview(
        candidate_id=int(candidate["id"]),
        company="Atlassian",
        job_title="Backend Grad",
        interview_round="tech1",
        result="rejected",
        feedback="system design fundamentals",
    )

    CareerEventService().sync_from_career_records("indexed-event-user")

    results = RetrievalService().search("system design fundamentals")
    assert results
    assert results[0].type == "career_event"
    assert "system design fundamentals" in results[0].snippet
