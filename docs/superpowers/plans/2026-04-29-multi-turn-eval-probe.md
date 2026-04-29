# Multi-Turn Eval Probe — 用 5 条双轮 case 决定下一个 Phase

> Plan date: 2026-04-29
> Scope: 用 5 条 hand-crafted 双轮 case 当作诊断器，跑一次，根据失败模式决定下一步 attack Phase 3B/4、Phase 5 还是单点 Resolver 修复。**这不是 CI 硬门禁**，是探针。

**Goal**: 新增一个 multi-turn eval，对同一 `user_id` 连续发 N 条消息打 `/chat`，每条都跑断言。报告产出后，下一阶段计划再写。

**Architecture**: 复用现有 eval harness 思路（参考 `evals/run_career_core_replay.py` 与 `evals/run_eval.py`）：本地起 FastAPI 服务，按 case 注入种子数据，按顺序发消息（同一 user_id，确保 memory + context 真实累积），跑断言，输出 `multi_turn_latest.md` + `multi_turn_latest.json`。

**Tech Stack**: Python 3, `httpx`/`requests`, JSONL dataset, 复用 `evals/run_eval.py` 的断言词汇（`plan_task_type` / `plan_needs_more_context` / `tool_trace_equals` / `answer_contains_all` 等）。

**Why this exists**: 当前 4 个候选下一步——`career_insights` 多证据动态改路、双轮闭环硬门禁、输出层统一、300 条抗噪样本——其中"动态改路"**不是 Phase 4 机器没做**，而是 Phase 4 机器（`switch_tool / replan_strategy / ask_for_context` + `MAX_REPLANS` 真闭环）已经在 `plan_executor.py` 落地，**但 `career_insights` 链路没把它用起来**。所以问题真正长什么样还不清楚：到底是 ToolResolver 给 `career_insights` 只映射了单工具 chain，还是 `decide_react_action` 在这个 task_type 下永远返回 `continue/finish`，还是输出层风格漂移，还是 Resolver 在二跳没接住补充信息。5 条精心设计的双轮 case 几小时内就能把这个真正的卡点定位到具体模块。

---

## File Structure

新增：

- `evals/dataset.multi_turn.jsonl` — 5 条双轮 case
- `evals/run_multi_turn_eval.py` — 多轮 runner（复用现有 seeder 和断言）
- `evals/reports/multi_turn_latest.md` / `.json` — 报告（gitignored）
- `docs/superpowers/plans/2026-04-29-multi-turn-eval-probe-findings.md` — Task 3 结束时产出，不在本计划内预先创建

**`app/` 下的生产代码本计划不动一行。** 这是探针，不是 feature。

---

## Task 1 — 写 5 条双轮 dataset

**Files**:
- New: `evals/dataset.multi_turn.jsonl`

**Steps**:

- [ ] Step 1: 定义每条 case 的 JSON 结构

每行一条 case：

```json
{
  "id": "string",
  "user_id": "string",
  "seed": { "candidates": [...], "resumes": [...], "applications": [...], "interviews": [...] },
  "turns": [
    { "message": "first user message", "expect": { /* turn 1 assertions */ } },
    { "message": "second user message", "expect": { /* turn 2 assertions */ } }
  ]
}
```

`expect` 的字段直接复用 `evals/run_eval.py` 已有词汇，避免新发明断言类型。

- [ ] Step 2: 写 5 条 case

**Case 1 — `resume-optimization-two-turn`**（探针：Phase 5 输出层）
- turn 1: `帮我优化简历` → `plan_task_type=resume_analysis`, `plan_needs_more_context=True`, `plan_missing_context_contains=["resume"]`, `tool_trace_equals=[]`
- turn 2: 粘贴一段简短简历内容 → `tool_trace` 含 `get_resume_by_id`（或同义解析路径），`answer_contains_all=["结论", "证据", "行动"]`（**故意写严：用来探 ResponseFormatter 是否已经统一三段输出**）

**Case 2 — `job-match-two-turn`**（探针：Resolver 二跳信息接收）
- turn 1: `帮我看看这个岗位适不适合我` → `plan_task_type=job_match`, `plan_missing_context_contains` 含 `job_detail` 或 `job_query`
- turn 2: 粘贴一段 JD 文本 → `tool_trace` 含 `match_resume_to_jobs`, `sources_nonempty`, `answer_contains_any=["匹配"]`

**Case 3 — `career-insights-two-turn`**（探针：现有 Phase 4 机器在 `career_insights` 上是否真的被触发）
- seed: applications 多条、interviews 0 条
- turn 1: `我投了很多岗位但都没回音，下一步怎么办？` → `plan_task_type=career_insights`, `tool_trace` 至少含 `get_career_insights`，answer 提到瓶颈类型
- turn 2: `我目标是 backend intern` → 期望诊断收敛到 `resume_positioning`（针对该目标），`answer_contains_any=["resume_positioning", "简历定位", "简历命中度"]`
- **额外断言**（这才是 Phase 4 机器有没有被用上的关键探针）：
  - `loop_trace[*].action_before` 集合在 turn 1 或 turn 2 中**应**出现 `switch_tool` 或 `replan_strategy` 之一；如果两轮里全是 `continue/finish`，说明机器虽然在 executor 里，但 `career_insights` 链路没让它转起来
  - `resolver_trace` 中 `executor.replan_count > 0` 至少出现一次

**Case 4 — `interview-prep-two-turn`**（探针：interview_prep 完整链路 + 输出统一）
- turn 1: `我下周有面试` → `plan_task_type` 是 `interview_prep` 或 `fallback`，期望 `follow_up_question` 追问公司/岗位/轮次
- turn 2: `Atlassian 的 backend intern, tech1 轮` → `tool_trace` 含 `get_interview_feedback` 或执行 interview prep 路径, `answer_contains_all=["结论", "证据", "行动"]`

**Case 5 — `third-party-then-self`**（探针：profile 防污染 + 主体切换）
- turn 1: `我朋友想转 PM，他怎么准备？` → 当前用户 profile **不应**被写入 PM 目标。断言：`tool_used != "get_candidate_profile"` 或 plan 标记为第三方语境。
- turn 2: `那我自己呢，我现在做后端` → 期望 profile/answer 围绕 backend，而非 PM。断言：`answer_contains_any=["backend", "后端"]`，且 `answer_not_contains=["PM", "产品经理"]`。

- [ ] Step 3: Sanity check JSONL 可解析

```bash
python3 -c "import json; [json.loads(l) for l in open('evals/dataset.multi_turn.jsonl')]; print('ok')"
```

---

## Task 2 — 写多轮 runner

**Files**:
- New: `evals/run_multi_turn_eval.py`

**Steps**:

- [ ] Step 1: 骨架（参照 `run_career_core_replay.py` 与 `run_eval.py`）

```python
# evals/run_multi_turn_eval.py
import argparse, json, sys
from pathlib import Path
import httpx

# 复用现有 helper；如不可直接 import，再 inline 最小版本。
from evals.run_eval import seed_case, check_expectations

def post_chat(base_url: str, user_id: str, message: str) -> dict:
    r = httpx.post(f"{base_url}/chat", json={"user_id": user_id, "message": message}, timeout=60)
    r.raise_for_status()
    return r.json()

def run_case(base_url: str, case: dict) -> dict:
    if "seed" in case:
        seed_case(base_url, case["seed"])
    turns = []
    for idx, turn in enumerate(case["turns"], start=1):
        resp = post_chat(base_url, case["user_id"], turn["message"])
        checks = check_expectations(resp, turn["expect"])
        turns.append({"turn": idx, "checks": checks, "resp_summary": {
            "plan_task_type": resp.get("plan", {}).get("task_type"),
            "tool_trace": resp.get("tool_trace"),
            "needs_more_context": resp.get("plan", {}).get("needs_more_context"),
            "answer_excerpt": (resp.get("answer") or "")[:160],
        }})
    return {"id": case["id"], "turns": turns,
            "passed": all(all(c["ok"] for c in t["checks"]) for t in turns)}
```

- [ ] Step 2: CLI + report writers（Markdown 报告必须按 turn 列出失败原因，否则探针的诊断信号就废了）

```python
def write_md(path: Path, results: list[dict]) -> None:
    lines = ["# Multi-Turn Eval Report\n"]
    total = len(results); passed = sum(1 for r in results if r["passed"])
    lines.append(f"- total: {total} | passed: {passed} | failed: {total - passed}\n")
    for r in results:
        lines.append(f"\n## {r['id']} — {'PASS' if r['passed'] else 'FAIL'}\n")
        for t in r["turns"]:
            lines.append(f"\n### turn {t['turn']}\n")
            lines.append(f"- plan.task_type: `{t['resp_summary']['plan_task_type']}`")
            lines.append(f"- tool_trace: `{t['resp_summary']['tool_trace']}`")
            lines.append(f"- needs_more_context: `{t['resp_summary']['needs_more_context']}`")
            lines.append(f"- answer: `{t['resp_summary']['answer_excerpt']}`")
            for c in t["checks"]:
                mark = "OK" if c["ok"] else "FAIL"
                lines.append(f"  - [{mark}] {c['name']}: got=`{c.get('got')}` want=`{c.get('want')}`")
    path.write_text("\n".join(lines), encoding="utf-8")

def main():
    p = argparse.ArgumentParser()
    p.add_argument("--base-url", default="http://127.0.0.1:8000")
    p.add_argument("--dataset", default="evals/dataset.multi_turn.jsonl")
    p.add_argument("--out-dir", default="evals/reports")
    args = p.parse_args()
    cases = [json.loads(l) for l in open(args.dataset, encoding="utf-8") if l.strip()]
    results = [run_case(args.base_url, c) for c in cases]
    out = Path(args.out_dir); out.mkdir(parents=True, exist_ok=True)
    (out / "multi_turn_latest.json").write_text(json.dumps(results, ensure_ascii=False, indent=2), encoding="utf-8")
    write_md(out / "multi_turn_latest.md", results)
    failed = sum(1 for r in results if not r["passed"])
    print(f"multi-turn: {len(results) - failed}/{len(results)} passed")
    sys.exit(0)  # 故意不用失败 exit code，这不是 CI 门禁

if __name__ == "__main__":
    main()
```

- [ ] Step 3: 本地干跑

```bash
# 终端 1
python3 -m uvicorn app.main:app --reload
# 终端 2
python3 evals/run_multi_turn_eval.py
```

预期：**会有 case 挂**。这就是目的，不要在本计划内"修"。

---

## Task 3 — 读失败模式，写决策备忘

**Files**:
- New: `docs/superpowers/plans/2026-04-29-multi-turn-eval-probe-findings.md`（Task 3 结束时创建）

**Steps**:

- [ ] Step 1: 按桶分类失败

| 失败现象 | 诊断含义 | 对应下一步 |
|---|---|---|
| turn 2 仍然 `needs_more_context=True` | `ContextRequirementResolver` 没接住补充信息（memory 已存但 resolver 没读） | 单点 Resolver 修复（~半天） |
| turn 2 `tool_trace` 没跑期望工具 | `ToolResolver` 在二跳给出的 chain 还跟一跳一样 | 单点 ToolResolver 调整 |
| `answer` 缺"结论/证据/行动"形态 | `ResponseFormatter` 还有 task_type 没接专用分支 | Phase 5 输出层（统一模板） |
| `career_insights` turn 2 诊断没变 + `loop_trace` 全是 `continue/finish` | Phase 4 机器在 `plan_executor` 里有，但 `career_insights` 链路没用上：要么 `ToolResolver.resolve` 给它的 chain 是单工具，要么 `decide_react_action` 对该 task_type 永远不返回 `replan_strategy/switch_tool` | 改 `ToolResolver` 的 career_insights 映射 + 改 `decide_react_action` 的 prompt/规则；不是新做 Phase 4 |
| `career_insights` turn 2 诊断没变 + `loop_trace` 已出现 `replan_strategy` 但 `guardrail_decision=rejected` | Phase 4 试图改路但被 `tool_resolver.normalize_executor_replan_chain` 否决 | 调 ToolResolver 的 replan chain 校验规则 |
| 第三方与本人主体之间 profile 漏 | `ProfileService.update_from_message` 主体识别有回归 | 修 ProfileService（小修） |

- [ ] Step 2: 写 1 页备忘

`docs/superpowers/plans/2026-04-29-multi-turn-eval-probe-findings.md` 包含：每条 case 的 raw 失败列表、桶计数、占比最高的桶 = 下一份计划要写的 Phase。

---

## Task 4 — 在这里停下

本计划到 findings 备忘为止。**下一份计划在备忘写完之后再写**，不要在备忘之前写。

这条规则的意义：Phase 4 机器已在 `plan_executor.py` 落地（`switch_tool / replan_strategy / ask_for_context / MAX_REPLANS`），所以下一步不是"做 Phase 4"，而是定位"机器在哪条链路上没被用起来"——可能是 `ToolResolver` 给某个 task_type 映射出的 chain 太短，可能是 `decide_react_action` 的 prompt/fallback 在该 task_type 下不主动改路，也可能是 `tool_resolver.normalize_executor_replan_chain` 把 LLM 提议否决了。先看 findings，再决定改哪一处。

---

## Self-Review

- Spec 覆盖：本计划只解决一个 outcome——知道下一个 Phase 是什么。它**不**实施那个 Phase。
- 占位扫描：无 TODO/TBD。每个 task 的产出都是具体文件。
- 防 scope creep：`app/` 下生产代码不动；如果 findings 显示某个修复半天就能完成，备忘里直接说明并允许 inline 修；否则必须新写一份计划。

---

## Execution Handoff

保存到 `docs/superpowers/plans/2026-04-29-multi-turn-eval-probe.md`。

两种执行方式：

1. **你写 case，我搭脚手架** — 5 条 case 由你写（1-2 小时，因为 case 内容关系到产品语义判断），`run_multi_turn_eval.py` 和报告 writer 由我写
2. **我两边都搭** — 我先写 dataset 和 runner，你 review case 是否匹配真实产品行为，再跑探针

选哪种？
