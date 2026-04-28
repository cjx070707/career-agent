"""MCP tools: job search and resume–job matching."""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

from career_mcp._registry import run_tool

if TYPE_CHECKING:
    from mcp.server.fastmcp import FastMCP


def register_jobs_tools(mcp: "FastMCP[Any]") -> None:
    @mcp.tool(
        name="search_jobs",
        description=(
            "[jobs] Search job postings with natural language. "
            "Optional location/work_type filter strings match metadata substrings."
        ),
        meta={"domain": "jobs"},
    )
    def search_jobs(
        query: str,
        location: str | None = None,
        work_type: str | None = None,
    ) -> dict:
        payload: dict = {"query": query}
        if location or work_type:
            filters: dict[str, str] = {}
            if location:
                filters["location"] = location
            if work_type:
                filters["work_type"] = work_type
            payload["filters"] = filters
        return run_tool("search_jobs", payload)

    @mcp.tool(
        name="match_resume_to_jobs",
        description="[jobs] Match a resume (by id) against indexed jobs; returns scored matches.",
        meta={"domain": "jobs"},
    )
    def match_resume_to_jobs(resume_id: int) -> dict:
        return run_tool("match_resume_to_jobs", {"resume_id": resume_id})
