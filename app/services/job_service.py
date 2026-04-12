from typing import Dict, List, Union

from app.db.session import get_connection
from app.services.retrieval_service import RetrievalService


class JobService:
    def __init__(self, retrieval_service: RetrievalService = None) -> None:
        self.retrieval_service = retrieval_service or RetrievalService()

    def create_job(self, title: str) -> Dict[str, Union[int, str]]:
        with get_connection() as connection:
            cursor = connection.execute(
                "INSERT INTO job_postings (title) VALUES (?)",
                (title,),
            )
            job_id = cursor.lastrowid
        self.retrieval_service.upsert_job(job_id=job_id, title=title)
        return {"id": job_id, "title": title}

    def list_jobs(self) -> List[Dict[str, Union[int, str]]]:
        with get_connection() as connection:
            rows = connection.execute(
                "SELECT id, title FROM job_postings ORDER BY id ASC"
            ).fetchall()
        return [{"id": row["id"], "title": row["title"]} for row in rows]
