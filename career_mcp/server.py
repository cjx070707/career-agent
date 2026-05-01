"""FastMCP entrypoint: modular tools mapped to app ToolRegistry."""

from __future__ import annotations

from typing import Any

from mcp.server.fastmcp import FastMCP

from career_mcp.domains.goals import register_goals_tools
from career_mcp.domains.jobs import register_jobs_tools
from career_mcp.domains.profile import register_profile_tools
from career_mcp.domains.records import register_records_tools


def build_mcp() -> FastMCP[Any]:
    mcp = FastMCP(
        "career-agent",
        instructions=(
            "Careerhub Agent MCP server — career coaching tools for USYD students.\n\n"
            "Domains:\n"
            "  [jobs]    job search & resume matching\n"
            "  [records] application & interview history\n"
            "  [profile] resume, gap analysis, candidate profile, career insights\n"
            "  [goals]   job-search goal tracking and progress logging\n\n"
            "All tools share the same SQLite + ChromaDB as the FastAPI agent."
        ),
    )
    register_goals_tools(mcp)
    register_jobs_tools(mcp)
    register_profile_tools(mcp)
    register_records_tools(mcp)
    return mcp
