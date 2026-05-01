#!/usr/bin/env python3
"""验收脚本：Structured Logging / Trace

用法：
    cd ~/project-大模型应用/AGENT
    .venv/bin/python scripts/verify_trace_logger.py
"""

import json
import os
import sys
import time

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

PASS = "\033[92m✅ PASS\033[0m"
FAIL = "\033[91m❌ FAIL\033[0m"
results = []

def check(label, ok, detail=""):
    tag = PASS if ok else FAIL
    print(f"  {tag}  {label}")
    if detail:
        print(f"         {detail}")
    results.append(ok)

from pathlib import Path

LOG_FILE = Path(__file__).resolve().parents[1] / "logs" / "agent_trace.jsonl"

# ── 1. 导入检查 ───────────────────────────────────────────────────────
print("\n【1】模块导入")
try:
    from app.utils.trace_logger import tracer, TraceLogger
    check("trace_logger 导入成功", True)
except Exception as e:
    check("trace_logger 导入成功", False, str(e))
    sys.exit(1)

# ── 2. 日志写入 ───────────────────────────────────────────────────────
print("\n【2】日志写入")

# 记录写入前的行数
before = 0
if LOG_FILE.exists():
    before = sum(1 for _ in open(LOG_FILE, encoding="utf-8"))

tracer.log_llm_call(
    user_id="__verify__",
    iteration=0,
    latency_ms=123,
    had_tool_calls=True,
    n_messages=4,
)
tracer.log_tool_call(
    user_id="__verify__",
    tool_name="search_jobs",
    args={"user_id": "__verify__", "query": "fintech intern Sydney"},
    latency_ms=45,
    ok=True,
)
tracer.log_tool_call(
    user_id="__verify__",
    tool_name="analyze_gap",
    args={"user_id": "__verify__", "jd_text": "x" * 200},  # long arg — should truncate
    latency_ms=890,
    ok=False,
    error="timeout",
)
tracer.log_agent_turn(
    user_id="__verify__",
    total_latency_ms=1234,
    tool_trace=["search_jobs", "analyze_gap"],
    stage="tool",
    iterations=2,
)

check("logs/agent_trace.jsonl 文件存在", LOG_FILE.exists())

after = sum(1 for _ in open(LOG_FILE, encoding="utf-8"))
check(f"写入了 4 行（before={before}, after={after}）", after - before == 4,
      f"差值={after - before}")

# ── 3. 日志格式验证 ───────────────────────────────────────────────────
print("\n【3】日志格式")

lines = open(LOG_FILE, encoding="utf-8").readlines()
last4 = [json.loads(l) for l in lines[-4:]]

llm_ev = last4[0]
check("llm_call 事件结构完整",
      all(k in llm_ev for k in ["event","ts","user_id","iteration","latency_ms","had_tool_calls","n_messages"]),
      str(list(llm_ev.keys())))
check("llm_call.had_tool_calls=True", llm_ev["had_tool_calls"] is True)
check("llm_call.latency_ms=123", llm_ev["latency_ms"] == 123)

tool_ev = last4[1]
check("tool_call 事件结构完整",
      all(k in tool_ev for k in ["event","ts","user_id","tool","args","latency_ms","ok"]))
check("tool_call.ok=True", tool_ev["ok"] is True)
check("tool_call.tool=search_jobs", tool_ev["tool"] == "search_jobs")

tool_err = last4[2]
check("tool_call error 事件记录正确", tool_err["ok"] is False and tool_err["error"] == "timeout")

# 长 arg 应被截断
jd_val = tool_err["args"].get("jd_text", "")
check(f"长参数被截断（len={len(jd_val)}，应≤123）", len(jd_val) <= 123, jd_val[:30])

turn_ev = last4[3]
check("agent_turn 事件结构完整",
      all(k in turn_ev for k in ["event","ts","user_id","stage","iterations","tool_trace","total_latency_ms"]))
check("agent_turn.tool_trace 正确", turn_ev["tool_trace"] == ["search_jobs", "analyze_gap"])
check("agent_turn.iterations=2", turn_ev["iterations"] == 2)

# ── 4. autonomous_agent_service 引用检查 ──────────────────────────────
print("\n【4】Agent 服务集成")
src = open(
    Path(__file__).resolve().parents[1] / "app/services/autonomous_agent_service.py"
).read()
check("import tracer 存在", "from app.utils.trace_logger import tracer" in src)
check("log_llm_call 调用存在", "tracer.log_llm_call(" in src)
check("log_tool_call 调用存在", "tracer.log_tool_call(" in src)
check("log_agent_turn 调用存在", "tracer.log_agent_turn(" in src)
check("time.monotonic() 计时存在", "time.monotonic()" in src)

# ── 总结 ─────────────────────────────────────────────────────────────
passed = sum(results)
total = len(results)
print()
if passed == total:
    print(f"\033[92m全部通过 {passed}/{total}\033[0m ✨ structured logging 验收完成\n")
    sys.exit(0)
else:
    print(f"\033[91m{passed}/{total} 通过，{total - passed} 项失败\033[0m\n")
    sys.exit(1)
