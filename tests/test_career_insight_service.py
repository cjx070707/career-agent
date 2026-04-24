from app.services.application_service import ApplicationService
from app.services.candidate_service import CandidateService
from app.services.career_insight_service import CareerInsightService
from app.services.interview_service import InterviewService
from app.services.profile_service import ProfileService
from app.services.retrieval_service import RetrievalService
from app.db.session import get_connection


def test_career_insight_service_aggregates_profile_applications_and_interviews(
    isolated_runtime,
) -> None:
    candidate = CandidateService().create_candidate(
        name="Insight User",
        user_id="insight-user",
    )
    ProfileService().update_from_message(
        user_id="insight-user",
        message="我想找 backend Python FastAPI 方向",
    )
    applications = ApplicationService()
    applications.create_application(
        candidate_id=int(candidate["id"]),
        company="Canva",
        job_title="Backend Intern",
        status="applied",
    )
    applications.create_application(
        candidate_id=int(candidate["id"]),
        company="Atlassian",
        job_title="Backend Grad",
        status="interview",
    )
    interviews = InterviewService()
    interviews.create_interview(
        candidate_id=int(candidate["id"]),
        company="Atlassian",
        job_title="Backend Grad",
        interview_round="tech1",
        result="rejected",
        feedback="need stronger system design examples",
    )

    insights = CareerInsightService().get_career_insights(
        user_id="insight-user",
        limit=10,
    )

    assert insights["profile"]["target_role_preference"] == "backend"
    assert set(insights["profile"]["skill_keywords"]) >= {"python", "fastapi"}
    assert insights["application_summary"]["total"] == 2
    assert insights["application_summary"]["status_counts"] == {
        "applied": 1,
        "interview": 1,
    }
    assert insights["interview_summary"]["total"] == 1
    assert insights["interview_summary"]["result_counts"] == {"rejected": 1}
    assert insights["interview_summary"]["feedback_highlights"] == [
        "need stronger system design examples"
    ]
    assert any("system design" in item for item in insights["suggestions"])


def test_career_insight_service_returns_sparse_data_suggestions(
    isolated_runtime,
) -> None:
    insights = CareerInsightService().get_career_insights(
        user_id="new-user",
        limit=10,
    )

    assert insights["profile"]["user_id"] == "new-user"
    assert insights["application_summary"]["total"] == 0
    assert insights["interview_summary"]["total"] == 0
    assert "先补充投递记录和面试反馈" in " ".join(insights["suggestions"])


def test_career_insight_service_refreshes_persisted_profile_signals(
    isolated_runtime,
) -> None:
    candidate = CandidateService().create_candidate(
        name="Persisted Insight User",
        user_id="persisted-insight-user",
    )
    InterviewService().create_interview(
        candidate_id=int(candidate["id"]),
        company="Canva",
        job_title="Backend Intern",
        interview_round="tech1",
        result="rejected",
        feedback="system design fundamentals",
    )

    CareerInsightService().get_career_insights(
        user_id="persisted-insight-user",
        limit=10,
    )

    profile = ProfileService().get_profile("persisted-insight-user")
    assert profile["interview_weaknesses"] == "system design fundamentals"
    assert profile["next_focus_areas"] == "system design fundamentals"


def test_career_insight_service_indexes_refreshed_profile_for_retrieval(
    isolated_runtime,
) -> None:
    candidate = CandidateService().create_candidate(
        name="Indexed Insight User",
        user_id="indexed-insight-user",
    )
    InterviewService().create_interview(
        candidate_id=int(candidate["id"]),
        company="Canva",
        job_title="Backend Intern",
        interview_round="tech1",
        result="rejected",
        feedback="system design fundamentals",
    )

    CareerInsightService().get_career_insights(
        user_id="indexed-insight-user",
        limit=10,
    )

    results = RetrievalService().search("system design fundamentals")
    assert results
    profile_sources = [result for result in results if result.type == "career_profile"]
    assert profile_sources
    assert "system design fundamentals" in profile_sources[0].snippet


def test_career_insight_service_syncs_career_events(
    isolated_runtime,
) -> None:
    candidate = CandidateService().create_candidate(
        name="Career Event Insight User",
        user_id="career-event-insight-user",
    )
    InterviewService().create_interview(
        candidate_id=int(candidate["id"]),
        company="Atlassian",
        job_title="Backend Grad",
        interview_round="tech1",
        result="rejected",
        feedback="system design fundamentals",
    )

    CareerInsightService().get_career_insights(
        user_id="career-event-insight-user",
        limit=10,
    )

    with get_connection() as connection:
        rows = connection.execute(
            """
            SELECT event_type, summary
            FROM career_events
            WHERE user_id = ?
            """,
            ("career-event-insight-user",),
        ).fetchall()
    assert len(rows) == 1
    assert rows[0]["event_type"] == "interview_feedback"
    assert "system design fundamentals" in rows[0]["summary"]

    results = RetrievalService().search("system design fundamentals")
    assert results[0].type == "career_event"
