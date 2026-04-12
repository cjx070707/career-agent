from dataclasses import dataclass
from typing import Optional

from app.db.session import get_connection


@dataclass
class MemoryTurn:
    role: str
    content: str


class MemoryService:
    """SQLite-backed short-term memory store for the MVP."""

    def __init__(self, db_path: Optional[str] = None, max_turns: int = 6) -> None:
        self.db_path = db_path
        self.max_turns = max_turns

    def load_recent_messages(self, user_id: str) -> list[MemoryTurn]:
        with get_connection(self.db_path) as connection:
            rows = connection.execute(
                """
                SELECT role, content
                FROM conversation_turns
                WHERE user_id = ?
                ORDER BY id DESC
                LIMIT ?
                """,
                (user_id, self.max_turns),
            ).fetchall()
        ordered_rows = list(reversed(rows))
        return [MemoryTurn(role=row["role"], content=row["content"]) for row in ordered_rows]

    def save_turn(self, user_id: str, user_message: str, assistant_message: str) -> None:
        with get_connection(self.db_path) as connection:
            connection.executemany(
                """
                INSERT INTO conversation_turns (user_id, role, content)
                VALUES (?, ?, ?)
                """,
                [
                    (user_id, "user", user_message),
                    (user_id, "assistant", assistant_message),
                ],
            )
            connection.execute(
                """
                DELETE FROM conversation_turns
                WHERE user_id = ?
                  AND id NOT IN (
                    SELECT id
                    FROM conversation_turns
                    WHERE user_id = ?
                    ORDER BY id DESC
                    LIMIT ?
                  )
                """,
                (user_id, user_id, self.max_turns),
            )

    def summarize_recent_context(self) -> str:
        return "Memory service placeholder."
