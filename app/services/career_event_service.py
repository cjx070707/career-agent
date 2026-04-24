from typing import Dict, List, Union

from app.db.session import get_connection
from app.services.retrieval_service import RetrievalService


class CareerEventService:
    def __init__(self, retrieval_service: RetrievalService = None) -> None:
        self.retrieval_service = retrieval_service or RetrievalService()

    def sync_from_career_records(
        self,
        user_id: str,
    ) -> List[Dict[str, Union[int, str]]]:
        events = self._application_events(user_id) + self._interview_events(user_id)
        synced: List[Dict[str, Union[int, str]]] = []
        for event in events:
            saved = self._upsert_event(event)
            self.retrieval_service.upsert_career_event(saved)
            synced.append(saved)
        return synced

    def _application_events(self, user_id: str) -> List[Dict[str, Union[int, str]]]:
        with get_connection() as connection:
            rows = connection.execute(
                """
                SELECT a.id, a.company, a.job_title, a.status, a.note, a.applied_at
                FROM applications a
                JOIN candidates c ON c.id = a.candidate_id
                WHERE c.user_id = ?
                ORDER BY a.id DESC
                """,
                (user_id,),
            ).fetchall()
        events: List[Dict[str, Union[int, str]]] = []
        for row in rows:
            note = str(row["note"] or "").strip()
            summary = (
                f"Application status: {row['status']} for {row['company']} "
                f"{row['job_title']}."
            )
            if note:
                summary += f" Note: {note}."
            events.append(
                {
                    "user_id": user_id,
                    "event_type": "application_status",
                    "title": f"{row['company']} - {row['job_title']} ({row['status']})",
                    "summary": summary,
                    "source_type": "application",
                    "source_id": int(row["id"]),
                    "occurred_at": str(row["applied_at"] or ""),
                }
            )
        return events

    def _interview_events(self, user_id: str) -> List[Dict[str, Union[int, str]]]:
        with get_connection() as connection:
            rows = connection.execute(
                """
                SELECT i.id, i.company, i.job_title, i.interview_round, i.result,
                       i.feedback, i.interviewed_at
                FROM interviews i
                JOIN candidates c ON c.id = i.candidate_id
                WHERE c.user_id = ?
                ORDER BY i.id DESC
                """,
                (user_id,),
            ).fetchall()
        events: List[Dict[str, Union[int, str]]] = []
        for row in rows:
            feedback = str(row["feedback"] or "").strip()
            summary = (
                f"Interview {row['interview_round']} result: {row['result']} "
                f"for {row['company']} {row['job_title']}."
            )
            if feedback:
                summary += f" Feedback: {feedback}."
            events.append(
                {
                    "user_id": user_id,
                    "event_type": "interview_feedback",
                    "title": (
                        f"{row['company']} - {row['job_title']} "
                        f"({row['interview_round']}/{row['result']})"
                    ),
                    "summary": summary,
                    "source_type": "interview",
                    "source_id": int(row["id"]),
                    "occurred_at": str(row["interviewed_at"] or ""),
                }
            )
        return events

    def _upsert_event(self, event: Dict[str, Union[int, str]]) -> Dict[str, Union[int, str]]:
        with get_connection() as connection:
            existing = connection.execute(
                """
                SELECT id
                FROM career_events
                WHERE user_id = ? AND event_type = ? AND source_type = ? AND source_id = ?
                """,
                (
                    event["user_id"],
                    event["event_type"],
                    event["source_type"],
                    event["source_id"],
                ),
            ).fetchone()
            if existing is None:
                cursor = connection.execute(
                    """
                    INSERT INTO career_events (
                        user_id, event_type, title, summary, source_type, source_id,
                        occurred_at
                    )
                    VALUES (?, ?, ?, ?, ?, ?, ?)
                    """,
                    (
                        event["user_id"],
                        event["event_type"],
                        event["title"],
                        event["summary"],
                        event["source_type"],
                        event["source_id"],
                        event["occurred_at"],
                    ),
                )
                event_id = int(cursor.lastrowid)
            else:
                event_id = int(existing["id"])
                connection.execute(
                    """
                    UPDATE career_events
                    SET title = ?, summary = ?, occurred_at = ?
                    WHERE id = ?
                    """,
                    (
                        event["title"],
                        event["summary"],
                        event["occurred_at"],
                        event_id,
                    ),
                )
            row = connection.execute(
                """
                SELECT id, user_id, event_type, title, summary, source_type, source_id,
                       occurred_at, created_at
                FROM career_events
                WHERE id = ?
                """,
                (event_id,),
            ).fetchone()
        return self._row_to_dict(row)

    def _row_to_dict(self, row) -> Dict[str, Union[int, str]]:
        return {
            "id": int(row["id"]),
            "user_id": str(row["user_id"]),
            "event_type": str(row["event_type"]),
            "title": str(row["title"]),
            "summary": str(row["summary"]),
            "source_type": str(row["source_type"]),
            "source_id": int(row["source_id"]),
            "occurred_at": str(row["occurred_at"] or ""),
            "created_at": str(row["created_at"] or ""),
        }
