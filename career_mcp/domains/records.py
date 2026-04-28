"""MCP tools: applications and interview feedback."""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

from career_mcp._registry import run_tool

if TYPE_CHECKING:
    from mcp.server.fastmcp import FastMCP


def register_records_tools(mcp: "FastMCP[Any]") -> None:
    @mcp.tool(
        name="get_applications",
        description="[records] List job applications for a user_id.",
        meta={"domain": "records"},
    )
    def get_applications(user_id: str, limit: int = 10) -> dict:
        return run_tool(
            "get_applications",
            {"user_id": user_id, "limit": limit},
        )

    @mcp.tool(
        name="get_interview_feedback",
        description="[records] List interview records for a user_id.",
        meta={"domain": "records"},
    )
    def get_interview_feedback(user_id: str, limit: int = 10) -> dict:
        return run_tool(
            "get_interview_feedback",
            {"user_id": user_id, "limit": limit},
        )
