"""Multi-turn eval harness — diagnostic probe, not a CI gate.

Each case fires N chat turns against the same user_id so memory and context
accumulate naturally. Per-turn assertions reuse the same vocabulary as
run_eval.py (plan_task_type, plan_needs_more_context, tool_trace_equals, …)
plus one new assertion: tool_trace_contains_any.

Usage:
    # terminal 1 — start the server
    python3 -m uvicorn app.main:app --reload

    # terminal 2 — run the probe
    python3 evals/run_multi_turn_eval.py

Optional flags:
    --base-url   default http://127.0.0.1:8000
    --dataset    default evals/dataset.multi_turn.jsonl
    --out-dir    default evals/reports

Always exits 0 — failures are signal, not a gate.
"""

from __future__ import annotations

import argparse
import datetime as _dt
import json
import sys
import urllib.error
import urllib.request
from pathlib import Path
from typing import Any, Dict, List, Optional

ROOT = Path(__file__).resolve().parent.parent
DEFAULT_DATASET = Path(__file__).resolve().parent / "dataset.multi_turn.jsonl"
DEFAULT_OUT_DIR = Path(__file__).resolve().parent / "reports"


# ---------------------------------------------------------------------------
# HTTP helper
# ---------------------------------------------------------------------------

def _post_json(url: str, payload: Dict[str, Any], timeout: float = 120.0) -> Dict[str, Any]:
    data = json.dumps(payload).encode("utf-8")
    req = urllib.request.Request(
        url,
        data=data,
        headers={"Content-Type": "application/json"},
        method="POST",
    )
    with urllib.request.urlopen(req, timeout=timeout) as resp:
        body = resp.read().decode("utf-8")
        return {"status_code": resp.status, "json": json.loads(body) if body else None}


# ---------------------------------------------------------------------------
# Seeder — mirrors run_eval.py._seed_case exactly
# ---------------------------------------------------------------------------

def _seed_case(base_url: str, case: Dict[str, Any]) -> None:
    """Seed DB with per-case fixtures (candidates / resumes / applications / interviews)."""
    seed = case.get("seed") or {}
    candidate_by_user: Dict[str, int] = {}

    for candidate in seed.get("candidates", []) or []:
        created = _post_json(
            f"{base_url}/candidates",
            {"name": candidate["name"], "user_id": candidate.get("user_id")},
        )["json"]
        candidate_by_user[candidate.get("user_id") or ""] = created["id"]

    for job in seed.get("jobs", []) or []:
        _post_json(f"{base_url}/jobs", {"title": job["title"]})

    for resume in seed.get("resumes", []) or []:
        owner = resume.get("user_id") or ""
        candidate_id = candidate_by_user.get(owner)
        if candidate_id is None:
            raise ValueError(f"resume for user_id={owner!r} needs a candidate seed first")
        _post_json(
            f"{base_url}/resumes",
            {
                "candidate_id": candidate_id,
                "title": resume.get("title", "MT Eval Resume"),
                "content": resume["content"],
                "version": resume.get("version", "v1"),
            },
        )

    for application in seed.get("applications", []) or []:
        owner = application.get("user_id") or ""
        candidate_id = candidate_by_user.get(owner)
        if candidate_id is None:
            raise ValueError(f"application for user_id={owner!r} needs a candidate seed first")
        _post_json(
            f"{base_url}/applications",
            {
                "candidate_id": candidate_id,
                "company": application["company"],
                "job_title": application["job_title"],
                "status": application["status"],
                "note": application.get("note"),
            },
        )

    for interview in seed.get("interviews", []) or []:
        owner = interview.get("user_id") or ""
        candidate_id = candidate_by_user.get(owner)
        if candidate_id is None:
            raise ValueError(f"interview for user_id={owner!r} needs a candidate seed first")
        _post_json(
            f"{base_url}/interviews",
            {
                "candidate_id": candidate_id,
                "company": interview["company"],
                "job_title": interview["job_title"],
                "interview_round": interview["interview_round"],
                "result": interview["result"],
                "feedback": interview.get("feedback"),
            },
        )


# ---------------------------------------------------------------------------
# Assertions — same vocabulary as run_eval.py + tool_trace_contains_any
# ---------------------------------------------------------------------------

def _as_list(value: Any) -> List[Any]:
    if isinstance(value, list):
        return value
    if value is None:
        return []
    return [value]


def _check_expectations(body: Dict[str, Any], expect: Dict[str, Any]) -> List[Dict[str, Any]]:
    """Run all expect assertions against a /chat response body.

    Each check dict has: name, ok, and optionally got/want for diagnosis.
    Uses the same field names as run_eval.py so reports are comparable.
    """
    checks: List[Dict[str, Any]] = []
    plan = body.get("plan") or {}
    answer = str(body.get("answer") or "")
    trace: List[str] = body.get("tool_trace") or []
    sources: List[Any] = body.get("sources") or []

    def _chk(name: str, ok: bool, *, got: Any = None, want: Any = None) -> None:
        entry: Dict[str, Any] = {"name": name, "ok": bool(ok)}
        if got is not None:
            entry["got"] = got
        if want is not None:
            entry["want"] = want
        checks.append(entry)

    # ---- plan assertions ----

    if "plan_task_type" in expect:
        allowed = _as_list(expect["plan_task_type"])
        _chk(
            "plan_task_type",
            plan.get("task_type") in allowed,
            got=plan.get("task_type"),
            want=allowed,
        )

    if "plan_needs_more_context" in expect:
        want = bool(expect["plan_needs_more_context"])
        _chk(
            "plan_needs_more_context",
            bool(plan.get("needs_more_context")) == want,
            got=plan.get("needs_more_context"),
            want=want,
        )

    if "plan_missing_context_contains" in expect:
        missing: List[str] = plan.get("missing_context") or []
        want = list(expect["plan_missing_context_contains"])
        _chk(
            "plan_missing_context_contains",
            all(item in missing for item in want),
            got=missing,
            want=want,
        )

    if expect.get("follow_up_question_nonempty"):
        fq = str(plan.get("follow_up_question") or "").strip()
        _chk("follow_up_question_nonempty", bool(fq), got=repr(fq))

    # ---- tool_trace assertions ----

    if "tool_trace_equals" in expect:
        want = list(expect["tool_trace_equals"])
        _chk("tool_trace_equals", trace == want, got=trace, want=want)

    if "tool_trace_prefix" in expect:
        want = list(expect["tool_trace_prefix"])
        _chk("tool_trace_prefix", trace[: len(want)] == want, got=trace, want=want)

    if "tool_trace_contains_any" in expect:
        # New: passes if at least one of the listed tool names appears anywhere in the trace.
        want = list(expect["tool_trace_contains_any"])
        _chk(
            "tool_trace_contains_any",
            any(t in trace for t in want),
            got=trace,
            want=want,
        )

    # ---- sources assertions ----

    if expect.get("sources_nonempty"):
        _chk("sources_nonempty", len(sources) > 0, got=len(sources))

    if expect.get("sources_empty"):
        _chk("sources_empty", len(sources) == 0, got=len(sources))

    # ---- answer assertions ----

    if "answer_contains_any" in expect:
        want = list(expect["answer_contains_any"])
        _chk(
            "answer_contains_any",
            any(needle in answer for needle in want),
            got=answer[:200],
            want=want,
        )

    if "answer_contains_all" in expect:
        want = list(expect["answer_contains_all"])
        _chk(
            "answer_contains_all",
            all(needle in answer for needle in want),
            got=answer[:200],
            want=want,
        )

    if "answer_not_contains" in expect:
        banned = list(expect["answer_not_contains"])
        hit = [needle for needle in banned if needle in answer]
        _chk("answer_not_contains", not hit, got=hit, want=banned)

    return checks


# ---------------------------------------------------------------------------
# Case runner
# ---------------------------------------------------------------------------

def _run_case(base_url: str, case: Dict[str, Any]) -> Dict[str, Any]:
    case_id = str(case.get("id", "<unknown>"))
    user_id = str(case["user_id"])

    # Seed fixtures
    try:
        _seed_case(base_url, case)
    except Exception as exc:
        return {
            "id": case_id,
            "error": f"seed failed: {exc}",
            "turns": [],
            "passed": False,
        }

    turn_results: List[Dict[str, Any]] = []
    all_turns = case.get("turns") or []

    for idx, turn in enumerate(all_turns, start=1):
        message = turn.get("message", "")
        print(f"  [mt-eval] {case_id} turn {idx}: {message[:60]!r}")

        try:
            resp = _post_json(
                f"{base_url}/chat",
                {"user_id": user_id, "message": message},
                timeout=240.0,
            )
        except urllib.error.HTTPError as exc:
            turn_results.append({
                "turn": idx,
                "error": f"HTTP {exc.code}: {exc.reason}",
                "checks": [],
                "resp_summary": {},
            })
            continue
        except Exception as exc:
            turn_results.append({
                "turn": idx,
                "error": f"{type(exc).__name__}: {exc}",
                "checks": [],
                "resp_summary": {},
            })
            continue

        if resp["status_code"] != 200 or resp["json"] is None:
            turn_results.append({
                "turn": idx,
                "error": f"unexpected status {resp['status_code']}",
                "checks": [],
                "resp_summary": {},
            })
            continue

        body = resp["json"]
        plan = body.get("plan") or {}
        checks = _check_expectations(body, turn.get("expect") or {})
        total_elapsed_ms = _extract_total_elapsed_ms(plan)

        failed_checks = [c["name"] for c in checks if not c["ok"]]
        status_str = "PASS" if not failed_checks else f"FAIL [{', '.join(failed_checks)}]"
        print(f"    → {status_str}")

        turn_results.append({
            "turn": idx,
            "checks": checks,
            "resp_summary": {
                "plan_task_type": plan.get("task_type"),
                "tool_trace": body.get("tool_trace"),
                "needs_more_context": plan.get("needs_more_context"),
                "follow_up_question": plan.get("follow_up_question"),
                "answer_excerpt": (body.get("answer") or "")[:200],
                "total_elapsed_ms": total_elapsed_ms,
            },
        })

    # Case passes only if all turns ran without error and all checks passed.
    all_turns_ran = len(turn_results) == len(all_turns)
    no_errors = all("error" not in t for t in turn_results)
    all_checks_ok = all(
        all(c["ok"] for c in t.get("checks", [])) for t in turn_results
    )
    passed = all_turns_ran and no_errors and all_checks_ok

    return {"id": case_id, "turns": turn_results, "passed": passed}


# ---------------------------------------------------------------------------
# Report writers
# ---------------------------------------------------------------------------

def _write_md(path: Path, results: List[Dict[str, Any]]) -> None:
    total = len(results)
    passed_count = sum(1 for r in results if r.get("passed"))
    lines: List[str] = [
        "# Multi-Turn Eval Report",
        "",
        f"generated_at: {_dt.datetime.now().isoformat(timespec='seconds')}",
        f"total: {total} | passed: {passed_count} | failed: {total - passed_count}",
        "",
        "| id | result | failed_turns |",
        "| --- | --- | --- |",
    ]
    for r in results:
        if "error" in r and not r.get("turns"):
            lines.append(f"| {r['id']} | ERROR | {r['error']} |")
            continue
        bad = [
            f"turn{t['turn']}"
            for t in r.get("turns", [])
            if "error" in t or any(not c["ok"] for c in t.get("checks", []))
        ]
        status = "PASS" if r.get("passed") else "FAIL"
        lines.append(f"| {r['id']} | {status} | {', '.join(bad) or '-'} |")
    lines.append("")

    for r in results:
        lines.append(f"## {r['id']} — {'PASS' if r.get('passed') else 'FAIL'}")
        lines.append("")
        if "error" in r and not r.get("turns"):
            lines.append(f"- error: `{r['error']}`")
            lines.append("")
            continue
        for t in r.get("turns", []):
            lines.append(f"### turn {t['turn']}")
            lines.append("")
            if "error" in t:
                lines.append(f"- error: `{t['error']}`")
                lines.append("")
                continue
            s = t.get("resp_summary", {})
            lines.append(f"- plan.task_type: `{s.get('plan_task_type')}`")
            lines.append(f"- tool_trace: `{s.get('tool_trace')}`")
            lines.append(f"- needs_more_context: `{s.get('needs_more_context')}`")
            lines.append(f"- follow_up_question: `{s.get('follow_up_question')}`")
            lines.append(f"- answer: `{s.get('answer_excerpt')}`")
            lines.append("")
            for c in t.get("checks", []):
                mark = "OK" if c["ok"] else "FAIL"
                parts: List[str] = []
                if "got" in c:
                    parts.append(f"got=`{c['got']}`")
                if "want" in c:
                    parts.append(f"want=`{c['want']}`")
                suffix = (" " + " ".join(parts)) if parts else ""
                lines.append(f"  - [{mark}] {c['name']}{suffix}")
            lines.append("")

    path.write_text("\n".join(lines), encoding="utf-8")


def _write_json(path: Path, results: List[Dict[str, Any]]) -> None:
    total = len(results)
    passed_count = sum(1 for r in results if r.get("passed"))
    payload = {
        "generated_at": _dt.datetime.now().isoformat(timespec="seconds"),
        "summary": {
            "total": total,
            "passed": passed_count,
            "failed": total - passed_count,
        },
        "cases": results,
    }
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")


def _extract_total_elapsed_ms(plan: Dict[str, Any]) -> Optional[float]:
    resolver_trace = plan.get("resolver_trace") if isinstance(plan, dict) else None
    if not isinstance(resolver_trace, list):
        return None
    for item in resolver_trace:
        if not isinstance(item, dict):
            continue
        if item.get("resolver") == "runtime_timing":
            value = item.get("total_elapsed_ms")
            if isinstance(value, (int, float)):
                return float(value)
    return None


def _percent(numerator: int, denominator: int) -> float:
    if denominator <= 0:
        return 0.0
    return (numerator / denominator) * 100.0


def _compute_metrics(results: List[Dict[str, Any]]) -> Dict[str, Any]:
    total_cases = len(results)
    passed_cases = sum(1 for r in results if r.get("passed"))

    route_correct = 0
    route_total = 0
    nmc_correct = 0
    nmc_total = 0
    latency_values: List[float] = []

    for case in results:
        for turn in case.get("turns", []):
            for check in turn.get("checks", []):
                name = str(check.get("name") or "")
                if name == "plan_task_type":
                    route_total += 1
                    if bool(check.get("ok")):
                        route_correct += 1
                if name == "plan_needs_more_context":
                    nmc_total += 1
                    if bool(check.get("ok")):
                        nmc_correct += 1
            timing = turn.get("resp_summary", {}).get("total_elapsed_ms")
            if isinstance(timing, (int, float)):
                latency_values.append(float(timing))

    avg_latency = (sum(latency_values) / len(latency_values)) if latency_values else None
    return {
        "total_cases": total_cases,
        "passed_cases": passed_cases,
        "route_correct": route_correct,
        "route_total": route_total,
        "nmc_correct": nmc_correct,
        "nmc_total": nmc_total,
        "avg_latency_ms": avg_latency,
        "multi_turn_pass_rate_pct": _percent(passed_cases, total_cases),
        "route_accuracy_pct": _percent(route_correct, route_total),
        "nmc_accuracy_pct": _percent(nmc_correct, nmc_total),
    }


def _write_metrics_summary(path: Path, metrics: Dict[str, Any]) -> None:
    generated_at = _dt.datetime.now().isoformat(timespec="seconds")
    latency = metrics.get("avg_latency_ms")
    latency_line = (
        f"- 平均响应延迟（可用样本）：{latency:.2f} ms"
        if isinstance(latency, (int, float))
        else "- 平均响应延迟：无可用 timing 字段，已跳过"
    )
    lines = [
        "# Eval Metrics Summary",
        f"generated_at: {generated_at}",
        "",
        "## 核心指标",
        "| 指标 | 数值 |",
        "|---|---|",
        (
            "| multi-turn eval 通过率 | "
            f"{metrics['passed_cases']}/{metrics['total_cases']} "
            f"({metrics['multi_turn_pass_rate_pct']:.2f}%) |"
        ),
        (
            "| 路由准确率（task_type 命中率） | "
            f"{metrics['route_correct']}/{metrics['route_total']} "
            f"({metrics['route_accuracy_pct']:.2f}%) |"
        ),
        (
            "| needs_more_context 准确率 | "
            f"{metrics['nmc_correct']}/{metrics['nmc_total']} "
            f"({metrics['nmc_accuracy_pct']:.2f}%) |"
        ),
        "",
        "## 说明",
        "- 数据来源：evals/dataset.multi_turn.jsonl（7 条双轮用例）",
        "- 运行环境：LLM Intent Classifier（Phase A）+ 统一输出协议（Phase B）+ LLM-driven ReAct（Phase C）",
        latency_line,
    ]
    path.write_text("\n".join(lines), encoding="utf-8")


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------

def main(argv: Optional[List[str]] = None) -> int:
    parser = argparse.ArgumentParser(
        description="Multi-turn eval probe. Always exits 0 (diagnostic, not a gate)."
    )
    parser.add_argument("--base-url", default="http://127.0.0.1:8000")
    parser.add_argument("--dataset", default=str(DEFAULT_DATASET))
    parser.add_argument("--out-dir", default=str(DEFAULT_OUT_DIR))
    args = parser.parse_args(argv)

    dataset_path = Path(args.dataset).resolve()
    out_dir = Path(args.out_dir).resolve()
    out_dir.mkdir(parents=True, exist_ok=True)

    # Load dataset
    cases: List[Dict[str, Any]] = []
    for line_no, line in enumerate(
        dataset_path.read_text(encoding="utf-8").splitlines(), start=1
    ):
        line = line.strip()
        if not line or line.startswith("#"):
            continue
        try:
            cases.append(json.loads(line))
        except json.JSONDecodeError as exc:
            raise SystemExit(f"[mt-eval] invalid JSON at line {line_no}: {exc}") from exc

    if not cases:
        print(f"[mt-eval] no cases in {dataset_path}", file=sys.stderr)
        return 1

    print(f"[mt-eval] {len(cases)} cases against {args.base_url}")
    results = [_run_case(args.base_url, c) for c in cases]

    passed_count = sum(1 for r in results if r.get("passed"))
    print(f"[mt-eval] {passed_count}/{len(results)} cases passed")

    json_path = out_dir / "multi_turn_latest.json"
    md_path = out_dir / "multi_turn_latest.md"
    metrics_path = out_dir / "metrics_summary.md"
    _write_json(json_path, results)
    _write_md(md_path, results)
    metrics = _compute_metrics(results)
    _write_metrics_summary(metrics_path, metrics)
    print(f"[mt-eval] report → {md_path}")
    print(f"[mt-eval] metrics → {metrics_path}")

    # Diagnostic probe — always exit 0.
    return 0


if __name__ == "__main__":
    sys.exit(main())
