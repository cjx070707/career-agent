"""AgentState — structured per-turn awareness snapshot.

Before each ReAct loop the agent builds an AgentState by making a handful
of lightweight DB lookups.  The state is then serialised into a concise
prompt block that tells the LLM:

  • what data already exists for this user (resume, applications, …)
  • what the user's known preferences are (skills, location, …)
  • what information is still missing for the current task family
  • how many active goals exist

This removes a whole class of reasoning errors where the model:
  - tries to run gap-analysis when no resume has been uploaded
  - forgets to suggest resume upload after a 'no resume' tool error
  - asks for location/skills that were already mentioned earlier

Design goals
------------
* Zero LLM calls — all state is derived from DB queries + profile JSON.
* Best-effort — any DB failure returns an "unknown" state, never crashes.
* Injectable — AgentStateService accepts service overrides for testing.
"""
from __future__ import annotations

import json
import logging
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional

from app.routing.task_classifier import TaskFamily

logger = logging.getLogger(__name__)


@dataclass
class AgentState:
    """Structured snapshot of agent context for one turn."""

    task_family: str = TaskFamily.GENERAL.value

    # ── Data availability ─────────────────────────────────────────
    has_resume: bool = False
    application_count: int = 0
    interview_count: int = 0
    active_goal_count: int = 0

    # ── Known user preferences (from profile JSON) ────────────────
    known_skills: List[str] = field(default_factory=list)
    experience_level: str = "unknown"   # entry / mid / senior / unknown
    preferred_locations: List[str] = field(default_factory=list)
    preferred_roles: List[str] = field(default_factory=list)

    # ── Computed gaps ─────────────────────────────────────────────
    missing_info: List[str] = field(default_factory=list)

    # ── Properties ───────────────────────────────────────────────

    @property
    def has_applications(self) -> bool:
        return self.application_count > 0

    @property
    def has_interviews(self) -> bool:
        return self.interview_count > 0

    def to_prompt_block(self) -> str:
        """Render as a compact system-prompt section (≤ 10 lines)."""
        lines: List[str] = ["【Agent 状态快照】"]

        # Task family
        lines.append(f"• 任务类型：{self.task_family}")

        # Data summary
        data_parts = [
            f"简历={'已上传' if self.has_resume else '未上传'}",
            f"投递={self.application_count} 条",
            f"面试={self.interview_count} 条",
            f"目标={self.active_goal_count} 个",
        ]
        lines.append("• 数据：" + "｜".join(data_parts))

        # Known preferences
        known_parts: List[str] = []
        if self.known_skills:
            known_parts.extend(self.known_skills[:5])
        if self.preferred_locations:
            known_parts.extend(self.preferred_locations[:2])
        if self.experience_level and self.experience_level != "unknown":
            known_parts.append(self.experience_level)
        if known_parts:
            lines.append("• 用户已知：" + "、".join(known_parts))
        else:
            lines.append("• 用户已知：暂无")

        # Missing info warnings
        if self.missing_info:
            for item in self.missing_info:
                lines.append(f"⚠️ 缺失：{item}")

        return "\n".join(lines)


# ── Missing-info inference rules ─────────────────────────────────────────────

_RESUME_FAMILIES = {TaskFamily.RESUME.value, TaskFamily.JOB_SEARCH.value}
_INTERVIEW_FAMILIES = {TaskFamily.INTERVIEW.value}
_APPLICATION_FAMILIES = {TaskFamily.APPLICATION.value}
_GOAL_FAMILIES = {TaskFamily.GOAL.value}


def _compute_missing_info(state: AgentState) -> List[str]:
    """Return a list of concise missing-info descriptions for this state."""
    gaps: List[str] = []
    tf = state.task_family

    if tf in _RESUME_FAMILIES and not state.has_resume:
        gaps.append("简历尚未上传（gap 分析 / 岗位匹配需要先上传简历）")

    if tf in _INTERVIEW_FAMILIES and not state.has_interviews:
        gaps.append("暂无面试记录，无法提供面试反馈分析")

    if tf in _APPLICATION_FAMILIES and not state.has_applications:
        gaps.append("暂无投递记录，无法查询投递状态")

    if tf in _GOAL_FAMILIES and state.active_goal_count == 0:
        gaps.append("尚未设定求职目标")

    if tf == TaskFamily.JOB_SEARCH.value and not state.known_skills:
        gaps.append("用户技能栈未知，建议先上传简历以获取精准匹配")

    return gaps


# ── Service ───────────────────────────────────────────────────────────────────

class AgentStateService:
    """Builds an AgentState snapshot with lightweight DB queries.

    All heavy lifting is done by the existing CRUD services; this class
    just orchestrates them and parses the profile JSON.
    """

    def __init__(
        self,
        resume_service=None,
        application_service=None,
        interview_service=None,
    ) -> None:
        # Lazy imports to avoid circular deps; overrideable for tests
        self._resume_svc = resume_service
        self._app_svc = application_service
        self._iv_svc = interview_service

    def _resume_service(self):
        if self._resume_svc is None:
            from app.services.resume_service import ResumeService
            self._resume_svc = ResumeService()
        return self._resume_svc

    def _application_service(self):
        if self._app_svc is None:
            from app.services.application_service import ApplicationService
            self._app_svc = ApplicationService()
        return self._app_svc

    def _interview_service(self):
        if self._iv_svc is None:
            from app.services.interview_service import InterviewService
            self._iv_svc = InterviewService()
        return self._iv_svc

    def build(
        self,
        user_id: str,
        task_family: TaskFamily,
        user_profile_json: str,
        goals: List[Dict[str, Any]],
    ) -> AgentState:
        """Return a fresh AgentState for this user + turn."""
        state = AgentState(
            task_family=task_family.value,
            active_goal_count=len([g for g in goals if g.get("status") == "active"]),
        )

        # ── DB checks (best-effort) ───────────────────────────────
        try:
            state.has_resume = self._resume_service().has_resume(user_id)
        except Exception as exc:
            logger.debug("AgentState: resume check failed: %s", exc)

        try:
            apps = self._application_service().list_applications_by_user(user_id, limit=1)
            state.application_count = len(apps)
            # For a rough count, query without limit (capped at 50 by service)
            all_apps = self._application_service().list_applications_by_user(user_id, limit=50)
            state.application_count = len(all_apps)
        except Exception as exc:
            logger.debug("AgentState: application check failed: %s", exc)

        try:
            all_ivs = self._interview_service().list_interviews_by_user(user_id, limit=50)
            state.interview_count = len(all_ivs)
        except Exception as exc:
            logger.debug("AgentState: interview check failed: %s", exc)

        # ── Profile JSON parsing ──────────────────────────────────
        try:
            if user_profile_json and user_profile_json not in ("{}", ""):
                prefs: Dict[str, Any] = json.loads(user_profile_json)
                # Accept several common key names from UserProfileService
                state.known_skills = _parse_list(prefs, ["skills", "技能", "known_skills"])
                state.preferred_locations = _parse_list(
                    prefs, ["preferred_locations", "locations", "城市", "location"]
                )
                state.preferred_roles = _parse_list(
                    prefs, ["preferred_roles", "roles", "岗位", "target_roles"]
                )
                state.experience_level = str(
                    prefs.get("experience_level")
                    or prefs.get("experience")
                    or prefs.get("经验")
                    or "unknown"
                )
        except Exception as exc:
            logger.debug("AgentState: profile parse failed: %s", exc)

        # ── Compute gaps ──────────────────────────────────────────
        state.missing_info = _compute_missing_info(state)

        return state


# ── Helpers ───────────────────────────────────────────────────────────────────

def _parse_list(prefs: Dict[str, Any], keys: List[str]) -> List[str]:
    """Try each key in order; return first non-empty list found, else []."""
    for k in keys:
        val = prefs.get(k)
        if isinstance(val, list) and val:
            return [str(v) for v in val if v]
        if isinstance(val, str) and val:
            return [val]
    return []
