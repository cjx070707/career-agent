"""Tests for AgentStateService and AgentState."""
from __future__ import annotations

import json
from unittest.mock import MagicMock

import pytest

from app.routing.task_classifier import TaskFamily
from app.services.agent_state_service import AgentState, AgentStateService, _compute_missing_info


# ── AgentState.to_prompt_block() ─────────────────────────────────────────────

class TestAgentStateToPromptBlock:
    def _state(self, **kwargs) -> AgentState:
        return AgentState(**kwargs)

    def test_contains_task_family(self):
        s = self._state(task_family="job_search")
        assert "job_search" in s.to_prompt_block()

    def test_shows_resume_uploaded(self):
        s = self._state(has_resume=True)
        assert "已上传" in s.to_prompt_block()

    def test_shows_resume_not_uploaded(self):
        s = self._state(has_resume=False)
        assert "未上传" in s.to_prompt_block()

    def test_shows_application_count(self):
        s = self._state(application_count=3)
        assert "3" in s.to_prompt_block()

    def test_shows_known_skills(self):
        s = self._state(known_skills=["Python", "FastAPI"])
        block = s.to_prompt_block()
        assert "Python" in block
        assert "FastAPI" in block

    def test_shows_missing_info_warning(self):
        s = self._state(missing_info=["简历尚未上传"])
        assert "⚠️" in s.to_prompt_block()
        assert "简历尚未上传" in s.to_prompt_block()

    def test_no_missing_info_no_warning(self):
        s = self._state(has_resume=True, missing_info=[])
        assert "⚠️" not in s.to_prompt_block()

    def test_skills_truncated_to_five(self):
        s = self._state(known_skills=["A", "B", "C", "D", "E", "F", "G"])
        block = s.to_prompt_block()
        # Only first 5 shown
        assert "A" in block
        assert "G" not in block


# ── _compute_missing_info() ───────────────────────────────────────────────────

class TestComputeMissingInfo:
    def _state(self, tf: str, **kwargs) -> AgentState:
        return AgentState(task_family=tf, **kwargs)

    def test_no_resume_for_resume_task(self):
        s = self._state("resume", has_resume=False)
        gaps = _compute_missing_info(s)
        assert any("简历" in g for g in gaps)

    def test_has_resume_no_gap(self):
        s = self._state("resume", has_resume=True)
        assert not _compute_missing_info(s)

    def test_no_interviews_for_interview_task(self):
        s = self._state("interview", has_resume=True, interview_count=0)
        gaps = _compute_missing_info(s)
        assert any("面试" in g for g in gaps)

    def test_has_interviews_no_gap(self):
        s = self._state("interview", interview_count=2)
        assert not _compute_missing_info(s)

    def test_no_applications_for_application_task(self):
        s = self._state("application", application_count=0)
        gaps = _compute_missing_info(s)
        assert any("投递" in g for g in gaps)

    def test_no_goals_for_goal_task(self):
        s = self._state("goal", active_goal_count=0)
        gaps = _compute_missing_info(s)
        assert any("目标" in g for g in gaps)

    def test_no_skills_for_job_search(self):
        s = self._state("job_search", has_resume=True, known_skills=[])
        gaps = _compute_missing_info(s)
        assert any("技能" in g for g in gaps)

    def test_general_task_no_gaps(self):
        s = self._state("general")
        assert not _compute_missing_info(s)


# ── AgentStateService.build() ─────────────────────────────────────────────────

class TestAgentStateServiceBuild:
    def _service(self, has_resume=False, app_count=0, iv_count=0):
        """Wire up a service with mocked CRUD services."""
        resume_svc = MagicMock()
        resume_svc.has_resume.return_value = has_resume

        app_svc = MagicMock()
        app_svc.list_applications_by_user.return_value = [{}] * app_count

        iv_svc = MagicMock()
        iv_svc.list_interviews_by_user.return_value = [{}] * iv_count

        return AgentStateService(
            resume_service=resume_svc,
            application_service=app_svc,
            interview_service=iv_svc,
        )

    def test_build_sets_task_family(self):
        svc = self._service()
        state = svc.build("u1", TaskFamily.JOB_SEARCH, "{}", [])
        assert state.task_family == "job_search"

    def test_build_detects_resume(self):
        svc = self._service(has_resume=True)
        state = svc.build("u1", TaskFamily.RESUME, "{}", [])
        assert state.has_resume is True

    def test_build_detects_no_resume(self):
        svc = self._service(has_resume=False)
        state = svc.build("u1", TaskFamily.RESUME, "{}", [])
        assert state.has_resume is False
        assert any("简历" in g for g in state.missing_info)

    def test_build_counts_applications(self):
        svc = self._service(app_count=3)
        state = svc.build("u1", TaskFamily.APPLICATION, "{}", [])
        assert state.application_count == 3

    def test_build_counts_interviews(self):
        svc = self._service(iv_count=2)
        state = svc.build("u1", TaskFamily.INTERVIEW, "{}", [])
        assert state.interview_count == 2

    def test_build_parses_skills_from_profile(self):
        profile = json.dumps({"skills": ["Python", "SQL", "FastAPI"]})
        svc = self._service()
        state = svc.build("u1", TaskFamily.JOB_SEARCH, profile, [])
        assert "Python" in state.known_skills
        assert "SQL" in state.known_skills

    def test_build_parses_location_from_profile(self):
        profile = json.dumps({"preferred_locations": ["Sydney", "Remote"]})
        svc = self._service()
        state = svc.build("u1", TaskFamily.JOB_SEARCH, profile, [])
        assert "Sydney" in state.preferred_locations

    def test_build_parses_experience_level(self):
        profile = json.dumps({"experience_level": "entry"})
        svc = self._service()
        state = svc.build("u1", TaskFamily.JOB_SEARCH, profile, [])
        assert state.experience_level == "entry"

    def test_build_active_goal_count(self):
        goals = [{"status": "active"}, {"status": "active"}, {"status": "done"}]
        svc = self._service()
        state = svc.build("u1", TaskFamily.GOAL, "{}", goals)
        assert state.active_goal_count == 2

    def test_build_tolerates_empty_profile(self):
        svc = self._service()
        state = svc.build("u1", TaskFamily.GENERAL, "", [])
        assert state.known_skills == []

    def test_build_tolerates_invalid_profile_json(self):
        svc = self._service()
        state = svc.build("u1", TaskFamily.GENERAL, "{not-json", [])
        assert state.known_skills == []

    def test_build_tolerates_db_failure(self):
        """Service must not raise even if DB calls fail."""
        resume_svc = MagicMock()
        resume_svc.has_resume.side_effect = RuntimeError("DB unavailable")
        app_svc = MagicMock()
        app_svc.list_applications_by_user.side_effect = RuntimeError("DB unavailable")
        iv_svc = MagicMock()
        iv_svc.list_interviews_by_user.side_effect = RuntimeError("DB unavailable")
        svc = AgentStateService(resume_svc, app_svc, iv_svc)
        state = svc.build("u1", TaskFamily.GENERAL, "{}", [])
        # Should return a default state without raising
        assert isinstance(state, AgentState)
