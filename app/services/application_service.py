from typing import Dict, List, Optional, Union

from app.db.session import get_connection


class ApplicationService:
    def create_application(
        self,
        candidate_id: int,
        company: str,
        job_title: str,
        status: str,
        note: Optional[str] = None,
    ) -> Dict[str, Union[int, str]]:
        normalized_note = str(note or "").strip()
        with get_connection() as connection:
            candidate = connection.execute(
                "SELECT id FROM candidates WHERE id = ?",
                (candidate_id,),
            ).fetchone()
            if candidate is None:
                raise ValueError(f"Candidate {candidate_id} not found")
            cursor = connection.execute(
                """
                INSERT INTO applications (candidate_id, company, job_title, status, note)
                VALUES (?, ?, ?, ?, ?)
                """,
                (candidate_id, company, job_title, status, normalized_note),
            )
            application_id = int(cursor.lastrowid)
            row = connection.execute(
                """
                SELECT id, candidate_id, company, job_title, status, note, applied_at, last_updated_at
                FROM applications
                WHERE id = ?
                """,
                (application_id,),
            ).fetchone()
        return self._row_to_dict(row)

    def list_applications_by_user(
        self,
        user_id: str,
        limit: int = 10,
    ) -> List[Dict[str, Union[int, str]]]:
        safe_limit = max(1, min(int(limit), 50))
        with get_connection() as connection:
            rows = connection.execute(
                """
                SELECT a.id, a.candidate_id, a.company, a.job_title, a.status, a.note, a.applied_at, a.last_updated_at
                FROM applications a
                JOIN candidates c ON c.id = a.candidate_id
                WHERE c.user_id = ?
                ORDER BY a.id DESC
                LIMIT ?
                """,
                (user_id, safe_limit),
            ).fetchall()
        return [self._row_to_dict(row) for row in rows]

    def update_application_status(
        self,
        application_id: int,
        status: str,
        note: Optional[str] = None,
    ) -> Dict[str, Union[int, str]]:
        normalized_note = str(note).strip() if note is not None else None
        with get_connection() as connection:
            existing = connection.execute(
                "SELECT id FROM applications WHERE id = ?",
                (application_id,),
            ).fetchone()
            if existing is None:
                raise ValueError(f"Application {application_id} not found")
            if normalized_note is None:
                connection.execute(
                    """
                    UPDATE applications
                    SET status = ?, last_updated_at = CURRENT_TIMESTAMP
                    WHERE id = ?
                    """,
                    (status, application_id),
                )
            else:
                connection.execute(
                    """
                    UPDATE applications
                    SET status = ?, note = ?, last_updated_at = CURRENT_TIMESTAMP
                    WHERE id = ?
                    """,
                    (status, normalized_note, application_id),
                )
            row = connection.execute(
                """
                SELECT id, candidate_id, company, job_title, status, note, applied_at, last_updated_at
                FROM applications
                WHERE id = ?
                """,
                (application_id,),
            ).fetchone()
        return self._row_to_dict(row)

    def _row_to_dict(self, row) -> Dict[str, Union[int, str]]:
        if row is None:
            raise ValueError("Application row not found")
        return {
            "id": int(row["id"]),
            "candidate_id": int(row["candidate_id"]),
            "company": str(row["company"]),
            "job_title": str(row["job_title"]),
            "status": str(row["status"]),
            "note": str(row["note"] or ""),
            "applied_at": str(row["applied_at"] or ""),
            "last_updated_at": str(row["last_updated_at"] or ""),
        }
