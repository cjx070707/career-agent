from dataclasses import dataclass, field
import re
from typing import Any, Dict, List, Optional

from app.llm.client import LLMClient
from app.schemas.chat import ChatPlan, ChatSource
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


class AgentService:
    """Minimal Agent orchestration for message -> memory -> retrieval -> answer."""

    def __init__(
        self,
        memory_service: Optional[MemoryService] = None,
        retrieval_service: Optional[RetrievalService] = None,
        llm_client: Optional[LLMClient] = None,
        tool_registry: Optional[ToolRegistry] = None,
    ) -> None:
        self.memory_service = memory_service or MemoryService()
        self.retrieval_service = retrieval_service or RetrievalService()
        self.llm_client = llm_client or LLMClient()
        self.tool_registry = tool_registry or build_default_tool_registry()
        self.candidate_service = CandidateService()
        self.resume_service = ResumeService()
        self.profile_service = ProfileService()

    def respond(self, user_id: str, message: str) -> AgentResult:
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
            )
        if plan.steps:
            tool_trace, execution_state = self._execute_plan(user_id, message, plan.steps)
            final_tool_name = tool_trace[-1] if tool_trace else None
            final_result = execution_state.get("last_result")
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
            )

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
            plan=None,
            tool_trace=[],
        )

    def _to_chat_source(self, result: RetrievalResult) -> ChatSource:
        return ChatSource(
            type=result.type,
            title=result.title,
            snippet=result.snippet,
        )

    def _build_plan(
        self,
        user_id: str,
        message: str,
        has_recent_memory: bool,
        profile: Dict[str, Any],
    ) -> ChatPlan:
        _ = has_recent_memory
        plan_payload = self.llm_client.generate_plan(
            message=message,
            memory_context=[turn.content for turn in self.memory_service.load_recent_messages(user_id)],
            profile=profile,
            available_tools=self.tool_registry.list_tool_names(),
            user_state={
                "has_candidate": self.candidate_service.has_candidate(),
                "has_resume": self.resume_service.has_resume(),
            },
        )
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
            payload = self._build_tool_payload(user_id, message, step, state)
            tool_result = self.tool_registry.run(step, payload)
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
            candidate = self.candidate_service.get_latest_candidate()
            return {"candidate_id": candidate["id"]}

        if tool_name == "get_resume_by_id":
            resume = self.resume_service.get_latest_resume()
            state["latest_resume_id"] = resume["id"]
            return {"resume_id": resume["id"]}

        if tool_name == "match_resume_to_jobs":
            resume_id = state.get("latest_resume_id")
            if resume_id is None:
                resume = self.resume_service.get_latest_resume()
                resume_id = resume["id"]
                state["latest_resume_id"] = resume_id
            return {"resume_id": resume_id}

        if tool_name == "search_jobs":
            resume_data = state.get("get_resume_by_id")
            query_parts = [message]
            if resume_data is not None:
                query_parts.append(str(resume_data.get("content", "")))
            query = self.profile_service.augment_job_query(user_id, " ".join(query_parts))
            return {"query": query}

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
            return (
                f"基于你的简历，当前最匹配的岗位是 {top_match['job_title']}，"
                f"匹配分数约为 {top_match['match_score']}。"
            )

        return "工具执行完成。"

    def _extract_sources(self, tool_name: str, tool_result: Any) -> List[ChatSource]:
        if tool_name == "search_jobs":
            return [
                ChatSource(
                    type=result["type"],
                    title=result["title"],
                    snippet=result["snippet"],
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
