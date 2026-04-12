from typing import Dict, List, Union

from app.db.session import get_connection


class ResumeService:
    def has_resume(self) -> bool:
        with get_connection() as connection:
            row = connection.execute(
                """
                SELECT 1
                FROM resumes
                LIMIT 1
                """
            ).fetchone()
        return row is not None

    def create_resume(
        self,
        candidate_id: int,
        title: str,
        content: str,
        version: str,
    ) -> Dict[str, Union[int, str]]:
        with get_connection() as connection:
            cursor = connection.execute(
                """
                INSERT INTO resumes (candidate_id, title, content, version)
                VALUES (?, ?, ?, ?)
                """,
                (candidate_id, title, content, version),
            )
            resume_id = cursor.lastrowid
        return {
            "id": resume_id,
            "candidate_id": candidate_id,
            "title": title,
            "content": content,
            "version": version,
        }

    def list_resumes(self) -> List[Dict[str, Union[int, str]]]:
        with get_connection() as connection:
            rows = connection.execute(
                """
                SELECT id, candidate_id, title, content, version
                FROM resumes
                ORDER BY id ASC
                """
            ).fetchall()
        return [
            {
                "id": row["id"],
                "candidate_id": row["candidate_id"],
                "title": row["title"],
                "content": row["content"],
                "version": row["version"],
            }
            for row in rows
        ]

    def get_resume_by_id(self, resume_id: int) -> Dict[str, Union[int, str]]:
        with get_connection() as connection:
            row = connection.execute(
                """
                SELECT id, candidate_id, title, content, version
                FROM resumes
                WHERE id = ?
                """,
                (resume_id,),
            ).fetchone()
        if row is None:
            raise ValueError(f"Resume {resume_id} not found")
        return {
            "id": row["id"],
            "candidate_id": row["candidate_id"],
            "title": row["title"],
            "content": row["content"],
            "version": row["version"],
        }

    def get_latest_resume(self) -> Dict[str, Union[int, str]]:
        with get_connection() as connection:
            row = connection.execute(
                """
                SELECT id, candidate_id, title, content, version
                FROM resumes
                ORDER BY id DESC
                LIMIT 1
                """
            ).fetchone()
        if row is None:
            raise ValueError("No resume available")
        return {
            "id": row["id"],
            "candidate_id": row["candidate_id"],
            "title": row["title"],
            "content": row["content"],
            "version": row["version"],
        }
