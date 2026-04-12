import json
from typing import Any, Dict

from app.llm.client import LLMClient
from app.llm.planner_eval import run_planner_eval


def format_plan_debug_output(plan: Dict[str, Any]) -> str:
    lines = [
        f"task_type: {plan.get('task_type')}",
        f"planner_source: {plan.get('planner_source')}",
        f"steps: {plan.get('steps')}",
        f"needs_more_context: {plan.get('needs_more_context')}",
        f"missing_context: {plan.get('missing_context')}",
        f"follow_up_question: {plan.get('follow_up_question')}",
        f"reason: {plan.get('reason')}",
    ]
    return "\n".join(lines)


def format_eval_debug_output(report: Dict[str, Any]) -> str:
    summary = report.get("summary", {})
    lines = [
        f"total_cases: {summary.get('total_cases')}",
        f"schema_success_rate: {summary.get('schema_success_rate')}",
        f"task_type_accuracy: {summary.get('task_type_accuracy')}",
        f"steps_accuracy: {summary.get('steps_accuracy')}",
        f"follow_up_accuracy: {summary.get('follow_up_accuracy')}",
        "results:",
    ]
    for result in report.get("results", []):
        lines.append(
            json.dumps(
                {
                    "name": result.get("name"),
                    "task_type_match": result.get("task_type_match"),
                    "steps_match": result.get("steps_match"),
                    "follow_up_match": result.get("follow_up_match"),
                },
                ensure_ascii=False,
            )
        )
    return "\n".join(lines)


def run_single_plan_debug(payload: Dict[str, Any]) -> str:
    client = LLMClient()
    plan = client.generate_plan(**payload)
    return format_plan_debug_output(plan)


def run_full_eval_debug() -> str:
    client = LLMClient()
    report = run_planner_eval(client)
    return format_eval_debug_output(report)
