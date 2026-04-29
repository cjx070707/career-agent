"""Run 30-case career core replay against AgentService.

Usage:
  python3 evals/run_career_core_replay.py
  python3 evals/run_career_core_replay.py --dataset evals/career_core_replay_30.jsonl
"""

from __future__ import annotations

import argparse
import json
import sys
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Dict, List, Optional

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from app.services.agent_service import AgentService


DEFAULT_DATASET = Path("evals/career_core_replay_30.jsonl")


@dataclass
class ReplayRow:
    case_id: str
    message: str
    expected_domain: str
    expected_intent_cluster: str
    expected_action: str
    should_call_planner: bool
    expected_fallback_type: str
    must_not_answer_pattern: str


def _load_dataset(path: Path) -> List[ReplayRow]:
    rows: List[ReplayRow] = []
    for line in path.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line:
            continue
        obj = json.loads(line)
        rows.append(
            ReplayRow(
                case_id=str(obj["id"]),
                message=str(obj["message"]),
                expected_domain=str(obj["expected_domain"]),
                expected_intent_cluster=str(obj["expected_intent_cluster"]),
                expected_action=str(obj["expected_action"]),
                should_call_planner=bool(obj["should_call_planner"]),
                expected_fallback_type=str(obj["expected_fallback_type"]),
                must_not_answer_pattern=str(obj.get("must_not_answer_pattern", "")),
            )
        )
    return rows


def _gateway_event(plan: Dict[str, Any]) -> Dict[str, Any]:
    resolver_trace = plan.get("resolver_trace") or []
    for item in resolver_trace:
        if item.get("resolver") == "intent_gateway":
            return item
    return {}


def _planner_called(gw: Dict[str, Any], plan: Dict[str, Any]) -> bool:
    if "planner_called" in gw:
        return bool(gw.get("planner_called"))
    planner_source = str(plan.get("planner_source") or "")
    return planner_source in {"model", "fallback"}


def _is_career_domain_case(row: ReplayRow) -> bool:
    return row.expected_domain == "career"


def run(dataset_path: Path) -> int:
    service = AgentService()
    rows = _load_dataset(dataset_path)

    report: List[Dict[str, Any]] = []
    career_total = 0
    career_true_fallback = 0
    core_journey_total = 0
    core_journey_planner_called = 0
    clarify_total = 0
    clarify_success = 0
    empty_talk_total = 0

    core_journeys = {
        "job_recommend",
        "job_match",
        "resume_analysis",
        "application_diag",
        "interview_prep",
    }

    # Use isolated users so each row is deterministic enough.
    for i, row in enumerate(rows):
        user_id = f"replay-user-{i:03d}"
        result = service.respond(user_id=user_id, message=row.message)
        plan = result.plan.model_dump() if result.plan is not None else {}
        gw = _gateway_event(plan)
        action = str(gw.get("gateway_action") or "route")
        fallback_type = str(gw.get("fallback_type") or "none")
        planner_called = _planner_called(gw, plan)
        gateway_domain = str(gw.get("gateway_domain") or ("career" if plan.get("task_type") != "fallback" else "non_career"))
        gateway_intent = str(gw.get("gateway_intent") or "unknown")
        answer = str(result.answer or "")

        if _is_career_domain_case(row):
            career_total += 1
            if fallback_type == "true":
                career_true_fallback += 1

        if row.expected_intent_cluster in core_journeys:
            core_journey_total += 1
            if planner_called:
                core_journey_planner_called += 1

        if action == "clarify":
            clarify_total += 1
            # Proxy of "second-hop likely effective": clarify with concrete follow-up.
            if bool(plan.get("follow_up_question")):
                clarify_success += 1

        if row.must_not_answer_pattern and row.must_not_answer_pattern in answer:
            empty_talk_total += 1

        report.append(
            {
                "id": row.case_id,
                "message": row.message,
                "expected_domain": row.expected_domain,
                "expected_action": row.expected_action,
                "expected_fallback_type": row.expected_fallback_type,
                "actual_gateway_domain": gateway_domain,
                "actual_gateway_intent": gateway_intent,
                "actual_gateway_action": action,
                "actual_planner_called": planner_called,
                "actual_fallback_type": fallback_type,
                "final_stage": result.stage,
                "plan_task_type": plan.get("task_type"),
                "answer": answer,
            }
        )

    true_fallback_rate = (career_true_fallback / career_total) if career_total else 0.0
    planner_dependency_rate = (core_journey_planner_called / core_journey_total) if core_journey_total else 0.0
    clarify_hit_rate = (clarify_success / clarify_total) if clarify_total else 1.0
    empty_talk_rate = (empty_talk_total / len(rows)) if rows else 0.0

    summary = {
        "cases": len(rows),
        "career_true_fallback_rate": round(true_fallback_rate, 4),
        "core_journey_planner_dependency_rate": round(planner_dependency_rate, 4),
        "clarify_followup_coverage_rate": round(clarify_hit_rate, 4),
        "empty_talk_answer_rate": round(empty_talk_rate, 4),
        "targets": {
            "career_true_fallback_rate_lt": 0.10,
            "core_journey_planner_dependency_rate_lt": 0.15,
            "clarify_followup_coverage_rate_gt": 0.80,
            "empty_talk_answer_rate_near": 0.0,
        },
    }

    out_dir = Path("evals/reports")
    out_dir.mkdir(parents=True, exist_ok=True)
    out_json = out_dir / "career_core_replay_report.json"
    out_md = out_dir / "career_core_replay_report.md"
    out_json.write_text(
        json.dumps({"summary": summary, "cases": report}, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    out_md.write_text(
        "\n".join(
            [
                "# Career Core Replay Report",
                "",
                f"- cases: {summary['cases']}",
                f"- career_true_fallback_rate: {summary['career_true_fallback_rate']}",
                f"- core_journey_planner_dependency_rate: {summary['core_journey_planner_dependency_rate']}",
                f"- clarify_followup_coverage_rate: {summary['clarify_followup_coverage_rate']}",
                f"- empty_talk_answer_rate: {summary['empty_talk_answer_rate']}",
                "",
                f"JSON: `{out_json}`",
            ]
        ),
        encoding="utf-8",
    )

    print(json.dumps(summary, ensure_ascii=False, indent=2))
    print(f"Saved report: {out_json}")
    return 0


def main() -> int:
    parser = argparse.ArgumentParser(description="Run 30-case career core replay.")
    parser.add_argument("--dataset", default=str(DEFAULT_DATASET), help="Path to replay jsonl dataset.")
    args = parser.parse_args()
    return run(Path(args.dataset))


if __name__ == "__main__":
    raise SystemExit(main())

