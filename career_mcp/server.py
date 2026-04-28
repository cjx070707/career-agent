"""FastMCP entrypoint: modular tools mapped to app ToolRegistry."""

from __future__ import annotations

from typing import Any

from mcp.server.fastmcp import FastMCP

from career_mcp.domains.jobs import register_jobs_tools
from career_mcp.domains.profile import register_profile_tools
from career_mcp.domains.records import register_records_tools


def build_mcp() -> FastMCP[Any]:
    mcp = FastMCP(
        "career-agent",
        instructions=(
            "Career Agent MCP: job search & matching, application/interview records, "
            "candidate profile & career insights. Tools mirror the FastAPI agent "
            "ToolRegistry (same SQLite + Chroma)."
        ),
    )
    register_jobs_tools(mcp)
    register_records_tools(mcp)
    register_profile_tools(mcp)
    return mcp
