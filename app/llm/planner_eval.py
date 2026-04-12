from typing import Any, Dict, List, Optional

from app.llm.planner_eval_cases import DEFAULT_PLANNER_EVAL_CASES
from app.schemas.chat import ChatPlan


def run_planner_eval(
    llm_client: Any,
    cases: Optional[List[Dict[str, Any]]] = None,
) -> Dict[str, Any]:
    eval_cases = cases or DEFAULT_PLANNER_EVAL_CASES
    results = []
    schema_successes = 0
    task_type_hits = 0
    steps_hits = 0
    follow_up_hits = 0

    for case in eval_cases:
        raw_plan = llm_client.generate_plan(**case["input"])
        parsed_plan = ChatPlan.model_validate(raw_plan)
        schema_successes += 1

        expected = case["expected"]
        task_type_match = parsed_plan.task_type == expected["task_type"]
        steps_match = parsed_plan.steps == expected["steps"]
        follow_up_match = (
            parsed_plan.needs_more_context == expected["needs_more_context"]
            and parsed_plan.missing_context == expected["missing_context"]
            and (
                parsed_plan.follow_up_question == expected["follow_up_question"]
                or (
                    expected["follow_up_question"] is not None
                    and parsed_plan.follow_up_question is not None
                    and expected["follow_up_question"] in parsed_plan.follow_up_question
                )
            )
        )

        task_type_hits += int(task_type_match)
        steps_hits += int(steps_match)
        follow_up_hits += int(follow_up_match)

        results.append(
            {
                "name": case["name"],
                "task_type_match": task_type_match,
                "steps_match": steps_match,
                "follow_up_match": follow_up_match,
                "plan": parsed_plan.model_dump(),
            }
        )

    total_cases = len(eval_cases)
    return {
        "summary": {
            "total_cases": total_cases,
            "schema_success_rate": schema_successes / total_cases if total_cases else 0.0,
            "task_type_accuracy": task_type_hits / total_cases if total_cases else 0.0,
            "steps_accuracy": steps_hits / total_cases if total_cases else 0.0,
            "follow_up_accuracy": follow_up_hits / total_cases if total_cases else 0.0,
        },
        "results": results,
    }
