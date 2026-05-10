"""Tests for MemoryVectorService and Phase 2 semantic recall integration."""
from __future__ import annotations

from pathlib import Path


# ── MemoryVectorService unit tests ───────────────────────────────────────────

class TestMemoryVectorService:
    """Uses isolated_runtime (tmp chroma dir) so tests never share state."""

    def _make_service(self, isolated_runtime):
        from app.services.memory_vector_service import MemoryVectorService
        return MemoryVectorService(
            persist_directory=isolated_runtime["chroma_path"],
            collection_name="test_mem_" + isolated_runtime["collection_name"][-8:],
        )

    def test_document_count_starts_at_zero(self, isolated_runtime):
        svc = self._make_service(isolated_runtime)
        assert svc.document_count("user-a") == 0

    def test_index_turn_increments_count(self, isolated_runtime):
        svc = self._make_service(isolated_runtime)
        svc.index_turn(turn_id=1, user_id="u1", session_id="s1",
                       role="user", content="找 Python backend 实习")
        assert svc.document_count("u1") == 1

    def test_index_turn_skips_empty_content(self, isolated_runtime):
        svc = self._make_service(isolated_runtime)
        svc.index_turn(turn_id=1, user_id="u1", session_id="s1", role="user", content="")
        svc.index_turn(turn_id=2, user_id="u1", session_id="s1", role="user", content="   ")
        assert svc.document_count("u1") == 0

    def test_search_returns_empty_when_no_turns(self, isolated_runtime):
        svc = self._make_service(isolated_runtime)
        results = svc.search("no-user", "找实习")
        assert results == []

    def test_search_returns_indexed_turn(self, isolated_runtime):
        svc = self._make_service(isolated_runtime)
        svc.index_turn(turn_id=1, user_id="u2", session_id="s1",
                       role="user", content="我在找 Python backend 实习岗位")
        results = svc.search("u2", "Python 实习")
        assert len(results) == 1
        assert results[0]["role"] == "user"
        assert "Python" in results[0]["content"]

    def test_search_isolates_by_user_id(self, isolated_runtime):
        svc = self._make_service(isolated_runtime)
        svc.index_turn(turn_id=1, user_id="alice", session_id="s1",
                       role="user", content="Alice 找 Python 工作")
        svc.index_turn(turn_id=2, user_id="bob", session_id="s2",
                       role="user", content="Bob 找 Java 工作")
        alice_results = svc.search("alice", "Python 工作")
        assert all("Alice" in r["content"] for r in alice_results)

    def test_search_excludes_current_session(self, isolated_runtime):
        svc = self._make_service(isolated_runtime)
        svc.index_turn(turn_id=1, user_id="u3", session_id="current-session",
                       role="user", content="当前 session 的内容")
        svc.index_turn(turn_id=2, user_id="u3", session_id="old-session",
                       role="user", content="另一个 session 的内容")
        results = svc.search("u3", "session", exclude_session="current-session")
        contents = [r["content"] for r in results]
        assert not any("当前" in c for c in contents)
        assert any("另一个" in c for c in contents)

    def test_search_respects_n_results_cap(self, isolated_runtime):
        svc = self._make_service(isolated_runtime)
        for i in range(5):
            svc.index_turn(turn_id=i, user_id="u4", session_id="s",
                           role="user", content=f"这是第 {i} 条消息关于 Python 实习")
        results = svc.search("u4", "Python 实习", n_results=2)
        assert len(results) <= 2

    def test_index_turn_upserts_same_id(self, isolated_runtime):
        """Upserting the same turn_id+user_id should not duplicate."""
        svc = self._make_service(isolated_runtime)
        svc.index_turn(turn_id=1, user_id="u5", session_id="s",
                       role="user", content="第一版内容")
        svc.index_turn(turn_id=1, user_id="u5", session_id="s",
                       role="user", content="更新后的内容")
        assert svc.document_count("u5") == 1

    def test_search_returns_role_in_result(self, isolated_runtime):
        svc = self._make_service(isolated_runtime)
        svc.index_turn(turn_id=1, user_id="u6", session_id="s",
                       role="assistant", content="根据你的简历，建议申请这些岗位")
        results = svc.search("u6", "简历岗位")
        assert results[0]["role"] == "assistant"


# ── _build_messages Phase 2 integration ──────────────────────────────────────

class TestBuildMessagesPhase2:
    """Test that semantic_turns are correctly merged into the message list."""

    def _build(self, history, message, semantic_turns=None, family=None):
        from app.routing.task_classifier import TaskFamily
        from app.services.autonomous_agent_service import AutonomousAgentService
        svc = AutonomousAgentService.__new__(AutonomousAgentService)
        return svc._build_messages(
            history,
            message,
            task_family=family or TaskFamily.JOB_SEARCH,
            semantic_turns=semantic_turns,
        )

    def test_semantic_turns_prepended_before_session_history(self):
        from app.services.memory_service import MemoryTurn
        history = [
            MemoryTurn(id=1, role="user", content="当前 session 的问题"),
            MemoryTurn(id=2, role="assistant", content="当前 session 的回答"),
        ]
        semantic = [{"role": "user", "content": "另一个 session 的相关信息"}]
        msgs = self._build(history, "新问题", semantic_turns=semantic)
        # Semantic turn should appear before session history
        contents = [m["content"] for m in msgs]
        sem_idx = contents.index("另一个 session 的相关信息")
        sess_idx = contents.index("当前 session 的问题")
        assert sem_idx < sess_idx

    def test_semantic_turns_deduplicated_against_session(self):
        from app.services.memory_service import MemoryTurn
        shared_content = "我在找 Python 实习"
        history = [
            MemoryTurn(id=1, role="user", content=shared_content),
            MemoryTurn(id=2, role="assistant", content="好的"),
        ]
        # Same content as in session — should be deduped
        semantic = [{"role": "user", "content": shared_content}]
        msgs = self._build(history, "继续", semantic_turns=semantic)
        contents = [m["content"] for m in msgs]
        assert contents.count(shared_content) == 1

    def test_empty_semantic_turns_handled_gracefully(self):
        msgs = self._build([], "新问题", semantic_turns=[])
        assert msgs[-1]["content"] == "新问题"
        assert len(msgs) == 1

    def test_none_semantic_turns_handled_gracefully(self):
        msgs = self._build([], "新问题", semantic_turns=None)
        assert msgs[-1]["content"] == "新问题"

    def test_semantic_turns_with_empty_content_skipped(self):
        semantic = [{"role": "user", "content": ""}, {"role": "user", "content": "   "}]
        msgs = self._build([], "新问题", semantic_turns=semantic)
        # Only the current message
        assert len(msgs) == 1
