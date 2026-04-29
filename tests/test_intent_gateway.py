import json

from app.routing.llm_intent_classifier import LLMIntentClassifier


class FakeClassifierLLM:
    def __init__(self, payload):
        self.payload = payload

    def is_configured(self):
        return True

    def _planner_base_url(self):
        return "https://example.test"

    def _planner_api_key(self):
        return "k"

    def _planner_model(self):
        return "gpt-test"

    def _disable_thinking(self, request):
        request["thinking"] = {"type": "disabled"}

    def _post_responses(self, *_args, **_kwargs):
        return {
            "choices": [
                {
                    "message": {
                        "content": json.dumps(self.payload, ensure_ascii=False),
                    }
                }
            ]
        }

    def _extract_chat_completion_text(self, payload):
        return payload["choices"][0]["message"]["content"]


def test_classifier_schema_failure_degrades_to_fallback() -> None:
    llm = FakeClassifierLLM(
        {
            "task_type": "career_insights",
            # missing required keys triggers schema failure
        }
    )
    classifier = LLMIntentClassifier(llm_client=llm)
    plan = classifier.classify(
        message="我该如何提升",
        recent_turns=[],
        user_state={"has_resume": True, "has_candidate": True, "has_job_detail": False},
        available_tools=[],
    )

    assert plan["task_type"] == "fallback"
    assert plan["planner_source"] == "fallback"


def test_classifier_non_career_fallback_plan_type_empty() -> None:
    llm = FakeClassifierLLM(
        {
            "task_type": "fallback",
            "steps": [],
            "needs_more_context": False,
            "missing_context": [],
            "follow_up_question": None,
            "plan_type": "",
            "reasoning": "non career",
        }
    )
    classifier = LLMIntentClassifier(llm_client=llm)
    plan = classifier.classify(
        message="今天天气怎么样",
        recent_turns=[],
        user_state={"has_resume": True, "has_candidate": True, "has_job_detail": False},
        available_tools=[],
    )

    assert plan["task_type"] == "fallback"
    assert plan["plan_type"] == ""
