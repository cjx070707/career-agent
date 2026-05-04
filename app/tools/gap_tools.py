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
                "缺失技能、优先级行动建议。此工具会自动通过 user_id 查找用户最新简历，"
                "无需用户提供简历内容，直接调用即可。"
                "当用户询问以下任意一类问题时必须直接调用此工具（不要先调其他工具）："
                "①'我适不适合这个岗位'/'我适合吗' ②'我和 JD 差多少'/'差距是什么' "
                "③'帮我看看这个 JD'/'分析这个岗位' ④'简历和岗位有什么差距'/'gap 分析'。"
                "只要消息里含有 JD 文本或岗位描述，立即调用此工具。"
                "【重要】如果工具返回 error 字段且提示没有找到简历，必须用中文明确告知用户："
                "系统中还没有你的简历，gap 分析需要先上传简历。"
                "上传方式：① 在聊天框直接 Cmd+V 粘贴简历截图；② 点击输入框旁的 📎 按钮选择图片文件。"
                "上传后系统会自动解析并存储，之后即可进行 gap 分析。"
            ),
            category="resume",
            input_model=AnalyzeGapToolInput,
            handler=lambda payload: gap_service.analyze(payload.user_id, payload.jd_text),
        ),
    ]
