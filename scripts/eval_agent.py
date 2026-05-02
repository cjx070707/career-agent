"""P2 eval: 5 scenarios × 3 phrasings = 15 test cases.

Each case asserts:
  1. tool_trace — was the right tool called (or no tool for chitchat)?
  2. LLM-as-judge — answer quality score 1-5.

Run:
    PYTHONPATH=. .venv/bin/python scripts/eval_agent.py
"""

import sys
import time
from dataclasses import dataclass, field
from typing import Optional

sys.path.insert(0, ".")

from app.llm.client import LLMClient
from app.services.autonomous_agent_service import AutonomousAgentService

# ── JD embedded in test messages so analyze_gap has real input ────────────
_SAMPLE_JD = (
    "岗位：Python后端工程师实习生（悉尼）\n"
    "要求：熟悉Python/FastAPI，了解SQL，有REST API开发经验，"
    "加分项：Docker、AWS、Redis。英文沟通能力强。"
)

# ── Test case definitions ─────────────────────────────────────────────────
SCENARIOS = [
    {
        "name": "search_jobs",
        "expected_tool": "search_jobs",
        "phrases": [
            "帮我搜一下悉尼的后端实习机会",
            "有没有墨尔本的软件工程师职位",
            "我想找悉尼的金融科技实习，有哪些",
        ],
    },
    {
        "name": "analyze_gap",
        "expected_tool": "analyze_gap",
        "phrases": [
            f"帮我分析一下我的简历和这个JD的差距：\n{_SAMPLE_JD}",
            f"我适合这个岗位吗，帮我做个gap分析：\n{_SAMPLE_JD}",
            f"我的简历和下面这个JD差多少：\n{_SAMPLE_JD}",
        ],
    },
    {
        "name": "set_goal",
        "expected_tool": "set_goal",
        "phrases": [
            "我想在6月前找到一份悉尼的后端实习，帮我设定这个目标",
            "帮我设定目标：三个月内拿到软件工程师实习offer",
            "我的求职目标是今年找到数据分析师工作，帮我记录下来",
        ],
    },
    {
        "name": "get_goals",
        "expected_tool": "get_goals",
        "phrases": [
            "我现在有哪些求职目标",
            "帮我看看我设了什么目标",
            "查一下我的目标进展",
        ],
    },
    {
        "name": "chitchat_no_tool",
        "expected_tool": None,   # no tool should be called
        "phrases": [
            "你好",
            "谢谢你的帮助",
            "你能帮我做什么",
        ],
    },
]


# ── LLM-as-judge ─────────────────────────────────────────────────────────

_JUDGE_SYSTEM = (
    "你是一个评估AI求职助手回答质量的裁判。\n"
    "评分标准（只输出一个1-5的整数，不要任何解释）：\n"
    "1 — 回答与问题完全不相关，或包含明显错误\n"
    "2 — 勉强相关但信息量很少，或有明显遗漏\n"
    "3 — 基本相关，但不够准确或缺乏具体行动建议\n"
    "4 — 回答准确、有用，给出了具体建议\n"
    "5 — 准确、有用、直接解决问题，语言简洁清晰"
)


def judge_answer(llm: LLMClient, question: str, answer: str) -> int:
    prompt = f"用户问题：{question}\n\nAI回答：{answer}\n\n评分（1-5）："
    try:
        raw = llm.simple_chat(_JUDGE_SYSTEM, prompt, timeout=20.0)
        for token in raw.strip().split():
            if token.isdigit():
                score = int(token)
                if 1 <= score <= 5:
                    return score
    except Exception:
        pass
    return 0  # judge failed


# ── Result container ──────────────────────────────────────────────────────

@dataclass
class CaseResult:
    scenario: str
    phrase: str
    tool_ok: bool
    quality: int          # 0 = judge failed
    tool_trace: list = field(default_factory=list)
    error: Optional[str] = None
    latency_ms: int = 0


# ── Runner ────────────────────────────────────────────────────────────────

def run_eval() -> None:
    llm = LLMClient()
    results: list[CaseResult] = []

    # Each eval run gets a fresh user_id so goals don't accumulate across runs
    run_id = str(int(time.time()))
    base_user = f"eval_{run_id}"

    print(f"\n{'='*60}")
    print(f"Career Agent — P2 Eval   (user prefix: {base_user})")
    print(f"{'='*60}\n")

    for scenario in SCENARIOS:
        name = scenario["name"]
        expected = scenario["expected_tool"]

        print(f"── Scenario: {name} (expected_tool={expected or 'none'}) ──")

        for idx, phrase in enumerate(scenario["phrases"]):
            # Each phrase gets its own isolated user so prior turns don't
            # pollute memory and cause the LLM to skip tool calls.
            user_id = f"{base_user}_{name}_{idx}"
            svc = AutonomousAgentService()

            # get_goals needs at least one goal to exist so the LLM has
            # a reason to call the tool (empty state → LLM answers inline).
            if name == "get_goals":
                svc.respond(user_id=user_id, message="帮我设定目标：找到悉尼后端实习")

            t0 = time.monotonic()
            try:
                result = svc.respond(user_id=user_id, message=phrase)
                latency = int((time.monotonic() - t0) * 1000)

                # Tool assertion
                if expected is None:
                    tool_ok = len(result.tool_trace) == 0
                else:
                    tool_ok = expected in result.tool_trace

                quality = judge_answer(llm, phrase, result.answer)

                cr = CaseResult(
                    scenario=name,
                    phrase=phrase[:40],
                    tool_ok=tool_ok,
                    quality=quality,
                    tool_trace=result.tool_trace,
                    latency_ms=latency,
                )
            except Exception as exc:
                latency = int((time.monotonic() - t0) * 1000)
                cr = CaseResult(
                    scenario=name,
                    phrase=phrase[:40],
                    tool_ok=False,
                    quality=0,
                    error=str(exc),
                    latency_ms=latency,
                )

            results.append(cr)
            status = "✓" if cr.tool_ok else "✗"
            print(
                f"  {status} [{cr.latency_ms:>5}ms] Q={cr.quality}/5  "
                f"tools={cr.tool_trace or '[]'}  \"{cr.phrase}...\""
            )
            if cr.error:
                print(f"      ERROR: {cr.error}")

        print()

    # ── Summary ──────────────────────────────────────────────────────────
    print(f"{'='*60}")
    print("RESULTS SUMMARY")
    print(f"{'='*60}")
    print(f"{'Scenario':<22} {'Tool':>8} {'Quality':>9} {'Latency':>10}")
    print(f"{'-'*55}")

    total_tool_ok = 0
    total_quality = 0
    quality_count = 0

    for scenario in SCENARIOS:
        name = scenario["name"]
        cases = [r for r in results if r.scenario == name]
        tool_pass = sum(1 for c in cases if c.tool_ok)
        q_scores = [c.quality for c in cases if c.quality > 0]
        avg_q = sum(q_scores) / len(q_scores) if q_scores else 0.0
        avg_lat = sum(c.latency_ms for c in cases) // len(cases) if cases else 0

        total_tool_ok += tool_pass
        total_quality += sum(q_scores)
        quality_count += len(q_scores)

        print(
            f"  {name:<20} {tool_pass}/{len(cases):>4}    "
            f"{avg_q:>5.1f}/5   {avg_lat:>7}ms"
        )

    total = len(results)
    overall_q = total_quality / quality_count if quality_count else 0.0
    print(f"{'-'*55}")
    print(
        f"  {'TOTAL':<20} {total_tool_ok}/{total:>4}    "
        f"{overall_q:>5.1f}/5"
    )
    print(f"\n  工具调用准确率: {total_tool_ok}/{total} = {total_tool_ok/total*100:.0f}%")
    print(f"  答案质量均分:   {overall_q:.2f}/5  (LLM-as-judge)\n")


if __name__ == "__main__":
    run_eval()
