from typing import Dict, List, Optional, Union

from app.db.session import get_connection


class InterviewService:
    def create_interview(
        self,
        candidate_id: int,
        company: str,
        job_title: str,
        interview_round: str,
        result: str,
        feedback: Optional[str] = None,
    ) -> Dict[str, Union[int, str]]:
        normalized_feedback = str(feedback or "").strip()
        with get_connection() as connection:
            candidate = connection.execute(
                "SELECT id FROM candidates WHERE id = ?",
                (candidate_id,),
            ).fetchone()
            if candidate is None:
                raise ValueError(f"Candidate {candidate_id} not found")
            cursor = connection.execute(
                """
                INSERT INTO interviews (
                    candidate_id, company, job_title, interview_round, result, feedback
                )
                VALUES (?, ?, ?, ?, ?, ?)
                """,
                (
                    candidate_id,
                    company,
                    job_title,
                    interview_round,
                    result,
                    normalized_feedback,
                ),
            )
            interview_id = int(cursor.lastrowid)
            row = connection.execute(
                """
                SELECT id, candidate_id, company, job_title, interview_round, result,
                       feedback, interviewed_at, last_updated_at
                FROM interviews
                WHERE id = ?
                """,
                (interview_id,),
            ).fetchone()
        return self._row_to_dict(row)

    def list_interviews_by_user(
        self,
        user_id: str,
        limit: int = 10,
    ) -> List[Dict[str, Union[int, str]]]:
        safe_limit = max(1, min(int(limit), 50))
        with get_connection() as connection:
            rows = connection.execute(
                """
                SELECT i.id, i.candidate_id, i.company, i.job_title, i.interview_round,
                       i.result, i.feedback, i.interviewed_at, i.last_updated_at
                FROM interviews i
                JOIN candidates c ON c.id = i.candidate_id
                WHERE c.user_id = ?
                ORDER BY i.id DESC
                LIMIT ?
                """,
                (user_id, safe_limit),
            ).fetchall()
        return [self._row_to_dict(row) for row in rows]

    def update_interview(
        self,
        interview_id: int,
        result: str,
        feedback: Optional[str] = None,
    ) -> Dict[str, Union[int, str]]:
        normalized_feedback = str(feedback).strip() if feedback is not None else None
        with get_connection() as connection:
            existing = connection.execute(
                "SELECT id FROM interviews WHERE id = ?",
                (interview_id,),
            ).fetchone()
            if existing is None:
                raise ValueError(f"Interview {interview_id} not found")
            if normalized_feedback is None:
                connection.execute(
                    """
                    UPDATE interviews
                    SET result = ?, last_updated_at = CURRENT_TIMESTAMP
                    WHERE id = ?
                    """,
                    (result, interview_id),
                )
            else:
                connection.execute(
                    """
                    UPDATE interviews
                    SET result = ?, feedback = ?, last_updated_at = CURRENT_TIMESTAMP
                    WHERE id = ?
                    """,
                    (result, normalized_feedback, interview_id),
                )
            row = connection.execute(
                """
                SELECT id, candidate_id, company, job_title, interview_round, result,
                       feedback, interviewed_at, last_updated_at
                FROM interviews
                WHERE id = ?
                """,
                (interview_id,),
            ).fetchone()
        return self._row_to_dict(row)

    def _row_to_dict(self, row) -> Dict[str, Union[int, str]]:
        if row is None:
            raise ValueError("Interview row not found")
        return {
            "id": int(row["id"]),
            "candidate_id": int(row["candidate_id"]),
            "company": str(row["company"]),
            "job_title": str(row["job_title"]),
            "interview_round": str(row["interview_round"]),
            "result": str(row["result"]),
            "feedback": str(row["feedback"] or ""),
            "interviewed_at": str(row["interviewed_at"] or ""),
            "last_updated_at": str(row["last_updated_at"] or ""),
        }
