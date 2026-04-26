"""Minimal eval harness for Stage B /chat contract.

Reads `evals/dataset.jsonl`, POSTs each case against a running FastAPI server,
checks the expectations, and writes a Markdown + JSON report to
`evals/reports/`.

Designed to be dependency-light: uses only the standard library plus
`urllib.request`. Run it with the service already started:

    python3 -m uvicorn app.main:app --reload
    python3 evals/run_eval.py

Optional flags:
    --base-url        default http://127.0.0.1:8000
    --dataset         default evals/dataset.jsonl
    --out-dir         default evals/reports
    --fail-threshold  fraction of cases that must pass (default 0.8)
"""

from __future__ import annotations

import argparse
import datetime as _dt
import json
import sys
import urllib.error
import urllib.request
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Dict, Iterable, List, Optional

ROOT = Path(__file__).resolve().parent
DEFAULT_DATASET = ROOT / "dataset.jsonl"
DEFAULT_OUT_DIR = ROOT / "reports"


@dataclass
class CaseResult:
    case_id: str
    passed: bool
    checks: List[Dict[str, Any]] = field(default_factory=list)
    response: Optional[Dict[str, Any]] = None
    error: Optional[str] = None


def _post_json(url: str, payload: Dict[str, Any], timeout: float = 60.0) -> Dict[str, Any]:
    data = json.dumps(payload).encode("utf-8")
    req = urllib.request.Request(
        url,
        data=data,
        headers={"Content-Type": "application/json"},
        method="POST",
    )
    with urllib.request.urlopen(req, timeout=timeout) as resp:
        body = resp.read().decode("utf-8")
        return {
            "status_code": resp.status,
            "json": json.loads(body) if body else None,
        }


def _load_dataset(path: Path) -> List[Dict[str, Any]]:
    cases: List[Dict[str, Any]] = []
    for line_no, line in enumerate(path.read_text(encoding="utf-8").splitlines(), start=1):
        line = line.strip()
        if not line or line.startswith("#"):
            continue
        try:
            cases.append(json.loads(line))
        except json.JSONDecodeError as exc:
            raise SystemExit(f"[eval] invalid JSON at line {line_no}: {exc}") from exc
    return cases


def _seed_case(base_url: str, case: Dict[str, Any]) -> Dict[str, Any]:
    """Apply per-case seed (candidates / resumes / jobs / warmup_messages).

    Returns a mapping of user_id -> candidate_id for any candidate created.
    """
    candidate_by_user: Dict[str, int] = {}
    seed = case.get("seed") or {}

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
            raise SystemExit(
                f"[eval] resume for user_id={owner!r} needs a candidate seed before it"
            )
        _post_json(
            f"{base_url}/resumes",
            {
                "candidate_id": candidate_id,
                "title": resume.get("title", "Eval Resume"),
                "content": resume["content"],
                "version": resume.get("version", "v1"),
            },
        )

    for application in seed.get("applications", []) or []:
        owner = application.get("user_id") or ""
        candidate_id = candidate_by_user.get(owner)
        if candidate_id is None:
            raise SystemExit(
                f"[eval] application for user_id={owner!r} needs a candidate seed before it"
            )
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
            raise SystemExit(
                f"[eval] interview for user_id={owner!r} needs a candidate seed before it"
            )
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

    for warmup in seed.get("warmup_messages", []) or []:
        _post_json(
            f"{base_url}/chat",
            {"user_id": case["user_id"], "message": warmup},
            timeout=240.0,
        )

    return candidate_by_user


def _as_list(value: Any) -> List[Any]:
    if isinstance(value, list):
        return value
    if value is None:
        return []
    return [value]


def _check(
    checks: List[Dict[str, Any]],
    name: str,
    ok: bool,
    *,
    got: Any = None,
    want: Any = None,
) -> None:
    entry: Dict[str, Any] = {"name": name, "pass": bool(ok)}
    if got is not None:
        entry["got"] = got
    if want is not None:
        entry["want"] = want
    checks.append(entry)


def _run_expectations(
    body: Dict[str, Any], expect: Dict[str, Any]
) -> List[Dict[str, Any]]:
    checks: List[Dict[str, Any]] = []
    plan = body.get("plan") or {}
    llm_trace = body.get("llm_trace") or {}

    _check(
        checks,
        "contract_version",
        body.get("contract_version") == "chat.v1",
        got=body.get("contract_version"),
        want="chat.v1",
    )

    if "plan_task_type" in expect:
        allowed = _as_list(expect["plan_task_type"])
        _check(
            checks,
            "plan_task_type",
            plan.get("task_type") in allowed,
            got=plan.get("task_type"),
            want=allowed,
        )

    if "planner_source" in expect:
        allowed = _as_list(expect["planner_source"])
        _check(
            checks,
            "planner_source",
            plan.get("planner_source") in allowed,
            got=plan.get("planner_source"),
            want=allowed,
        )

    if "plan_needs_more_context" in expect:
        want = bool(expect["plan_needs_more_context"])
        _check(
            checks,
            "plan_needs_more_context",
            bool(plan.get("needs_more_context")) == want,
            got=plan.get("needs_more_context"),
            want=want,
        )

    if "plan_missing_context_contains" in expect:
        missing = plan.get("missing_context") or []
        want = list(expect["plan_missing_context_contains"])
        _check(
            checks,
            "plan_missing_context_contains",
            all(item in missing for item in want),
            got=missing,
            want=want,
        )

    if "tool_trace_prefix" in expect:
        want = list(expect["tool_trace_prefix"])
        trace = body.get("tool_trace") or []
        ok = trace[: len(want)] == want
        _check(checks, "tool_trace_prefix", ok, got=trace, want=want)

    if "tool_trace_equals" in expect:
        want = list(expect["tool_trace_equals"])
        trace = body.get("tool_trace") or []
        _check(checks, "tool_trace_equals", trace == want, got=trace, want=want)

    sources = body.get("sources") or []
    if expect.get("sources_nonempty"):
        _check(checks, "sources_nonempty", len(sources) > 0, got=len(sources))

    if expect.get("sources_empty"):
        _check(checks, "sources_empty", len(sources) == 0, got=len(sources))

    if "source_type" in expect:
        want = expect["source_type"]
        ok = bool(sources) and all(s.get("type") == want for s in sources)
        _check(checks, "source_type", ok, got=[s.get("type") for s in sources], want=want)

    if "source_types_include" in expect:
        want = list(expect["source_types_include"])
        got = [s.get("type") for s in sources]
        ok = all(item in got for item in want)
        _check(checks, "source_types_include", ok, got=got, want=want)

    if "source_snippet_contains_any" in expect:
        want = list(expect["source_snippet_contains_any"])
        snippets = [str(s.get("snippet") or "") for s in sources]
        ok = any(any(needle in snippet for needle in want) for snippet in snippets)
        _check(
            checks,
            "source_snippet_contains_any",
            ok,
            got=snippets,
            want=want,
        )

    if "source_field_contains" in expect:
        spec = expect["source_field_contains"] or {}
        field_name = str(spec.get("field") or "")
        needles = list(spec.get("any") or [])
        field_values = [str(s.get(field_name) or "") for s in sources]
        ok = bool(field_name and needles) and any(
            any(needle in value for needle in needles) for value in field_values
        )
        _check(
            checks,
            f"source_field_contains:{field_name}",
            ok,
            got=field_values,
            want=needles,
        )

    # Stricter variant used for filter/slot enforcement: every source must
    # match at least one needle. Accepts either a single spec dict or a list
    # of spec dicts so a case can assert on multiple fields at once.
    if "source_field_all_contain" in expect:
        raw_specs = expect["source_field_all_contain"]
        specs = raw_specs if isinstance(raw_specs, list) else [raw_specs]
        for spec in specs:
            field_name = str(spec.get("field") or "")
            needles = list(spec.get("any") or [])
            field_values = [str(s.get(field_name) or "") for s in sources]
            ok = (
                bool(field_name and needles and sources)
                and all(
                    any(needle.lower() in value.lower() for needle in needles)
                    for value in field_values
                )
            )
            _check(
                checks,
                f"source_field_all_contain:{field_name}",
                ok,
                got=field_values,
                want=needles,
            )

    if "llm_trace_allowed" in expect:
        for field_name, allowed in expect["llm_trace_allowed"].items():
            allowed_list = _as_list(allowed)
            actual = llm_trace.get(field_name)
            _check(
                checks,
                f"llm_trace.{field_name}",
                actual in allowed_list,
                got=actual,
                want=allowed_list,
            )

    answer = str(body.get("answer") or "")
    if "answer_contains_any" in expect:
        want = list(expect["answer_contains_any"])
        ok = any(needle in answer for needle in want)
        _check(checks, "answer_contains_any", ok, got=answer[:200], want=want)

    if "answer_contains_all" in expect:
        want = list(expect["answer_contains_all"])
        ok = all(needle in answer for needle in want)
        _check(checks, "answer_contains_all", ok, got=answer[:200], want=want)

    if "answer_not_contains" in expect:
        banned = list(expect["answer_not_contains"])
        hit = [needle for needle in banned if needle in answer]
        _check(
            checks,
            "answer_not_contains",
            not hit,
            got=hit,
            want=banned,
        )

    return checks


def run_case(base_url: str, case: Dict[str, Any]) -> CaseResult:
    case_id = case.get("id", "<unknown>")
    try:
        _seed_case(base_url, case)
        # Gray-zone cases can trigger planner retries (~2×45s) plus a
        # summarizer/generate call. Give each case a generous budget so the
        # harness measures quality, not IO luck.
        resp = _post_json(
            f"{base_url}/chat",
            {"user_id": case["user_id"], "message": case["message"]},
            timeout=240.0,
        )
    except urllib.error.HTTPError as exc:
        return CaseResult(case_id=case_id, passed=False, error=f"HTTP {exc.code}: {exc.reason}")
    except urllib.error.URLError as exc:
        return CaseResult(case_id=case_id, passed=False, error=f"URLError: {exc.reason}")
    except Exception as exc:  # pragma: no cover - defensive
        return CaseResult(case_id=case_id, passed=False, error=f"{type(exc).__name__}: {exc}")

    if resp["status_code"] != 200 or resp["json"] is None:
        return CaseResult(
            case_id=case_id,
            passed=False,
            error=f"unexpected status {resp['status_code']}",
            response=resp["json"],
        )

    body = resp["json"]
    checks = _run_expectations(body, case.get("expect") or {})
    all_passed = all(c["pass"] for c in checks)
    return CaseResult(case_id=case_id, passed=all_passed, checks=checks, response=body)


def _summarize(results: Iterable[CaseResult]) -> Dict[str, Any]:
    results = list(results)
    total = len(results)
    passed = sum(1 for r in results if r.passed)
    return {
        "total": total,
        "passed": passed,
        "failed": total - passed,
        "pass_rate": (passed / total) if total else 0.0,
    }


def _write_json_report(path: Path, summary: Dict[str, Any], results: List[CaseResult]) -> None:
    payload = {
        "generated_at": _dt.datetime.now().isoformat(timespec="seconds"),
        "summary": summary,
        "cases": [
            {
                "id": r.case_id,
                "passed": r.passed,
                "checks": r.checks,
                "error": r.error,
                "response": r.response,
            }
            for r in results
        ],
    }
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")


def _write_md_report(path: Path, summary: Dict[str, Any], results: List[CaseResult]) -> None:
    lines: List[str] = []
    lines.append("# Eval Report")
    lines.append("")
    lines.append(
        f"- generated_at: {_dt.datetime.now().isoformat(timespec='seconds')}"
    )
    lines.append(
        f"- total: {summary['total']} | passed: {summary['passed']} | "
        f"failed: {summary['failed']} | pass_rate: {summary['pass_rate']:.0%}"
    )
    lines.append("")
    lines.append("| id | result | failed_checks |")
    lines.append("| --- | --- | --- |")
    for r in results:
        if r.error:
            lines.append(f"| {r.case_id} | ERROR | {r.error} |")
            continue
        bad = [c["name"] for c in r.checks if not c["pass"]]
        status = "PASS" if r.passed else "FAIL"
        lines.append(f"| {r.case_id} | {status} | {', '.join(bad) or '-'} |")
    lines.append("")

    for r in results:
        lines.append(f"## {r.case_id}")
        if r.error:
            lines.append(f"- error: `{r.error}`")
            lines.append("")
            continue
        for c in r.checks:
            flag = "OK" if c["pass"] else "FAIL"
            detail_parts: List[str] = []
            if "got" in c:
                detail_parts.append(f"got=`{c['got']}`")
            if "want" in c:
                detail_parts.append(f"want=`{c['want']}`")
            suffix = (" " + " ".join(detail_parts)) if detail_parts else ""
            lines.append(f"- [{flag}] {c['name']}{suffix}")
        lines.append("")
    path.write_text("\n".join(lines), encoding="utf-8")


def main(argv: Optional[List[str]] = None) -> int:
    parser = argparse.ArgumentParser(description="Run the Stage B /chat eval harness.")
    parser.add_argument("--base-url", default="http://127.0.0.1:8000")
    parser.add_argument("--dataset", default=str(DEFAULT_DATASET))
    parser.add_argument("--out-dir", default=str(DEFAULT_OUT_DIR))
    parser.add_argument("--fail-threshold", type=float, default=0.8)
    args = parser.parse_args(argv)

    dataset_path = Path(args.dataset).resolve()
    out_dir = Path(args.out_dir).resolve()
    out_dir.mkdir(parents=True, exist_ok=True)

    cases = _load_dataset(dataset_path)
    if not cases:
        print(f"[eval] no cases found in {dataset_path}", file=sys.stderr)
        return 1

    print(f"[eval] running {len(cases)} cases against {args.base_url}")
    results = [run_case(args.base_url, case) for case in cases]
    summary = _summarize(results)
    print(
        f"[eval] total={summary['total']} passed={summary['passed']} "
        f"failed={summary['failed']} pass_rate={summary['pass_rate']:.0%}"
    )

    _write_md_report(out_dir / "latest.md", summary, results)
    _write_json_report(out_dir / "latest.json", summary, results)
    print(f"[eval] report written to {out_dir / 'latest.md'}")

    return 0 if summary["pass_rate"] >= args.fail_threshold else 1


if __name__ == "__main__":
    sys.exit(main())
