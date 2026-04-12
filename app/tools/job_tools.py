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
                    "type": result.type,
                    "title": result.title,
                    "snippet": result.snippet,
                }
                for result in retrieval_service.search(payload.query)
            ],
        )
    ]
