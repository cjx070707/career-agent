"""MCP server smoke tests (skipped without Python>=3.10 + mcp)."""

from __future__ import annotations

import pytest

mcp_mod = pytest.importorskip("mcp.server.fastmcp", reason="mcp SDK not installed")


def test_build_mcp_registers_all_domain_tools() -> None:
    from career_mcp.server import build_mcp

    app = build_mcp()
    names = [t.name for t in app._tool_manager.list_tools()]
    assert set(names) == {
        "search_jobs",
        "match_resume_to_jobs",
        "get_applications",
        "get_interview_feedback",
        "get_candidate_profile",
        "get_resume_by_id",
        "get_career_insights",
    }
