from typing import Any, List
import re

from app.schemas.chat import ChatSource


class ToolResponseFormatter:
    DIAGNOSIS_LABELS = {
        "insufficient_evidence": "证据不足",
        "application_volume": "投递样本不足",
        "resume_positioning": "简历定位与表达",
        "interview_performance": "面试表现",
        "skill_gap": "技能缺口",
        "job_targeting": "岗位定位偏差",
    }

    def build_tool_evidence(self, tool_name: str, tool_result: Any) -> List[str]:
        evidence: List[str] = [f"tool={tool_name}"]
        if tool_name in ("get_resume_by_id", "get_resume_summary") and isinstance(tool_result, dict):
            content = str(tool_result.get("content") or tool_result.get("summary") or "")
            title = str(tool_result.get("title") or "")
            if title:
                evidence.append(f"resume_title={title}")
            # Truncate resume content to avoid token overload and thinking-mode slowdowns.
            if content:
                evidence.append("resume_content=" + content[:3000])
            return evidence
        if tool_name == "search_jobs" and isinstance(tool_result, list):
            for row in tool_result[:5]:
                evidence.append(
                    "job: {title} | company={company} | location={location} | snippet={snippet}".format(
                        title=str(row.get("title") or ""),
                        company=str(row.get("company") or ""),
                        location=str(row.get("location") or ""),
                        snippet=str(row.get("reason") or row.get("snippet") or ""),
                    )
                )
            return evidence
        if tool_name == "match_resume_to_jobs" and isinstance(tool_result, dict):
            for row in (tool_result.get("matches") or [])[:5]:
                evidence.append(
                    "match: {title} | score={score} | rationale={rationale}".format(
                        title=str(row.get("job_title") or ""),
                        score=str(row.get("match_score") or ""),
                        rationale=str(row.get("rationale") or ""),
                    )
                )
            return evidence
        if tool_name == "get_career_insights" and isinstance(tool_result, dict):
            profile = tool_result.get("profile") or {}
            app = tool_result.get("application_summary") or {}
            interview = tool_result.get("interview_summary") or {}
            evidence.append(f"target_role={profile.get('target_role_preference') or ''}")
            evidence.append(f"applications_total={app.get('total') or 0}")
            evidence.append(f"interviews_total={interview.get('total') or 0}")
            for item in (tool_result.get('next_actions') or tool_result.get('suggestions') or [])[:3]:
                evidence.append(f"suggestion={item}")
            return evidence
        if isinstance(tool_result, list):
            for item in tool_result[:5]:
                evidence.append(str(item))
            return evidence
        if isinstance(tool_result, dict):
            for k, v in list(tool_result.items())[:12]:
                evidence.append(f"{k}={v}")
            return evidence
        evidence.append(str(tool_result))
        return evidence

    def _format_three_section(self, conclusion: str, evidence: str, actions: List[str]) -> str:
        clean_actions = [str(item).strip() for item in actions if str(item).strip()][:3]
        if not clean_actions:
            clean_actions = ["补充关键上下文后，我会给出更具体的下一步建议。"]
        action_lines = [f"{idx}. {item}" for idx, item in enumerate(clean_actions, start=1)]
        return (
            f"【结论】\n{conclusion.strip()}\n\n"
            f"【证据】\n{evidence.strip()}\n\n"
            "【行动建议】\n" + "\n".join(action_lines)
        )

    def _compact_text(self, content: str) -> str:
        compact = re.sub(r"\s+", " ", content).strip()
        return compact[:4000]

    def _normalize_resume_text(self, content: str) -> str:
        text = content.replace("\r", "\n")
        text = re.sub(r"(?m)^\s*#+\s*", "", text)
        text = re.sub(r"(?i)\bparsed resume\b", "", text)
        text = re.sub(r"(?i)\bresume parsed from image\b", "", text)
        text = re.sub(r"(?im)^\s*email\s*:\s*[^\n]+$", "", text)
        text = re.sub(r"(?im)^\s*(phone|mobile|tel|电话)\s*:\s*[^\n]+$", "", text)
        text = re.sub(r"(?im)^\s*(name|姓名)\s*:\s*[^\n]+$", "", text)
        # Remove common section headers from OCR/markdown exports.
        text = re.sub(r"(?im)^\s*(summary|education|skills?|experience|projects?)\s*[:：]?\s*$", "", text)
        # Drop leftover inline tags if OCR merged labels into one line.
        text = re.sub(r"(?i)\b(name|email|phone)\s*:\s*[^\s;，。]+", "", text)
        text = re.sub(r"(?i)\b(summary|education|skills?)\b\s*[:：-]?", "", text)
        text = re.sub(r"[ \t]+", " ", text)
        text = re.sub(r"\n{2,}", "\n", text)
        return text.strip()

    def _resume_summary_line(self, text: str) -> str:
        if not text:
            return ""
        lines = [line.strip() for line in text.split("\n") if line.strip()]
        noisy_markers = (
            "education",
            "skill",
            "skills",
            "email",
            "phone",
            "联系方式",
            "邮箱",
            "电话",
        )
        strong_markers = (
            "summary",
            "experience",
            "project",
            "intern",
            "实习",
            "项目",
            "负责",
            "构建",
            "优化",
        )
        for line in lines:
            lowered = line.lower()
            if any(marker in lowered for marker in noisy_markers):
                continue
            if any(marker in lowered for marker in strong_markers) and len(line) >= 12:
                cleaned = re.sub(r"(?i)^(summary|experience|project)\s*[:：-]?\s*", "", line).strip()
                return cleaned[:120] if cleaned else line[:120]
        return self._first_sentence(text)

    def _first_sentence(self, text: str) -> str:
        if not text:
            return ""
        parts = re.split(r"[。！？.!?;；\n]", text)
        for part in parts:
            candidate = part.strip()
            if len(candidate) >= 12:
                return candidate[:120]
        return text[:120]

    def _infer_role_hint(self, text: str) -> str:
        lowered = text.lower()
        mapping = [
            ("data analyst", "偏数据分析方向"),
            ("backend", "偏后端开发方向"),
            ("frontend", "偏前端开发方向"),
            ("full stack", "偏全栈开发方向"),
            ("machine learning", "偏机器学习方向"),
            ("product", "偏产品方向"),
            ("数据分析", "偏数据分析方向"),
            ("后端", "偏后端开发方向"),
            ("前端", "偏前端开发方向"),
            ("全栈", "偏全栈开发方向"),
            ("机器学习", "偏机器学习方向"),
            ("产品", "偏产品方向"),
        ]
        for key, label in mapping:
            if key in lowered:
                return label
        return "方向信息不够明确，建议在简历抬头补充目标岗位"

    def _extract_resume_keywords(self, text: str) -> List[str]:
        lowered = text.lower()
        candidates = [
            "python",
            "java",
            "sql",
            "fastapi",
            "django",
            "flask",
            "react",
            "typescript",
            "node",
            "aws",
            "docker",
            "kubernetes",
            "machine learning",
            "pandas",
            "tableau",
            "power bi",
        ]
        found: List[str] = []
        for item in candidates:
            if item in lowered:
                found.append(item)
        return found[:6]

    def _extract_highlights(self, text: str) -> List[str]:
        fragments = re.split(r"[。！？.!?\n]", text)
        selected: List[str] = []
        strong_markers = ("project", "实习", "项目", "intern", "built", "developed", "优化", "提升", "设计")
        noisy_markers = ("name:", "email:", "phone:", "education", "skills")
        for frag in fragments:
            line = frag.strip()
            if not line:
                continue
            lowered = line.lower()
            if any(marker in lowered for marker in noisy_markers):
                continue
            if any(marker in lowered for marker in strong_markers) and len(line) >= 10:
                selected.append(line[:90])
            if len(selected) >= 2:
                break
        return selected

    def _extract_resume_risks(self, text: str) -> List[str]:
        lowered = text.lower()
        risks: List[str] = []
        has_number = bool(re.search(r"\d", text))
        if not has_number:
            risks.append("缺少量化成果（如效率提升、规模、指标）")
        if "project" not in lowered and "项目" not in text:
            risks.append("项目信息不足，建议补充代表性项目")
        if "intern" not in lowered and "实习" not in text and "experience" not in lowered and "经历" not in text:
            risks.append("经历描述偏少，建议补充实习/实践经历")
        return risks[:3]

    def _next_actions_from_risks(self, risks: List[str]) -> List[str]:
        actions: List[str] = []
        if any("量化成果" in item for item in risks):
            actions.append("为每段经历补 1-2 个量化结果")
        if any("项目信息不足" in item for item in risks):
            actions.append("补充 1-2 个项目并写清问题、动作、结果")
        if any("经历描述偏少" in item for item in risks):
            actions.append("增加与目标岗位相关的实践经历")
        return actions[:3]

    def extract_sources(self, tool_name: str, tool_result: Any) -> List[ChatSource]:
        if tool_name == "search_jobs":
            return [
                ChatSource(
                    type=result["type"],
                    title=result["title"],
                    snippet=str(result.get("reason") or result.get("snippet") or "").strip(),
                    company=result.get("company"),
                    location=result.get("location"),
                    work_type=result.get("work_type"),
                    posted_at=result.get("posted_at"),
                    url=result.get("url"),
                )
                for result in tool_result
            ]

        if tool_name == "match_resume_to_jobs":
            return [
                ChatSource(type="job_posting", title=match["job_title"], snippet=match["rationale"])
                for match in tool_result.get("matches", [])
            ]

        if tool_name == "get_applications":
            return [
                ChatSource(
                    type="application",
                    title=f"{item.get('company', '')} - {item.get('job_title', '')}".strip(" -"),
                    snippet=f"状态：{item.get('status', '')}；备注：{item.get('note', '')}".strip(),
                )
                for item in (tool_result if isinstance(tool_result, list) else [])
            ]

        if tool_name == "get_interview_feedback":
            return [
                ChatSource(
                    type="interview_feedback",
                    title=f"{item.get('company', '')} - {item.get('job_title', '')}".strip(" -"),
                    snippet=(
                        f"轮次：{item.get('interview_round', '')}；"
                        f"结果：{item.get('result', '')}；"
                        f"反馈：{item.get('feedback', '')}"
                    ).strip(),
                )
                for item in (tool_result if isinstance(tool_result, list) else [])
            ]

        if tool_name == "get_career_insights":
            data = tool_result if isinstance(tool_result, dict) else {}
            applications = data.get("application_summary", {}).get("recent", [])
            interviews = data.get("interview_summary", {}).get("recent", [])
            sources: List[ChatSource] = [
                ChatSource(
                    type="application",
                    title=f"{item.get('company', '')} - {item.get('job_title', '')}".strip(" -"),
                    snippet=f"状态：{item.get('status', '')}；备注：{item.get('note', '')}".strip(),
                )
                for item in applications
            ]
            sources.extend(
                ChatSource(
                    type="interview_feedback",
                    title=f"{item.get('company', '')} - {item.get('job_title', '')}".strip(" -"),
                    snippet=(
                        f"轮次：{item.get('interview_round', '')}；"
                        f"结果：{item.get('result', '')}；"
                        f"反馈：{item.get('feedback', '')}"
                    ).strip(),
                )
                for item in interviews
            )
            return sources

        return []
