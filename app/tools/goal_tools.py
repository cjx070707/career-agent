from typing import Optional

from pydantic import BaseModel, Field

from app.services.goal_service import GoalService
from app.tools.base import ToolDefinition


# ------------------------------------------------------------------
# Input schemas
# ------------------------------------------------------------------

class GetGoalsInput(BaseModel):
    user_id: str = Field(description="The user whose goals to retrieve")


class SetGoalInput(BaseModel):
    user_id: str = Field(description="The user setting the goal")
    goal_text: str = Field(description="The goal in natural language, e.g. '3个月内拿到fintech后端实习'")
    deadline: Optional[str] = Field(
        default=None,
        description="Optional deadline, e.g. '3 months', '2026-08-01'",
    )


class LogProgressInput(BaseModel):
    goal_id: int = Field(description="ID of the goal to update")
    note: str = Field(description="Progress note, e.g. '本周投了3家公司，收到1个面试邀请'")


class UpdateGoalStatusInput(BaseModel):
    goal_id: int = Field(description="ID of the goal")
    status: str = Field(description="New status: 'completed' or 'abandoned'")


# ------------------------------------------------------------------
# Builder
# ------------------------------------------------------------------

def build_goal_tools() -> list[ToolDefinition]:
    svc = GoalService()

    def _get_goals(payload: GetGoalsInput) -> dict:
        goals = svc.get_active_goals(payload.user_id)
        if not goals:
            return {"goals": [], "summary": "用户当前没有设定求职目标。"}
        return {"goals": goals, "summary": f"用户当前有 {len(goals)} 个活跃目标。"}

    def _set_goal(payload: SetGoalInput) -> dict:
        goal = svc.set_goal(
            user_id=payload.user_id,
            goal_text=payload.goal_text,
            deadline=payload.deadline,
        )
        return {"created": goal, "message": f"目标已记录：{payload.goal_text}"}

    def _log_progress(payload: LogProgressInput) -> dict:
        entry = svc.log_progress(goal_id=payload.goal_id, note=payload.note)
        return {"logged": entry, "message": "进展已记录。"}

    def _update_status(payload: UpdateGoalStatusInput) -> dict:
        if payload.status == "completed":
            svc.complete_goal(payload.goal_id)
        elif payload.status == "abandoned":
            svc.abandon_goal(payload.goal_id)
        else:
            raise ValueError(f"Invalid status: {payload.status}. Use 'completed' or 'abandoned'.")
        return {"goal_id": payload.goal_id, "status": payload.status}

    return [
        ToolDefinition(
            name="get_goals",
            description=(
                "获取用户当前的求职目标和近期进展。"
                "每次对话开始时应调用此工具，了解用户是否有进行中的目标需要跟进。"
            ),
            input_model=GetGoalsInput,
            handler=_get_goals,
            category="goal_tracking",
        ),
        ToolDefinition(
            name="set_goal",
            description=(
                "为用户设定新的求职目标，并可选填截止时间。"
                "当用户表达明确的求职意向时调用，例如'我想三个月内拿到实习'。"
            ),
            input_model=SetGoalInput,
            handler=_set_goal,
            category="goal_tracking",
        ),
        ToolDefinition(
            name="log_progress",
            description=(
                "记录用户在某个目标上的进展，例如本周投了几家、面试结果如何。"
                "当用户汇报进展时调用。"
            ),
            input_model=LogProgressInput,
            handler=_log_progress,
            category="goal_tracking",
        ),
        ToolDefinition(
            name="update_goal_status",
            description=(
                "将目标标记为已完成（completed）或已放弃（abandoned）。"
                "当用户明确表示目标达成或放弃时调用。"
            ),
            input_model=UpdateGoalStatusInput,
            handler=_update_status,
            category="goal_tracking",
        ),
    ]
