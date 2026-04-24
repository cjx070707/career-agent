from collections import Counter
import re
from typing import Dict, List

from app.db.session import get_connection


class ProfileService:
    def get_profile(self, user_id: str) -> Dict[str, object]:
        with get_connection() as connection:
            row = connection.execute(
                """
                SELECT user_id, target_role_preference, skill_keywords, career_focus_notes,
                       application_patterns, interview_weaknesses, next_focus_areas
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
                "application_patterns": "",
                "interview_weaknesses": "",
                "next_focus_areas": "",
            }
        keywords = [item for item in row["skill_keywords"].split(",") if item]
        return {
            "user_id": row["user_id"],
            "target_role_preference": row["target_role_preference"],
            "skill_keywords": keywords,
            "career_focus_notes": row["career_focus_notes"],
            "application_patterns": row["application_patterns"],
            "interview_weaknesses": row["interview_weaknesses"],
            "next_focus_areas": row["next_focus_areas"],
        }

    def update_from_message(self, user_id: str, message: str) -> Dict[str, object]:
        current = self.get_profile(user_id)
        lowered = message.lower()
        tokens = set(re.findall(r"[a-zA-Z0-9]+", lowered))

        target_role = current["target_role_preference"]
        if (
            "全栈" in message
            or "full-stack" in lowered
            or "full stack" in lowered
            or "fullstack" in tokens
        ):
            target_role = "full-stack"
        elif "devops" in tokens:
            target_role = "devops"
        elif (
            "机器学习" in message
            or "machine learning" in lowered
            or "ai" in tokens
            or "ml" in tokens
        ):
            target_role = "ai/ml"
        elif "数据" in message or "data" in tokens:
            target_role = "data"
        elif "后端" in message or "backend" in lowered:
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

    def refresh_from_career_records(self, user_id: str) -> Dict[str, object]:
        applications = self._list_application_statuses(user_id)
        feedback_highlights = self._list_interview_feedback(user_id)

        application_patterns = self._format_status_counts(applications)
        interview_weaknesses = " | ".join(feedback_highlights[:3])
        next_focus_areas = feedback_highlights[0] if feedback_highlights else ""

        current = self.get_profile(user_id)
        with get_connection() as connection:
            connection.execute(
                """
                INSERT INTO career_profiles (
                    user_id, target_role_preference, skill_keywords, career_focus_notes,
                    application_patterns, interview_weaknesses, next_focus_areas, updated_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, CURRENT_TIMESTAMP)
                ON CONFLICT(user_id) DO UPDATE SET
                    application_patterns = excluded.application_patterns,
                    interview_weaknesses = excluded.interview_weaknesses,
                    next_focus_areas = excluded.next_focus_areas,
                    updated_at = CURRENT_TIMESTAMP
                """,
                (
                    user_id,
                    str(current["target_role_preference"]),
                    ",".join(current["skill_keywords"]),
                    str(current["career_focus_notes"]),
                    application_patterns,
                    interview_weaknesses,
                    next_focus_areas,
                ),
            )

        return self.get_profile(user_id)

    def augment_job_query(self, user_id: str, message: str) -> str:
        profile = self.get_profile(user_id)
        query_parts: List[str] = [message]
        query_parts.extend(self._job_query_defaults(message))
        if profile["target_role_preference"]:
            query_parts.append(str(profile["target_role_preference"]))
        if profile["skill_keywords"]:
            query_parts.extend(profile["skill_keywords"][:3])
        for long_term_signal in (
            "application_patterns",
            "interview_weaknesses",
            "next_focus_areas",
        ):
            if profile.get(long_term_signal):
                query_parts.append(str(profile[long_term_signal]))
        return " ".join(part for part in query_parts if part).strip()

    def _extract_skill_keywords(self, message: str) -> List[str]:
        lowered = message.lower()
        allowed = (
            "python",
            "fastapi",
            "sql",
            "react",
            "frontend",
            "backend",
            "typescript",
            "go",
            "rust",
            "docker",
            "kubernetes",
            "aws",
            "gcp",
            "pandas",
            "pytorch",
        )
        tokens = set(re.findall(r"[a-zA-Z0-9]+", lowered))
        return [keyword for keyword in allowed if keyword in tokens]

    def _job_query_defaults(self, message: str) -> List[str]:
        lowered = message.lower()
        tokens = set(re.findall(r"[a-zA-Z0-9]+", lowered))
        defaults: List[str] = ["sydney", "university of sydney", "usyd"]

        if "数据分析" in message or "data analys" in lowered:
            defaults.extend(["data", "analyst", "analytics"])
        if "实习" in message or "intern" in lowered:
            defaults.extend(["intern", "internship"])
        if "graduate" in lowered or "校招" in message or "应届" in message:
            defaults.extend(["graduate", "grad program"])
        if "后端" in message or "backend" in lowered:
            defaults.append("backend")
        if "前端" in message or "frontend" in lowered:
            defaults.append("frontend")
        if (
            "全栈" in message
            or "full-stack" in lowered
            or "full stack" in lowered
            or "fullstack" in tokens
        ):
            defaults.extend(["fullstack", "full stack"])
        if (
            "机器学习" in message
            or "machine learning" in lowered
            or "ai" in tokens
            or "ml" in tokens
        ):
            defaults.extend(["ai", "ml", "machine learning"])

        deduped: List[str] = []
        seen = set()
        for item in defaults:
            if item not in seen:
                deduped.append(item)
                seen.add(item)
        return deduped

    def _list_application_statuses(self, user_id: str) -> List[str]:
        with get_connection() as connection:
            rows = connection.execute(
                """
                SELECT a.status
                FROM applications a
                JOIN candidates c ON c.id = a.candidate_id
                WHERE c.user_id = ?
                ORDER BY a.id DESC
                """,
                (user_id,),
            ).fetchall()
        return [str(row["status"]).strip() for row in rows if str(row["status"]).strip()]

    def _list_interview_feedback(self, user_id: str) -> List[str]:
        with get_connection() as connection:
            rows = connection.execute(
                """
                SELECT i.feedback
                FROM interviews i
                JOIN candidates c ON c.id = i.candidate_id
                WHERE c.user_id = ?
                ORDER BY i.id DESC
                """,
                (user_id,),
            ).fetchall()
        return [
            str(row["feedback"]).strip()
            for row in rows
            if str(row["feedback"]).strip()
        ]

    def _format_status_counts(self, statuses: List[str]) -> str:
        counts = Counter(statuses)
        return "; ".join(f"{status}: {counts[status]}" for status in sorted(counts))
