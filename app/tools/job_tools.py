from app.schemas.tool import SearchJobsToolInput
from app.services.retrieval_service import RetrievalService
from app.tools.base import ToolDefinition


def build_job_tools() -> list[ToolDefinition]:
    retrieval_service = RetrievalService()
    return [
        ToolDefinition(
            name="search_jobs",
            description="Search jobs using a natural language query.",
            input_model=SearchJobsToolInput,
            handler=lambda payload: [
                {
                    "type": hit.type,
                    "title": hit.title,
                    "snippet": hit.snippet,
                    "matched_terms": hit.matched_terms,
                    "reason": hit.reason,
                }
                for hit in retrieval_service.search_with_reasons(payload.query)
            ],
        )
    ]
