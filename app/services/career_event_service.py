import hashlib
from typing import Any, Dict, List, Optional, Union

from app.db.session import get_connection
from app.llm.client import LLMClient
from app.services.retrieval_service import RetrievalService


class CareerEventService:
    def __init__(
        self,
        retrieval_service: RetrievalService = None,
        llm_client: Optional[LLMClient] = None,
    ) -> None:
        self.retrieval_service = retrieval_service or RetrievalService()
        self.llm_client = llm_client or LLMClient()

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

    def sync_from_message(
        self,
        user_id: str,
        message: str,
    ) -> List[Dict[str, Union[int, str]]]:
        try:
            extracted_events = self.llm_client.extract_career_events(
                user_id=user_id,
                message=message,
            )
        except Exception:
            return []

        synced: List[Dict[str, Union[int, str]]] = []
        for event in extracted_events:
            normalized = self._message_event(user_id, message, event)
            if normalized is None:
                continue
            saved = self._upsert_event(normalized)
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

    def _message_event(
        self,
        user_id: str,
        message: str,
        event: Dict[str, Any],
    ) -> Optional[Dict[str, Union[int, str]]]:
        event_type = str(event.get("event_type") or "").strip()
        title = str(event.get("title") or "").strip()
        summary = str(event.get("summary") or "").strip()
        occurred_at = str(event.get("occurred_at") or "").strip()
        allowed_event_types = {
            "application_status",
            "interview_feedback",
            "assessment_result",
            "career_milestone",
        }
        if event_type not in allowed_event_types:
            return None
        if not title or not summary:
            return None
        return {
            "user_id": user_id,
            "event_type": event_type,
            "title": title,
            "summary": summary,
            "source_type": "message",
            "source_id": self._message_source_id(
                user_id=user_id,
                message=message,
                event_type=event_type,
                title=title,
                summary=summary,
            ),
            "occurred_at": occurred_at,
        }

    def _message_source_id(
        self,
        user_id: str,
        message: str,
        event_type: str,
        title: str,
        summary: str,
    ) -> int:
        digest = hashlib.sha256(
            f"{user_id}:{message}:{event_type}:{title}:{summary}".encode("utf-8")
        ).hexdigest()
        return int(digest[:12], 16) % 2_147_483_647

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
