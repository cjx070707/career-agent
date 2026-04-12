from app.llm.planner_debug import format_eval_debug_output, format_plan_debug_output
from pathlib import Path


def test_format_plan_debug_output_includes_key_sections() -> None:
    text = format_plan_debug_output(
        {
            "task_type": "job_search",
            "reason": "planned by model",
            "steps": ["search_jobs"],
            "needs_more_context": False,
            "missing_context": [],
            "follow_up_question": None,
            "planner_source": "model",
        }
    )

    assert "task_type: job_search" in text
    assert "steps: ['search_jobs']" in text
    assert "reason: planned by model" in text
    assert "planner_source: model" in text


def test_format_eval_debug_output_includes_summary_metrics() -> None:
    text = format_eval_debug_output(
        {
            "summary": {
                "total_cases": 5,
                "schema_success_rate": 1.0,
                "task_type_accuracy": 0.8,
                "steps_accuracy": 0.6,
                "follow_up_accuracy": 0.9,
            },
            "results": [
                {
                    "name": "job_search_with_profile",
                    "task_type_match": True,
                    "steps_match": True,
                    "follow_up_match": True,
                }
            ],
        }
    )

    assert "total_cases: 5" in text
    assert "task_type_accuracy: 0.8" in text
    assert "job_search_with_profile" in text


def test_debug_script_bootstraps_project_root() -> None:
    script = Path("scripts/debug_planner.py").read_text(encoding="utf-8")

    assert "sys.path" in script
    assert "Path(__file__).resolve().parents[1]" in script
