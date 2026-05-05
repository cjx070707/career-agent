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

    def _classifier_model(self):
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

    def test_implicit_job_search_phrase_forces_job_search(self):
        plan = self._classify(
            {
                "task_type": "job_match_planning",
                "steps": ["get_candidate_profile", "get_resume_by_id", "search_jobs", "match_resume_to_jobs"],
                "needs_more_context": False,
                "missing_context": [],
                "follow_up_question": None,
                "plan_type": "",
                "reasoning": "misclassified by model",
            },
            "我想找一份 data analyst 实习",
            user_state={"has_resume": True, "has_candidate": True, "has_job_detail": False},
        )
        self.assertEqual(plan["task_type"], "job_search")
        self.assertEqual(plan["steps"], ["search_jobs"])

    def test_recommend_with_resume_forces_full_match_chain(self):
        plan = self._classify(
            {
                "task_type": "career_insights",
                "steps": ["get_career_insights"],
                "needs_more_context": False,
                "missing_context": [],
                "follow_up_question": None,
                "plan_type": "",
                "reasoning": "model picked insights only",
            },
            "结合我的情况推荐适合投的岗位",
            user_state={"has_resume": True, "has_candidate": True, "has_job_detail": False},
        )
        self.assertEqual(plan["task_type"], "job_match_planning")
        self.assertEqual(
            plan["steps"],
            ["get_candidate_profile", "get_resume_by_id", "search_jobs", "match_resume_to_jobs"],
        )

    def test_compound_search_and_match_phrase_forces_full_chain(self):
        plan = self._classify(
            {
                "task_type": "job_search",
                "steps": ["search_jobs"],
                "needs_more_context": False,
                "missing_context": [],
                "follow_up_question": None,
                "plan_type": "",
                "reasoning": "model under-planned",
            },
            "帮我找 data 岗并用我的简历看看匹配度",
            user_state={"has_resume": True, "has_candidate": True, "has_job_detail": False},
        )
        self.assertEqual(plan["task_type"], "job_match_planning")
        self.assertEqual(
            plan["steps"],
            ["get_candidate_profile", "get_resume_by_id", "search_jobs", "match_resume_to_jobs"],
        )


if __name__ == "__main__":
    unittest.main()
