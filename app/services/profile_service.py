import re
from typing import Dict, List

from app.db.session import get_connection


class ProfileService:
    def get_profile(self, user_id: str) -> Dict[str, object]:
        with get_connection() as connection:
            row = connection.execute(
                """
                SELECT user_id, target_role_preference, skill_keywords, career_focus_notes
                FROM career_profiles
                WHERE user_id = ?
                """,
                (user_id,),
            ).fetchone()
        if row is None:
            return {
                "user_id": user_id,
                "target_role_preference": "",
                "skill_keywords": [],
                "career_focus_notes": "",
            }
        keywords = [item for item in row["skill_keywords"].split(",") if item]
        return {
            "user_id": row["user_id"],
            "target_role_preference": row["target_role_preference"],
            "skill_keywords": keywords,
            "career_focus_notes": row["career_focus_notes"],
        }

    def update_from_message(self, user_id: str, message: str) -> Dict[str, object]:
        current = self.get_profile(user_id)
        lowered = message.lower()

        target_role = current["target_role_preference"]
        if "后端" in message or "backend" in lowered:
            target_role = "backend"
        elif "前端" in message or "frontend" in lowered:
            target_role = "frontend"

        keywords = set(current["skill_keywords"])
        for keyword in self._extract_skill_keywords(message):
            keywords.add(keyword)

        notes = current["career_focus_notes"]
        if "方向" in message and target_role:
            notes = f"User currently prefers {target_role} roles."

        with get_connection() as connection:
            connection.execute(
                """
                INSERT INTO career_profiles (
                    user_id, target_role_preference, skill_keywords, career_focus_notes, updated_at
                ) VALUES (?, ?, ?, ?, CURRENT_TIMESTAMP)
                ON CONFLICT(user_id) DO UPDATE SET
                    target_role_preference = excluded.target_role_preference,
                    skill_keywords = excluded.skill_keywords,
                    career_focus_notes = excluded.career_focus_notes,
                    updated_at = CURRENT_TIMESTAMP
                """,
                (user_id, target_role, ",".join(sorted(keywords)), notes),
            )

        return self.get_profile(user_id)

    def augment_job_query(self, user_id: str, message: str) -> str:
        profile = self.get_profile(user_id)
        query_parts: List[str] = [message]
        if profile["target_role_preference"]:
            query_parts.append(str(profile["target_role_preference"]))
        if profile["skill_keywords"]:
            query_parts.extend(profile["skill_keywords"][:3])
        return " ".join(part for part in query_parts if part).strip()

    def _extract_skill_keywords(self, message: str) -> List[str]:
        lowered = message.lower()
        allowed = ("python", "fastapi", "sql", "react", "frontend", "backend")
        tokens = set(re.findall(r"[a-zA-Z0-9]+", lowered))
        return [keyword for keyword in allowed if keyword in tokens]
