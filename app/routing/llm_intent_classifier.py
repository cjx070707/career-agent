import json
from typing import Any, Dict, List, Optional

import httpx
from pydantic import BaseModel, Field, ValidationError

from app.llm.client import LLMClient


class ClassifierOutput(BaseModel):
    task_type: str
    steps: List[str] = Field(default_factory=list)
    needs_more_context: bool = False
    missing_context: List[str] = Field(default_factory=list)
    follow_up_question: Optional[str] = None
    plan_type: str = ""
    reasoning: str = ""


class LLMIntentClassifier:
    """Single-call LLM intent classifier replacing rule-based router/gateway."""

    ALLOWED_TASK_TYPES = {
        "resume_analysis",
        "job_match",
        "job_match_planning",
        "job_search",
        "career_insights",
        "interview_prep",
        "fallback",
    }
    TIMEOUT_SECONDS = 8.0

    def __init__(self, llm_client: Optional[LLMClient] = None) -> None:
        self.llm_client = llm_client or LLMClient()
        self.last_reasoning = ""

    def classify(
        self,
        *,
        message: str,
        recent_turns: List[str],
        user_state: Dict[str, Any],
        available_tools: List[str],
    ) -> Dict[str, Any]:
        self.last_reasoning = ""

        if not self.llm_client.is_configured():
            return self._fallback_output("llm_not_configured")

        request = self._build_request(
            message=message,
            recent_turns=recent_turns,
            user_state=user_state,
            available_tools=available_tools,
        )
        try:
            payload = self.llm_client._post_responses(
                f"{self.llm_client._planner_base_url().rstrip('/')}/chat/completions",
                api_key=self.llm_client._planner_api_key(),
                payload=request,
                timeout=self.TIMEOUT_SECONDS,
            )
            raw = self.llm_client._extract_chat_completion_text(payload).strip()
            parsed = json.loads(raw) if raw else {}
            normalized = self._normalize(
                payload=parsed,
                message=message,
                user_state=user_state,
                available_tools=available_tools,
            )
            self.last_reasoning = normalized["reasoning"]
            return normalized
        except (RuntimeError, ValueError, TypeError, json.JSONDecodeError, ValidationError, httpx.HTTPError):
            return self._fallback_output("schema_or_request_error")

    def _normalize(
        self,
        *,
        payload: Dict[str, Any],
        message: str,
        user_state: Dict[str, Any],
        available_tools: List[str],
    ) -> Dict[str, Any]:
        parsed = ClassifierOutput.model_validate(payload)
        task_type = str(parsed.task_type or "").strip().lower()
        if task_type not in self.ALLOWED_TASK_TYPES:
            task_type = "fallback"

        missing_context = [
            str(item).strip() for item in parsed.missing_context if isinstance(item, str) and str(item).strip()
        ]
        steps = [str(item).strip() for item in parsed.steps if isinstance(item, str) and str(item).strip()]

        if task_type == "fallback":
            steps = []
        lowered = message.lower()
        implicit_search_markers = (
            "我想找",
            "我要找",
            "帮我找",
            "找一份",
            "search",
            "find",
        )
        recommend_markers = (
            "结合我的情况推荐",
            "推荐适合投",
            "适合投的岗位",
            "what jobs fit me",
            "recommend jobs",
        )

        if any(marker in lowered or marker in message for marker in recommend_markers) and bool(user_state.get("has_resume")):
            task_type = "job_match_planning"
            steps = [
                step
                for step in ["get_candidate_profile", "get_resume_by_id", "search_jobs", "match_resume_to_jobs"]
                if step in available_tools
            ]
            parsed.needs_more_context = False

        is_compound_search_match = (
            ("匹配" in message or "match" in lowered)
            and ("简历" in message or "resume" in lowered)
            and any(marker in lowered or marker in message for marker in implicit_search_markers)
        )
        if is_compound_search_match and bool(user_state.get("has_resume")):
            task_type = "job_match_planning"
            steps = [
                step
                for step in ["get_candidate_profile", "get_resume_by_id", "search_jobs", "match_resume_to_jobs"]
                if step in available_tools
            ]
            parsed.needs_more_context = False

        if any(marker in lowered or marker in message for marker in implicit_search_markers) and not is_compound_search_match:
            has_explicit_goal_planning = any(
                marker in lowered or marker in message
                for marker in ("设定目标", "制定目标", "目标规划", "goal plan", "set goal")
            )
            if not has_explicit_goal_planning:
                task_type = "job_search"
                if "search_jobs" in available_tools:
                    steps = ["search_jobs"]

        if any(marker in message or marker in lowered for marker in ("我朋友", "我同学", "my friend", "friend wants")):
            return {
                "task_type": "fallback",
                "steps": [],
                "needs_more_context": False,
                "missing_context": [],
                "follow_up_question": None,
                "plan_type": "third_party_advice",
                "reasoning": str(parsed.reasoning or "").strip() or "third_party_advice",
                "planner_source": "model",
                "domain": "career_advice",
                "action": "advise",
                "required_context": [],
            }
        if task_type == "job_match":
            has_jd_hint = bool(user_state.get("has_job_detail")) or any(
                marker in lowered
                for marker in ("jd", "job description", "岗位描述", "招聘链接", "requirements", "职责", "要求")
            )
            if not has_jd_hint:
                return {
                    "task_type": "job_match",
                    "steps": [],
                    "needs_more_context": True,
                    "missing_context": ["job_detail"],
                    "follow_up_question": "请贴一下岗位 JD 或招聘链接，我再帮你判断匹配度。",
                    "plan_type": "",
                    "reasoning": str(parsed.reasoning or "").strip() or "job_match_without_jd",
                    "planner_source": "model",
                    "domain": "job_match",
                    "action": "compare",
                    "required_context": ["resume", "job_detail"],
                }

        if task_type == "job_match_planning" and not bool(user_state.get("has_resume")):
            task_type = "job_search"
            if "search_jobs" in available_tools:
                steps = ["search_jobs"]

        payload_out = {
            "task_type": task_type,
            "steps": steps,
            "needs_more_context": bool(parsed.needs_more_context),
            "missing_context": missing_context,
            "follow_up_question": (
                parsed.follow_up_question.strip()
                if isinstance(parsed.follow_up_question, str) and parsed.follow_up_question.strip()
                else None
            ),
            "plan_type": str(parsed.plan_type or "").strip(),
            "reasoning": str(parsed.reasoning or "").strip(),
            "planner_source": "model",
        }
        if task_type == "job_match":
            payload_out["domain"] = "job_match"
            payload_out["action"] = "compare"
            payload_out["required_context"] = ["resume", "job_detail"]
        return payload_out

    def _fallback_output(self, reason: str) -> Dict[str, Any]:
        return {
            "task_type": "fallback",
            "steps": [],
            "needs_more_context": False,
            "missing_context": [],
            "follow_up_question": None,
            "plan_type": "",
            "reasoning": reason,
            "planner_source": "fallback",
        }

    def _build_request(
        self,
        *,
        message: str,
        recent_turns: List[str],
        user_state: Dict[str, Any],
        available_tools: List[str],
    ) -> Dict[str, Any]:
        schema = ClassifierOutput.model_json_schema()
        request = {
            "model": self.llm_client._classifier_model(),
            "messages": [
                {"role": "system", "content": CLASSIFIER_SYSTEM_PROMPT},
                {
                    "role": "user",
                    "content": json.dumps(
                        {
                            "message": message,
                            "recent_turns": recent_turns,
                            "user_state": user_state,
                            "available_tools": available_tools,
                        },
                        ensure_ascii=False,
                    ),
                },
            ],
            "response_format": {
                "type": "json_schema",
                "json_schema": {
                    "name": "intent_classifier_output",
                    "strict": True,
                    "schema": schema,
                },
            },
        }
        if getattr(self.llm_client, "_disable_thinking", None):
            self.llm_client._disable_thinking(request)
        return request


CLASSIFIER_SYSTEM_PROMPT = """
You are an intent classifier for a vertical career agent.
Return JSON only. No markdown.

Task types:
1) resume_analysis
- User wants resume review, summary, optimization, or stronger positioning.

2) job_match
- User asks if a specific role/JD fits them. Usually needs resume + job_detail.

3) job_match_planning
- User wants "what jobs fit me" style recommendations or wants platform-level matching chain.
- This does NOT require a specific JD.

4) job_search
- User wants raw job discovery/search without resume-fit scoring.

5) career_insights
- User asks improvement strategy, bottleneck diagnosis, growth path, next-step advice for self.

6) interview_prep
- User asks interview preparation, likely questions, mock interview, answer polishing.

7) fallback
- Out of career scope, third-party advice (e.g., "my friend"), unsafe/unknown, or unclear intent.

How to use recent_turns:
- Treat recent_turns as dialogue memory. Resolve follow-up phrases like "就按刚才那个", "那就匹配当前平台".
- If current message is short/elliptical, infer intent from the nearest relevant prior turn.
- Do not ask for context already provided in recent_turns.

When needs_more_context must be true:
- Missing critical user-provided context that cannot be replaced by tools.
- Typical missing_context values: resume, job_detail, target_role.
- Set to false when inline resume text exists in current message even if user_state.has_resume is false.
- For job_match_planning and job_search, do NOT require job_detail.

Few-shot examples (input -> output):

[resume_analysis]
Input: "我的简历该怎么更强"
Output: {"task_type":"resume_analysis","steps":["get_resume_by_id"],"needs_more_context":false,"missing_context":[],"follow_up_question":null,"reasoning":"resume strengthening request"}
Input: "能不能帮我把这份CV打磨一下，更像后端实习投递版本"
Output: {"task_type":"resume_analysis","steps":["get_resume_by_id"],"needs_more_context":false,"missing_context":[],"follow_up_question":null,"reasoning":"cv polishing request"}

[job_match]
Input: "这个岗位适合我吗？这是JD: 需要Java Spring和3年经验"
Output: {"task_type":"job_match","steps":["match_resume_to_jobs"],"needs_more_context":false,"missing_context":[],"follow_up_question":null,"reasoning":"specific jd fit check"}
Input: "我和这个职位匹配度高不高"
Output: {"task_type":"job_match","steps":[],"needs_more_context":true,"missing_context":["job_detail"],"follow_up_question":"请贴一下岗位 JD 或链接，我再帮你判断匹配度。","reasoning":"fit check without jd"}

[job_match_planning]
Input: "有什么岗位适合我?"
Output: {"task_type":"job_match_planning","steps":["get_candidate_profile","get_resume_by_id","search_jobs","match_resume_to_jobs"],"needs_more_context":false,"missing_context":[],"follow_up_question":null,"reasoning":"recommendation style fit planning"}
Input: "就匹配当前平台的就可以"
Output: {"task_type":"job_match_planning","steps":["get_candidate_profile","get_resume_by_id","search_jobs","match_resume_to_jobs"],"needs_more_context":false,"missing_context":[],"follow_up_question":null,"reasoning":"follow-up confirming platform matching"}

[job_search]
Input: "帮我找悉尼的数据分析实习"
Output: {"task_type":"job_search","steps":["search_jobs"],"needs_more_context":false,"missing_context":[],"follow_up_question":null,"reasoning":"pure job search"}
Input: "有没有 backend intern opening"
Output: {"task_type":"job_search","steps":["search_jobs"],"needs_more_context":false,"missing_context":[],"follow_up_question":null,"reasoning":"english variant job search"}
Input: "我想找一份 data analyst 实习"
Output: {"task_type":"job_search","steps":["search_jobs"],"needs_more_context":false,"missing_context":[],"follow_up_question":null,"reasoning":"implicit search intent"}

Intent boundary:
- Phrases like "我想找/我要找/帮我找 + 岗位" are job_search, not goal planning.
- Only choose goal-setting semantics when the user explicitly asks to set/plan a goal.
- Compound request like "找岗位 + 用我的简历看匹配度" must use job_match_planning chain (profile -> resume -> search -> match).

[career_insights]
Input: "我该如何提升"
Output: {"task_type":"career_insights","steps":["get_career_insights"],"needs_more_context":false,"missing_context":[],"follow_up_question":null,"reasoning":"self improvement strategy"}
Input: "我最近投递没进展，下一步怎么办"
Output: {"task_type":"career_insights","steps":["get_career_insights"],"needs_more_context":false,"missing_context":[],"follow_up_question":null,"reasoning":"application stagnation diagnosis"}

[interview_prep]
Input: "下周后端实习一面，帮我做面试准备"
Output: {"task_type":"interview_prep","steps":["get_interview_feedback"],"needs_more_context":false,"missing_context":[],"follow_up_question":null,"reasoning":"interview prep request"}
Input: "可以模拟一轮 PM 面试吗"
Output: {"task_type":"interview_prep","steps":["get_interview_feedback"],"needs_more_context":false,"missing_context":[],"follow_up_question":null,"reasoning":"mock interview request"}

[fallback]
Input: "我朋友想转 PM"
Output: {"task_type":"fallback","steps":[],"needs_more_context":false,"missing_context":[],"follow_up_question":null,"plan_type":"third_party_advice","reasoning":"third-party advice should not use user profile"}
Input: "今天天气怎么样"
Output: {"task_type":"fallback","steps":[],"needs_more_context":false,"missing_context":[],"follow_up_question":null,"plan_type":"","reasoning":"non-career domain"}

Always output valid JSON matching the schema.
""".strip()
