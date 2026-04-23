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
