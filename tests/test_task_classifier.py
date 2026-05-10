"""Unit tests for app/routing/task_classifier.py."""
from __future__ import annotations

import pytest

from app.routing.task_classifier import TaskFamily, classify, score_turn


# ── classify() ───────────────────────────────────────────────────────────────

class TestClassify:
    def test_job_search_find_jobs(self):
        assert classify("帮我找一些 Python backend 岗位") == TaskFamily.JOB_SEARCH

    def test_job_search_intern(self):
        assert classify("有没有 data engineer intern 的岗位") == TaskFamily.JOB_SEARCH

    def test_job_search_tech_stack(self):
        assert classify("推荐一些 React 前端职位") == TaskFamily.JOB_SEARCH

    def test_interview_prep(self):
        assert classify("怎么准备 system design 面试") == TaskFamily.INTERVIEW

    def test_interview_feedback(self):
        assert classify("Canva 面试没过，反馈是 system design 不行") == TaskFamily.INTERVIEW

    def test_interview_oa(self):
        assert classify("我收到了 OA，怎么准备") == TaskFamily.INTERVIEW

    def test_application_tracking(self):
        assert classify("我最近投了哪些岗位") == TaskFamily.APPLICATION

    def test_application_status(self):
        assert classify("申请状态是什么") == TaskFamily.APPLICATION

    def test_resume_upload(self):
        assert classify("帮我分析简历和这个 JD 的差距") == TaskFamily.RESUME

    def test_resume_gap(self):
        assert classify("我的 gap 分析结果是什么") == TaskFamily.RESUME

    def test_goal_set(self):
        assert classify("帮我设定一个求职目标") == TaskFamily.GOAL

    def test_goal_progress(self):
        assert classify("我的进展怎么样") == TaskFamily.GOAL

    def test_general_greeting(self):
        assert classify("你好") == TaskFamily.GENERAL

    def test_general_vague(self):
        assert classify("给我一些建议") == TaskFamily.GENERAL

    def test_general_unrelated(self):
        assert classify("今天天气不错") == TaskFamily.GENERAL


# ── score_turn() ──────────────────────────────────────────────────────────────

class TestScoreTurn:
    def test_relevant_turn_scores_above_zero(self):
        score = score_turn("我在找 Python 岗位", TaskFamily.JOB_SEARCH)
        assert score > 0

    def test_irrelevant_turn_scores_zero(self):
        score = score_turn("面试反馈很差", TaskFamily.JOB_SEARCH)
        assert score == 0

    def test_general_family_always_scores_above_zero(self):
        # GENERAL turns should always be considered relevant
        assert score_turn("任何内容", TaskFamily.GENERAL) > 0

    def test_interview_turn_scores_for_interview_family(self):
        assert score_turn("我的 Canva 面试没过", TaskFamily.INTERVIEW) > 0

    def test_resume_turn_scores_for_resume_family(self):
        assert score_turn("你的简历缺少项目经验", TaskFamily.RESUME) > 0

    def test_resume_turn_does_not_score_for_goal_family(self):
        assert score_turn("你的简历缺少项目经验", TaskFamily.GOAL) == 0


# ── context budget integration — _build_messages behaviour ───────────────────

class TestBuildMessagesContextBudget:
    """Test that AutonomousAgentService._build_messages respects the budget."""

    def _make_turns(self, pairs: list[tuple[str, str]]):
        """Return a flat list of MemoryTurn-like objects from (user, agent) pairs."""
        from app.services.memory_service import MemoryTurn

        turns = []
        idx = 1
        for user_msg, agent_msg in pairs:
            turns.append(MemoryTurn(id=idx, role="user", content=user_msg))
            idx += 1
            turns.append(MemoryTurn(id=idx, role="assistant", content=agent_msg))
            idx += 1
        return turns

    def _build(self, history, message, family=TaskFamily.JOB_SEARCH):
        from app.services.autonomous_agent_service import AutonomousAgentService
        svc = AutonomousAgentService.__new__(AutonomousAgentService)
        return svc._build_messages(history, message, task_family=family)

    def test_always_includes_current_message(self):
        msgs = self._build([], "找 Python 岗位")
        assert msgs[-1] == {"role": "user", "content": "找 Python 岗位"}

    def test_anchor_turns_always_included(self):
        # Build 6 exchanges (12 turns), only the last 2 exchanges are anchored
        history = self._make_turns([
            ("找工作", "好的"),
            ("有没有实习", "有"),
            ("推荐 React 岗位", "这里有几个"),
            ("golang 呢", "有一些"),
            ("薪资怎么样", "根据等级不同"),
            ("继续", "好"),
        ])
        msgs = self._build(history, "再找找", TaskFamily.JOB_SEARCH)
        contents = [m["content"] for m in msgs]
        # Last 2 exchanges = "薪资怎么样" + "根据等级不同" + "继续" + "好"
        assert "薪资怎么样" in contents
        assert "继续" in contents

    def test_irrelevant_older_turns_excluded(self):
        # Mix of job_search and interview turns; ask about jobs → interview turns drop
        history = self._make_turns([
            # interview turns (older)
            ("面试结果怎么样", "Canva 面试没过"),
            ("面试反馈", "system design 不行"),
            # job search turns (recent anchor zone)
            ("找 Python 实习", "有几个"),
            ("薪资范围", "60-80k"),
        ])
        msgs = self._build(history, "还有其他 Python 岗位吗", TaskFamily.JOB_SEARCH)
        contents = [m["content"] for m in msgs]
        # Anchor: last 4 sanitised turns (job search) are always included
        assert "找 Python 实习" in contents
        # Old interview turns should NOT be included (irrelevant to job_search)
        assert "面试结果怎么样" not in contents

    def test_relevant_older_turns_included(self):
        # All older turns are also job search — most-recent relevant ones included.
        # Phase 2 allocates 2 slots to semantic recall, so session_budget = 2.
        # The most-recent relevant older turns ("Python 岗位呢") should appear.
        history = self._make_turns([
            ("找实习", "有几个实习岗位"),       # older but relevant
            ("Python 岗位呢", "这里有很多"),     # older but relevant (most-recent ↑)
            ("backend 薪资", "根据经验不同"),    # anchor zone
            ("remote 可以吗", "有一些 remote"),  # anchor zone
        ])
        msgs = self._build(history, "再找找", TaskFamily.JOB_SEARCH)
        contents = [m["content"] for m in msgs]
        # Most-recent relevant older turn should be kept
        assert "Python 岗位呢" in contents

    def test_total_history_capped_at_budget(self):
        # 10 exchanges = 20 turns; budget is 8 history messages max
        history = self._make_turns([
            ("找工作", "好的"),
            ("Python 实习", "有"),
            ("golang 岗", "有些"),
            ("frontend 呢", "也有"),
            ("backend 薪资", "不同"),
            ("remote 岗", "有"),
            ("intern 实习", "有不少"),
            ("sydney 岗位", "有"),
            ("data 岗位", "有"),
            ("ml 岗位", "有"),
        ])
        msgs = self._build(history, "再查查", TaskFamily.JOB_SEARCH)
        # Exclude the current user message itself; count history
        history_msgs = [m for m in msgs if m["content"] != "再查查"]
        from app.services.autonomous_agent_service import AutonomousAgentService
        assert len(history_msgs) <= AutonomousAgentService._HISTORY_BUDGET

    def test_skips_error_assistant_turns(self):
        from app.services.memory_service import MemoryTurn
        history = [
            MemoryTurn(id=1, role="user", content="找工作"),
            MemoryTurn(id=2, role="assistant", content="抱歉，暂时无法回答：connection error"),
        ]
        msgs = self._build(history, "再试试", TaskFamily.JOB_SEARCH)
        contents = [m["content"] for m in msgs]
        assert "抱歉，暂时无法回答：connection error" not in contents
