"""SQLite-backed memory: short-term window + running summary."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Dict, List, Optional

from app.db.session import get_connection

# How many raw turns to keep verbatim in context (12 turns = 6 user/agent exchanges)
WINDOW_SIZE = 12
# When total stored turns exceed this, compress the oldest batch
ARCHIVE_THRESHOLD = 24


@dataclass
class MemoryTurn:
    id: int
    role: str
    content: str
    session_id: Optional[str] = None


@dataclass
class SessionMeta:
    session_id: str
    title: str          # first user message, truncated
    created_at: str     # ISO timestamp of first turn
    turn_count: int


class MemoryService:
    """Two-layer memory: sliding window (raw) + running summary (compressed)."""

    def __init__(self, db_path: Optional[str] = None) -> None:
        self.db_path = db_path

    # ── Raw turns ────────────────────────────────────────────────────

    def load_recent_messages(self, user_id: str, session_id: Optional[str] = None) -> List[MemoryTurn]:
        """Return the most recent WINDOW_SIZE turns for a session (or globally), oldest first."""
        with get_connection(self.db_path) as conn:
            if session_id:
                rows = conn.execute(
                    """
                    SELECT id, role, content, session_id
                    FROM conversation_turns
                    WHERE user_id = ? AND session_id = ?
                    ORDER BY id DESC
                    LIMIT ?
                    """,
                    (user_id, session_id, WINDOW_SIZE),
                ).fetchall()
            else:
                rows = conn.execute(
                    """
                    SELECT id, role, content, session_id
                    FROM conversation_turns
                    WHERE user_id = ?
                    ORDER BY id DESC
                    LIMIT ?
                    """,
                    (user_id, WINDOW_SIZE),
                ).fetchall()
        return [
            MemoryTurn(id=r["id"], role=r["role"], content=r["content"], session_id=r["session_id"])
            for r in reversed(rows)
        ]

    def load_session_messages(self, user_id: str, session_id: str) -> List[MemoryTurn]:
        """Return ALL turns for a session (for frontend display, no window limit)."""
        with get_connection(self.db_path) as conn:
            rows = conn.execute(
                """
                SELECT id, role, content, session_id
                FROM conversation_turns
                WHERE user_id = ? AND session_id = ?
                ORDER BY id ASC
                """,
                (user_id, session_id),
            ).fetchall()
        return [
            MemoryTurn(id=r["id"], role=r["role"], content=r["content"], session_id=r["session_id"])
            for r in rows
        ]

    def list_sessions(self, user_id: str) -> List[SessionMeta]:
        """Return all sessions for a user, newest first, with title and turn count."""
        with get_connection(self.db_path) as conn:
            rows = conn.execute(
                """
                SELECT
                    session_id,
                    MIN(created_at) AS created_at,
                    COUNT(*) AS turn_count,
                    -- first user message as title
                    (SELECT content FROM conversation_turns t2
                     WHERE t2.user_id = t1.user_id
                       AND t2.session_id = t1.session_id
                       AND t2.role = 'user'
                     ORDER BY t2.id ASC LIMIT 1) AS first_msg
                FROM conversation_turns t1
                WHERE user_id = ? AND session_id IS NOT NULL
                GROUP BY session_id
                ORDER BY created_at DESC
                """,
                (user_id,),
            ).fetchall()
        return [
            SessionMeta(
                session_id=r["session_id"],
                title=(r["first_msg"] or "新对话")[:60],
                created_at=r["created_at"],
                turn_count=r["turn_count"],
            )
            for r in rows
        ]

    def save_single_turn(
        self,
        user_id: str,
        role: str,
        content: str,
        session_id: Optional[str] = None,
    ) -> int:
        """Append a single turn (any role) and return its row id."""
        with get_connection(self.db_path) as conn:
            cursor = conn.execute(
                "INSERT INTO conversation_turns (user_id, role, content, session_id) VALUES (?, ?, ?, ?)",
                (user_id, role, content, session_id),
            )
            return cursor.lastrowid  # type: ignore[return-value]

    def save_turn(
        self,
        user_id: str,
        user_message: str,
        assistant_message: str,
        session_id: Optional[str] = None,
    ) -> None:
        """Append a user+assistant turn pair. Does NOT auto-delete — caller
        decides when to archive (via maybe_archive)."""
        with get_connection(self.db_path) as conn:
            conn.executemany(
                "INSERT INTO conversation_turns (user_id, role, content, session_id) VALUES (?, ?, ?, ?)",
                [
                    (user_id, "user", user_message, session_id),
                    (user_id, "assistant", assistant_message, session_id),
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
