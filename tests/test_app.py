from pathlib import Path

from fastapi.testclient import TestClient

from app.env import settings
from app.main import app
from app.services.candidate_service import CandidateService
from app.services.job_service import JobService
from app.services.retrieval_service import RetrievalService
from app.services.resume_service import ResumeService
from app.services.application_service import ApplicationService
from app.services.interview_service import InterviewService


client = TestClient(app)


def test_health_endpoint_returns_ok(isolated_runtime) -> None:
    response = client.get("/health")

    assert response.status_code == 200
    assert response.json() == {"status": "ok"}


def test_chat_endpoint_returns_mock_agent_response(isolated_runtime) -> None:
    original_api_key = settings.openai_api_key
    settings.openai_api_key = None

    try:
        response = client.post(
            "/chat",
            json={"user_id": "user-basic", "message": "hello"},
        )
    finally:
        settings.openai_api_key = original_api_key

    assert response.status_code == 200
    body = response.json()
    assert body["answer"] == "Fallback response for 'hello'."
    assert body["memory_used"] is False
    assert body["sources"] == []
    assert body["tool_used"] is None
    assert body["plan"] is not None
    assert body["plan"]["task_type"] == "fallback"
    assert body["plan"]["planner_source"] in {"router", "model", "fallback"}
    assert body["plan"]["steps"] == []
    assert body["tool_trace"] == []
    assert body["llm_trace"] == {
        "planner_source": "fallback",
        "job_search_summary_source": "not_used",
        "generate_source": "fallback",
    }


def test_chat_endpoint_uses_recent_memory_for_same_user(isolated_runtime) -> None:
    first_response = client.post(
        "/chat",
        json={"user_id": "user-memory", "message": "I want backend roles"},
    )
    second_response = client.post(
        "/chat",
        json={"user_id": "user-memory", "message": "What should I focus on next?"},
    )

    assert first_response.status_code == 200
    assert second_response.status_code == 200
    assert second_response.json()["memory_used"] is True


def test_chat_endpoint_returns_job_sources_for_matching_queries(isolated_runtime) -> None:
    response = client.post(
        "/chat",
        json={
            "user_id": "user-jobs",
            "message": "What backend FastAPI Python jobs fit me?",
        },
    )

    assert response.status_code == 200
    body = response.json()
    assert body["sources"]
    assert all(source["type"] == "job_posting" for source in body["sources"])
    titles = [source["title"] for source in body["sources"]]
    assert "Backend Engineer Intern" in titles


def test_candidates_endpoint_reads_from_sqlite(isolated_runtime) -> None:
    CandidateService().create_candidate(name="Jesse")

    response = client.get("/candidates")

    assert response.status_code == 200
    assert response.json() == [{"id": 1, "name": "Jesse"}]


def test_candidates_endpoint_creates_candidate(isolated_runtime) -> None:
    create_response = client.post(
        "/candidates",
        json={"name": "Alice"},
    )
    list_response = client.get("/candidates")

    assert create_response.status_code == 201
    assert create_response.json() == {"id": 1, "name": "Alice"}
    assert list_response.status_code == 200
    assert list_response.json() == [{"id": 1, "name": "Alice"}]


def test_jobs_endpoint_reads_from_sqlite(isolated_runtime) -> None:
    JobService().create_job(title="Backend Engineer Intern")

    response = client.get("/jobs")

    assert response.status_code == 200
    assert response.json() == [{"id": 1, "title": "Backend Engineer Intern"}]


def test_jobs_endpoint_creates_job(isolated_runtime) -> None:
    create_response = client.post(
        "/jobs",
        json={"title": "AI Platform Backend Engineer"},
    )
    list_response = client.get("/jobs")

    assert create_response.status_code == 201
    assert create_response.json() == {"id": 1, "title": "AI Platform Backend Engineer"}
    assert list_response.status_code == 200
    assert list_response.json() == [{"id": 1, "title": "AI Platform Backend Engineer"}]


def test_jobs_endpoint_auto_indexes_new_jobs(isolated_runtime) -> None:
    client.post(
        "/jobs",
        json={"title": "Chroma Search Backend Engineer"},
    )

    retrieval = RetrievalService(
        persist_directory=Path(settings.chroma_persist_directory),
        collection_name=settings.chroma_collection_name,
    )
    results = retrieval.search("chroma search backend")

    assert results
    assert results[0].title == "Chroma Search Backend Engineer"


def test_applications_endpoint_create_list_and_update(isolated_runtime) -> None:
    candidate = CandidateService().create_candidate(name="App User", user_id="app-user")
    create_response = client.post(
        "/applications",
        json={
            "candidate_id": candidate["id"],
            "company": "Canva",
            "job_title": "Data Analyst Intern",
            "status": "applied",
            "note": "resume submitted",
        },
    )
    list_response = client.get("/applications", params={"user_id": "app-user"})
    patch_response = client.patch(
        f"/applications/{create_response.json()['id']}",
        json={"status": "interview", "note": "HR screening passed"},
    )
    list_after_patch = client.get("/applications", params={"user_id": "app-user"})

    assert create_response.status_code == 201
    created = create_response.json()
    assert created["company"] == "Canva"
    assert created["job_title"] == "Data Analyst Intern"
    assert created["status"] == "applied"
    assert list_response.status_code == 200
    assert len(list_response.json()) == 1
    assert list_response.json()[0]["company"] == "Canva"
    assert patch_response.status_code == 200
    assert patch_response.json()["status"] == "interview"
    assert list_after_patch.status_code == 200
    assert list_after_patch.json()[0]["status"] == "interview"


def test_interviews_endpoint_create_list_and_update(isolated_runtime) -> None:
    candidate = CandidateService().create_candidate(name="Iv User", user_id="iv-user")
    create_response = client.post(
        "/interviews",
        json={
            "candidate_id": candidate["id"],
            "company": "Canva",
            "job_title": "Data Analyst Intern",
            "interview_round": "hr",
            "result": "pending",
            "feedback": "good communication",
        },
    )
    list_response = client.get("/interviews", params={"user_id": "iv-user"})
    patch_response = client.patch(
        f"/interviews/{create_response.json()['id']}",
        json={"result": "passed", "feedback": "strong product thinking"},
    )
    list_after_patch = client.get("/interviews", params={"user_id": "iv-user"})

    assert create_response.status_code == 201
    created = create_response.json()
    assert created["company"] == "Canva"
    assert created["interview_round"] == "hr"
    assert created["result"] == "pending"
    assert list_response.status_code == 200
    assert len(list_response.json()) == 1
    assert list_response.json()[0]["company"] == "Canva"
    assert patch_response.status_code == 200
    assert patch_response.json()["result"] == "passed"
    assert list_after_patch.status_code == 200
    assert list_after_patch.json()[0]["result"] == "passed"


def test_resumes_endpoint_reads_from_sqlite(isolated_runtime) -> None:
    candidate = CandidateService().create_candidate(name="Jesse")
    ResumeService().create_resume(
        candidate_id=int(candidate["id"]),
        title="Backend Resume",
        content="FastAPI, Python, projects",
        version="v1",
    )

    response = client.get("/resumes")

    assert response.status_code == 200
    assert response.json() == [
        {
            "id": 1,
            "candidate_id": 1,
            "title": "Backend Resume",
            "content": "FastAPI, Python, projects",
            "version": "v1",
        }
    ]


def test_resumes_endpoint_creates_resume(isolated_runtime) -> None:
    candidate = CandidateService().create_candidate(name="Alice")

    create_response = client.post(
        "/resumes",
        json={
            "candidate_id": candidate["id"],
            "title": "Intern Resume",
            "content": "Python, SQL, backend internships",
            "version": "v1",
        },
    )
    list_response = client.get("/resumes")

    assert create_response.status_code == 201
    assert create_response.json() == {
        "id": 1,
        "candidate_id": 1,
        "title": "Intern Resume",
        "content": "Python, SQL, backend internships",
        "version": "v1",
    }
    assert list_response.status_code == 200
    assert list_response.json() == [
        {
            "id": 1,
            "candidate_id": 1,
            "title": "Intern Resume",
            "content": "Python, SQL, backend internships",
            "version": "v1",
        }
    ]


def test_match_endpoint_returns_structured_job_matches(isolated_runtime) -> None:
    candidate = CandidateService().create_candidate(name="Match User")
    client.post(
        "/jobs",
        json={"title": "Python FastAPI Backend Engineer"},
    )
    client.post(
        "/jobs",
        json={"title": "React Frontend Engineer"},
    )
    resume_response = client.post(
        "/resumes",
        json={
            "candidate_id": candidate["id"],
            "title": "Backend Resume",
            "content": "Python FastAPI backend APIs and SQL projects",
            "version": "v1",
        },
    )

    response = client.post(
        "/matches/resume",
        json={"resume_id": resume_response.json()["id"]},
    )

    assert response.status_code == 200
    body = response.json()
    assert body["resume_id"] == 1
    assert body["matches"]
    assert body["matches"][0]["job_title"] == "Python FastAPI Backend Engineer"
    assert body["matches"][0]["match_score"] >= 60
    assert body["matches"][0]["matched_keywords"]


def test_chat_endpoint_routes_to_candidate_profile_tool(isolated_runtime) -> None:
    CandidateService().create_candidate(name="Jesse")

    response = client.post(
        "/chat",
        json={"user_id": "user-profile", "message": "看看我的资料"},
    )

    assert response.status_code == 200
    body = response.json()
    assert body["tool_used"] == "get_candidate_profile"
    assert body["plan"]["task_type"] == "candidate_profile"
    assert body["plan"]["steps"] == ["get_candidate_profile"]
    assert "资料" in body["plan"]["reason"]
    assert body["plan"]["needs_more_context"] is False
    assert body["tool_trace"] == ["get_candidate_profile"]
    assert "Jesse" in body["answer"]


def test_chat_endpoint_routes_to_search_jobs_tool(isolated_runtime) -> None:
    client.post(
        "/jobs",
        json={"title": "Python FastAPI Backend Engineer"},
    )

    response = client.post(
        "/chat",
        json={"user_id": "user-search", "message": "帮我找一些 Python backend 岗位"},
    )

    assert response.status_code == 200
    body = response.json()
    assert body["tool_used"] == "search_jobs"
    assert body["plan"]["task_type"] == "job_search"
    assert body["plan"]["steps"] == ["search_jobs"]
    assert "搜索" in body["plan"]["reason"]
    assert body["plan"]["needs_more_context"] is False
    assert body["tool_trace"] == ["search_jobs"]
    assert "Python FastAPI Backend Engineer" in body["answer"]
    assert body["sources"]


def test_chat_endpoint_routes_to_match_resume_tool(isolated_runtime) -> None:
    candidate = CandidateService().create_candidate(name="Route User")
    client.post(
        "/jobs",
        json={"title": "Python FastAPI Backend Engineer"},
    )
    client.post(
        "/resumes",
        json={
            "candidate_id": candidate["id"],
            "title": "Backend Resume",
            "content": "Python FastAPI backend APIs and SQL projects",
            "version": "v1",
        },
    )

    response = client.post(
        "/chat",
        json={"user_id": "user-match", "message": "我适合投哪些岗位"},
    )

    assert response.status_code == 200
    body = response.json()
    assert body["tool_used"] == "match_resume_to_jobs"
    assert body["plan"]["task_type"] == "job_match"
    assert body["plan"]["steps"] == ["match_resume_to_jobs"]
    assert "匹配" in body["plan"]["reason"]
    assert body["plan"]["needs_more_context"] is False
    assert body["tool_trace"] == ["match_resume_to_jobs"]
    assert "Python FastAPI Backend Engineer" in body["answer"]


def test_chat_endpoint_returns_multi_step_plan_for_complex_matching(isolated_runtime) -> None:
    candidate = CandidateService().create_candidate(name="Planner User")
    client.post(
        "/jobs",
        json={"title": "Python FastAPI Backend Engineer"},
    )
    client.post(
        "/resumes",
        json={
            "candidate_id": candidate["id"],
            "title": "Planner Resume",
            "content": "Python FastAPI backend APIs and SQL projects",
            "version": "v1",
        },
    )

    response = client.post(
        "/chat",
        json={"user_id": "planner-user", "message": "结合我的情况推荐适合投的岗位"},
    )

    assert response.status_code == 200
    body = response.json()
    assert body["plan"]["task_type"] == "job_match_planning"
    assert body["plan"]["steps"] == [
        "get_candidate_profile",
        "get_resume_by_id",
        "search_jobs",
        "match_resume_to_jobs",
    ]
    assert "推荐" in body["plan"]["reason"]
    assert body["plan"]["needs_more_context"] is False
    assert body["tool_trace"] == body["plan"]["steps"]
    assert "Python FastAPI Backend Engineer" in body["answer"]
    assert "匹配理由" in body["answer"]
    assert "匹配关键词" in body["answer"]
    assert "Resume overlaps" not in body["answer"]


def test_chat_search_uses_long_term_profile_preference(isolated_runtime) -> None:
    client.post(
        "/jobs",
        json={"title": "Python FastAPI Backend Engineer"},
    )
    client.post(
        "/jobs",
        json={"title": "React Frontend Engineer"},
    )

    first_response = client.post(
        "/chat",
        json={"user_id": "profile-user", "message": "我想走 Python FastAPI 后端方向"},
    )
    second_response = client.post(
        "/chat",
        json={"user_id": "profile-user", "message": "帮我找一些岗位"},
    )

    assert first_response.status_code == 200
    assert second_response.status_code == 200
    body = second_response.json()
    assert body["tool_used"] == "search_jobs"
    assert body["plan"]["task_type"] == "job_search"
    assert body["plan"]["steps"] == ["search_jobs"]
    assert body["plan"]["planner_source"] == "router"
    assert "backend" in body["plan"]["reason"].lower()
    assert body["sources"][0]["title"] == "Python FastAPI Backend Engineer"


def test_chat_executor_stops_when_search_finds_no_jobs(isolated_runtime) -> None:
    candidate = CandidateService().create_candidate(name="Stop User")
    client.post(
        "/resumes",
        json={
            "candidate_id": candidate["id"],
            "title": "Unmatched Resume",
            "content": "Cobol mainframe legacy systems",
            "version": "v1",
        },
    )

    response = client.post(
        "/chat",
        json={"user_id": "stop-user", "message": "结合我的情况推荐适合投的岗位"},
    )

    assert response.status_code == 200
    body = response.json()
    assert body["plan"]["steps"] == [
        "get_candidate_profile",
        "get_resume_by_id",
        "search_jobs",
        "match_resume_to_jobs",
    ]
    assert body["tool_trace"] == [
        "get_candidate_profile",
        "get_resume_by_id",
        "search_jobs",
    ]
    assert body["tool_used"] == "search_jobs"
    assert body["answer"] == "暂时没有合适的岗位结果，建议换个关键词再试。"


def test_chat_asks_for_resume_when_matching_without_resume(isolated_runtime) -> None:
    CandidateService().create_candidate(name="Need Resume User")

    response = client.post(
        "/chat",
        json={"user_id": "need-resume-user", "message": "我适合投哪些岗位"},
    )

    assert response.status_code == 200
    body = response.json()
    assert body["tool_used"] is None
    assert body["tool_trace"] == []
    assert body["plan"]["task_type"] == "job_match"
    assert body["plan"]["steps"] == []
    assert body["plan"]["needs_more_context"] is True
    assert body["plan"]["missing_context"] == ["resume"]
    assert body["plan"]["planner_source"] == "router"
    assert "简历" in body["answer"]


def test_chat_does_not_borrow_other_users_resume(isolated_runtime) -> None:
    owner = CandidateService().create_candidate(
        name="Resume Owner",
        user_id="resume-owner",
    )
    ResumeService().create_resume(
        candidate_id=int(owner["id"]),
        title="Owner Resume",
        content="Python backend FastAPI SQL",
        version="v1",
    )
    CandidateService().create_candidate(
        name="Need Resume User",
        user_id="need-resume-user",
    )

    response = client.post(
        "/chat",
        json={"user_id": "need-resume-user", "message": "我适合投哪些岗位"},
    )

    assert response.status_code == 200
    body = response.json()
    assert body["tool_used"] is None
    assert body["tool_trace"] == []
    assert body["plan"]["task_type"] == "job_match"
    assert body["plan"]["steps"] == []
    assert body["plan"]["needs_more_context"] is True
    assert body["plan"]["missing_context"] == ["resume"]
    assert "简历" in body["answer"]


def test_chat_routes_to_application_history_tool(isolated_runtime) -> None:
    candidate = CandidateService().create_candidate(name="History User", user_id="history-user")
    ApplicationService().create_application(
        candidate_id=int(candidate["id"]),
        company="Atlassian",
        job_title="Grad Program",
        status="applied",
    )

    response = client.post(
        "/chat",
        json={"user_id": "history-user", "message": "我最近投了哪些岗位？"},
    )

    assert response.status_code == 200
    body = response.json()
    assert body["tool_used"] == "get_applications"
    assert body["plan"]["task_type"] == "application_history"
    assert body["tool_trace"] == ["get_applications"]
    assert body["sources"]
    assert body["sources"][0]["type"] == "application"
    assert "Atlassian" in body["answer"]


def test_chat_routes_to_interview_history_tool(isolated_runtime) -> None:
    candidate = CandidateService().create_candidate(name="Interview User", user_id="interview-user")
    InterviewService().create_interview(
        candidate_id=int(candidate["id"]),
        company="Canva",
        job_title="Data Analyst Intern",
        interview_round="hr",
        result="pending",
        feedback="good communication",
    )

    response = client.post(
        "/chat",
        json={"user_id": "interview-user", "message": "我最近面试反馈怎么样？"},
    )

    assert response.status_code == 200
    body = response.json()
    assert body["tool_used"] == "get_interview_feedback"
    assert body["plan"]["task_type"] == "interview_history"
    assert body["tool_trace"] == ["get_interview_feedback"]
    assert body["sources"]
    assert body["sources"][0]["type"] == "interview_feedback"
    assert "Canva" in body["answer"]


def test_chat_routes_to_career_insights_tool(isolated_runtime) -> None:
    candidate = CandidateService().create_candidate(name="Career User", user_id="career-user")
    ApplicationService().create_application(
        candidate_id=int(candidate["id"]),
        company="Canva",
        job_title="Backend Intern",
        status="applied",
    )
    InterviewService().create_interview(
        candidate_id=int(candidate["id"]),
        company="Atlassian",
        job_title="Backend Grad",
        interview_round="tech1",
        result="rejected",
        feedback="need stronger system design examples",
    )

    response = client.post(
        "/chat",
        json={
            "user_id": "career-user",
            "message": "结合我的投递和面试反馈，我下一步该准备什么？",
        },
    )

    assert response.status_code == 200
    body = response.json()
    assert body["tool_used"] == "get_career_insights"
    assert body["plan"]["task_type"] == "career_insights"
    assert body["tool_trace"] == ["get_career_insights"]
    assert {source["type"] for source in body["sources"]} >= {
        "application",
        "interview_feedback",
    }
    assert "下一步" in body["answer"]
    assert "system design" in body["answer"]
