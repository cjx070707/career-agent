from app.schemas.tool import CareerInsightsToolInput
from app.services.career_insight_service import CareerInsightService
from app.tools.base import ToolDefinition


def build_career_insight_tools() -> list[ToolDefinition]:
    career_insight_service = CareerInsightService()
    return [
        ToolDefinition(
            name="get_career_insights",
            description="Summarize a user's career profile, applications, and interview feedback.",
            input_model=CareerInsightsToolInput,
            handler=lambda payload: career_insight_service.get_career_insights(
                user_id=payload.user_id,
                limit=payload.limit,
            ),
        )
    ]
