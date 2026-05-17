"""LLM-as-Judge eval runner for Career Agent answer quality.

Calls /chat/sync for each case, then asks the judge LLM to score:
  - tool_appropriateness  (1-5): right tool called, no unnecessary calls
  - answer_relevance      (1-5): directly answers the user's question
  - no_hallucination      (1-5): no made-up jobs, skills, companies
  - tone_fit              (1-5): coaching tone, not robotic

Writes reports to evals/reports/judge_latest.md and judge_latest.json.

Usage:
    # Start the backend first:
    uvicorn app.main:app --reload

    # Run judge eval:
    python3 evals/run_judge_eval.py
    python3 evals/run_judge_eval.py --dataset evals/dataset.jsonl --judge-model qwen-plus
"""

from __future__ import annotations

import argparse
import datetime as _dt
import json
import os
import sys
import time
import urllib.request
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Dict, List, Optional

ROOT = Path(__file__).resolve().parent
DEFAULT_DATASET = ROOT / "dataset.jsonl"
DEFAULT_OUT_DIR = ROOT / "reports"

# ── Judge rubric ─────────────────────────────────────────────────────────────

JUDGE_SYSTEM_PROMPT = """\
你是一个 AI agent 质量评审专家。你的任务是评估一个求职辅导 agent 的回答质量。

评分维度（每项 1-5 分，5 最好）：
1. tool_appropriateness: 工具调用是否合适？调了正确的工具、没有多余调用？（无工具调用的闲聊场景若未调工具则得 5 分）
2. answer_relevance: 回答是否直接回答了用户问题？没有跑题或答非所问？
3. no_hallucination: 回答里有没有编造的岗位、公司、技能信息？（5=完全没有幻觉，1=严重幻觉）
4. tone_fit: 语气是否符合 career coaching 场景？友好、有建设性，而不是机器人式罗列？

输出格式（严格 JSON，不要加任何额外文字）：
{
  "tool_appropriateness": <1-5>,
  "answer_relevance": <1-5>,
  "no_hallucination": <1-5>,
  "tone_fit": <1-5>,
  "reasoning": "<50字以内的评分依据>"
}
"""

JUDGE_USER_TEMPLATE = """\
=== 用户输入 ===
{user_message}

=== Agent 工具调用轨迹 ===
{tool_trace}

=== Agent 最终回答 ===
{answer}

请根据以上内容打分。
"""

# ── HTTP helpers ─────────────────────────────────────────────────────────────

def _post_json(url: str, payload: Dict[str, Any], timeout: float = 60.0) -> Dict[str, Any]:
    data = json.dumps(payload).encode("utf-8")
    req = urllib.request.Request(
        url, data=data,
        headers={"Content-Type": "application/json"},
        method="POST",
    )
    with urllib.request.urlopen(req, timeout=timeout) as resp:
        return {"status_code": resp.status, "json": json.loads(resp.read().decode("utf-8"))}


def _call_judge(
    base_url: str, api_key: str, model: str,
    user_message: str, tool_trace: List[str], answer: str,
) -> Optional[Dict[str, Any]]:
    """Call the judge LLM and return parsed scores, or None on failure."""
    user_content = JUDGE_USER_TEMPLATE.format(
        user_message=user_message,
        tool_trace=json.dumps(tool_trace, ensure_ascii=False) if tool_trace else "（无工具调用）",
        answer=answer[:800],  # truncate to keep prompt short
    )
    payload = {
        "model": model,
        "messages": [
            {"role": "system", "content": JUDGE_SYSTEM_PROMPT},
            {"role": "user", "content": user_content},
        ],
        "temperature": 0.0,
        "max_tokens": 300,
    }
    headers_data = json.dumps(payload).encode("utf-8")
    req = urllib.request.Request(
        f"{base_url.rstrip('/')}/chat/completions",
        data=headers_data,
        headers={
            "Content-Type": "application/json",
            "Authorization": f"Bearer {api_key}",
        },
        method="POST",
    )
    try:
        with urllib.request.urlopen(req, timeout=30.0) as resp:
            result = json.loads(resp.read().decode("utf-8"))
        content = result["choices"][0]["message"]["content"].strip()
        # Strip markdown code fences if present
        if content.startswith("```"):
            content = content.split("```")[1]
            if content.startswith("json"):
                content = content[4:]
        return json.loads(content)
    except Exception as exc:  # noqa: BLE001
        print(f"  [judge error] {exc}", file=sys.stderr)
        return None


# ── Seed helpers (reuse logic from run_eval.py) ───────────────────────────────

def _seed_case(base_url: str, case: Dict[str, Any]) -> Dict[str, int]:
    seed = case.get("seed") or {}
    candidate_by_user: Dict[str, int] = {}

    for c in seed.get("candidates", []):
        r = _post_json(f"{base_url}/candidates", {"name": c["name"], "user_id": c.get("user_id")})
        if r["status_code"] in (200, 201):
            cid = r["json"].get("id") or r["json"].get("candidate_id")
            if cid and c.get("user_id"):
                candidate_by_user[c["user_id"]] = int(cid)

    for res in seed.get("resumes", []):
        uid = res.get("user_id", "")
        cid = candidate_by_user.get(uid)
        if cid:
            _post_json(f"{base_url}/resumes", {
                "candidate_id": cid, "title": res["title"],
                "content": res["content"], "version": res.get("version", "v1"),
            })

    for msg in seed.get("warmup_messages", []):
        _post_json(f"{base_url}/chat/sync", {"user_id": case["user_id"], "message": msg})

    return candidate_by_user


# ── Main ──────────────────────────────────────────────────────────────────────

@dataclass
class JudgeResult:
    case_id: str
    user_message: str
    tool_trace: List[str]
    answer: str
    scores: Optional[Dict[str, Any]]
    error: Optional[str] = None

    @property
    def avg_score(self) -> float:
        if not self.scores:
            return 0.0
        dims = ["tool_appropriateness", "answer_relevance", "no_hallucination", "tone_fit"]
        vals = [self.scores.get(d, 0) for d in dims]
        return sum(vals) / len(vals)

    @property
    def passed(self) -> bool:
        if not self.scores:
            return False
        dims = ["tool_appropriateness", "answer_relevance", "no_hallucination", "tone_fit"]
        avg = self.avg_score
        hallucination_ok = self.scores.get("no_hallucination", 0) >= 4
        return avg >= 3.5 and hallucination_ok


def _write_report(results: List[JudgeResult], out_dir: Path) -> None:
    out_dir.mkdir(parents=True, exist_ok=True)
    ts = _dt.datetime.now().isoformat(timespec="seconds")

    passed = sum(1 for r in results if r.passed)
    total = len(results)
    avg_all = sum(r.avg_score for r in results) / total if total else 0.0

    # ── Markdown ──────────────────────────────────────────────────────────────
    lines = [
        "# Judge Eval Report",
        "",
        f"- generated_at: {ts}",
        f"- total: {total} | passed: {passed} | pass_rate: {passed/total:.0%}" if total else "",
        f"- avg_score: {avg_all:.2f} / 5.0",
        "",
        "| id | avg | tool | relevance | no_halluc | tone | pass | reasoning |",
        "| --- | --- | --- | --- | --- | --- | --- | --- |",
    ]
    for r in results:
        s = r.scores or {}
        lines.append(
            f"| {r.case_id} "
            f"| {r.avg_score:.1f} "
            f"| {s.get('tool_appropriateness', '?')} "
            f"| {s.get('answer_relevance', '?')} "
            f"| {s.get('no_hallucination', '?')} "
            f"| {s.get('tone_fit', '?')} "
            f"| {'✅' if r.passed else '❌'} "
            f"| {s.get('reasoning', r.error or '')[:60]} |"
        )

    lines += ["", "## Details", ""]
    for r in results:
        lines.append(f"### {r.case_id}")
        lines.append(f"**User**: {r.user_message}")
        lines.append(f"**Tools**: {r.tool_trace or '(none)'}")
        lines.append(f"**Answer** (truncated): {r.answer[:300]}...")
        if r.scores:
            lines.append(f"**Scores**: {json.dumps(r.scores, ensure_ascii=False)}")
        if r.error:
            lines.append(f"**Error**: {r.error}")
        lines.append("")

    md = "\n".join(lines)
    (out_dir / "judge_latest.md").write_text(md, encoding="utf-8")

    # ── JSON ──────────────────────────────────────────────────────────────────
    payload = {
        "generated_at": ts,
        "total": total,
        "passed": passed,
        "pass_rate": round(passed / total, 3) if total else 0,
        "avg_score": round(avg_all, 3),
        "results": [
            {
                "id": r.case_id,
                "avg_score": round(r.avg_score, 2),
                "passed": r.passed,
                "scores": r.scores,
                "tool_trace": r.tool_trace,
                "answer_preview": r.answer[:200],
            }
            for r in results
        ],
    }
    (out_dir / "judge_latest.json").write_text(
        json.dumps(payload, indent=2, ensure_ascii=False), encoding="utf-8"
    )

    print(f"\n[judge] Report written to {out_dir}/judge_latest.md")
    print(f"[judge] pass_rate={passed}/{total}  avg_score={avg_all:.2f}/5.0")


def main() -> None:
    ap = argparse.ArgumentParser(description="LLM-as-judge eval for Career Agent")
    ap.add_argument("--base-url", default="http://127.0.0.1:8000")
    ap.add_argument("--dataset", default=str(DEFAULT_DATASET))
    ap.add_argument("--out-dir", default=str(DEFAULT_OUT_DIR))
    ap.add_argument("--judge-model", default=os.getenv("JUDGE_MODEL", "qwen-plus"))
    ap.add_argument("--judge-base-url", default=os.getenv("OPENAI_BASE_URL", "https://dashscope.aliyuncs.com/compatible-mode/v1"))
    ap.add_argument("--judge-api-key", default=os.getenv("OPENAI_API_KEY", ""))
    ap.add_argument("--case-ids", nargs="*", help="Run only these case IDs")
    ap.add_argument("--fail-threshold", type=float, default=0.75)
    args = ap.parse_args()

    if not args.judge_api_key:
        sys.exit("[judge] OPENAI_API_KEY not set. Export it or pass --judge-api-key.")

    dataset_path = Path(args.dataset)
    cases = [
        json.loads(line)
        for line in dataset_path.read_text(encoding="utf-8").splitlines()
        if line.strip() and not line.startswith("#")
    ]
    if args.case_ids:
        cases = [c for c in cases if c["id"] in args.case_ids]
    if not cases:
        sys.exit("[judge] No cases to run.")

    print(f"[judge] Running {len(cases)} cases against {args.base_url}")
    print(f"[judge] Judge model: {args.judge_model}")

    results: List[JudgeResult] = []

    for i, case in enumerate(cases, 1):
        cid = case["id"]
        msg = case["message"]
        uid = case.get("user_id", f"eval-judge-{cid}")
        print(f"  [{i}/{len(cases)}] {cid}: {msg[:50]}", end=" ... ", flush=True)

        # Seed
        try:
            _seed_case(args.base_url, case)
        except Exception as exc:
            print(f"SEED_ERR({exc})")
            results.append(JudgeResult(cid, msg, [], "", None, error=f"seed error: {exc}"))
            continue

        # Call agent
        try:
            resp = _post_json(
                f"{args.base_url}/chat/sync",
                {"user_id": uid, "message": msg},
                timeout=90.0,
            )
            body = resp["json"]
            answer = body.get("answer", "")
            tool_trace = body.get("tool_trace") or []
        except Exception as exc:
            print(f"AGENT_ERR({exc})")
            results.append(JudgeResult(cid, msg, [], "", None, error=f"agent error: {exc}"))
            continue

        # Call judge
        scores = _call_judge(
            args.judge_base_url, args.judge_api_key, args.judge_model,
            msg, tool_trace, answer,
        )

        jr = JudgeResult(cid, msg, tool_trace, answer, scores)
        results.append(jr)

        status = f"avg={jr.avg_score:.1f} {'PASS' if jr.passed else 'FAIL'}"
        print(status)
        time.sleep(0.5)  # rate limit courtesy

    _write_report(results, Path(args.out_dir))

    passed = sum(1 for r in results if r.passed)
    rate = passed / len(results) if results else 0
    if rate < args.fail_threshold:
        sys.exit(f"[judge] FAIL: pass_rate {rate:.0%} < threshold {args.fail_threshold:.0%}")


if __name__ == "__main__":
    main()
