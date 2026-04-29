from dataclasses import dataclass, field
import time
from typing import Any, Dict, List, Optional

from app.llm.client import LLMClient
from app.env import settings
from app.resolvers.context_requirement_resolver import ContextRequirementResolver
from app.resolvers.tool_resolver import ToolResolver
from app.routing.intent_router import IntentRouter
from app.schemas.chat import ChatPlan, ChatSource, LLMTrace
from app.services.candidate_service import CandidateService
from app.services.career_event_service import CareerEventService
from app.services.career_diagnostic_planner import CareerDiagnosticPlanner
from app.services.memory_service import MemoryService
from app.services.plan_executor import PlanExecutor
from app.services.profile_service import ProfileService
from app.services.retrieval_service import RetrievalResult, RetrievalService
from app.services.response_formatter import ToolResponseFormatter
from app.services.resume_service import ResumeService
from app.services.tool_payload_builder import ToolPayloadBuilder
from app.tools.registry import ToolRegistry, build_default_tool_registry
from app.routing.intent_gateway import IntentGateway


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
    LOOP_ENABLED_TASK_TYPES = {"job_match_planning", "career_insights", "interview_prep"}
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
        self.intent_gateway = IntentGateway()
        self.career_event_service = CareerEventService(
            retrieval_service=self.retrieval_service,
            llm_client=self.llm_client,
        )
        self.career_diagnostic_planner = CareerDiagnosticPlanner(
            llm_client=self.llm_client,
        )

    def respond(self, user_id: str, message: str) -> AgentResult:
        request_started = time.perf_counter()
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
        self._apply_diagnostic_plan(
            plan=plan,
            message=message,
            profile=profile,
            context_resolution=context_resolution,
            memory_context=[turn.content for turn in recent_turns],
        )
        if plan.needs_more_context:
            answer = plan.follow_up_question or "我还需要更多信息，才能继续。"
            self.memory_service.save_turn(user_id, message, answer)
            self._append_runtime_timing_trace(
                plan=plan,
                execution_ms=0.0,
                total_ms=(time.perf_counter() - request_started) * 1000,
            )
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

        if plan.task_type == "fallback" and not plan.steps:
            fallback_type = None
            for item in plan.resolver_trace or []:
                if item.get("resolver") == "intent_gateway":
                    fallback_type = item.get("fallback_type")
                    break
            if fallback_type == "system":
                answer = plan.follow_up_question or "我目前遇到系统规划超时，先做一个安全下一步：请告诉我你的目标岗位/简历内容，以便继续。"
            elif fallback_type == "recoverable":
                answer = plan.follow_up_question or "我还需要更多信息才能继续。请补充目标岗位/简历/岗位 JD 等关键内容。"
            elif plan.plan_type == "third_party_advice":
                # Third-party questions (e.g. "my friend wants to become a PM")
                # need a substantive LLM answer, not a generic capability listing.
                answer = self.llm_client.generate(
                    message=message,
                    memory_context=[turn.content for turn in recent_turns],
                    evidence=[],
                )
            else:
                answer = self._format_router_fallback_answer(message)
            self.memory_service.save_turn(user_id, message, answer)
            self._append_runtime_timing_trace(
                plan=plan,
                execution_ms=0.0,
                total_ms=(time.perf_counter() - request_started) * 1000,
            )
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

        execute_started = time.perf_counter()
        if execution_steps:
            if self._should_use_react_loop(plan.task_type):
                allowed_executor_tools = self.tool_resolver.executor_allowed_tool_order(
                    plan=plan,
                    available_tools=self.tool_registry.list_tool_names(),
                )
                tool_trace, execution_state, loop_trace = self.plan_executor.execute_react_loop(
                    user_id=user_id,
                    message=message,
                    initial_steps=execution_steps,
                    task_type=plan.task_type,
                    build_payload=self._build_tool_payload,
                    should_continue_after_step=self._should_continue_after_step,
                    replan_budget=self.MAX_REPLANS,
                    whitelist_executor_tools=allowed_executor_tools,
                    validate_replan_chain=lambda proposed, exec_trace: self.tool_resolver.normalize_executor_replan_chain(
                        plan=plan,
                        proposed_tools=list(proposed),
                        available_tools=self.tool_registry.list_tool_names(),
                        executed_trace=list(exec_trace),
                    ),
                )
            else:
                tool_trace, execution_state, loop_trace = self.plan_executor.execute_plan(
                    user_id=user_id,
                    message=message,
                    steps=execution_steps,
                    build_payload=self._build_tool_payload,
                    should_continue_after_step=self._should_continue_after_step,
                )
                execution_state["_loop_control"] = {
                    "executor_mode": "sequential",
                    "replan_budget": 0,
                    "strategy_replans_used": 0,
                    "switch_count": 0,
                    "replan_count": 0,
                    "step_repeat_count": 0,
                    "terminated_by": "finish",
                    "last_observation": execution_state.get("last_observation"),
                }
            # If `_execute_plan` could not run any step (e.g., the planner asked
            # for `get_candidate_profile` but the user has no candidate yet), we
            # fall through to the generic retrieval+LLM answer path so the
            # request still produces a helpful response rather than 500-ing.
            final_tool_name = tool_trace[-1] if tool_trace else None
            final_result = execution_state.get("last_result")
        else:
            tool_trace, final_tool_name, final_result, loop_trace = [], None, None, []
            execution_state = {}
        execute_elapsed_ms = (time.perf_counter() - execute_started) * 1000
        loop_control = execution_state.get("_loop_control") if execution_steps else None
        if isinstance(loop_control, dict):
            plan.resolver_trace = list(plan.resolver_trace) + [
                {
                    "resolver": "executor",
                    "executor_mode": str(loop_control.get("executor_mode") or "sequential"),
                    "replan_budget": int(loop_control.get("replan_budget") or 0),
                    "strategy_replans_used": int(loop_control.get("strategy_replans_used") or 0),
                    "switch_count": int(loop_control.get("switch_count") or 0),
                    "replan_count": int(loop_control.get("replan_count") or 0),
                    "terminated_by": str(loop_control.get("terminated_by") or "finish"),
                }
            ]

        missing_context = execution_state.get("_missing_context") if execution_steps else None
        follow_up_question = execution_state.get("_follow_up_question") if execution_steps else None
        if isinstance(missing_context, list) and missing_context:
            plan.needs_more_context = True
            plan.missing_context = [str(item) for item in missing_context if str(item).strip()]
            if isinstance(follow_up_question, str) and follow_up_question.strip():
                plan.follow_up_question = follow_up_question.strip()
            answer = plan.follow_up_question or "我还需要更多信息，才能继续。"
            self.memory_service.save_turn(user_id, message, answer)
            self._append_runtime_timing_trace(
                plan=plan,
                execution_ms=execute_elapsed_ms,
                total_ms=(time.perf_counter() - request_started) * 1000,
            )
            return AgentResult(
                answer=answer,
                stage="fallback",
                memory_used=bool(recent_turns),
                sources=[],
                tool_used=None,
                plan=plan,
                tool_trace=tool_trace,
                loop_trace=loop_trace,
                llm_trace=self._build_llm_trace(plan),
            )

        if tool_trace:
            if (
                plan.task_type == "resume_analysis"
                and final_tool_name == "get_resume_by_id"
                and self._is_resume_optimization_request(message)
            ):
                answer = self.response_formatter.format_resume_optimization_answer(final_result, message)
            elif plan.task_type == "interview_prep":
                answer = self._format_interview_prep_answer(
                    message=message,
                    profile=profile,
                    execution_state=execution_state,
                )
            elif final_tool_name == "search_jobs":
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
            self._append_runtime_timing_trace(
                plan=plan,
                execution_ms=execute_elapsed_ms,
                total_ms=(time.perf_counter() - request_started) * 1000,
            )
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
        self._append_runtime_timing_trace(
            plan=plan,
            execution_ms=execute_elapsed_ms,
            total_ms=(time.perf_counter() - request_started) * 1000,
        )
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
        self.llm_client.last_plan_timed_out = False
        self.llm_client.last_plan_elapsed_ms = 0.0

    def _format_router_fallback_answer(self, message: str) -> str:
        _ = message
        return (
            "我可以帮你找岗位和做岗位搜索，也可以做这些事：简历总结与分析、岗位匹配、"
            "面试准备、投递/面试诊断，以及第三方求职建议。"
        )

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
        planner_used = False
        router_started = time.perf_counter()
        plan_payload = self.intent_router.route(
            message=message,
            memory_context=memory_context,
            profile=profile,
            available_tools=available_tools,
            user_state=user_state,
        )
        router_elapsed_ms = (time.perf_counter() - router_started) * 1000
        gateway_decision = None
        gateway_event = {
            "resolver": "intent_gateway",
            "router_hit": plan_payload is not None,
            "router_reason": "router_hit" if plan_payload is not None else "router_miss",
            "gateway_domain": None,
            "gateway_intent": None,
            "gateway_action": None,
            "gateway_confidence": None,
            "planner_called": False,
            "planner_source": None,
            "fallback_type": "none",
        }
        if plan_payload is None:
            # Router miss: hand over to IntentGateway.
            gateway_decision = self.intent_gateway.resolve_after_router_miss(
                message=message,
                profile=profile,
                user_state=user_state,
                memory_context=memory_context,
                available_tools=available_tools,
            )
            gateway_event.update(
                {
                    "gateway_domain": gateway_decision.domain,
                    "gateway_intent": gateway_decision.intent_cluster,
                    "gateway_action": gateway_decision.action,
                    "gateway_confidence": float(gateway_decision.confidence),
                    "fallback_type": gateway_decision.fallback_type,
                }
            )

            if gateway_decision.action in {"route", "clarify", "true_fallback"}:
                plan_payload = gateway_decision.local_plan_payload or {}
                plan_payload["planner_source"] = "gateway"
            elif gateway_decision.action == "escalate_to_planner":
                planner_used = True
                gateway_event["planner_called"] = True
                plan_payload = self.llm_client.generate_plan(
                    message=message,
                    memory_context=memory_context,
                    profile=profile,
                    available_tools=available_tools,
                    user_state=user_state,
                )
                gateway_event["planner_source"] = getattr(self.llm_client, "last_plan_source", None)
                # Planner timeout/error should never become true-fallback
                # inside career domain; recover locally.
                if (
                    gateway_decision.domain == "career"
                    and (
                        bool(getattr(self.llm_client, "last_plan_timed_out", False))
                        or getattr(self.llm_client, "last_plan_source", None) == "fallback"
                    )
                ):
                    gateway_event["fallback_type"] = "system"
                    plan_payload = self._build_system_fallback_plan_for_gateway(
                        message=message,
                        intent_cluster=gateway_decision.intent_cluster,
                    )
                    plan_payload["planner_source"] = "gateway"
            else:
                # Safety: unknown action => keep system safe behavior.
                plan_payload = self.intent_gateway._build_true_fallback_plan()
                plan_payload["planner_source"] = "gateway"
                gateway_event["fallback_type"] = "true"
        # Ensure `planner_source` is always populated so the /chat contract is
        # stable even when the payload comes from an older fallback path.
        if not plan_payload.get("planner_source"):
            plan_payload["planner_source"] = self.llm_client.last_plan_source
        runtime_trace = {
            "resolver": "planner_runtime",
            "router_hit": not planner_used,
            "planner_used": planner_used,
            "planner_source": plan_payload.get("planner_source"),
            "planner_elapsed_ms": round(float(getattr(self.llm_client, "last_plan_elapsed_ms", 0.0)), 2),
            "planner_timeout": bool(getattr(self.llm_client, "last_plan_timed_out", False)),
            "router_elapsed_ms": round(router_elapsed_ms, 2),
        }
        existing_trace = plan_payload.get("resolver_trace", [])
        if not isinstance(existing_trace, list):
            existing_trace = []
        plan_payload["resolver_trace"] = list(existing_trace) + [gateway_event, runtime_trace]
        return ChatPlan.model_validate(plan_payload)

    def _build_system_fallback_plan_for_gateway(
        self,
        *,
        message: str,
        intent_cluster: str,
    ) -> Dict[str, Any]:
        _ = message
        # System fallback should be executable next-step guidance.
        if intent_cluster in {"job_match", "job_recommend"}:
            follow_up = "我这边的规划超时了。为了继续做岗位匹配/推荐，请补充：目标岗位 JD/链接 + 你的简历（或简历内容）。"
        elif intent_cluster == "resume_analysis":
            follow_up = "我这边的规划超时了。为了继续做简历分析，请上传或粘贴你的简历内容。"
        elif intent_cluster == "application_diag":
            follow_up = "我这边的规划超时了。为了继续投递诊断，请告诉我你的目标岗位方向，以及最近的大致投递/反馈情况（不需要完整列表）。"
        elif intent_cluster == "interview_prep":
            follow_up = "我这边的规划超时了。为了继续面试准备，请告诉我目标岗位名称/方向，以及是否已有面试轮次或反馈。"
        else:
            follow_up = "我这边的规划超时了。请告诉我你想完成的求职目标：岗位匹配 / 投递诊断 / 面试准备，并补充目标岗位信息。"

        return {
            "task_type": "fallback",
            "reason": "system_fallback: planner_timeout_overridden_by_gateway",
            "steps": [],
            "needs_more_context": False,
            "missing_context": [],
            "follow_up_question": follow_up,
            "domain": "conversation",
            "action": "system_fallback",
            "planner_source": "gateway",
            "confidence": 0.6,
            "plan_type": "direct",
            "evidence_policy": "system_local_recovery",
            "stop_criteria": ["system fallback returned"],
            # Key for AgentService fallback answer branching.
            "resolver_trace": [
                {
                    "resolver": "intent_gateway",
                    "fallback_type": "system",
                }
            ],
        }

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
        # Preserve previous resolver_trace (e.g., IntentGateway event) so
        # downstream debugging remains possible.
        plan.resolver_trace = list(plan.resolver_trace or []) + list(resolution.resolver_trace)

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

    def _should_apply_diagnostic_planner(self, plan: ChatPlan) -> bool:
        task_type = str(plan.task_type or "").strip().lower()
        domain = str(plan.domain or "").strip().lower()
        action = str(plan.action or "").strip().lower()
        if task_type == "career_insights":
            return True
        return domain == "career_strategy" and action == "diagnose"

    def _is_fallback_diagnostic_output(self, plan: ChatPlan) -> bool:
        diagnostic_plan = plan.diagnostic_plan
        if diagnostic_plan is None:
            return False
        hypotheses = list(diagnostic_plan.diagnostic_hypotheses or [])
        if not hypotheses:
            return False
        first = hypotheses[0]
        return (
            first.bottleneck_type == "insufficient_evidence"
            and float(diagnostic_plan.confidence) <= 0.4
            and "enough evidence collected" in list(diagnostic_plan.stop_criteria or [])
        )

    def _apply_diagnostic_plan(
        self,
        *,
        plan: ChatPlan,
        message: str,
        profile: Dict[str, Any],
        context_resolution: Any,
        memory_context: List[str],
    ) -> None:
        if plan.needs_more_context:
            plan.diagnostic_plan = None
            plan.resolver_trace = list(plan.resolver_trace) + [
                {
                    "resolver": "diagnostic_planner",
                    "status": "skipped",
                    "reason": "context_missing",
                }
            ]
            return

        if not self._should_apply_diagnostic_planner(plan):
            plan.diagnostic_plan = None
            plan.resolver_trace = list(plan.resolver_trace) + [
                {
                    "resolver": "diagnostic_planner",
                    "status": "skipped",
                    "reason": "not_applicable",
                }
            ]
            return

        resolution_payload = (
            context_resolution.model_dump()
            if hasattr(context_resolution, "model_dump")
            else dict(context_resolution or {})
        )
        plan_payload = plan.model_dump()
        diagnostic_output = self.career_diagnostic_planner.plan(
            message=message,
            plan_semantics=plan_payload,
            profile=profile,
            context_resolution=resolution_payload,
            memory_context=memory_context,
        )
        plan.diagnostic_plan = diagnostic_output
        status = "fallback" if self._is_fallback_diagnostic_output(plan) else "applied"
        plan.resolver_trace = list(plan.resolver_trace) + [
            {
                "resolver": "diagnostic_planner",
                "status": status,
                "reason": "career_diagnosis_task",
                "confidence": float(diagnostic_output.confidence),
            }
        ]

    def _tool_chain_to_steps(self, tool_chain: List[Dict[str, Any]]) -> List[str]:
        return [
            str(item.get("tool_name")).strip()
            for item in tool_chain
            if isinstance(item, dict) and str(item.get("tool_name") or "").strip()
        ]

    def _append_runtime_timing_trace(
        self,
        *,
        plan: ChatPlan,
        execution_ms: float,
        total_ms: float,
    ) -> None:
        plan.resolver_trace = list(plan.resolver_trace) + [
            {
                "resolver": "runtime_timing",
                "execution_elapsed_ms": round(execution_ms, 2),
                "total_elapsed_ms": round(total_ms, 2),
            }
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

    def _is_resume_optimization_request(self, message: str) -> bool:
        lowered = message.lower()
        markers = ("优化简历", "改简历", "润色简历", "简历怎么改", "简历优化", "optimize resume", "improve resume")
        return any(marker in message or marker in lowered for marker in markers)

    def _format_interview_prep_answer(
        self,
        *,
        message: str,
        profile: Dict[str, Any],
        execution_state: Dict[str, Any],
    ) -> str:
        resume_data = execution_state.get("get_resume_by_id")
        resume_text = ""
        if isinstance(resume_data, dict):
            resume_text = str(resume_data.get("content", "")).lower()

        role = str(profile.get("target_role_preference") or "").strip()
        if not role:
            lowered = message.lower()
            if "数据分析" in message or "data analyst" in lowered:
                role = "数据分析"
            elif "后端" in message or "backend" in lowered:
                role = "后端开发"
            elif "前端" in message or "frontend" in lowered:
                role = "前端开发"
            else:
                role = "目标岗位"

        strengths: List[str] = []
        if "sql" in resume_text:
            strengths.append("SQL")
        if "python" in resume_text:
            strengths.append("Python")
        if "fastapi" in resume_text:
            strengths.append("FastAPI")
        if "tableau" in resume_text:
            strengths.append("Tableau")
        if "机器学习" in resume_text or "machine learning" in resume_text:
            strengths.append("机器学习基础")
        strengths = strengths[:3]

        strengths_line = "、".join(strengths) if strengths else "你已有的项目经历"
        return (
            f"面试准备计划（{role}）：\n"
            f"1. 先用 {strengths_line} 组织一段 90 秒自我介绍，重点讲 1 个最有代表性的项目（背景-动作-结果）。\n"
            "2. 技术准备分三块：岗位核心知识（按目标岗位 JD）、项目追问（为什么这么做/如何取舍）、"
            "行为题（协作与复盘）。\n"
            "3. 本周执行：每天 1 轮模拟问答（30 分钟）+ 1 次复盘，记录薄弱点并在下一轮针对性补齐。"
        )

    def _extract_sources(self, tool_name: str, tool_result: Any) -> List[ChatSource]:
        return self.response_formatter.extract_sources(tool_name, tool_result)
