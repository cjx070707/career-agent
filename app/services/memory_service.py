"""SQLite-backed memory: short-term window + running summary."""

from __future__ import annotations

from dataclasses import dataclass
from typing import List, Optional, Tuple

from app.db.session import get_connection

# How many raw turns to keep verbatim in context
WINDOW_SIZE = 6
# When total stored turns exceed this, compress the oldest batch
ARCHIVE_THRESHOLD = 14


@dataclass
class MemoryTurn:
    id: int
    role: str
    content: str


class MemoryService:
    """Two-layer memory: sliding window (raw) + running summary (compressed)."""

    def __init__(self, db_path: Optional[str] = None) -> None:
        self.db_path = db_path

    # ── Raw turns ────────────────────────────────────────────────────

    def load_recent_messages(self, user_id: str) -> List[MemoryTurn]:
        """Return the most recent WINDOW_SIZE turns, oldest first."""
        with get_connection(self.db_path) as conn:
            rows = conn.execute(
                """
                SELECT id, role, content
                FROM conversation_turns
                WHERE user_id = ?
                ORDER BY id DESC
                LIMIT ?
                """,
                (user_id, WINDOW_SIZE),
            ).fetchall()
        return [
            MemoryTurn(id=r["id"], role=r["role"], content=r["content"])
            for r in reversed(rows)
        ]

    def save_turn(self, user_id: str, user_message: str, assistant_message: str) -> None:
        """Append a user+assistant turn pair. Does NOT auto-delete — caller
        decides when to archive (via maybe_archive)."""
        with get_connection(self.db_path) as conn:
            conn.executemany(
                "INSERT INTO conversation_turns (user_id, role, content) VALUES (?, ?, ?)",
                [
                    (user_id, "user", user_message),
                    (user_id, "assistant", assistant_message),
                ],
            )

    def count_turns(self, user_id: str) -> int:
        with get_connection(self.db_path) as conn:
            row = conn.execute(
                "SELECT COUNT(*) AS n FROM conversation_turns WHERE user_id = ?",
                (user_id,),
            ).fetchone()
        return row["n"] if row else 0

    def get_archive_candidates(self, user_id: str) -> List[MemoryTurn]:
        """Return turns older than the WINDOW_SIZE — these are candidates for
        compression and deletion."""
        with get_connection(self.db_path) as conn:
            # IDs of the recent window we want to keep
            keep_ids = [
                r["id"]
                for r in conn.execute(
                    """
                    SELECT id FROM conversation_turns
                    WHERE user_id = ?
                    ORDER BY id DESC
                    LIMIT ?
                    """,
                    (user_id, WINDOW_SIZE),
                ).fetchall()
            ]
            if not keep_ids:
                return []
            placeholders = ",".join("?" * len(keep_ids))
            rows = conn.execute(
                f"""
                SELECT id, role, content
                FROM conversation_turns
                WHERE user_id = ? AND id NOT IN ({placeholders})
                ORDER BY id ASC
                """,
                (user_id, *keep_ids),
            ).fetchall()
        return [MemoryTurn(id=r["id"], role=r["role"], content=r["content"]) for r in rows]

    def delete_turns_by_ids(self, turn_ids: List[int]) -> None:
        if not turn_ids:
            return
        with get_connection(self.db_path) as conn:
            placeholders = ",".join("?" * len(turn_ids))
            conn.execute(
                f"DELETE FROM conversation_turns WHERE id IN ({placeholders})",
                turn_ids,
            )

    def needs_archive(self, user_id: str) -> bool:
        return self.count_turns(user_id) > ARCHIVE_THRESHOLD

    # ── Running summary ──────────────────────────────────────────────

    def load_summary(self, user_id: str) -> str:
        with get_connection(self.db_path) as conn:
            row = conn.execute(
                "SELECT summary FROM conversation_summaries WHERE user_id = ?",
                (user_id,),
            ).fetchone()
        return row["summary"] if row else ""

    def save_summary(self, user_id: str, summary: str) -> None:
        with get_connection(self.db_path) as conn:
            conn.execute(
                """
                INSERT INTO conversation_summaries (user_id, summary)
                VALUES (?, ?)
                ON CONFLICT(user_id) DO UPDATE SET
                    summary = excluded.summary,
                    updated_at = CURRENT_TIMESTAMP
                """,
                (user_id, summary),
            )

    # ── User profile / preferences ───────────────────────────────────

    def load_user_profile(self, user_id: str) -> str:
        """Return raw JSON string of stored preferences, or empty string."""
        with get_connection(self.db_path) as conn:
            row = conn.execute(
                "SELECT preferences FROM user_profiles WHERE user_id = ?",
                (user_id,),
            ).fetchone()
        return row["preferences"] if row else ""

    def save_user_profile(self, user_id: str, preferences_json: str) -> None:
        with get_connection(self.db_path) as conn:
            conn.execute(
                """
                INSERT INTO user_profiles (user_id, preferences)
                VALUES (?, ?)
                ON CONFLICT(user_id) DO UPDATE SET
                    preferences = excluded.preferences,
                    updated_at = CURRENT_TIMESTAMP
                """,
                (user_id, preferences_json),
            )
