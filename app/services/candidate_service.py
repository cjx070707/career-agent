from typing import Dict, List, Optional, Union

from app.db.session import get_connection


class CandidateService:
    def has_candidate(self, user_id: Optional[str] = None) -> bool:
        with get_connection() as connection:
            if user_id:
                row = connection.execute(
                    "SELECT 1 FROM candidates WHERE user_id = ? LIMIT 1",
                    (user_id,),
                ).fetchone()
                if row is not None:
                    return True
                total = connection.execute(
                    "SELECT COUNT(*) AS count FROM candidates"
                ).fetchone()
                return int(total["count"]) == 1
            row = connection.execute("SELECT 1 FROM candidates LIMIT 1").fetchone()
            return row is not None

    def create_candidate(
        self,
        name: str,
        user_id: Optional[str] = None,
    ) -> Dict[str, Union[int, str]]:
        with get_connection() as connection:
            cursor = connection.execute(
                "INSERT INTO candidates (name, user_id) VALUES (?, ?)",
                (name, user_id),
            )
            candidate_id = cursor.lastrowid
        return {"id": candidate_id, "name": name}

    def list_candidates(self) -> List[Dict[str, Union[int, str]]]:
        with get_connection() as connection:
            rows = connection.execute(
                "SELECT id, name FROM candidates ORDER BY id ASC"
            ).fetchall()
        return [{"id": row["id"], "name": row["name"]} for row in rows]

    def get_candidate_by_id(self, candidate_id: int) -> Dict[str, Union[int, str]]:
        with get_connection() as connection:
            row = connection.execute(
                "SELECT id, name FROM candidates WHERE id = ?",
                (candidate_id,),
            ).fetchone()
        if row is None:
            raise ValueError(f"Candidate {candidate_id} not found")
        return {"id": row["id"], "name": row["name"]}

    def get_latest_candidate(self, user_id: Optional[str] = None) -> Dict[str, Union[int, str]]:
        with get_connection() as connection:
            if user_id:
                row = connection.execute(
                    """
                    SELECT id, name
                    FROM candidates
                    WHERE user_id = ?
                    ORDER BY id DESC
                    LIMIT 1
                    """,
                    (user_id,),
                ).fetchone()
                if row is None:
                    total = connection.execute(
                        "SELECT COUNT(*) AS count FROM candidates"
                    ).fetchone()
                    if int(total["count"]) == 1:
                        row = connection.execute(
                            "SELECT id, name FROM candidates ORDER BY id DESC LIMIT 1"
                        ).fetchone()
            else:
                row = connection.execute(
                    "SELECT id, name FROM candidates ORDER BY id DESC LIMIT 1"
                ).fetchone()
        if row is None:
            raise ValueError("No candidate available")
        return {"id": row["id"], "name": row["name"]}
