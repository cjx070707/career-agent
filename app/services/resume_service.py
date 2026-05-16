import json
from typing import Any, Dict, List, Optional, Union

from app.db.session import get_connection


def _row_to_dict(row) -> Dict[str, Any]:
    """Convert a DB row to dict, merging parsed_json into structured fields."""
    result: Dict[str, Any] = {
        "id": row["id"],
        "candidate_id": row["candidate_id"],
        "title": row["title"],
        "content": row["content"],
        "version": row["version"],
    }
    raw = row["parsed_json"] if "parsed_json" in row.keys() else None
    if raw:
        try:
            result["parsed"] = json.loads(raw)
        except Exception:
            pass
    return result


class ResumeService:
    def has_resume(self, user_id: Optional[str] = None) -> bool:
        with get_connection() as connection:
            if user_id:
                row = connection.execute(
                    """
                    SELECT 1
                    FROM resumes
                    INNER JOIN candidates ON candidates.id = resumes.candidate_id
                    WHERE candidates.user_id = ?
                    LIMIT 1
                    """,
                    (user_id,),
                ).fetchone()
                if row is not None:
                    return True
                total = connection.execute(
                    "SELECT COUNT(*) AS count FROM resumes"
                ).fetchone()
                candidate_total = connection.execute(
                    "SELECT COUNT(*) AS count FROM candidates"
                ).fetchone()
                return int(total["count"]) == 1 and int(candidate_total["count"]) == 1
            row = connection.execute(
                "SELECT 1 FROM resumes LIMIT 1"
            ).fetchone()
            return row is not None

    def create_resume(
        self,
        candidate_id: int,
        title: str,
        content: str,
        version: str,
        parsed_json: Optional[str] = None,
    ) -> Dict[str, Any]:
        with get_connection() as connection:
            cursor = connection.execute(
                """
                INSERT INTO resumes (candidate_id, title, content, version, parsed_json)
                VALUES (?, ?, ?, ?, ?)
                """,
                (candidate_id, title, content, version, parsed_json),
            )
            resume_id = cursor.lastrowid
        result: Dict[str, Any] = {
            "id": resume_id,
            "candidate_id": candidate_id,
            "title": title,
            "content": content,
            "version": version,
        }
        if parsed_json:
            try:
                result["parsed"] = json.loads(parsed_json)
            except Exception:
                pass
        return result

    def list_resumes(self) -> List[Dict[str, Any]]:
        with get_connection() as connection:
            rows = connection.execute(
                """
                SELECT id, candidate_id, title, content, version, parsed_json
                FROM resumes
                ORDER BY id ASC
                """
            ).fetchall()
        return [_row_to_dict(row) for row in rows]

    def get_resume_by_id(self, resume_id: int) -> Dict[str, Any]:
        with get_connection() as connection:
            row = connection.execute(
                """
                SELECT id, candidate_id, title, content, version, parsed_json
                FROM resumes
                WHERE id = ?
                """,
                (resume_id,),
            ).fetchone()
        if row is None:
            raise ValueError(f"Resume {resume_id} not found")
        return _row_to_dict(row)

    def get_latest_resume(self, user_id: Optional[str] = None) -> Dict[str, Any]:
        with get_connection() as connection:
            if user_id:
                row = connection.execute(
                    """
                    SELECT resumes.id, resumes.candidate_id, resumes.title,
                           resumes.content, resumes.version, resumes.parsed_json
                    FROM resumes
                    INNER JOIN candidates ON candidates.id = resumes.candidate_id
                    WHERE candidates.user_id = ?
                    ORDER BY resumes.id DESC
                    LIMIT 1
                    """,
                    (user_id,),
                ).fetchone()
                if row is None:
                    total = connection.execute(
                        "SELECT COUNT(*) AS count FROM resumes"
                    ).fetchone()
                    candidate_total = connection.execute(
                        "SELECT COUNT(*) AS count FROM candidates"
                    ).fetchone()
                    if int(total["count"]) == 1 and int(candidate_total["count"]) == 1:
                        row = connection.execute(
                            """
                            SELECT id, candidate_id, title, content, version, parsed_json
                            FROM resumes
                            ORDER BY id DESC
                            LIMIT 1
                            """
                        ).fetchone()
            else:
                row = connection.execute(
                    """
                    SELECT id, candidate_id, title, content, version, parsed_json
                    FROM resumes
                    ORDER BY id DESC
                    LIMIT 1
                    """
                ).fetchone()
        if row is None:
            raise ValueError("No resume available")
        return _row_to_dict(row)
