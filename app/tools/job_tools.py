import os

from app.schemas.tool import SearchJobsToolInput
from app.services.retrieval_service import RetrievalService
from app.tools.base import ToolDefinition


def _build_eval_mock_jobs() -> list[dict]:
    return [
        {
            "type": "job_posting",
            "title": "Data Analyst Intern (Mock)",
            "snippet": "Mocked eval posting for stable search assertions.",
            "company": "Mock Analytics",
            "location": "Sydney NSW",
            "work_type": "intern",
            "posted_at": "2026-05-05",
            "url": "https://mock.example/jobs/data-analyst-intern",
            "tags": ["data", "analyst", "intern"],
            "matched_terms": ["data", "analyst", "intern"],
            "reason": "命中关键词：data、analyst、intern",
        },
        {
            "type": "job_posting",
            "title": "Junior Data Analyst (Mock)",
            "snippet": "Mocked eval posting for location/source checks.",
            "company": "Mock BI",
            "location": "Sydney NSW",
            "work_type": "intern",
            "posted_at": "2026-05-05",
            "url": "https://mock.example/jobs/junior-data-analyst",
            "tags": ["data", "analyst"],
            "matched_terms": ["data", "analyst"],
            "reason": "命中关键词：data、analyst",
        },
    ]


def build_job_tools() -> list[ToolDefinition]:
    retrieval_service = RetrievalService()

    def _search(payload: SearchJobsToolInput) -> list[dict]:
        if os.getenv("EVAL_USE_ADZUNA_MOCK", "").strip() == "1":
            return _build_eval_mock_jobs()

        filters: dict | None = None
        if payload.location or payload.work_type:
            filters = {}
            if payload.location:
                filters["location"] = payload.location
            if payload.work_type:
                filters["work_type"] = payload.work_type
        return [
            {
                "type": hit.type,
                "title": hit.title,
                "snippet": hit.snippet,
                "company": hit.company,
                "location": hit.location,
                "work_type": hit.work_type,
                "posted_at": hit.posted_at,
                "url": hit.url,
                "tags": hit.tags,
                "matched_terms": hit.matched_terms,
                "reason": hit.reason,
            }
            for hit in retrieval_service.search_with_reasons(
                payload.query, filters=filters
            )
        ]

    return [
        ToolDefinition(
            name="search_jobs",
            description=(
                "Search the live job postings database for real, current openings. "
                "You MUST call this tool whenever the user asks about job or internship opportunities — "
                "your training data does not contain current job listings and will be wrong or fabricated. "
                "Only this tool has access to real, up-to-date postings."
            ),
            category="job_search",
            input_model=SearchJobsToolInput,
            # Tool layer transports the structured retrieval payload unchanged.
            handler=_search,
        )
    ]
