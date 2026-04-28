from dataclasses import dataclass, field
import re
from typing import Any, Dict, List, Optional

from app.llm.client import LLMClient
from app.env import settings
from app.routing.filter_extractor import extract_filters
from app.routing.intent_router import IntentRouter
from app.schemas.chat import ChatPlan, ChatSource, LLMTrace
from app.services.candidate_service import CandidateService
from app.services.career_event_service import CareerEventService
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
        self.candidate_service = CandidateService()
        self.resume_service = ResumeService()
        self.profile_service = ProfileService()
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
        if plan.needs_more_context and not plan.steps:
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
        if plan.steps:
            if self._should_use_react_loop(plan.task_type):
                tool_trace, execution_state, loop_trace = self._execute_react_loop(
                    user_id=user_id,
                    message=message,
                    initial_steps=plan.steps,
                    task_type=plan.task_type,
                )
            else:
                tool_trace, execution_state, loop_trace = self._execute_plan(
                    user_id,
                    message,
                    plan.steps,
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
                answer = self._format_tool_answer(final_tool_name, final_result)
            sources = self._extract_sources(final_tool_name, final_result)
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
    ) -> tuple[List[str], Dict[str, Any], List[Dict[str, Any]]]:
        trace: List[str] = []
        state: Dict[str, Any] = {}
        queue: List[str] = [step for step in steps if step in self.tool_registry.list_tool_names()]
        while queue:
            step = queue.pop(0)
            try:
                payload = self._build_tool_payload(user_id, message, step, state)
                tool_result = self.tool_registry.run(step, payload)
            except ValueError:
                # Planner asked for a step whose prerequisite is missing
                # (e.g., no candidate / resume for this user). Stop executing
                # and let the caller fall back to the generic answer path.
                break
            if not bool(tool_result.get("ok", False)):
                break
            trace.append(step)
            state[step] = tool_result["data"]
            state["last_result"] = tool_result["data"]
            if not self._should_continue_after_step(step, tool_result["data"], state):
                break
        return trace, state, []

    def _execute_react_loop(
        self,
        *,
        user_id: str,
        message: str,
        initial_steps: List[str],
        task_type: str,
    ) -> tuple[List[str], Dict[str, Any], List[Dict[str, Any]]]:
        trace: List[str] = []
        state: Dict[str, Any] = {}
        loop_trace: List[Dict[str, Any]] = []
        queue: List[str] = [
            step for step in initial_steps if step in self.tool_registry.list_tool_names()
        ]

        while queue and len(trace) < self.MAX_LOOP_STEPS:
            step = queue.pop(0)
            try:
                payload = self._build_tool_payload(user_id, message, step, state)
                tool_result = self.tool_registry.run(step, payload)
            except ValueError:
                break

            observation_summary = self._summarize_observation(step, tool_result.get("data"))
            if not bool(tool_result.get("ok", False)):
                loop_trace.append(
                    {
                        "step": step,
                        "action": "finish",
                        "decision": "stop",
                        "reason": "tool_error",
                        "observation_summary": observation_summary,
                    }
                )
                break

            trace.append(step)
            state[step] = tool_result["data"]
            state["last_result"] = tool_result["data"]
            state["_last_step"] = step

            if not self._should_continue_after_step(step, tool_result["data"], state):
                loop_trace.append(
                    {
                        "step": step,
                        "action": "finish",
                        "decision": "stop",
                        "reason": "rule_stop_after_step",
                        "observation_summary": observation_summary,
                    }
                )
                break
            if self._is_no_progress(step, tool_result["data"], state):
                loop_trace.append(
                    {
                        "step": step,
                        "action": "finish",
                        "decision": "stop",
                        "reason": "no_progress",
                        "observation_summary": observation_summary,
                    }
                )
                break

            if not queue:
                loop_trace.append(
                    {
                        "step": step,
                        "action": "finish",
                        "decision": "finish",
                        "reason": "plan_exhausted",
                        "observation_summary": observation_summary,
                    }
                )
                break

            react_action = self._decide_react_action(
                task_type=task_type,
                message=message,
                state=state,
                last_observation={
                    "step": step,
                    "result": tool_result["data"],
                    "summary": observation_summary,
                },
                remaining_steps=list(queue),
            )
            action = str(react_action.get("action") or "finish").strip().lower()
            if action != "tool":
                loop_trace.append(
                    {
                        "step": step,
                        "action": "finish",
                        "decision": "finish",
                        "reason": str(react_action.get("reason") or "observer_finish"),
                        "observation_summary": observation_summary,
                    }
                )
                break

            next_tool = str(react_action.get("tool_name") or "").strip()
            if not next_tool:
                loop_trace.append(
                    {
                        "step": step,
                        "action": "finish",
                        "decision": "finish",
                        "reason": "missing_tool_name",
                        "observation_summary": observation_summary,
                    }
                )
                break

            executed_counts: Dict[str, int] = {}
            for executed_step in trace:
                executed_counts[executed_step] = executed_counts.get(executed_step, 0) + 1
            if executed_counts.get(next_tool, 0) >= self.MAX_STEP_REPEAT:
                loop_trace.append(
                    {
                        "step": step,
                        "action": "finish",
                        "decision": "stop",
                        "reason": "max_step_repeat_reached",
                        "observation_summary": observation_summary,
                    }
                )
                break

            if not queue or queue[0] != next_tool:
                queue.insert(0, next_tool)
            queue = self._dedupe_over_repeated_steps(queue, trace)
            loop_trace.append(
                {
                    "step": step,
                    "action": "tool",
                    "decision": str(react_action.get("decision") or "continue"),
                    "reason": str(react_action.get("reason") or ""),
                    "next_tool": next_tool,
                    "observation_summary": str(
                        react_action.get("observation_summary") or observation_summary
                    ),
                }
            )

        return trace, state, loop_trace

    def _decide_react_action(
        self,
        *,
        task_type: str,
        message: str,
        state: Dict[str, Any],
        last_observation: Optional[Dict[str, Any]],
        remaining_steps: List[str],
    ) -> Dict[str, Any]:
        decider = getattr(self.llm_client, "decide_react_action", None)
        if callable(decider):
            result = decider(
                task_type=task_type,
                message=message,
                state=state,
                last_observation=last_observation,
                available_tools=remaining_steps or self.tool_registry.list_tool_names(),
            )
            if "decision" not in result:
                result["decision"] = "continue" if result.get("action") == "tool" else "stop"
            return result
        fallback_decider = getattr(self.llm_client, "decide_next_action", None)
        if callable(fallback_decider):
            fallback = fallback_decider(
                task_type=task_type,
                message=message,
                current_step=str((last_observation or {}).get("step") or ""),
                tool_result=(last_observation or {}).get("result"),
                remaining_steps=remaining_steps,
                available_tools=self.tool_registry.list_tool_names(),
            )
            decision = str(fallback.get("decision") or "continue").strip().lower()
            if decision == "stop":
                return {
                    "action": "finish",
                    "tool_name": None,
                    "reason": "legacy_stop",
                    "decision": "stop",
                }
            if decision == "replan":
                steps = fallback.get("steps") if isinstance(fallback.get("steps"), list) else []
                next_tool = str(steps[0]).strip() if steps else None
                return {
                    "action": "tool" if next_tool else "finish",
                    "tool_name": next_tool,
                    "reason": str(fallback.get("reason") or "legacy_replan"),
                    "decision": "replan" if next_tool else "stop",
                }
            next_tool = remaining_steps[0] if remaining_steps else None
            return {
                "action": "tool" if next_tool else "finish",
                "tool_name": next_tool,
                "reason": str(fallback.get("reason") or "legacy_continue"),
                "decision": "continue" if next_tool else "stop",
            }
        return {"action": "finish", "tool_name": None, "reason": "no_decider", "decision": "stop"}

    def _should_use_react_loop(self, task_type: Optional[str]) -> bool:
        return bool(settings.agent_enable_observe_loop and (task_type or "") in self.LOOP_ENABLED_TASK_TYPES)

    def _normalize_replanned_steps(
        self,
        replacement_steps: List[Any],
        current_queue: List[str],
        trace: List[str],
    ) -> List[str]:
        allowed = set(self.tool_registry.list_tool_names())
        executed = set(trace)
        normalized = [
            str(step).strip()
            for step in replacement_steps
            if isinstance(step, str) and str(step).strip() in allowed and str(step).strip() not in executed
        ]
        if normalized:
            return normalized
        return current_queue

    def _dedupe_over_repeated_steps(self, queue: List[str], trace: List[str]) -> List[str]:
        if not queue:
            return queue
        executed_counts: Dict[str, int] = {}
        for step in trace:
            executed_counts[step] = executed_counts.get(step, 0) + 1
        filtered: List[str] = []
        for step in queue:
            if executed_counts.get(step, 0) >= self.MAX_STEP_REPEAT:
                continue
            filtered.append(step)
        return filtered

    def _should_observe_decision(
        self,
        *,
        task_type: str,
        current_step: str,
        remaining_steps: List[str],
    ) -> bool:
        if task_type == "job_match_planning":
            return current_step in {"search_jobs", "match_resume_to_jobs"} and bool(
                remaining_steps
            )
        if task_type == "career_insights":
            return current_step == "get_career_insights" and bool(remaining_steps)
        return False

    def _summarize_observation(self, step: str, tool_result: Any) -> str:
        if step == "search_jobs" and isinstance(tool_result, list):
            return f"found {len(tool_result)} job candidates"
        if step == "match_resume_to_jobs" and isinstance(tool_result, dict):
            matches = tool_result.get("matches", [])
            if isinstance(matches, list):
                return f"matched resume against {len(matches)} jobs"
        if step == "get_career_insights" and isinstance(tool_result, dict):
            return "generated career insight summary"
        return "tool executed"

    def _is_no_progress(self, step: str, tool_result: Any, state: Dict[str, Any]) -> bool:
        signature = self._progress_signature(step, tool_result)
        previous = state.get("_last_progress_signature")
        state["_last_progress_signature"] = signature
        if previous is None:
            return False
        return previous == signature

    def _progress_signature(self, step: str, tool_result: Any) -> Any:
        if step == "search_jobs" and isinstance(tool_result, list):
            return (
                step,
                tuple(
                    str(item.get("title", "")).strip().lower()
                    for item in tool_result[:3]
                    if isinstance(item, dict)
                ),
            )
        if step == "match_resume_to_jobs" and isinstance(tool_result, dict):
            matches = tool_result.get("matches", [])
            if isinstance(matches, list):
                return (
                    step,
                    tuple(
                        (
                            str(match.get("job_title", "")).strip().lower(),
                            str(match.get("match_score", "")),
                        )
                        for match in matches[:3]
                        if isinstance(match, dict)
                    ),
                )
        return (step, str(tool_result)[:400])

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

        if tool_name == "get_career_insights":
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

        if tool_name == "get_career_insights":
            data = tool_result if isinstance(tool_result, dict) else {}
            profile = data.get("profile", {})
            applications = data.get("application_summary", {})
            interviews = data.get("interview_summary", {})
            strengths = data.get("strengths", [])
            risk_areas = data.get("risk_areas", [])
            next_actions = data.get("next_actions", data.get("suggestions", []))

            role = str(profile.get("target_role_preference", "")).strip() or "暂未明确"
            app_total = int(applications.get("total", 0) or 0)
            interview_total = int(interviews.get("total", 0) or 0)
            answer_parts = [
                f"当前状态：目标方向是 {role}，",
                f"最近有 {app_total} 条投递记录、{interview_total} 条面试反馈。"
            ]
            if strengths:
                answer_parts.append(
                    "已有优势：" + "；".join(str(item) for item in strengths[:2]) + "。"
                )
            if risk_areas:
                answer_parts.append(
                    "主要风险：" + "；".join(str(item) for item in risk_areas[:2]) + "。"
                )
            feedback_highlights = interviews.get("feedback_highlights", [])
            if feedback_highlights:
                answer_parts.append(
                    "面试反馈里最需要关注的是：" + "；".join(feedback_highlights[:2]) + "。"
                )
            if next_actions:
                answer_parts.append("推荐行动（下一步）：" + "；".join(str(item) for item in next_actions[:2]) + "。")
            elif not app_total and not interview_total:
                answer_parts.append("推荐行动（下一步）：先补充投递记录和面试反馈。")
            return "".join(answer_parts)

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

        if tool_name == "get_career_insights":
            data = tool_result if isinstance(tool_result, dict) else {}
            applications = data.get("application_summary", {}).get("recent", [])
            interviews = data.get("interview_summary", {}).get("recent", [])
            sources: List[ChatSource] = [
                ChatSource(
                    type="application",
                    title=f"{item.get('company', '')} - {item.get('job_title', '')}".strip(" -"),
                    snippet=f"状态：{item.get('status', '')}；备注：{item.get('note', '')}".strip(),
                )
                for item in applications
            ]
            sources.extend(
                ChatSource(
                    type="interview_feedback",
                    title=f"{item.get('company', '')} - {item.get('job_title', '')}".strip(" -"),
                    snippet=(
                        f"轮次：{item.get('interview_round', '')}；"
                        f"结果：{item.get('result', '')}；"
                        f"反馈：{item.get('feedback', '')}"
                    ).strip(),
                )
                for item in interviews
            )
            return sources

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
