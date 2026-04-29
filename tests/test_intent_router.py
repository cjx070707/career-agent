import json
import unittest

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


class LLMIntentClassifierTests(unittest.TestCase):
    def _classify(self, payload, message, recent_turns=None, user_state=None):
        llm = FakeClassifierLLM(payload)
        classifier = LLMIntentClassifier(llm_client=llm)
        return classifier.classify(
            message=message,
            recent_turns=recent_turns or [],
            user_state=user_state or {"has_resume": True, "has_candidate": True, "has_job_detail": False},
            available_tools=[
                "get_candidate_profile",
                "get_resume_by_id",
                "search_jobs",
                "match_resume_to_jobs",
                "get_career_insights",
                "get_interview_feedback",
            ],
        )

    def test_resume_analysis_case(self):
        plan = self._classify(
            {
                "task_type": "resume_analysis",
                "steps": ["get_resume_by_id"],
                "needs_more_context": False,
                "missing_context": [],
                "follow_up_question": None,
                "plan_type": "",
                "reasoning": "resume improvement",
            },
            "我的简历该怎么更强",
        )
        self.assertEqual(plan["task_type"], "resume_analysis")

    def test_job_match_planning_or_search_case(self):
        plan = self._classify(
            {
                "task_type": "job_match_planning",
                "steps": ["get_candidate_profile", "get_resume_by_id", "search_jobs", "match_resume_to_jobs"],
                "needs_more_context": False,
                "missing_context": [],
                "follow_up_question": None,
                "plan_type": "",
                "reasoning": "recommend jobs",
            },
            "有什么岗位适合我?",
        )
        self.assertIn(plan["task_type"], {"job_match_planning", "job_search"})

    def test_follow_up_platform_matching_case(self):
        plan = self._classify(
            {
                "task_type": "job_match_planning",
                "steps": ["get_candidate_profile", "get_resume_by_id", "search_jobs", "match_resume_to_jobs"],
                "needs_more_context": False,
                "missing_context": [],
                "follow_up_question": None,
                "plan_type": "",
                "reasoning": "follow-up",
            },
            "就匹配当前平台的就可以",
            recent_turns=["用户: 有什么岗位适合我", "助手: 我可以帮你匹配当前平台岗位"],
        )
        self.assertEqual(plan["task_type"], "job_match_planning")
        self.assertFalse(plan["needs_more_context"])

    def test_career_insights_case(self):
        plan = self._classify(
            {
                "task_type": "career_insights",
                "steps": ["get_career_insights"],
                "needs_more_context": False,
                "missing_context": [],
                "follow_up_question": None,
                "plan_type": "",
                "reasoning": "growth advice",
            },
            "我该如何提升",
        )
        self.assertEqual(plan["task_type"], "career_insights")

    def test_third_party_is_fallback_with_plan_type(self):
        plan = self._classify(
            {
                "task_type": "fallback",
                "steps": [],
                "needs_more_context": False,
                "missing_context": [],
                "follow_up_question": None,
                "plan_type": "third_party_advice",
                "reasoning": "third party",
            },
            "我朋友想转 PM",
        )
        self.assertEqual(plan["task_type"], "fallback")
        self.assertEqual(plan["plan_type"], "third_party_advice")

    def test_inline_resume_means_no_more_context(self):
        plan = self._classify(
            {
                "task_type": "resume_analysis",
                "steps": ["get_resume_by_id"],
                "needs_more_context": False,
                "missing_context": [],
                "follow_up_question": None,
                "plan_type": "",
                "reasoning": "inline resume present",
            },
            "这是我的简历：教育背景... 项目经历...",
            user_state={"has_resume": False, "has_candidate": True, "has_job_detail": False},
        )
        self.assertFalse(plan["needs_more_context"])


if __name__ == "__main__":
    unittest.main()
