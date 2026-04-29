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

    def format_tool_answer(self, tool_name: str, tool_result: Any) -> str:
        if tool_name == "get_candidate_profile":
            return f"我查到了你的候选人资料，当前姓名是 {tool_result['name']}。"

        if tool_name == "search_jobs":
            if not tool_result:
                return "我暂时没有找到相关岗位。"
            titles = ", ".join(result["title"] for result in tool_result[:3])
            return f"我找到了这些相关岗位：{titles}。"

        if tool_name == "match_resume_to_jobs":
            matches = tool_result.get("matches", [])
            if not matches:
                return "我暂时没有找到和这份简历高度匹配的岗位。"
            top_match = matches[0]
            answer_parts = [
                f"基于你的简历，优先推荐 {top_match['job_title']}，"
                f"匹配分数约为 {top_match['match_score']}。"
            ]
            rationale = str(top_match.get("rationale", "")).strip()
            if rationale:
                answer_parts.append(f"匹配理由：{rationale}。")
            if len(matches) > 1:
                follow_ups = "、".join(match["job_title"] for match in matches[1:3])
                answer_parts.append(f"也可以继续关注 {follow_ups}。")
            return "".join(answer_parts)

        if tool_name == "get_resume_by_id":
            resume = tool_result if isinstance(tool_result, dict) else {}
            content = str(resume.get("content", "")).strip()
            if not content:
                return "我没有读取到可总结的简历内容，请上传或粘贴简历。"

            raw_title = str(resume.get("title", "")).strip()
            title = raw_title or "未命名简历"
            if "resume parsed from image" in title.lower():
                title = "已上传简历"
            normalized = self._normalize_resume_text(content)
            compact = self._compact_text(normalized)
            role_hint = self._infer_role_hint(compact)
            keywords = self._extract_resume_keywords(compact)
            highlights = self._extract_highlights(normalized)
            risks = self._extract_resume_risks(compact)
            actions = self._next_actions_from_risks(risks)

            summary_line = self._resume_summary_line(normalized)
            if not summary_line:
                summary_line = "已读取到简历文本，建议补充更完整的经历与成果描述。"

            answer_parts = [
                f"简历总结：{summary_line}",
                f"整体定位：{role_hint}",
                "核心技能/关键词：" + ("、".join(keywords) if keywords else "暂未识别出明确技能关键词"),
                "经历或项目亮点：" + ("；".join(highlights) if highlights else "当前文本中可提取亮点较少"),
                "风险/缺口：" + ("；".join(risks) if risks else "未发现明显结构性缺口"),
                "下一步优化建议：" + ("；".join(actions) if actions else "保持当前结构，补充量化成果即可"),
                f"（基于简历：{title}）",
            ]
            return "\n".join(answer_parts)

        if tool_name == "get_applications":
            rows = tool_result if isinstance(tool_result, list) else []
            if not rows:
                return "你最近还没有投递记录。"
            summary = []
            for row in rows[:3]:
                company = str(row.get("company", "")).strip()
                title = str(row.get("job_title", "")).strip()
                status = str(row.get("status", "")).strip()
                summary.append(f"{company} - {title}（{status}）")
            return "你最近的投递包括：" + "；".join(summary) + "。"

        if tool_name == "get_interview_feedback":
            rows = tool_result if isinstance(tool_result, list) else []
            if not rows:
                return "你最近还没有面试反馈记录。"
            summary = []
            for row in rows[:3]:
                company = str(row.get("company", "")).strip()
                title = str(row.get("job_title", "")).strip()
                round_name = str(row.get("interview_round", "")).strip()
                result = str(row.get("result", "")).strip()
                summary.append(f"{company} - {title}（{round_name}/{result}）")
            return "你最近的面试反馈包括：" + "；".join(summary) + "。"

        if tool_name == "get_career_insights":
            data = tool_result if isinstance(tool_result, dict) else {}
            profile = data.get("profile", {})
            applications = data.get("application_summary", {})
            interviews = data.get("interview_summary", {})
            strengths = data.get("strengths", [])
            risk_areas = data.get("risk_areas", [])
            next_actions = data.get("next_actions", data.get("suggestions", []))
            diagnosis = data.get("diagnosis", {}) if isinstance(data.get("diagnosis", {}), dict) else {}

            role = str(profile.get("target_role_preference", "")).strip() or "暂未明确"
            app_total = int(applications.get("total", 0) or 0)
            interview_total = int(interviews.get("total", 0) or 0)
            answer_parts = [
                f"当前状态：目标方向是 {role}，",
                f"最近有 {app_total} 条投递记录、{interview_total} 条面试反馈。",
            ]
            if strengths:
                answer_parts.append("已有优势：" + "；".join(str(item) for item in strengths[:2]) + "。")
            if risk_areas:
                answer_parts.append("主要风险：" + "；".join(str(item) for item in risk_areas[:2]) + "。")
            feedback_highlights = interviews.get("feedback_highlights", [])
            if feedback_highlights:
                answer_parts.append("面试反馈里最需要关注的是：" + "；".join(feedback_highlights[:2]) + "。")
            diagnosis_type = str(diagnosis.get("bottleneck_type", "")).strip()
            diagnosis_summary = str(diagnosis.get("diagnosis_summary", "")).strip()
            if diagnosis_type and diagnosis_summary:
                diagnosis_label = self.DIAGNOSIS_LABELS.get(diagnosis_type, diagnosis_type)
                answer_parts.append(
                    f"初步诊断：当前主要瓶颈可能是 {diagnosis_label}，原因是 {diagnosis_summary}。"
                )
            if next_actions:
                answer_parts.append("推荐行动（下一步）：" + "；".join(str(item) for item in next_actions[:2]) + "。")
            elif not app_total and not interview_total:
                answer_parts.append("推荐行动（下一步）：先补充投递记录和面试反馈。")
            return "".join(answer_parts)

        return "我已执行相关工具，但当前结果不足以直接给出建议。请补充更具体的目标岗位、简历或岗位描述。"

    def format_resume_optimization_answer(self, tool_result: Any, message: str) -> str:
        resume = tool_result if isinstance(tool_result, dict) else {}
        content = str(resume.get("content", "")).strip()
        if not content:
            return "我没有读取到可优化的简历内容，请上传或粘贴简历。"

        normalized = self._normalize_resume_text(content)
        compact = self._compact_text(normalized)
        role_hint = self._infer_role_hint(compact)
        keywords = self._extract_resume_keywords(compact)
        risks = self._extract_resume_risks(compact)

        top_risks = risks[:3]
        if not top_risks:
            top_risks = ["经历描述还可以更聚焦目标岗位，建议补充量化成果和项目影响"]

        rewrite_suggestions: List[str] = []
        if any("量化成果" in item for item in top_risks):
            rewrite_suggestions.append("将“负责接口开发”改为“负责 8 个核心接口开发，查询耗时下降 35%”。")
        if any("项目信息不足" in item for item in top_risks):
            rewrite_suggestions.append("每个项目用“问题-动作-结果”三行写法，至少写出一个业务结果。")
        if any("经历描述偏少" in item for item in top_risks):
            rewrite_suggestions.append("补 1 段与目标岗位最相关的实习/实践经历，并写清技术栈和成果。")
        if not rewrite_suggestions:
            rewrite_suggestions.append("把最相关的项目放在最前面，并补充可量化结果（效率、规模、转化等）。")

        keyword_line = "、".join(keywords[:5]) if keywords else "建议补充目标岗位核心关键词（如 Python/SQL/业务指标）"
        _ = message
        return (
            f"优化方向：先按 {role_hint} 岗位标准优化。\n"
            "优先优化 3 项：\n"
            f"1) {top_risks[0]}\n"
            f"2) {top_risks[1] if len(top_risks) > 1 else '项目亮点需要更聚焦目标岗位'}\n"
            f"3) {top_risks[2] if len(top_risks) > 2 else '关键词需要更贴近目标岗位 JD'}\n"
            "改写示例：\n"
            f"- {rewrite_suggestions[0]}\n"
            f"- {rewrite_suggestions[1] if len(rewrite_suggestions) > 1 else '每段经历保留“场景-动作-结果”结构'}\n"
            f"关键词建议：{keyword_line}\n"
            "下一步：先改完最相关的 2 段经历，再发我，我帮你做第二轮精修。"
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
