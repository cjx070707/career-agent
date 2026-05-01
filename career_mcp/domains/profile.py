"""MCP tools: resume, candidate profile, gap analysis, career insights."""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

from career_mcp._registry import run_tool

if TYPE_CHECKING:
    from mcp.server.fastmcp import FastMCP


def register_profile_tools(mcp: "FastMCP[Any]") -> None:
    @mcp.tool(
        name="get_resume",
        description=(
            "[profile] Fetch the latest resume for a user_id. "
            "Use this before analyze_gap or any resume-based analysis."
        ),
        meta={"domain": "profile"},
    )
    def get_resume(user_id: str) -> dict:
        return run_tool("get_resume", {"user_id": user_id})

    @mcp.tool(
        name="analyze_gap",
        description=(
            "[profile] Compare a user's resume against a job description. "
            "Returns match score (0-100), matched skills, missing skills, "
            "and prioritised action suggestions."
        ),
        meta={"domain": "profile"},
    )
    def analyze_gap(user_id: str, jd_text: str) -> dict:
        return run_tool("analyze_gap", {"user_id": user_id, "jd_text": jd_text})

    @mcp.tool(
        name="get_candidate_profile",
        description="[profile] Fetch candidate row by candidate_id.",
        meta={"domain": "profile"},
    )
    def get_candidate_profile(candidate_id: int) -> dict:
        return run_tool("get_candidate_profile", {"candidate_id": candidate_id})

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
