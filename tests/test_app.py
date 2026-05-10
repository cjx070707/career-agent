"""Integration tests for app/main.py endpoints.

Chat tests that require a live LLM API have been removed — the new
AutonomousAgentService uses LLM function-calling which is non-deterministic
without mocks. Tool-routing tests belong in unit tests with mocked LLM.

Remaining coverage:
  - /health
  - /chat/sync  (chitchat fast-gate path, memory persistence)
  - /candidates, /jobs, /resumes CRUD
  - /applications, /interviews CRUD
  - /matches/resume (keyword-based, no LLM)
"""
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


def test_chat_sync_fast_gate_returns_chitchat_response(isolated_runtime) -> None:
    """Chitchat 'hello' hits Fast Gate → stage=fast_gate, no tool calls."""
    original_api_key = settings.openai_api_key
    settings.openai_api_key = None

    try:
        response = client.post(
            "/chat/sync",
            json={"user_id": "user-basic", "message": "hello"},
        )
    finally:
        settings.openai_api_key = original_api_key

    assert response.status_code == 200
    body = response.json()
    assert body["answer"]
    assert body["stage"] == "fast_gate"
    assert body["memory_used"] is False
    assert body["sources"] == []
    assert body["tool_used"] is None
    assert body["tool_trace"] == []


def test_chat_sync_memory_used_on_second_turn(isolated_runtime) -> None:
    """After first fast-gate turn saves memory, a subsequent ReAct turn sees it."""
    # First turn via fast gate — saves a turn to memory
    client.post(
        "/chat/sync",
        json={"user_id": "user-memory", "message": "你好"},
    )
    # Second turn with a longer message goes to ReAct path, loads history
    second_response = client.post(
        "/chat/sync",
        json={"user_id": "user-memory", "message": "帮我看看有什么适合我的岗位"},
    )

    assert second_response.status_code == 200
    # memory_used reflects whether history was loaded — True because first turn was saved
    assert second_response.json()["memory_used"] is True


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
