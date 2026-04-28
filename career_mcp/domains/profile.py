"""MCP tools: candidate profile, resume, career insights."""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

from career_mcp._registry import run_tool

if TYPE_CHECKING:
    from mcp.server.fastmcp import FastMCP


def register_profile_tools(mcp: "FastMCP[Any]") -> None:
    @mcp.tool(
        name="get_candidate_profile",
        description="[profile] Fetch candidate row by candidate_id.",
        meta={"domain": "profile"},
    )
    def get_candidate_profile(candidate_id: int) -> dict:
        return run_tool("get_candidate_profile", {"candidate_id": candidate_id})

    @mcp.tool(
        name="get_resume_by_id",
        description="[profile] Fetch resume content by resume_id.",
        meta={"domain": "profile"},
    )
    def get_resume_by_id(resume_id: int) -> dict:
        return run_tool("get_resume_by_id", {"resume_id": resume_id})

    @mcp.tool(
        name="get_career_insights",
        description=(
            "[profile] Aggregate applications + interviews for coaching-style insights."
        ),
        meta={"domain": "profile"},
    )
    def get_career_insights(user_id: str, limit: int = 10) -> dict:
        return run_tool(
            "get_career_insights",
            {"user_id": user_id, "limit": limit},
        )
