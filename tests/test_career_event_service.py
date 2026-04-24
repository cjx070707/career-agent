from app.services.application_service import ApplicationService
from app.services.candidate_service import CandidateService
from app.services.career_event_service import CareerEventService
from app.services.interview_service import InterviewService
from app.services.retrieval_service import RetrievalService


class ExtractingLLM:
    def __init__(self, events=None, error=None) -> None:
        self.events = events or []
        self.error = error
        self.calls = []

    def extract_career_events(self, **kwargs):
        self.calls.append(kwargs)
        if self.error is not None:
            raise self.error
        return self.events


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


def test_career_event_service_syncs_llm_events_from_message(
    isolated_runtime,
) -> None:
    llm = ExtractingLLM(
        events=[
            {
                "event_type": "interview_feedback",
                "title": "Canva backend interview feedback",
                "summary": "Rejected after Canva backend interview; prepare system design fundamentals.",
                "occurred_at": "2026-04-20",
            }
        ]
    )
    service = CareerEventService(llm_client=llm)

    events = service.sync_from_message(
        "message-event-user",
        "Canva backend 面试挂了，反馈是 system design fundamentals 不够。",
    )

    assert len(events) == 1
    assert events[0]["event_type"] == "interview_feedback"
    assert events[0]["source_type"] == "message"
    assert isinstance(events[0]["source_id"], int)
    assert "system design fundamentals" in events[0]["summary"]
    results = RetrievalService().search("Canva system design fundamentals")
    assert results
    assert results[0].type == "career_event"
    assert "system design fundamentals" in results[0].snippet
    assert llm.calls[0]["user_id"] == "message-event-user"


def test_career_event_service_message_sync_is_idempotent(
    isolated_runtime,
) -> None:
    llm = ExtractingLLM(
        events=[
            {
                "event_type": "application_status",
                "title": "Atlassian application moved to OA",
                "summary": "Atlassian backend graduate application moved to OA.",
            }
        ]
    )
    service = CareerEventService(llm_client=llm)

    first = service.sync_from_message(
        "idempotent-event-user",
        "Atlassian backend graduate application moved to OA.",
    )
    second = service.sync_from_message(
        "idempotent-event-user",
        "Atlassian backend graduate application moved to OA.",
    )

    assert len(first) == 1
    assert len(second) == 1
    assert first[0]["id"] == second[0]["id"]


def test_career_event_service_message_sync_ignores_empty_or_failed_extraction(
    isolated_runtime,
) -> None:
    empty_service = CareerEventService(llm_client=ExtractingLLM(events=[]))
    failed_service = CareerEventService(
        llm_client=ExtractingLLM(error=RuntimeError("model unavailable"))
    )

    assert empty_service.sync_from_message("quiet-user", "今天喝了咖啡。") == []
    assert failed_service.sync_from_message(
        "quiet-user",
        "Canva feedback was system design fundamentals.",
    ) == []
