"""MCP tools: goal tracking and progress logging."""

from __future__ import annotations

from typing import TYPE_CHECKING, Any, Optional

from career_mcp._registry import run_tool

if TYPE_CHECKING:
    from mcp.server.fastmcp import FastMCP


def register_goals_tools(mcp: "FastMCP[Any]") -> None:
    @mcp.tool(
        name="get_goals",
        description=(
            "[goals] Get a user's active job-search goals and recent progress notes."
        ),
        meta={"domain": "goals"},
    )
    def get_goals(user_id: str) -> dict:
        return run_tool("get_goals", {"user_id": user_id})

    @mcp.tool(
        name="set_goal",
        description=(
            "[goals] Create a new job-search goal for a user, with an optional deadline."
        ),
        meta={"domain": "goals"},
    )
    def set_goal(
        user_id: str,
        goal_text: str,
        deadline: Optional[str] = None,
    ) -> dict:
        payload: dict = {"user_id": user_id, "goal_text": goal_text}
        if deadline:
            payload["deadline"] = deadline
        return run_tool("set_goal", payload)

    @mcp.tool(
        name="log_progress",
        description=(
            "[goals] Append a progress note to an existing goal (by goal_id)."
        ),
        meta={"domain": "goals"},
    )
    def log_progress(goal_id: int, note: str) -> dict:
        return run_tool("log_progress", {"goal_id": goal_id, "note": note})

    @mcp.tool(
        name="update_goal_status",
        description=(
            "[goals] Mark a goal as 'completed' or 'abandoned'."
        ),
        meta={"domain": "goals"},
    )
    def update_goal_status(goal_id: int, status: str) -> dict:
        return run_tool("update_goal_status", {"goal_id": goal_id, "status": status})
