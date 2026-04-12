from app.llm.planner_eval import run_planner_eval


class EvalStubLLMClient:
    def __init__(self, plans):
        self._plans = plans
        self._index = 0

    def generate_plan(
        self,
        message,
        memory_context,
        profile,
        available_tools,
        user_state=None,
    ):
        plan = self._plans[self._index]
        self._index += 1
        return plan


def test_run_planner_eval_returns_summary_metrics() -> None:
    stub = EvalStubLLMClient(
        [
            {
                "task_type": "job_search",
                "reason": "search",
                "steps": ["search_jobs"],
                "needs_more_context": False,
                "missing_context": [],
                "follow_up_question": None,
            },
            {
                "task_type": "job_match",
                "reason": "ask for resume",
                "steps": [],
                "needs_more_context": True,
                "missing_context": ["resume"],
                "follow_up_question": "请先提供简历",
            },
            {
                "task_type": "job_match_planning",
                "reason": "tools missing",
                "steps": ["get_candidate_profile", "search_jobs"],
                "needs_more_context": True,
                "missing_context": ["tooling"],
                "follow_up_question": None,
            },
            {
                "task_type": "job_match_planning",
                "reason": "multi step recommendation",
                "steps": [
                    "get_candidate_profile",
                    "get_resume_by_id",
                    "search_jobs",
                    "match_resume_to_jobs",
                ],
                "needs_more_context": False,
                "missing_context": [],
                "follow_up_question": None,
            },
            {
                "task_type": "candidate_profile",
                "reason": "ask for candidate info",
                "steps": [],
                "needs_more_context": True,
                "missing_context": ["candidate_profile"],
                "follow_up_question": "请先补充你的基本信息",
            },
        ]
    )

    report = run_planner_eval(stub)

    assert report["summary"]["total_cases"] >= 5
    assert report["summary"]["schema_success_rate"] == 1.0
    assert report["summary"]["task_type_accuracy"] == 1.0
    assert report["summary"]["steps_accuracy"] == 1.0
    assert report["summary"]["follow_up_accuracy"] == 1.0
    assert len(report["results"]) >= 2


def test_run_planner_eval_includes_expanded_high_value_cases() -> None:
    stub = EvalStubLLMClient(
        [
            {
                "task_type": "job_search",
                "reason": "search",
                "steps": ["search_jobs"],
                "needs_more_context": False,
                "missing_context": [],
                "follow_up_question": None,
            },
            {
                "task_type": "job_match",
                "reason": "ask for resume",
                "steps": [],
                "needs_more_context": True,
                "missing_context": ["resume"],
                "follow_up_question": "请先提供简历",
            },
            {
                "task_type": "job_match_planning",
                "reason": "tools missing",
                "steps": ["get_candidate_profile", "search_jobs"],
                "needs_more_context": True,
                "missing_context": ["tooling"],
                "follow_up_question": None,
            },
            {
                "task_type": "job_match_planning",
                "reason": "multi step recommendation",
                "steps": [
                    "get_candidate_profile",
                    "get_resume_by_id",
                    "search_jobs",
                    "match_resume_to_jobs",
                ],
                "needs_more_context": False,
                "missing_context": [],
                "follow_up_question": None,
            },
            {
                "task_type": "candidate_profile",
                "reason": "ask for candidate info",
                "steps": [],
                "needs_more_context": True,
                "missing_context": ["candidate_profile"],
                "follow_up_question": "请先补充你的基本信息",
            },
        ]
    )

    report = run_planner_eval(stub)
    case_names = [result["name"] for result in report["results"]]

    assert report["summary"]["total_cases"] >= 5
    assert "job_match_missing_tools" in case_names
    assert "multi_step_recommendation" in case_names
    assert "candidate_profile_missing_candidate" in case_names
