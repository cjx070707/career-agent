import json
from typing import Optional

from app.db.session import get_connection


class GoalService:
    """Persistent goal tracking across conversations."""

    # ------------------------------------------------------------------
    # Queries
    # ------------------------------------------------------------------

    def get_active_goals(self, user_id: str) -> list[dict]:
        """Return all active goals for a user, each with recent progress notes."""
        with get_connection() as conn:
            rows = conn.execute(
                """
                SELECT id, goal_text, deadline, status, plan_json, created_at, updated_at
                FROM goals
                WHERE user_id = ? AND status = 'active'
                ORDER BY created_at ASC
                """,
                (user_id,),
            ).fetchall()

            goals = []
            for row in rows:
                progress_rows = conn.execute(
                    """
                    SELECT note, created_at
                    FROM goal_progress
                    WHERE goal_id = ?
                    ORDER BY created_at DESC
                    LIMIT 5
                    """,
                    (row["id"],),
                ).fetchall()
                goals.append({
                    "id": row["id"],
                    "goal_text": row["goal_text"],
                    "deadline": row["deadline"],
                    "status": row["status"],
                    "plan": json.loads(row["plan_json"] or "{}"),
                    "created_at": row["created_at"],
                    "updated_at": row["updated_at"],
                    "recent_progress": [
                        {"note": p["note"], "created_at": p["created_at"]}
                        for p in progress_rows
                    ],
                })
            return goals

    def get_all_goals(self, user_id: str) -> list[dict]:
        """Return all goals (active + completed + abandoned)."""
        with get_connection() as conn:
            rows = conn.execute(
                """
                SELECT id, goal_text, deadline, status, plan_json, created_at, updated_at
                FROM goals
                WHERE user_id = ?
                ORDER BY created_at DESC
                """,
                (user_id,),
            ).fetchall()
            return [
                {
                    "id": row["id"],
                    "goal_text": row["goal_text"],
                    "deadline": row["deadline"],
                    "status": row["status"],
                    "plan": json.loads(row["plan_json"] or "{}"),
                    "created_at": row["created_at"],
                    "updated_at": row["updated_at"],
                }
                for row in rows
            ]

    # ------------------------------------------------------------------
    # Mutations
    # ------------------------------------------------------------------

    def set_goal(
        self,
        user_id: str,
        goal_text: str,
        deadline: Optional[str] = None,
    ) -> dict:
        """Create a new active goal. Previous active goals remain unchanged."""
        with get_connection() as conn:
            cursor = conn.execute(
                """
                INSERT INTO goals (user_id, goal_text, deadline, status, plan_json)
                VALUES (?, ?, ?, 'active', '{}')
                """,
                (user_id, goal_text, deadline),
            )
            goal_id = cursor.lastrowid
        return {"id": goal_id, "goal_text": goal_text, "deadline": deadline, "status": "active"}

    def update_plan(self, goal_id: int, plan: dict) -> None:
        """Persist a structured plan (dict) for a goal."""
        with get_connection() as conn:
            conn.execute(
                """
                UPDATE goals
                SET plan_json = ?, updated_at = CURRENT_TIMESTAMP
                WHERE id = ?
                """,
                (json.dumps(plan, ensure_ascii=False), goal_id),
            )

    def log_progress(self, goal_id: int, note: str) -> dict:
        """Append a progress note to a goal."""
        with get_connection() as conn:
            # Verify goal exists
            row = conn.execute("SELECT id FROM goals WHERE id = ?", (goal_id,)).fetchone()
            if row is None:
                raise ValueError(f"Goal {goal_id} not found")
            cursor = conn.execute(
                "INSERT INTO goal_progress (goal_id, note) VALUES (?, ?)",
                (goal_id, note),
            )
            progress_id = cursor.lastrowid
            # Touch updated_at on the parent goal
            conn.execute(
                "UPDATE goals SET updated_at = CURRENT_TIMESTAMP WHERE id = ?",
                (goal_id,),
            )
        return {"id": progress_id, "goal_id": goal_id, "note": note}

    def complete_goal(self, goal_id: int) -> None:
        self._set_status(goal_id, "completed")

    def abandon_goal(self, goal_id: int) -> None:
        self._set_status(goal_id, "abandoned")

    def _set_status(self, goal_id: int, status: str) -> None:
        with get_connection() as conn:
            conn.execute(
                "UPDATE goals SET status = ?, updated_at = CURRENT_TIMESTAMP WHERE id = ?",
                (status, goal_id),
            )
