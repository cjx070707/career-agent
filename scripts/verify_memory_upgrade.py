#!/usr/bin/env python3
"""验收脚本：memory upgrade（running summary + user profile）

用法：
    cd ~/project-大模型应用/AGENT
    .venv/bin/python scripts/verify_memory_upgrade.py
"""

import json
import sys
import os

# 保证能 import app.*
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

PASS = "\033[92m✅ PASS\033[0m"
FAIL = "\033[91m❌ FAIL\033[0m"
INFO = "\033[94mℹ️ \033[0m"

results = []

def check(label, ok, detail=""):
    tag = PASS if ok else FAIL
    print(f"  {tag}  {label}")
    if detail:
        print(f"         {detail}")
    results.append(ok)

# ── 初始化 DB ────────────────────────────────────────────────────────
print("\n【1】初始化 DB")
try:
    from app.db.session import init_db, get_connection
    init_db()
    check("init_db() 无异常", True)
except Exception as e:
    check("init_db() 无异常", False, str(e))
    sys.exit(1)

# ── 检查新表是否存在 ──────────────────────────────────────────────────
print("\n【2】新表检查")
with get_connection() as conn:
    tables = {r[0] for r in conn.execute("SELECT name FROM sqlite_master WHERE type='table'").fetchall()}

check("conversation_summaries 表存在", "conversation_summaries" in tables)
check("user_profiles 表存在", "user_profiles" in tables)
check("conversation_turns 表存在", "conversation_turns" in tables)

# ── MemoryService 基本读写 ────────────────────────────────────────────
print("\n【3】MemoryService 读写")
from app.services.memory_service import MemoryService, WINDOW_SIZE, ARCHIVE_THRESHOLD

mem = MemoryService()
TEST_USER = "__verify_test__"

# 清理上次遗留数据
with get_connection() as conn:
    conn.execute("DELETE FROM conversation_turns WHERE user_id=?", (TEST_USER,))
    conn.execute("DELETE FROM conversation_summaries WHERE user_id=?", (TEST_USER,))
    conn.execute("DELETE FROM user_profiles WHERE user_id=?", (TEST_USER,))

check(f"WINDOW_SIZE = {WINDOW_SIZE}（建议 10-12）", 10 <= WINDOW_SIZE <= 14,
      f"实际值：{WINDOW_SIZE}")
check(f"ARCHIVE_THRESHOLD = {ARCHIVE_THRESHOLD}（应 > WINDOW_SIZE）",
      ARCHIVE_THRESHOLD > WINDOW_SIZE,
      f"实际值：{ARCHIVE_THRESHOLD}")

# save_turn
mem.save_turn(TEST_USER, "你好", "你好！")
mem.save_turn(TEST_USER, "我想找工作", "好的，请告诉我你的目标。")
count = mem.count_turns(TEST_USER)
check("save_turn 写入成功（count=4）", count == 4, f"实际 count={count}")

# load_recent_messages
msgs = mem.load_recent_messages(TEST_USER)
check("load_recent_messages 返回正确条数", len(msgs) == 4, f"实际={len(msgs)}")
check("消息顺序：最旧在前", msgs[0].role == "user" and msgs[0].content == "你好")

# summary 读写
mem.save_summary(TEST_USER, "用户想在 Sydney 找 fintech 实习。")
summary = mem.load_summary(TEST_USER)
check("save/load summary 正常", summary == "用户想在 Sydney 找 fintech 实习。")

# user_profile 读写
mem.save_user_profile(TEST_USER, json.dumps({"location": "Sydney", "industry": "fintech"}))
profile = mem.load_user_profile(TEST_USER)
check("save/load user_profile 正常", "Sydney" in profile)

# ── archive 逻辑 ──────────────────────────────────────────────────────
print("\n【4】Archive 逻辑")

# 塞够 ARCHIVE_THRESHOLD + 2 条数据触发压缩判断
with get_connection() as conn:
    conn.execute("DELETE FROM conversation_turns WHERE user_id=?", (TEST_USER,))
    rows = []
    for i in range(ARCHIVE_THRESHOLD + 2):
        role = "user" if i % 2 == 0 else "assistant"
        rows.append((TEST_USER, role, f"消息{i}"))
    conn.executemany(
        "INSERT INTO conversation_turns (user_id, role, content) VALUES (?,?,?)", rows
    )

total = mem.count_turns(TEST_USER)
check(f"成功塞入 {total} 条 turns", total == ARCHIVE_THRESHOLD + 2)
check("needs_archive() 返回 True", mem.needs_archive(TEST_USER))

candidates = mem.get_archive_candidates(TEST_USER)
expected_candidates = total - WINDOW_SIZE
check(
    f"get_archive_candidates 返回 {len(candidates)} 条（应={expected_candidates}）",
    len(candidates) == expected_candidates,
)

# 模拟删除 archived turns
ids = [t.id for t in candidates]
mem.delete_turns_by_ids(ids)
remaining = mem.count_turns(TEST_USER)
check(f"删除后剩余 {remaining} 条（应={WINDOW_SIZE}）", remaining == WINDOW_SIZE)

# ── system prompt 注入检查 ────────────────────────────────────────────
print("\n【5】System prompt 注入")
from app.services.autonomous_agent_service import AutonomousAgentService

# Mock memory
class MockMem:
    def load_recent_messages(self, uid): return []
    def load_summary(self, uid): return "用户之前聊过想找 data science 实习。"
    def load_user_profile(self, uid): return json.dumps({"location": "Sydney", "industry": "fintech"})
    def save_turn(self, *a): pass
    def count_turns(self, uid): return 0
    def needs_archive(self, uid): return False

class MockGoals:
    def get_active_goals(self, uid): return []

class MockProfiler:
    def update_profile(self, *a): pass

class MockSummarizer:
    def maybe_compress(self, uid): pass

svc = AutonomousAgentService.__new__(AutonomousAgentService)
svc.memory = MockMem()
svc.goals = MockGoals()
svc.profiler = MockProfiler()
svc.summarizer = MockSummarizer()

prompt = svc._build_system_prompt(
    "testuser",
    goals=[],
    summary="用户之前聊过想找 data science 实习。",
    user_profile=json.dumps({"location": "Sydney", "industry": "fintech"}),
)

check("system prompt 包含历史摘要", "历史对话摘要" in prompt and "data science" in prompt)
check("system prompt 包含用户偏好", "用户已知偏好" in prompt and "Sydney" in prompt)

# ── 清理 ─────────────────────────────────────────────────────────────
with get_connection() as conn:
    conn.execute("DELETE FROM conversation_turns WHERE user_id=?", (TEST_USER,))
    conn.execute("DELETE FROM conversation_summaries WHERE user_id=?", (TEST_USER,))
    conn.execute("DELETE FROM user_profiles WHERE user_id=?", (TEST_USER,))

# ── 总结 ─────────────────────────────────────────────────────────────
print()
passed = sum(results)
total_checks = len(results)
if passed == total_checks:
    print(f"\033[92m全部通过 {passed}/{total_checks}\033[0m ✨ memory upgrade 验收完成\n")
    sys.exit(0)
else:
    print(f"\033[91m{passed}/{total_checks} 通过，{total_checks - passed} 项失败\033[0m\n")
    sys.exit(1)
