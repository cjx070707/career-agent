from dataclasses import dataclass, field
import re
from typing import Any, Dict, List, Optional

from app.llm.client import LLMClient
from app.routing.filter_extractor import extract_filters
from app.routing.intent_router import IntentRouter
from app.schemas.chat import ChatPlan, ChatSource, LLMTrace
from app.services.candidate_service import CandidateService
from app.services.memory_service import MemoryService
from app.services.profile_service import ProfileService
from app.services.retrieval_service import RetrievalResult, RetrievalService
from app.services.resume_service import ResumeService
from app.services.tool_registry import ToolRegistry, build_default_tool_registry


@dataclass
class AgentResult:
    answer: str
    memory_used: bool
    sources: list[ChatSource]
    tool_used: Optional[str] = None
    plan: Optional[ChatPlan] = None
    tool_trace: List[str] = field(default_factory=list)
    llm_trace: LLMTrace = field(default_factory=LLMTrace)


class AgentService:
    """Minimal Agent orchestration for message -> memory -> retrieval -> answer."""

    def __init__(
        self,
        memory_service: Optional[MemoryService] = None,
        retrieval_service: Optional[RetrievalService] = None,
        llm_client: Optional[LLMClient] = None,
        tool_registry: Optional[ToolRegistry] = None,
        intent_router: Optional[IntentRouter] = None,
    ) -> None:
        self.memory_service = memory_service or MemoryService()
        self.retrieval_service = retrieval_service or RetrievalService()
        self.llm_client = llm_client or LLMClient()
        self.tool_registry = tool_registry or build_default_tool_registry()
        self.intent_router = intent_router or IntentRouter()
        self.candidate_service = CandidateService()
        self.resume_service = ResumeService()
        self.profile_service = ProfileService()

    def respond(self, user_id: str, message: str) -> AgentResult:
        self._reset_llm_trace_markers()
        recent_turns = self.memory_service.load_recent_messages(user_id)
        profile = self.profile_service.update_from_message(user_id, message)
        plan = self._build_plan(user_id, message, bool(recent_turns), profile)
        if plan.needs_more_context and not plan.steps:
            answer = plan.follow_up_question or "我还需要更多信息，才能继续。"
            self.memory_service.save_turn(user_id, message, answer)
            return AgentResult(
                answer=answer,
                memory_used=bool(recent_turns),
                sources=[],
                tool_used=None,
                plan=plan,
                tool_trace=[],
                llm_trace=self._build_llm_trace(plan),
            )
        if plan.steps:
            tool_trace, execution_state = self._execute_plan(user_id, message, plan.steps)
            # If `_execute_plan` could not run any step (e.g., the planner asked
            # for `get_candidate_profile` but the user has no candidate yet), we
            # fall through to the generic retrieval+LLM answer path so the
            # request still produces a helpful response rather than 500-ing.
            final_tool_name = tool_trace[-1] if tool_trace else None
            final_result = execution_state.get("last_result")
        else:
            tool_trace, final_tool_name, final_result = [], None, None

        if tool_trace:
            if final_tool_name == "search_jobs":
                jobs = final_result if isinstance(final_result, list) else []
                answer = self.llm_client.summarize_job_search(
                    message=message,
                    memory_context=[turn.content for turn in recent_turns],
                    jobs=jobs,
                )
            else:
                answer = self._format_tool_answer(final_tool_name, final_result)
            sources = self._extract_sources(final_tool_name, final_result)
            self.memory_service.save_turn(user_id, message, answer)
            return AgentResult(
                answer=answer,
                memory_used=bool(recent_turns),
                sources=sources,
                tool_used=final_tool_name,
                plan=plan,
                tool_trace=tool_trace,
                llm_trace=self._build_llm_trace(plan),
            )

        retrieval_results: list[RetrievalResult] = []
        if plan.task_type != "fallback":
            retrieval_results = self.retrieval_service.search(message)
        answer = self.llm_client.generate(
            message=message,
            memory_context=[turn.content for turn in recent_turns],
            evidence=[result.title for result in retrieval_results],
        )

        self.memory_service.save_turn(user_id, message, answer)
        return AgentResult(
            answer=answer,
            memory_used=bool(recent_turns),
            sources=[self._to_chat_source(result) for result in retrieval_results],
            tool_used=None,
            # Keep `plan` present across every path so the /chat contract stays
            # stable; clients should always be able to read plan.task_type and
            # plan.planner_source without null-checking.
            plan=plan,
            tool_trace=[],
            llm_trace=self._build_llm_trace(plan),
        )

    def _reset_llm_trace_markers(self) -> None:
        self.llm_client.last_plan_source = "not_used"
        self.llm_client.last_job_search_summary_source = "not_used"
        self.llm_client.last_generate_source = "not_used"

    def _build_llm_trace(self, plan: Optional[ChatPlan]) -> LLMTrace:
        planner_source = "not_used"
        if plan is not None:
            planner_source = plan.planner_source or self.llm_client.last_plan_source
        return LLMTrace(
            planner_source=planner_source,
            job_search_summary_source=self.llm_client.last_job_search_summary_source,
            generate_source=self.llm_client.last_generate_source,
        )

    def _to_chat_source(self, result: RetrievalResult) -> ChatSource:
        return ChatSource(
            type=result.type,
            title=result.title,
            snippet=result.snippet,
            company=result.company,
            location=result.location,
            work_type=result.work_type,
            posted_at=result.posted_at,
            url=result.url,
        )

    def _build_plan(
        self,
        user_id: str,
        message: str,
        has_recent_memory: bool,
        profile: Dict[str, Any],
    ) -> ChatPlan:
        _ = has_recent_memory
        memory_context = [
            turn.content for turn in self.memory_service.load_recent_messages(user_id)
        ]
        available_tools = self.tool_registry.list_tool_names()
        user_state = {
            "has_candidate": self.candidate_service.has_candidate(user_id),
            "has_resume": self.resume_service.has_resume(user_id),
        }
        plan_payload = self.intent_router.route(
            message=message,
            memory_context=memory_context,
            profile=profile,
            available_tools=available_tools,
            user_state=user_state,
        )
        if plan_payload is None:
            plan_payload = self.llm_client.generate_plan(
                message=message,
                memory_context=memory_context,
                profile=profile,
                available_tools=available_tools,
                user_state=user_state,
            )
        # Ensure `planner_source` is always populated so the /chat contract is
        # stable even when the payload comes from an older fallback path.
        if not plan_payload.get("planner_source"):
            plan_payload["planner_source"] = self.llm_client.last_plan_source
        return ChatPlan.model_validate(plan_payload)

    def _execute_plan(
        self,
        user_id: str,
        message: str,
        steps: List[str],
    ) -> tuple[List[str], Dict[str, Any]]:
        trace: List[str] = []
        state: Dict[str, Any] = {}

        for step in steps:
            try:
                payload = self._build_tool_payload(user_id, message, step, state)
                tool_result = self.tool_registry.run(step, payload)
            except ValueError:
                # Planner asked for a step whose prerequisite is missing
                # (e.g., no candidate / resume for this user). Stop executing
                # and let the caller fall back to the generic answer path.
                break
            trace.append(step)
            state[step] = tool_result["data"]
            state["last_result"] = tool_result["data"]
            if not self._should_continue_after_step(step, tool_result["data"], state):
                break

        return trace, state

    def _should_continue_after_step(
        self,
        step: str,
        tool_result: Any,
        state: Dict[str, Any],
    ) -> bool:
        if step != "search_jobs":
            return True

        if not tool_result:
            state["last_result"] = []
            return False

        resume_data = state.get("get_resume_by_id")
        if not resume_data:
            return True

        resume_tokens = self._tokenize(str(resume_data.get("content", "")))
        if not resume_tokens:
            return True

        search_tokens: set[str] = set()
        for item in tool_result:
            search_tokens |= self._tokenize(
                f"{item.get('title', '')} {item.get('snippet', '')}"
            )

        meaningful_overlap = (
            resume_tokens - self._low_signal_tokens()
        ) & (
            search_tokens - self._low_signal_tokens()
        )
        if meaningful_overlap:
            return True

        state["last_result"] = []
        return False

    def _build_tool_payload(
        self,
        user_id: str,
        message: str,
        tool_name: str,
        state: Dict[str, Any],
    ) -> Dict[str, Any]:
        if tool_name == "get_candidate_profile":
            candidate = self.candidate_service.get_latest_candidate(user_id)
            return {"candidate_id": candidate["id"]}

        if tool_name == "get_resume_by_id":
            resume = self.resume_service.get_latest_resume(user_id)
            state["latest_resume_id"] = resume["id"]
            return {"resume_id": resume["id"]}

        if tool_name == "match_resume_to_jobs":
            resume_id = state.get("latest_resume_id")
            if resume_id is None:
                resume = self.resume_service.get_latest_resume(user_id)
                resume_id = resume["id"]
                state["latest_resume_id"] = resume_id
            return {"resume_id": resume_id}

        if tool_name == "search_jobs":
            resume_data = state.get("get_resume_by_id")
            query_parts = [message]
            if resume_data is not None:
                query_parts.append(str(resume_data.get("content", "")))
            query = self.profile_service.augment_job_query(user_id, " ".join(query_parts))
            # Structured slots come from the user's own message only; resume
            # text is free-form and would produce noisy location/work_type
            # signals (e.g., a Melbourne alumnus asking about Sydney jobs).
            payload: Dict[str, Any] = {"query": query}
            slot_filters = extract_filters(message)
            if slot_filters:
                payload["filters"] = slot_filters
            return payload

        if tool_name == "get_applications":
            return {"user_id": user_id, "limit": 10}

        if tool_name == "get_interview_feedback":
            return {"user_id": user_id, "limit": 10}

        return {}

    def _format_tool_answer(self, tool_name: str, tool_result: Any) -> str:
        if tool_name == "get_candidate_profile":
            return f"我查到了你的候选人资料，当前姓名是 {tool_result['name']}。"

        if tool_name == "search_jobs":
            if not tool_result:
                return "我暂时没有找到相关岗位。"
            titles = ", ".join(result["title"] for result in tool_result[:3])
            return f"我找到了这些相关岗位：{titles}。"

        if tool_name == "match_resume_to_jobs":
            matches = tool_result.get("matches", [])
            if not matches:
                return "我暂时没有找到和这份简历高度匹配的岗位。"
            top_match = matches[0]
            answer_parts = [
                f"基于你的简历，优先推荐 {top_match['job_title']}，"
                f"匹配分数约为 {top_match['match_score']}。"
            ]
            rationale = str(top_match.get("rationale", "")).strip()
            if rationale:
                answer_parts.append(f"匹配理由：{rationale}。")
            if len(matches) > 1:
                follow_ups = "、".join(
                    match["job_title"] for match in matches[1:3]
                )
                answer_parts.append(f"也可以继续关注 {follow_ups}。")
            return "".join(answer_parts)

        if tool_name == "get_applications":
            rows = tool_result if isinstance(tool_result, list) else []
            if not rows:
                return "你最近还没有投递记录。"
            summary = []
            for row in rows[:3]:
                company = str(row.get("company", "")).strip()
                title = str(row.get("job_title", "")).strip()
                status = str(row.get("status", "")).strip()
                summary.append(f"{company} - {title}（{status}）")
            return "你最近的投递包括：" + "；".join(summary) + "。"

        if tool_name == "get_interview_feedback":
            rows = tool_result if isinstance(tool_result, list) else []
            if not rows:
                return "你最近还没有面试反馈记录。"
            summary = []
            for row in rows[:3]:
                company = str(row.get("company", "")).strip()
                title = str(row.get("job_title", "")).strip()
                round_name = str(row.get("interview_round", "")).strip()
                result = str(row.get("result", "")).strip()
                summary.append(f"{company} - {title}（{round_name}/{result}）")
            return "你最近的面试反馈包括：" + "；".join(summary) + "。"

        return "工具执行完成。"

    def _extract_sources(self, tool_name: str, tool_result: Any) -> List[ChatSource]:
        if tool_name == "search_jobs":
            # /chat sources expose short evidence text, not the raw tool payload.
            return [
                ChatSource(
                    type=result["type"],
                    title=result["title"],
                    snippet=str(result.get("reason") or result.get("snippet") or "").strip(),
                    company=result.get("company"),
                    location=result.get("location"),
                    work_type=result.get("work_type"),
                    posted_at=result.get("posted_at"),
                    url=result.get("url"),
                )
                for result in tool_result
            ]

        if tool_name == "match_resume_to_jobs":
            return [
                ChatSource(
                    type="job_posting",
                    title=match["job_title"],
                    snippet=match["rationale"],
                )
                for match in tool_result.get("matches", [])
            ]

        if tool_name == "get_applications":
            return [
                ChatSource(
                    type="application",
                    title=f"{item.get('company', '')} - {item.get('job_title', '')}".strip(" -"),
                    snippet=f"状态：{item.get('status', '')}；备注：{item.get('note', '')}".strip(),
                )
                for item in (tool_result if isinstance(tool_result, list) else [])
            ]

        if tool_name == "get_interview_feedback":
            return [
                ChatSource(
                    type="interview_feedback",
                    title=f"{item.get('company', '')} - {item.get('job_title', '')}".strip(" -"),
                    snippet=(
                        f"轮次：{item.get('interview_round', '')}；"
                        f"结果：{item.get('result', '')}；"
                        f"反馈：{item.get('feedback', '')}"
                    ).strip(),
                )
                for item in (tool_result if isinstance(tool_result, list) else [])
            ]

        return []

    def _tokenize(self, text: str) -> set[str]:
        return set(re.findall(r"[a-zA-Z0-9]+", text.lower()))

    def _low_signal_tokens(self) -> set[str]:
        return {
            "engineer",
            "intern",
            "platform",
            "systems",
            "system",
            "role",
            "job",
            "jobs",
        }
