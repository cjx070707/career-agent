"""Resume-to-JD gap analysis service.

Fetches the user's latest resume, then calls the LLM to produce a structured
gap analysis: matched skills, missing skills, match score, and concrete suggestions.
"""
from typing import Any, Dict

from app.llm.client import LLMClient
from app.services.resume_service import ResumeService

_SYSTEM_PROMPT = """\
你是一名专业的求职辅导专家。你的任务是对比候选人的简历和目标岗位的 JD，给出结构化的 gap 分析。

输出格式（严格按以下结构，用中文回答）：

【匹配度】X/100（整数）

【已匹配技能】
- 技能1
- 技能2
...

【差距/缺失技能】
- 缺失点1（说明 JD 要求了什么，简历里为何不足）
- 缺失点2
...

【优先级建议】
1. 最重要的行动（具体，可执行）
2. 第二重要的行动
3. 第三重要的行动

【总结】
一句话总结当前匹配情况和最关键的提升方向。

要求：
- 匹配度评分要客观，不要给虚高分
- 差距分析要具体，指出 JD 的哪个要求和简历哪里对不上
- 建议要可落地，不要泛泛而谈
"""


class GapService:
    def __init__(
        self,
        llm_client: LLMClient = None,
        resume_service: ResumeService = None,
    ) -> None:
        self._llm = llm_client or LLMClient()
        self._resume_svc = resume_service or ResumeService()

    def analyze(self, user_id: str, jd_text: str) -> Dict[str, Any]:
        """Run gap analysis for the given user against a JD.

        Returns a dict with keys:
          - resume_title: str
          - analysis: str  (full structured text from LLM)
          - error: str | None
        """
        # 1. Fetch resume
        try:
            resume = self._resume_svc.get_latest_resume(user_id)
        except ValueError as exc:
            return {
                "resume_title": None,
                "analysis": None,
                "error": f"无法获取简历：{exc}",
            }

        resume_content: str = str(resume.get("content", "")).strip()
        if not resume_content:
            return {
                "resume_title": resume.get("title"),
                "analysis": None,
                "error": "简历内容为空，无法进行 gap 分析。",
            }

        # 2. Build user message
        user_content = (
            f"【候选人简历】\n{resume_content}\n\n"
            f"【目标岗位 JD】\n{jd_text.strip()}"
        )

        # 3. LLM call
        try:
            analysis = self._llm.simple_chat(
                system_prompt=_SYSTEM_PROMPT,
                user_content=user_content,
                timeout=45.0,
            )
        except Exception as exc:  # noqa: BLE001
            return {
                "resume_title": resume.get("title"),
                "analysis": None,
                "error": f"LLM 调用失败：{exc}",
            }

        if not analysis:
            return {
                "resume_title": resume.get("title"),
                "analysis": None,
                "error": "LLM 未返回有效内容，请重试。",
            }

        return {
            "resume_title": resume.get("title"),
            "analysis": analysis,
            "error": None,
        }
