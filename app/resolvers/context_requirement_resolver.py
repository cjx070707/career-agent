import re
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional, Union

from app.schemas.chat import ChatPlan


@dataclass
class ContextRequirementResolution:
    required_context: List[str]
    missing_context: List[str]
    needs_more_context: bool
    follow_up_question: Optional[str]
    resolver_trace: List[Dict[str, Any]] = field(default_factory=list)

    def model_dump(self) -> Dict[str, Any]:
        return {
            "required_context": list(self.required_context),
            "missing_context": list(self.missing_context),
            "needs_more_context": self.needs_more_context,
            "follow_up_question": self.follow_up_question,
            "resolver_trace": list(self.resolver_trace),
        }


class ContextRequirementResolver:
    def resolve(
        self,
        *,
        plan: Union[ChatPlan, Dict[str, Any]],
        message: str,
        user_state: Dict[str, Any],
        profile: Dict[str, Any],
        memory_context: List[str],
    ) -> ContextRequirementResolution:
        plan_data = self._plan_data(plan)
        task_type = str(plan_data.get("task_type") or "")
        domain = str(plan_data.get("domain") or "")
        action = str(plan_data.get("action") or "")
        plan_type = str(plan_data.get("plan_type") or "")
        trace: List[Dict[str, Any]] = []

        base_required = self._as_list(plan_data.get("required_context"))
        inferred_required: List[str] = []

        if plan_type == "third_party_advice":
            trace.append(
                {
                    "resolver": "context_requirement",
                    "decision": "third_party_advice_no_current_user_context",
                    "reason": "third-party advice must not depend on current user profile or resume",
                }
            )
            return ContextRequirementResolution(
                required_context=[],
                missing_context=[],
                needs_more_context=False,
                follow_up_question=None,
                resolver_trace=trace,
            )

        if self._is_resume_summary(task_type, domain, action):
            inferred_required.append("resume")
            trace.append(self._trace("require", "resume", "resume summary needs a resume"))

        if self._is_job_match_compare(task_type, domain, action):
            inferred_required.extend(["resume", "job_detail"])
            trace.append(self._trace("require", "resume", "job matching needs resume evidence"))
            trace.append(self._trace("require", "job_detail", "job comparison needs job detail"))

        if self._is_job_search(task_type, domain, action):
            inferred_required.append("job_query")
            trace.append(self._trace("require", "job_query", "job search needs a query"))

        if self._is_interview_prep(task_type, domain, action):
            inferred_required.append("target_role")
            trace.append(self._trace("require", "target_role", "interview prep needs target role"))

        if self._is_career_strategy(task_type, domain, action):
            inferred_required.append("profile")
            trace.append(self._trace("require", "profile", "career strategy needs profile context"))

        required_context = self._dedupe(base_required + inferred_required)
        missing_context = [
            item
            for item in required_context
            if not self._has_context(item, message, user_state, profile, memory_context)
        ]
        for item in required_context:
            trace.append(
                self._trace(
                    "available" if item not in missing_context else "missing",
                    item,
                    f"{item} context {'available' if item not in missing_context else 'missing'}",
                )
            )

        follow_up_question = self._follow_up_question(missing_context)
        return ContextRequirementResolution(
            required_context=required_context,
            missing_context=missing_context,
            needs_more_context=bool(missing_context),
            follow_up_question=follow_up_question,
            resolver_trace=trace,
        )

    def _plan_data(self, plan: Union[ChatPlan, Dict[str, Any]]) -> Dict[str, Any]:
        if isinstance(plan, ChatPlan):
            return plan.model_dump()
        return dict(plan)

    def _as_list(self, value: Any) -> List[str]:
        if not isinstance(value, list):
            return []
        return [str(item).strip() for item in value if str(item).strip()]

    def _dedupe(self, items: List[str]) -> List[str]:
        seen = set()
        deduped: List[str] = []
        for item in items:
            if item not in seen:
                deduped.append(item)
                seen.add(item)
        return deduped

    def _trace(self, decision: str, context: str, reason: str) -> Dict[str, Any]:
        return {
            "resolver": "context_requirement",
            "decision": decision,
            "context": context,
            "reason": reason,
        }

    def _is_resume_summary(self, task_type: str, domain: str, action: str) -> bool:
        return task_type == "resume_analysis" and (
            domain in {"", "resume_analysis"} and action in {"", "summarize"}
        )

    def _is_job_match_compare(self, task_type: str, domain: str, action: str) -> bool:
        if task_type not in {"job_match", "job_match_planning"} and domain != "job_match":
            return False
        return action == "compare"

    def _is_job_search(self, task_type: str, domain: str, action: str) -> bool:
        return task_type == "job_search" or (domain == "job_search" and action in {"", "search"})

    def _is_interview_prep(self, task_type: str, domain: str, action: str) -> bool:
        return task_type == "interview_prep" or (domain == "interview_prep" and action == "plan")

    def _is_career_strategy(self, task_type: str, domain: str, action: str) -> bool:
        return task_type == "career_insights" or (domain == "career_strategy" and action == "diagnose")

    def _has_context(
        self,
        item: str,
        message: str,
        user_state: Dict[str, Any],
        profile: Dict[str, Any],
        memory_context: List[str],
    ) -> bool:
        if item == "resume":
            # Prefer the DB flag; fall back to detecting inline resume text in
            # the current message so that users who paste resume content directly
            # are not repeatedly asked to upload a file.
            return bool(user_state.get("has_resume")) or self._message_has_inline_resume(message)
        if item == "job_detail":
            return bool(user_state.get("has_job_detail")) or self._message_has_job_detail(message)
        if item == "job_query":
            return bool(message.strip()) or bool(profile.get("target_role_preference"))
        if item == "target_role":
            return self._has_target_role(message, profile, memory_context)
        if item == "profile":
            return bool(profile)
        if item == "location":
            return self._has_location(message, profile)
        return bool(user_state.get(f"has_{item}") or profile.get(item))

    def _message_has_inline_resume(self, message: str) -> bool:
        """True when the user appears to have pasted resume content inline.

        Two signals, either is sufficient:
        1. Explicit introduction phrase — high-confidence handoff markers.
        2. Long message (≥80 chars) with ≥2 structural resume keywords — catches
           paste-dumps that skip the intro phrase.
        """
        lowered = message.lower()
        intro_phrases = (
            "这是我的简历",
            "以下是我的简历",
            "我的简历如下",
            "简历内容如下",
            "my resume:",
            "here is my resume",
            "here's my resume",
        )
        if any(phrase in message or phrase in lowered for phrase in intro_phrases):
            return True
        if len(message) >= 80:
            structural_keywords = (
                "技能", "经历", "项目", "实习", "教育", "工作",
                "skills", "experience", "project", "intern", "education",
            )
            hits = sum(1 for kw in structural_keywords if kw in message or kw in lowered)
            if hits >= 2:
                return True
        return False

    def _message_has_job_detail(self, message: str) -> bool:
        lowered = message.lower()
        return any(
            marker in lowered
            for marker in ("jd", "job description", "requirements", "招聘链接", "岗位描述", "职责", "要求")
        )

    def _has_target_role(
        self,
        message: str,
        profile: Dict[str, Any],
        memory_context: List[str],
    ) -> bool:
        if str(profile.get("target_role_preference") or "").strip():
            return True
        # If the agent previously asked for the target role and the user replied
        # with any non-trivial message, treat the reply as the role being provided.
        role_ask_markers = ("哪个目标岗位", "目标岗位的面试", "岗位名称或方向", "想准备哪个")
        if any(marker in turn for marker in role_ask_markers for turn in memory_context):
            if len(message.strip()) >= 2:
                return True
        text = " ".join([message] + list(memory_context)).lower()
        role_keywords = (
            "backend", "frontend", "full stack", "full-stack", "data analyst", "devops",
            "后端", "前端", "全栈", "数据", "机器学习", "算法", "产品", "设计",
            "金融", "投研", "量化", "分析师", "运营", "市场", "销售", "研究员",
        )
        return any(role in text for role in role_keywords)

    def _has_location(self, message: str, profile: Dict[str, Any]) -> bool:
        if profile.get("location") or profile.get("preferred_location"):
            return True
        lowered = message.lower()
        known_locations = ("sydney", "melbourne", "brisbane", "remote", "澳洲", "悉尼", "墨尔本")
        return any(location in lowered for location in known_locations)

    def _follow_up_question(self, missing_context: List[str]) -> Optional[str]:
        if not missing_context:
            return None
        if "resume" in missing_context:
            return "我需要你的简历内容才能继续。请上传简历文件，或粘贴简历文本。"
        if "job_detail" in missing_context:
            return "请提供岗位 JD / 招聘链接 / 岗位描述，我才能继续评估匹配度。"
        if "target_role" in missing_context:
            return "你想准备哪个目标岗位的面试？请告诉我岗位名称或方向。"
        if "job_query" in missing_context:
            return "你想搜索什么方向、地点或类型的岗位？"
        return f"我还需要这些信息才能继续：{', '.join(missing_context)}。"
