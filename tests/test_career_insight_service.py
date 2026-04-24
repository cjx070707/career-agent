from app.services.application_service import ApplicationService
from app.services.candidate_service import CandidateService
from app.services.career_insight_service import CareerInsightService
from app.services.interview_service import InterviewService
from app.services.profile_service import ProfileService


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
