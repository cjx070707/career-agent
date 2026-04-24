from app.mcp_server import list_tools, call_tool
from app.services.candidate_service import CandidateService
from app.services.job_service import JobService
from app.services.resume_service import ResumeService
from app.services.tool_registry import build_default_tool_registry


def test_default_tool_registry_exposes_core_tool_names(isolated_runtime) -> None:
    registry = build_default_tool_registry()

    assert registry.list_tool_names() == [
        "get_candidate_profile",
        "get_resume_by_id",
        "get_applications",
        "get_interview_feedback",
        "get_career_insights",
        "search_jobs",
        "match_resume_to_jobs",
    ]


def test_get_candidate_profile_tool_returns_candidate(isolated_runtime) -> None:
    candidate = CandidateService().create_candidate(name="Tool User")
    registry = build_default_tool_registry()

    result = registry.run(
        "get_candidate_profile",
        {"candidate_id": candidate["id"]},
    )

    assert result["ok"] is True
    assert result["tool_name"] == "get_candidate_profile"
    assert result["data"] == {"id": 1, "name": "Tool User"}
    assert result["error"] is None


def test_search_jobs_and_match_tools_return_structured_results(isolated_runtime) -> None:
    candidate = CandidateService().create_candidate(name="Match Tool User")
    JobService().create_job(title="Python FastAPI Backend Engineer")
    ResumeService().create_resume(
        candidate_id=int(candidate["id"]),
        title="Backend Resume",
        content="Python FastAPI backend SQL APIs",
        version="v1",
    )
    registry = build_default_tool_registry()

    search_result = registry.run(
        "search_jobs",
        {"query": "python fastapi backend"},
    )
    match_result = registry.run(
        "match_resume_to_jobs",
        {"resume_id": 1},
    )

    assert search_result["ok"] is True
    assert search_result["data"]
    assert search_result["data"][0]["title"] == "Python FastAPI Backend Engineer"
    first = search_result["data"][0]
    assert {"type", "title", "snippet", "matched_terms", "reason"} <= set(first.keys())
    assert "location" in first
    assert "work_type" in first
    assert first["type"] == "job_posting"
    assert isinstance(first["snippet"], str)
    assert isinstance(first["matched_terms"], list)
    assert isinstance(first["reason"], str)
    assert set(first["matched_terms"]) >= {"python", "fastapi", "backend"}
    assert len(first["matched_terms"]) <= 3
    assert "命中关键词" in first["reason"]
    assert match_result["ok"] is True
    assert match_result["data"]["resume_id"] == 1
    assert (
        match_result["data"]["matches"][0]["job_title"]
        == "Python FastAPI Backend Engineer"
    )


def test_search_jobs_tool_forwards_structured_filters(isolated_runtime) -> None:
    registry = build_default_tool_registry()

    # Sanity: without filters we may see any location.
    search_result = registry.run(
        "search_jobs",
        {
            "query": "engineer",
            "filters": {"location": "Sydney", "work_type": "intern"},
        },
    )

    assert search_result["ok"] is True
    assert search_result["data"]
    for hit in search_result["data"]:
        location = str(hit.get("location") or "").lower()
        work_type = str(hit.get("work_type") or "").lower()
        assert "sydney" in location, f"expected Sydney, got {location}"
        assert "intern" in work_type, f"expected intern, got {work_type}"


def test_search_jobs_tool_without_filters_is_backward_compatible(isolated_runtime) -> None:
    registry = build_default_tool_registry()

    # Existing call shape (no filters key) must continue to work.
    result = registry.run("search_jobs", {"query": "python fastapi backend"})

    assert result["ok"] is True
    assert result["data"]


def test_mcp_server_lists_and_calls_tools(isolated_runtime) -> None:
    candidate = CandidateService().create_candidate(name="MCP User")

    tools = list_tools()
    result = call_tool(
        "get_candidate_profile",
        {"candidate_id": candidate["id"]},
    )

    assert "get_candidate_profile" in tools
    assert result["ok"] is True
    assert result["tool_name"] == "get_candidate_profile"
    assert result["data"]["name"] == "MCP User"


def test_get_applications_tool_returns_user_history(isolated_runtime) -> None:
    candidate = CandidateService().create_candidate(name="Apply User", user_id="apply-user")
    from app.services.application_service import ApplicationService

    service = ApplicationService()
    service.create_application(
        candidate_id=int(candidate["id"]),
        company="Canva",
        job_title="Data Analyst Intern",
        status="applied",
    )
    service.create_application(
        candidate_id=int(candidate["id"]),
        company="Atlassian",
        job_title="Backend Intern",
        status="interview",
    )
    registry = build_default_tool_registry()

    result = registry.run("get_applications", {"user_id": "apply-user", "limit": 10})

    assert result["ok"] is True
    assert result["data"]
    assert len(result["data"]) == 2
    assert result["data"][0]["company"] == "Atlassian"
    assert result["data"][0]["status"] == "interview"


def test_get_interview_feedback_tool_returns_user_history(isolated_runtime) -> None:
    candidate = CandidateService().create_candidate(name="Interview User", user_id="iv-user")
    from app.services.interview_service import InterviewService

    service = InterviewService()
    service.create_interview(
        candidate_id=int(candidate["id"]),
        company="Canva",
        job_title="Data Analyst Intern",
        interview_round="hr",
        result="pending",
    )
    service.create_interview(
        candidate_id=int(candidate["id"]),
        company="Atlassian",
        job_title="Backend Intern",
        interview_round="tech1",
        result="passed",
    )
    registry = build_default_tool_registry()

    result = registry.run("get_interview_feedback", {"user_id": "iv-user", "limit": 10})

    assert result["ok"] is True
    assert result["data"]
    assert len(result["data"]) == 2
    assert result["data"][0]["company"] == "Atlassian"
    assert result["data"][0]["result"] == "passed"


def test_get_career_insights_tool_returns_aggregated_user_state(
    isolated_runtime,
) -> None:
    candidate = CandidateService().create_candidate(name="Insight User", user_id="tool-insight-user")
    from app.services.application_service import ApplicationService
    from app.services.interview_service import InterviewService

    ApplicationService().create_application(
        candidate_id=int(candidate["id"]),
        company="Canva",
        job_title="Backend Intern",
        status="applied",
    )
    InterviewService().create_interview(
        candidate_id=int(candidate["id"]),
        company="Canva",
        job_title="Backend Intern",
        interview_round="hr",
        result="passed",
        feedback="good communication",
    )
    registry = build_default_tool_registry()

    result = registry.run("get_career_insights", {"user_id": "tool-insight-user", "limit": 10})

    assert result["ok"] is True
    assert result["data"]["application_summary"]["total"] == 1
    assert result["data"]["interview_summary"]["total"] == 1
    assert result["data"]["interview_summary"]["feedback_highlights"] == [
        "good communication"
    ]
