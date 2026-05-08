"""Resume-to-JD gap analysis service.

Fetches the user's latest resume, then calls the LLM to produce a structured
gap analysis: matched skills, missing skills, match score, and concrete suggestions.
"""
import json
from typing import Any, Dict

from app.llm.client import LLMClient
from app.services.resume_service import ResumeService

_SYSTEM_PROMPT = """\
你是一名专业的求职辅导专家。对比候选人简历和目标 JD，输出以下 JSON，不要输出任何其他内容：

{
  "match_score": <0-100 整数，客观评分>,
  "matched_skills": [<简历中已具备的技能，字符串列表>],
  "missing_skills": [<JD 要求但简历缺失的技能，字符串列表>],
  "suggestions": [<3 条具体可执行的提升建议，字符串列表>]
}

要求：
- match_score 要客观，不要虚高
- missing_skills 要具体指出 JD 哪个要求对不上
- suggestions 要可落地，不要泛泛而谈
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
        except ValueError:
            return {
                "resume_title": None,
                "analysis": None,
                "error": "未找到简历",
            }

        resume_content: str = str(resume.get("content", "")).strip()
        if not resume_content:
            return {
                "resume_title": resume.get("title"),
                "analysis": None,
                "error": "未找到简历",
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

        # Parse JSON output; fall back to raw text if LLM doesn't comply
        try:
            # Strip markdown code fences if present
            text = analysis.strip().removeprefix("```json").removeprefix("```").removesuffix("```").strip()
            structured = json.loads(text)
            return {
                "resume_title": resume.get("title"),
                "match_score": int(structured.get("match_score", 0)),
                "matched_skills": structured.get("matched_skills", []),
                "missing_skills": structured.get("missing_skills", []),
                "suggestions": structured.get("suggestions", []),
                "error": None,
            }
        except (json.JSONDecodeError, ValueError):
            return {
                "resume_title": resume.get("title"),
                "match_score": None,
                "matched_skills": [],
                "missing_skills": [],
                "suggestions": [],
                "analysis": analysis,
                "error": None,
            }
