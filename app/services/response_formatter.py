from typing import Any, List

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

        return "工具执行完成。"

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
