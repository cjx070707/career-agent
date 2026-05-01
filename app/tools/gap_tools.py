from pydantic import BaseModel, Field

from app.services.gap_service import GapService
from app.tools.base import ToolDefinition


class AnalyzeGapToolInput(BaseModel):
    user_id: str = Field(..., min_length=1, description="当前用户的 user_id")
    jd_text: str = Field(..., min_length=10, description="目标岗位的职位描述（JD）全文")


def build_gap_tools() -> list[ToolDefinition]:
    gap_service = GapService()
    return [
        ToolDefinition(
            name="analyze_gap",
            description=(
                "对比用户简历与目标岗位 JD，给出结构化 gap 分析：匹配度评分、已匹配技能、"
                "缺失技能、优先级行动建议。当用户询问'我适不适合这个岗位'、'我和 JD 差多少'、"
                "'帮我看看这个 JD'、'简历和岗位有什么差距'时调用。"
            ),
            category="resume",
            input_model=AnalyzeGapToolInput,
            handler=lambda payload: gap_service.analyze(payload.user_id, payload.jd_text),
        ),
    ]
