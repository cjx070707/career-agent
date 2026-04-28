from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional

from app.llm.client import LLMClient
from app.env import settings
from app.resolvers.context_requirement_resolver import ContextRequirementResolver
from app.resolvers.tool_resolver import ToolResolver
from app.routing.intent_router import IntentRouter
from app.schemas.chat import ChatPlan, ChatSource, LLMTrace
from app.services.candidate_service import CandidateService
from app.services.career_event_service import CareerEventService
from app.services.memory_service import MemoryService
from app.services.plan_executor import PlanExecutor
from app.services.profile_service import ProfileService
from app.services.retrieval_service import RetrievalResult, RetrievalService
from app.services.response_formatter import ToolResponseFormatter
from app.services.resume_service import ResumeService
from app.services.tool_payload_builder import ToolPayloadBuilder
from app.tools.registry import ToolRegistry, build_default_tool_registry


@dataclass
class AgentResult:
    answer: str
    memory_used: bool
    sources: list[ChatSource]
    stage: str
    tool_used: Optional[str] = None
    plan: Optional[ChatPlan] = None
    tool_trace: List[str] = field(default_factory=list)
    loop_trace: List[Dict[str, Any]] = field(default_factory=list)
    llm_trace: LLMTrace = field(default_factory=LLMTrace)


class AgentService:
    """Minimal Agent orchestration for message -> memory -> retrieval -> answer."""
    LOOP_ENABLED_TASK_TYPES = {"job_match_planning", "career_insights"}
    MAX_LOOP_STEPS = 8
    MAX_REPLANS = 2
    MAX_STEP_REPEAT = 2

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
        self.context_requirement_resolver = ContextRequirementResolver()
        self.tool_resolver = ToolResolver()
        self.candidate_service = CandidateService()
        self.resume_service = ResumeService()
        self.profile_service = ProfileService()
        self.tool_payload_builder = ToolPayloadBuilder(
            candidate_service=self.candidate_service,
            resume_service=self.resume_service,
            profile_service=self.profile_service,
        )
        self.response_formatter = ToolResponseFormatter()
        self.plan_executor = PlanExecutor(
            tool_registry=self.tool_registry,
            llm_client=self.llm_client,
            max_loop_steps=self.MAX_LOOP_STEPS,
            max_step_repeat=self.MAX_STEP_REPEAT,
        )
        self.career_event_service = CareerEventService(
            retrieval_service=self.retrieval_service,
            llm_client=self.llm_client,
        )

    def respond(self, user_id: str, message: str) -> AgentResult:
        self._reset_llm_trace_markers()
        recent_turns = self.memory_service.load_recent_messages(user_id)
        profile = self.profile_service.update_from_message(user_id, message)
        self.career_event_service.sync_from_message(user_id, message)
        plan = self._build_plan(user_id, message, bool(recent_turns), profile)
        user_state = self._build_user_state(user_id=user_id, message=message)
        context_resolution = self.context_requirement_resolver.resolve(
            plan=plan,
            message=message,
            user_state=user_state,
            profile=profile,
            memory_context=[turn.content for turn in recent_turns],
        )
        self._apply_context_resolution(plan, context_resolution)
        if plan.needs_more_context:
            answer = plan.follow_up_question or "我还需要更多信息，才能继续。"
            self.memory_service.save_turn(user_id, message, answer)
            return AgentResult(
                answer=answer,
                stage="fallback",
                memory_used=bool(recent_turns),
                sources=[],
                tool_used=None,
                plan=plan,
                tool_trace=[],
                loop_trace=[],
                llm_trace=self._build_llm_trace(plan),
            )

        tool_resolution = self.tool_resolver.resolve(
            plan=plan,
            resolved_context=context_resolution,
            available_tools=self.tool_registry.list_tool_names(),
        )
        self._apply_tool_resolution(plan, tool_resolution)

        if plan.task_type == "fallback" and plan.planner_source == "router" and not plan.steps:
            answer = self._format_router_fallback_answer(message)
            self.memory_service.save_turn(user_id, message, answer)
            return AgentResult(
                answer=answer,
                stage="fallback",
                memory_used=bool(recent_turns),
                sources=[],
                tool_used=None,
                plan=plan,
                tool_trace=[],
                loop_trace=[],
                llm_trace=self._build_llm_trace(plan),
            )
        resolved_steps = self._tool_chain_to_steps(plan.tool_chain)
        execution_steps = resolved_steps if resolved_steps else list(plan.steps)
        if tool_resolution.executable is False:
            execution_steps = []

        if execution_steps:
            if self._should_use_react_loop(plan.task_type):
                tool_trace, execution_state, loop_trace = self.plan_executor.execute_react_loop(
                    user_id=user_id,
                    message=message,
                    initial_steps=execution_steps,
                    task_type=plan.task_type,
                    build_payload=self._build_tool_payload,
                    should_continue_after_step=self._should_continue_after_step,
                )
            else:
                tool_trace, execution_state, loop_trace = self.plan_executor.execute_plan(
                    user_id=user_id,
                    message=message,
                    steps=execution_steps,
                    build_payload=self._build_tool_payload,
                    should_continue_after_step=self._should_continue_after_step,
                )
            # If `_execute_plan` could not run any step (e.g., the planner asked
            # for `get_candidate_profile` but the user has no candidate yet), we
            # fall through to the generic retrieval+LLM answer path so the
            # request still produces a helpful response rather than 500-ing.
            final_tool_name = tool_trace[-1] if tool_trace else None
            final_result = execution_state.get("last_result")
        else:
            tool_trace, final_tool_name, final_result, loop_trace = [], None, None, []

        if tool_trace:
            if final_tool_name == "search_jobs":
                jobs = final_result if isinstance(final_result, list) else []
                answer = self.llm_client.summarize_job_search(
                    message=message,
                    memory_context=[turn.content for turn in recent_turns],
                    jobs=jobs,
                )
            else:
                answer = self.response_formatter.format_tool_answer(final_tool_name, final_result)
            sources = self.response_formatter.extract_sources(final_tool_name, final_result)
            self.memory_service.save_turn(user_id, message, answer)
            return AgentResult(
                answer=answer,
                stage="tool",
                memory_used=bool(recent_turns),
                sources=sources,
                tool_used=final_tool_name,
                plan=plan,
                tool_trace=tool_trace,
                loop_trace=loop_trace,
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
            stage="done",
            memory_used=bool(recent_turns),
            sources=[self._to_chat_source(result) for result in retrieval_results],
            tool_used=None,
            # Keep `plan` present across every path so the /chat contract stays
            # stable; clients should always be able to read plan.task_type and
            # plan.planner_source without null-checking.
            plan=plan,
            tool_trace=[],
            loop_trace=[],
            llm_trace=self._build_llm_trace(plan),
        )

    def _reset_llm_trace_markers(self) -> None:
        self.llm_client.last_plan_source = "not_used"
        self.llm_client.last_job_search_summary_source = "not_used"
        self.llm_client.last_generate_source = "not_used"

    def _format_router_fallback_answer(self, message: str) -> str:
        _ = message
        return "你好！我可以帮你找岗位、分析简历匹配度、查看投递记录，或者结合面试反馈给你下一步准备建议。"

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
        user_state = self._build_user_state(user_id=user_id, message=message)
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

    def _build_user_state(self, *, user_id: str, message: str) -> Dict[str, Any]:
        return {
            "has_candidate": self.candidate_service.has_candidate(user_id),
            "has_resume": self.resume_service.has_resume(user_id),
            "has_job_detail": self._message_has_job_detail(message),
        }

    def _message_has_job_detail(self, message: str) -> bool:
        lowered = message.lower()
        return any(
            marker in lowered
            for marker in ("jd", "job description", "requirements", "招聘链接", "岗位描述", "职责", "要求")
        )

    def _apply_context_resolution(self, plan: ChatPlan, resolution: Any) -> None:
        plan.required_context = resolution.required_context
        plan.missing_context = resolution.missing_context
        plan.needs_more_context = resolution.needs_more_context
        plan.follow_up_question = resolution.follow_up_question
        plan.resolver_trace = list(resolution.resolver_trace)

    def _apply_tool_resolution(self, plan: ChatPlan, resolution: Any) -> None:
        plan.tool_chain = list(resolution.tool_chain)
        plan.resolver_trace = list(plan.resolver_trace) + list(resolution.resolver_trace)
        if resolution.executable is False and resolution.blocking_reason:
            plan.resolver_trace.append(
                {
                    "resolver": "tool",
                    "decision": "block_execution",
                    "reason": resolution.blocking_reason,
                }
            )

    def _tool_chain_to_steps(self, tool_chain: List[Dict[str, Any]]) -> List[str]:
        return [
            str(item.get("tool_name")).strip()
            for item in tool_chain
            if isinstance(item, dict) and str(item.get("tool_name") or "").strip()
        ]

    def _execute_plan(
        self,
        user_id: str,
        message: str,
        steps: List[str],
    ) -> tuple[List[str], Dict[str, Any], List[Dict[str, Any]]]:
        return self.plan_executor.execute_plan(
            user_id=user_id,
            message=message,
            steps=steps,
            build_payload=self._build_tool_payload,
            should_continue_after_step=self._should_continue_after_step,
        )

    def _execute_react_loop(
        self,
        *,
        user_id: str,
        message: str,
        initial_steps: List[str],
        task_type: str,
    ) -> tuple[List[str], Dict[str, Any], List[Dict[str, Any]]]:
        return self.plan_executor.execute_react_loop(
            user_id=user_id,
            message=message,
            initial_steps=initial_steps,
            task_type=task_type,
            build_payload=self._build_tool_payload,
            should_continue_after_step=self._should_continue_after_step,
        )

    def _should_use_react_loop(self, task_type: Optional[str]) -> bool:
        return bool(settings.agent_enable_observe_loop and (task_type or "") in self.LOOP_ENABLED_TASK_TYPES)

    def _should_continue_after_step(
        self,
        step: str,
        tool_result: Any,
        state: Dict[str, Any],
    ) -> bool:
        return self.plan_executor.should_continue_after_search(
            step=step,
            tool_result=tool_result,
            state=state,
        )

    def _build_tool_payload(
        self,
        user_id: str,
        message: str,
        tool_name: str,
        state: Dict[str, Any],
    ) -> Dict[str, Any]:
        return self.tool_payload_builder.build(
            user_id=user_id,
            message=message,
            tool_name=tool_name,
            state=state,
        )

    def _format_tool_answer(self, tool_name: str, tool_result: Any) -> str:
        return self.response_formatter.format_tool_answer(tool_name, tool_result)

    def _extract_sources(self, tool_name: str, tool_result: Any) -> List[ChatSource]:
        return self.response_formatter.extract_sources(tool_name, tool_result)
