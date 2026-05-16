from fastapi import APIRouter, Query
from app.services.goal_service import GoalService

router = APIRouter(tags=["goals"])
_svc = GoalService()


@router.get("/goals")
def list_goals(user_id: str = Query(..., min_length=1)):
    return _svc.get_active_goals(user_id)


@router.post("/goals")
def create_goal(body: dict):
    # body: {user_id, goal_text, deadline?}
    return _svc.set_goal(body["user_id"], body["goal_text"], body.get("deadline"))


@router.patch("/goals/{goal_id}/complete")
def complete_goal(goal_id: int):
    _svc.complete_goal(goal_id)
    return {"ok": True}


@router.patch("/goals/{goal_id}/abandon")
def abandon_goal(goal_id: int):
    _svc.abandon_goal(goal_id)
    return {"ok": True}
