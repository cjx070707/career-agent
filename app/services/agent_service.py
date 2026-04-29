from dataclasses import dataclass, field
import time
from typing import Any, Dict, List, Optional

from app.llm.client import LLMClient
from app.env import settings
from app.resolvers.context_requirement_resolver import ContextRequirementResolver
from app.resolvers.tool_resolver import ToolResolver
from app.routing.llm_intent_classifier import LLMIntentClassifier
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
    ) -> None:
        self.memory_service = memory_service or MemoryService()
        self.retrieval_service = retrieval_service or RetrievalService()
        self.llm_client = llm_client or LLMClient()
        self.tool_registry = tool_registry or build_default_tool_registry()
        self.intent_classifier = LLMIntentClassifier(llm_client=self.llm_client)
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
        if plan.task_type == "interview_prep" and not self._message_has_role_hint(message):
            plan.needs_more_context = True
            plan.missing_context = ["target_role"]
            plan.follow_up_question = "你想准备哪个目标岗位的面试？请告诉我岗位名称或方向。"
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
            if plan.plan_type == "third_party_advice" or self._is_third_party_advice_message(message):
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
        if plan.task_type in {"resume_analysis", "interview_prep"}:
            answer = (
                f"【结论】\n{answer[:120]}\n\n"
                "【证据】\n当前回答基于用户当轮输入与可检索到的上下文信息生成。\n\n"
                "【行动建议】\n1. 补充目标岗位与关键要求。\n2. 提供可量化项目结果以便给出更精确建议。"
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

        fastpath = self._build_fastpath_plan(message=message)
        if fastpath is not None:
            plan_payload = fastpath
        else:
            plan_payload = self.intent_classifier.classify(
                message=message,
                recent_turns=memory_context,
                user_state=user_state,
                available_tools=available_tools,
            )

        if not plan_payload.get("planner_source"):
            plan_payload["planner_source"] = self.llm_client.last_plan_source
        if not plan_payload.get("reason"):
            plan_payload["reason"] = "classified by llm intent classifier"
        existing_trace = plan_payload.get("resolver_trace", [])
        if not isinstance(existing_trace, list):
            existing_trace = []
        plan_payload["resolver_trace"] = list(existing_trace) + [
            {
                "resolver": "intent_classifier",
                "source": plan_payload.get("planner_source"),
                "reasoning": getattr(self.intent_classifier, "last_reasoning", ""),
            }
        ]
        return ChatPlan.model_validate(plan_payload)

    def _build_fastpath_plan(self, *, message: str) -> Optional[Dict[str, Any]]:
        stripped = message.strip().lower()
        if stripped in {"你好", "您好", "hi", "hello", "hey", "nihao"}:
            return {
                "task_type": "fallback",
                "reason": "greeting fastpath",
                "steps": [],
                "needs_more_context": False,
                "missing_context": [],
                "follow_up_question": None,
                "planner_source": "router",
            }

        capability_markers = ("你会什么", "能做什么", "what can you do", "有什么用")
        if any(marker in stripped for marker in capability_markers):
            return {
                "task_type": "fallback",
                "reason": "capability help fastpath",
                "steps": [],
                "needs_more_context": False,
                "missing_context": [],
                "follow_up_question": None,
                "planner_source": "router",
            }
        return None

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

    def _message_has_role_hint(self, message: str) -> bool:
        lowered = message.lower()
        return any(
            marker in lowered
            for marker in ("后端", "前端", "数据", "产品", "backend", "frontend", "data", "pm", "product")
        )

    def _is_third_party_advice_message(self, message: str) -> bool:
        lowered = message.lower()
        return any(
            marker in message or marker in lowered
            for marker in ("我朋友", "我同学", "朋友想", "他想", "她想", "my friend", "friend wants")
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
            f"【结论】\n你可以按 {role} 面试准备节奏推进，先明确自我介绍主线，再做高频问答演练。\n\n"
            f"【证据】\n可直接利用你现有的 {strengths_line} 作为回答素材，覆盖项目深挖与行为题场景。\n\n"
            "【行动建议】\n"
            "1. 先用现有经历组织 90 秒自我介绍（背景-动作-结果）。\n"
            "2. 技术准备分三块：岗位核心知识、项目追问、行为题复盘。\n"
            "3. 本周每天 1 轮 30 分钟模拟问答并记录薄弱点。"
        )

    def _extract_sources(self, tool_name: str, tool_result: Any) -> List[ChatSource]:
        return self.response_formatter.extract_sources(tool_name, tool_result)
