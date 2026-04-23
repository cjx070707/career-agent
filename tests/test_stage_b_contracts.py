from fastapi.testclient import TestClient

from app.main import app
from app.services.candidate_service import CandidateService
from app.services.job_service import JobService
from app.services.resume_service import ResumeService


client = TestClient(app)


def test_chat_search_contract_is_stable(isolated_runtime) -> None:
    client.post("/jobs", json={"title": "Python FastAPI Backend Engineer"})

    response = client.post(
        "/chat",
        json={"user_id": "stage-b-search", "message": "帮我找一些 Python backend 岗位"},
    )

    assert response.status_code == 200
    body = response.json()
    assert set(body.keys()) == {
        "answer",
        "memory_used",
        "sources",
        "tool_used",
        "plan",
        "tool_trace",
        "llm_trace",
    }
    assert body["tool_used"] == "search_jobs"
    assert body["plan"]["task_type"] == "job_search"
    assert body["plan"]["planner_source"] == "router"
    assert body["plan"]["steps"] == ["search_jobs"]
    assert body["tool_trace"] == ["search_jobs"]
    assert body["llm_trace"]["planner_source"] == "router"
    assert body["llm_trace"]["generate_source"] == "not_used"
    assert body["sources"]
    first_source = body["sources"][0]
    assert {"type", "title", "snippet"} <= set(first_source.keys())
    assert "location" in first_source
    assert "work_type" in first_source
    assert first_source["type"] == "job_posting"
    assert isinstance(first_source["title"], str) and first_source["title"]
    assert "命中关键词" in first_source["snippet"]
    titles = [source["title"] for source in body["sources"]]
    assert "Python FastAPI Backend Engineer" in titles


def test_chat_recommendation_contract_is_stable(isolated_runtime) -> None:
    candidate = CandidateService().create_candidate(name="Stage B User")
    client.post("/jobs", json={"title": "Python FastAPI Backend Engineer"})
    client.post(
        "/resumes",
        json={
            "candidate_id": candidate["id"],
            "title": "Backend Resume",
            "content": "Python FastAPI backend SQL APIs",
            "version": "v1",
        },
    )

    response = client.post(
        "/chat",
        json={"user_id": "stage-b-user", "message": "结合我的情况推荐适合投的岗位"},
    )

    assert response.status_code == 200
    body = response.json()
    assert body["tool_used"] == "match_resume_to_jobs"
    assert body["plan"]["task_type"] == "job_match_planning"
    assert body["plan"]["planner_source"] == "router"
    assert body["tool_trace"] == [
        "get_candidate_profile",
        "get_resume_by_id",
        "search_jobs",
        "match_resume_to_jobs",
    ]
    assert body["llm_trace"]["planner_source"] == "router"
    assert body["llm_trace"]["job_search_summary_source"] == "not_used"
    assert body["llm_trace"]["generate_source"] == "not_used"
    assert "基于你的简历，优先推荐" in body["answer"]
    assert "匹配理由：" in body["answer"]
    assert "匹配关键词" in body["answer"]
    assert body["sources"]
    assert body["sources"][0]["type"] == "job_posting"
    assert body["sources"][0]["title"] == "Python FastAPI Backend Engineer"


def test_chat_missing_context_contract_is_stable(isolated_runtime) -> None:
    CandidateService().create_candidate(name="Need Resume User", user_id="need-resume")

    response = client.post(
        "/chat",
        json={"user_id": "need-resume", "message": "我适合投哪些岗位"},
    )

    assert response.status_code == 200
    body = response.json()
    assert body["tool_used"] is None
    assert body["sources"] == []
    assert body["tool_trace"] == []
    assert body["plan"]["task_type"] == "job_match"
    assert body["plan"]["steps"] == []
    assert body["plan"]["needs_more_context"] is True
    assert body["plan"]["missing_context"] == ["resume"]
    assert body["plan"]["planner_source"] == "router"
    assert body["answer"] == body["plan"]["follow_up_question"]
    assert "简历" in body["answer"]


def test_search_jobs_tool_contract_is_stable(isolated_runtime) -> None:
    JobService().create_job(title="Python FastAPI Backend Engineer")

    response = client.post(
        "/chat",
        json={"user_id": "stage-b-search-tool", "message": "帮我找一些 Python backend 岗位"},
    )

    assert response.status_code == 200
    body = response.json()
    first_source = body["sources"][0]

    assert isinstance(first_source["title"], str) and first_source["title"]
    assert isinstance(first_source["snippet"], str)
    assert first_source["snippet"]
    assert "命中关键词" in first_source["snippet"]
    titles = [source["title"] for source in body["sources"]]
    assert "Python FastAPI Backend Engineer" in titles


def test_chat_search_contract_supports_chinese_query(isolated_runtime) -> None:
    client.post("/jobs", json={"title": "Backend Engineer Intern"})

    response = client.post(
        "/chat",
        json={"user_id": "stage-b-chinese", "message": "帮我找一些后端实习岗位"},
    )

    assert response.status_code == 200
    body = response.json()
    assert body["tool_used"] == "search_jobs"
    assert body["plan"]["planner_source"] == "router"
    assert body["sources"]
    assert body["sources"][0]["type"] == "job_posting"
    assert isinstance(body["sources"][0]["snippet"], str)
    assert body["sources"][0]["snippet"]


def test_chat_search_contract_supports_low_lexical_overlap_query(
    isolated_runtime,
) -> None:
    client.post("/jobs", json={"title": "AI Platform Backend Engineer"})

    response = client.post(
        "/chat",
        json={"user_id": "stage-b-low-lex", "message": "帮我找一些 kubernetes helm sre 岗位"},
    )

    assert response.status_code == 200
    body = response.json()
    assert body["tool_used"] == "search_jobs"
    assert body["plan"]["planner_source"] == "router"
    assert body["sources"]
    assert body["sources"][0]["type"] == "job_posting"
    assert isinstance(body["sources"][0]["snippet"], str)
    assert body["sources"][0]["snippet"]


def test_chat_recommendation_answer_does_not_repeat_job_titles(isolated_runtime) -> None:
    candidate = CandidateService().create_candidate(name="Dedupe User")
    client.post("/jobs", json={"title": "Python FastAPI Backend Engineer"})
    client.post("/jobs", json={"title": "Python FastAPI Backend Engineer"})
    client.post("/jobs", json={"title": "Python FastAPI Backend Engineer"})
    client.post(
        "/resumes",
        json={
            "candidate_id": candidate["id"],
            "title": "Backend Resume",
            "content": "Python FastAPI backend SQL APIs",
            "version": "v1",
        },
    )

    response = client.post(
        "/chat",
        json={"user_id": "dedupe-user", "message": "结合我的情况推荐适合投的岗位"},
    )

    assert response.status_code == 200
    body = response.json()
    answer = body["answer"]
    assert answer.count("Python FastAPI Backend Engineer") <= 1
    assert "Python FastAPI Backend Engineer、Python FastAPI Backend Engineer" not in answer


def test_demo_page_is_served_by_fastapi(isolated_runtime) -> None:
    response = client.get("/demo/")

    assert response.status_code == 200
    assert "Career Agent Demo" in response.text
    assert "/chat" in response.text
