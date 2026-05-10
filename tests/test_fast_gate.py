"""Unit tests for app/routing/fast_gate.py.

Tests that the fast gate correctly identifies pure chitchat vs career queries.
No LLM calls — pure deterministic logic.
"""
import pytest
from app.routing.fast_gate import GateDecision, fast_gate


# ── Chitchat cases — should be intercepted ──────────────────────────────────

@pytest.mark.parametrize("msg", [
    # Greetings
    "你好",
    "您好",
    "hi",
    "Hi",
    "HI",
    "hello",
    "Hello!",
    "hey",
    "嗨",
    "哈喽",
    "早",
    "晚上好",
    "下午好",
    "早上好",
    "你好！",
    "嗨～",
    # Thanks
    "谢谢",
    "谢了",
    "感谢",
    "多谢",
    "thanks",
    "thank you",
    "thx",
    "谢谢！",
    # Acknowledgements
    "好的",
    "好",
    "ok",
    "OK",
    "okay",
    "嗯",
    "明白",
    "收到",
    "了解",
    "知道了",
    "好哒",
    "好的。",
    # Farewells
    "再见",
    "拜拜",
    "bye",
    "goodbye",
    "晚安",
    "先这样",
    # Filler
    "哈哈",
    "哈哈哈",
    "😄",
    "👍",
    "🙏",
])
def test_chitchat_detected(msg):
    result = fast_gate(msg)
    assert result.is_chitchat is True, f"Expected chitchat for {msg!r}, got reason={result.reason}"
    assert result.reason == "chitchat_pattern"


# ── Leading/trailing whitespace shouldn't matter ─────────────────────────────

def test_strips_whitespace():
    result = fast_gate("  你好  ")
    assert result.is_chitchat is True


# ── Career / substantive messages — must NOT be intercepted ─────────────────

@pytest.mark.parametrize("msg", [
    # Explicit job searches
    "帮我找 Python 实习",
    "我想找数据分析岗位",
    "推荐适合我的岗位",
    "搜索北京的后端工程师职位",
    # Resume / profile
    "帮我分析一下我的简历",
    "我的简历有哪些不足",
    "结合我的情况推荐适合投的岗位",
    # Goal setting
    "我想设定一个求职目标",
    "帮我制定找工作计划",
    # Interview / application
    "我刚面了字节的一面",
    "我投了腾讯的产品经理岗位",
    # Longer messages that happen to start with chitchat words
    "你好，我想了解一下前端工程师的面试流程",
    "谢谢，能再帮我搜搜上海的实习岗位吗",
    # English career queries
    "help me find a software engineering internship",
    "what jobs should I apply for",
])
def test_career_queries_not_intercepted(msg):
    result = fast_gate(msg)
    assert result.is_chitchat is False, f"Expected NOT chitchat for {msg!r}"


# ── Too-long guard ────────────────────────────────────────────────────────────

def test_too_long_returns_false():
    # Exactly 16 chars — one over the limit
    msg = "你好你好你好你好你好你好你好你好"  # 16 Chinese chars = 16 chars
    assert len(msg.strip()) > 15
    result = fast_gate(msg)
    assert result.is_chitchat is False
    assert result.reason == "too_long"


def test_exactly_15_chars_checked():
    # A 15-char greeting should still be checked (not short-circuited by length guard)
    msg = "早上好" + "！" * 12   # 3 + 12 = 15 chars
    assert len(msg.strip()) == 15
    result = fast_gate(msg)
    # It matches the greeting pattern, so should be chitchat
    assert result.is_chitchat is True


# ── GateDecision dataclass ────────────────────────────────────────────────────

def test_gate_decision_fields():
    d = GateDecision(is_chitchat=True, reason="chitchat_pattern")
    assert d.is_chitchat is True
    assert d.reason == "chitchat_pattern"


def test_no_pattern_match_reason():
    result = fast_gate("abc")  # short but no pattern
    assert result.is_chitchat is False
    assert result.reason == "no_pattern_match"
