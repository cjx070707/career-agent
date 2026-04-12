from typing import Dict, List, Union

from app.db.session import get_connection


class CandidateService:
    def has_candidate(self) -> bool:
        with get_connection() as connection:
            row = connection.execute(
                "SELECT 1 FROM candidates LIMIT 1"
            ).fetchone()
        return row is not None

    def create_candidate(self, name: str) -> Dict[str, Union[int, str]]:
        with get_connection() as connection:
            cursor = connection.execute(
                "INSERT INTO candidates (name) VALUES (?)",
                (name,),
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

    def get_latest_candidate(self) -> Dict[str, Union[int, str]]:
        with get_connection() as connection:
            row = connection.execute(
                "SELECT id, name FROM candidates ORDER BY id DESC LIMIT 1"
            ).fetchone()
        if row is None:
            raise ValueError("No candidate available")
        return {"id": row["id"], "name": row["name"]}
