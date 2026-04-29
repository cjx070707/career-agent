from app.services.agent_service import AgentService
from app.env import settings
from app.services.interview_service import InterviewService
from app.services.candidate_service import CandidateService
from app.services.job_service import JobService
from app.services.memory_service import MemoryService
from app.services.resume_service import ResumeService
from app.tools.registry import ToolRegistry
from app.tools.base import ToolDefinition
from app.schemas.tool import SearchJobsToolInput
from app.schemas.diagnostic_planner import DiagnosticPlannerOutput
import time


class FakeLLMClient:
    def __init__(self) -> None:
        self.called = False
        self.summarize_job_search_calls = []
        self.last_plan_source = "not_used"
        self.last_job_search_summary_source = "not_used"
        self.last_generate_source = "not_used"
        self.observe_calls = []

    def generate_plan(self, **kwargs):
        self.called = True
        self.last_plan_source = "model"
        return {
            "task_type": "job_search",
            "reason": "planned by fake llm",
            "steps": ["search_jobs"],
            "needs_more_context": False,
            "planner_source": "model",
        }

    def generate(self, message: str, memory_context: list[str], evidence: list[str]) -> str:
        self.last_generate_source = "fallback"
        return f"fake-generate:{message}"

    def summarize_job_search(
        self, message: str, memory_context: list[str], jobs: list
    ) -> str:
        self.last_job_search_summary_source = "model"
        self.summarize_job_search_calls.append(
            {"message": message, "memory_context": list(memory_context), "jobs": jobs}
        )
        return "fake-job-search-summary"

    def decide_next_action(self, **kwargs):
        self.observe_calls.append(kwargs)
        return {"decision": "continue", "reason": "default", "steps": []}

    def decide_react_action(self, **kwargs):
        self.observe_calls.append(kwargs)
        return {
            "action": "continue",
            "reason": "default continue",
            "observation_summary": "",
            "tool_name": "",
            "planned_tools": [],
        }


class PlannerAwareLLMClient(FakeLLMClient):
    def __init__(self) -> None:
        super().__init__()
        self.diagnostic_calls = []

    def generate_diagnostic_plan(self, **kwargs):
        self.diagnostic_calls.append(kwargs)
        return {
            "diagnostic_hypotheses": [
                {
                    "bottleneck_type": "resume_positioning",
                    "summary": "Likely weak resume-to-interview conversion.",
                    "rationale": "Applications are mostly early-stage.",
                    "confidence": 0.7,
                    "evidence_refs": ["applications.status_counts"],
                }
            ],
            "evidence_to_collect": [
                {
                    "source": "applications",
                    "reason": "Need funnel status breakdown.",
                    "priority": "high",
                    "required": True,
                }
            ],
            "next_question": "Can you share your latest application statuses?",
            "confidence": 0.7,
            "stop_criteria": ["main bottleneck hypothesis selected"],
        }


class TimeoutFallbackPlanLLMClient(FakeLLMClient):
    def generate_plan(self, **kwargs):
        self.called = True
        self.last_plan_source = "fallback"
        return {
            "task_type": "fallback",
            "reason": "planner unavailable_or_timeout: use deterministic local fallback.",
            "steps": [],
            "needs_more_context": False,
            "missing_context": [],
            "follow_up_question": None,
            "planner_source": "fallback",
        }


def test_agent_service_uses_router_first_for_obvious_job_search(isolated_runtime) -> None:
    fake_llm = FakeLLMClient()
    CandidateService().create_candidate(name="Planner User")
    JobService().create_job(title="Python FastAPI Backend Engineer")
    service = AgentService(llm_client=fake_llm)

    result = service.respond("planner-user", "帮我找一些 Python backend 岗位")

    assert fake_llm.called is False
    assert result.plan is not None
    assert result.plan.task_type == "job_search"
    assert result.plan.steps == ["search_jobs"]
    assert result.plan.planner_source == "router"
    assert result.tool_trace == ["search_jobs"]
    assert result.llm_trace.model_dump() == {
        "planner_source": "router",
        "job_search_summary_source": "model",
        "generate_source": "not_used",
    }


def test_agent_service_handles_oral_job_fit_phrase_without_fallback(
    isolated_runtime,
) -> None:
    fake_llm = FakeLLMClient()
    candidate = CandidateService().create_candidate(
        name="Oral Fit User",
        user_id="oral-fit-user",
    )
    ResumeService().create_resume(
        candidate_id=int(candidate["id"]),
        title="Data Resume",
        content="Data analyst, SQL, Python, dashboard projects",
        version="v1",
    )
    JobService().create_job(title="Junior Data Analyst")
    service = AgentService(llm_client=fake_llm)

    result = service.respond("oral-fit-user", "有什么适合我的岗位啊")

    assert fake_llm.called is False
    assert result.plan is not None
    assert result.plan.task_type in {"job_match", "job_match_planning", "job_search"}
    assert result.plan.planner_source == "router"
    assert result.plan.task_type != "fallback"
    assert "match_resume_to_jobs" in result.tool_trace


def test_agent_service_background_recommend_tradeoff_uses_match_planning_chain(
    isolated_runtime,
) -> None:
    fake_llm = FakeLLMClient()
    candidate = CandidateService().create_candidate(
        name="Tradeoff User",
        user_id="tradeoff-user",
    )
    ResumeService().create_resume(
        candidate_id=int(candidate["id"]),
        title="Tradeoff Resume",
        content="Backend and data projects using Python SQL FastAPI",
        version="v1",
    )
    JobService().create_job(title="Data Analyst Intern")
    JobService().create_job(title="Backend Python Intern")
    service = AgentService(llm_client=fake_llm)

    result = service.respond("tradeoff-user", "根据我背景，推荐3个最适合我投的岗位并解释取舍")

    assert result.plan is not None
    assert result.plan.task_type == "job_match_planning"
    assert result.plan.planner_source == "router"
    assert "search_jobs" in result.tool_trace
    assert "match_resume_to_jobs" in result.tool_trace
    assert result.loop_trace


def test_agent_service_handles_nihao_via_router_fastpath(isolated_runtime) -> None:
    fake_llm = FakeLLMClient()
    service = AgentService(llm_client=fake_llm)

    result = service.respond("nihao-user", "nihao")

    assert fake_llm.called is False
    assert result.plan is not None
    assert result.plan.task_type == "fallback"
    assert result.plan.planner_source == "router"
    assert result.tool_trace == []


def test_agent_service_handles_capability_help_via_router_fastpath(isolated_runtime) -> None:
    fake_llm = FakeLLMClient()
    service = AgentService(llm_client=fake_llm)

    result = service.respond("help-user", "你到底有什么用啊")

    assert fake_llm.called is False
    assert result.plan is not None
    assert result.plan.task_type == "fallback"
    assert result.plan.planner_source == "router"
    assert "简历总结" in result.answer
    assert "岗位搜索" in result.answer
    assert "第三方求职建议" in result.answer


def test_agent_service_handles_resume_presence_query_via_router_fastpath(
    isolated_runtime,
) -> None:
    candidate = CandidateService().create_candidate(
        name="Resume Presence User",
        user_id="resume-presence-user",
    )
    ResumeService().create_resume(
        candidate_id=int(candidate["id"]),
        title="Backend Resume",
        content="Python FastAPI SQL",
        version="v1",
    )
    fake_llm = FakeLLMClient()
    service = AgentService(llm_client=fake_llm)

    result = service.respond("resume-presence-user", "我的简历你有吗")

    assert fake_llm.called is False
    assert result.plan is not None
    assert result.plan.task_type == "resume_analysis"
    assert result.plan.planner_source == "router"
    assert result.tool_trace == ["get_resume_by_id"]
    assert "简历总结" in result.answer


def test_agent_service_uses_llm_layer_for_gray_query(isolated_runtime) -> None:
    fake_llm = FakeLLMClient()
    CandidateService().create_candidate(name="Planner User")
    JobService().create_job(title="Python FastAPI Backend Engineer")
    service = AgentService(llm_client=fake_llm)

    result = service.respond("planner-user", "你觉得最近市场怎么样")

    # Router miss -> IntentGateway: career-domain uncertain should clarify first.
    assert fake_llm.called is False
    assert result.plan is not None
    assert result.plan.task_type == "job_match"
    assert result.stage == "fallback"
    assert result.tool_trace == []


def test_agent_service_planner_timeout_falls_back_without_long_wait(
    isolated_runtime,
) -> None:
    timeout_llm = TimeoutFallbackPlanLLMClient()
    service = AgentService(llm_client=timeout_llm)

    started = time.perf_counter()
    result = service.respond("planner-timeout-user", "有 Atlassian 的 grad program 吗")
    elapsed = time.perf_counter() - started

    assert timeout_llm.called is True
    assert elapsed < 1.0
    assert result.plan is not None
    assert result.stage == "fallback"
    assert result.tool_trace == []
    # Planner failed, so we should recover locally via IntentGateway system fallback.
    assert any(
        item.get("resolver") == "intent_gateway" and item.get("fallback_type") == "system"
        for item in (result.plan.resolver_trace or [])
    )
    assert "规划超时" in result.answer or "超时" in result.answer


def test_agent_service_router_miss_application_diag_clarify_not_true_fallback(
    isolated_runtime,
) -> None:
    fake_llm = FakeLLMClient()
    service = AgentService(llm_client=fake_llm)

    # Router miss: "没回音" does not match router's application history
    # branch (which expects "最近/记录/进展/状态").
    result = service.respond("gateway-appdiag-user", "我投递没回音")

    assert fake_llm.called is False
    assert result.plan is not None
    # Router miss + gateway clarify => recoverable fallback.
    assert any(
        item.get("resolver") == "intent_gateway" and item.get("fallback_type") == "recoverable"
        for item in (result.plan.resolver_trace or [])
    )
    assert result.plan.needs_more_context is True
    assert result.tool_trace == []


def test_agent_service_router_miss_job_fit_gateway_route_skips_planner(
    isolated_runtime,
) -> None:
    # Seed candidate + resume so gateway can locally route.
    candidate = CandidateService().create_candidate(name="Gateway Fit User", user_id="gw-fit-user")
    ResumeService().create_resume(
        candidate_id=int(candidate["id"]),
        title="Backend Resume",
        content="Python FastAPI SQL backend APIs",
        version="v1",
    )
    JobService().create_job(title="Backend Engineer")

    fake_llm = FakeLLMClient()
    service = AgentService(llm_client=fake_llm)

    # Ensure router truly misses; gateway should handle the route.
    from app.routing.intent_router import IntentRouter

    router = IntentRouter()
    router_plan = router.route(
        message="该岗位是否值得我投？JD：FastAPI 后端",
        memory_context=[],
        profile={},
        available_tools=[],
        user_state={"has_candidate": True, "has_resume": True, "has_job_detail": True},
    )
    assert router_plan is None

    result = service.respond("gw-fit-user", "该岗位是否值得我投？JD：FastAPI 后端")

    assert fake_llm.called is False
    assert result.plan is not None
    assert any(
        item.get("resolver") == "intent_gateway" and item.get("gateway_action") == "route"
        for item in (result.plan.resolver_trace or [])
    )


def test_agent_service_appends_runtime_timing_trace(isolated_runtime) -> None:
    service = AgentService(llm_client=FakeLLMClient())
    result = service.respond("timing-trace-user", "你好")
    assert result.plan is not None
    timing_items = [
        item for item in result.plan.resolver_trace if item.get("resolver") == "runtime_timing"
    ]
    assert timing_items
    assert "execution_elapsed_ms" in timing_items[-1]
    assert "total_elapsed_ms" in timing_items[-1]


def test_agent_routes_career_direction_to_career_insights(isolated_runtime) -> None:
    fake_llm = PlannerAwareLLMClient()
    service = AgentService(llm_client=fake_llm)

    result = service.respond("career-direction-user", "你觉得我下一步职业方向应该怎么考虑？")

    assert fake_llm.called is False
    assert result.plan is not None
    assert result.plan.task_type == "career_insights"
    assert result.tool_trace == ["get_career_insights"]
    assert result.tool_used == "get_career_insights"
    assert result.plan.diagnostic_plan is not None
    DiagnosticPlannerOutput.model_validate(result.plan.diagnostic_plan.model_dump())
    planner_events = [
        item
        for item in result.plan.resolver_trace
        if item.get("resolver") == "diagnostic_planner"
    ]
    assert planner_events
    assert planner_events[-1]["status"] in {"applied", "fallback"}
    assert "推荐行动" in result.answer


def test_agent_service_resolver_missing_context_returns_follow_up_without_tools(
    isolated_runtime,
) -> None:
    fake_llm = PlannerAwareLLMClient()
    service = AgentService(llm_client=fake_llm)

    result = service.respond("interview-prep-missing-role", "帮我准备面试")

    assert result.plan is not None
    assert result.plan.task_type == "interview_prep"
    assert result.plan.needs_more_context is True
    assert result.plan.missing_context == ["target_role"]
    assert result.answer == result.plan.follow_up_question
    assert result.tool_trace == []
    assert result.plan.resolver_trace
    assert result.plan.diagnostic_plan is None
    planner_events = [
        item
        for item in result.plan.resolver_trace
        if item.get("resolver") == "diagnostic_planner"
    ]
    assert planner_events[-1]["status"] == "skipped"
    assert planner_events[-1]["reason"] == "context_missing"
    assert fake_llm.diagnostic_calls == []


def test_agent_service_executes_tool_chain_when_plan_steps_conflict(
    isolated_runtime,
) -> None:
    class ConflictingStepsLLM(FakeLLMClient):
        def generate_plan(self, **kwargs):
            self.called = True
            self.last_plan_source = "model"
            return {
                "task_type": "job_search",
                "reason": "model picked the wrong low-level step",
                "steps": ["get_candidate_profile"],
                "domain": "job_search",
                "action": "search",
                "needs_more_context": False,
                "planner_source": "model",
            }

    fake_llm = ConflictingStepsLLM()
    JobService().create_job(title="Python FastAPI Backend Engineer")
    service = AgentService(llm_client=fake_llm)

    result = service.respond(
        "conflicting-steps-user",
        "你觉得最近市场怎么样，顺便给我一些岗位建议",
    )

    assert fake_llm.called is True
    assert result.plan is not None
    assert result.plan.steps == ["get_candidate_profile"]
    assert [step["tool_name"] for step in result.plan.tool_chain] == ["search_jobs"]
    assert result.tool_trace == ["search_jobs"]


def test_agent_service_executes_tool_chain_when_plan_steps_empty(
    isolated_runtime,
) -> None:
    class EmptyStepsJobSearchLLM(FakeLLMClient):
        def generate_plan(self, **kwargs):
            self.called = True
            self.last_plan_source = "model"
            return {
                "task_type": "job_search",
                "reason": "semantic plan with empty legacy steps",
                "steps": [],
                "domain": "job_search",
                "action": "search",
                "needs_more_context": False,
                "planner_source": "model",
            }

    fake_llm = EmptyStepsJobSearchLLM()
    JobService().create_job(title="Data Analyst Intern")
    service = AgentService(llm_client=fake_llm)

    result = service.respond(
        "empty-steps-tool-chain-user",
        "你觉得最近市场怎么样，顺便给我一些岗位建议",
    )

    assert fake_llm.called is True
    assert result.plan is not None
    assert result.plan.steps == []
    assert [step["tool_name"] for step in result.plan.tool_chain] == ["search_jobs"]
    assert result.tool_trace == ["search_jobs"]


def test_agent_service_keeps_legacy_no_tool_path_when_steps_and_tool_chain_empty(
    isolated_runtime,
) -> None:
    class EmptyStepsNoToolChainLLM(FakeLLMClient):
        def generate_plan(self, **kwargs):
            self.called = True
            self.last_plan_source = "model"
            return {
                "task_type": "retrieval",
                "reason": "retrieve evidence without tool execution",
                "steps": [],
                "domain": "retrieval",
                "action": "search",
                "needs_more_context": False,
                "planner_source": "model",
            }

    fake_llm = EmptyStepsNoToolChainLLM()
    service = AgentService(llm_client=fake_llm)

    result = service.respond(
        "legacy-no-tool-user",
        "你觉得最近市场怎么样，顺便给我一些岗位建议",
    )

    assert fake_llm.called is True
    assert result.plan is not None
    assert result.plan.steps == []
    assert result.plan.tool_chain == []
    assert result.tool_trace == []
    assert result.answer.startswith("fake-generate:")


def test_agent_service_includes_resolver_trace_on_plan(isolated_runtime) -> None:
    fake_llm = FakeLLMClient()
    JobService().create_job(title="Python FastAPI Backend Engineer")
    service = AgentService(llm_client=fake_llm)

    result = service.respond("resolver-trace-user", "帮我找 Python backend 岗位")

    assert result.plan is not None
    trace = result.plan.resolver_trace
    assert trace
    assert {item["resolver"] for item in trace} >= {"context_requirement", "tool"}


def test_agent_service_non_career_task_keeps_diagnostic_plan_none(isolated_runtime) -> None:
    fake_llm = PlannerAwareLLMClient()
    JobService().create_job(title="Python FastAPI Backend Engineer")
    service = AgentService(llm_client=fake_llm)

    result = service.respond("non-career-task-user", "帮我找 Python backend 岗位")

    assert result.plan is not None
    assert result.plan.task_type == "job_search"
    assert result.plan.diagnostic_plan is None
    planner_events = [
        item
        for item in result.plan.resolver_trace
        if item.get("resolver") == "diagnostic_planner"
    ]
    assert planner_events
    assert planner_events[-1]["status"] == "skipped"
    assert planner_events[-1]["reason"] == "not_applicable"
    assert fake_llm.diagnostic_calls == []


class PlannerRequestingMissingCandidateLLM(FakeLLMClient):
    def generate_plan(self, **kwargs):
        self.called = True
        self.last_plan_source = "model"
        return {
            "task_type": "candidate_profile",
            "reason": "planner asked for candidate profile",
            "steps": ["get_candidate_profile"],
            "needs_more_context": False,
            "missing_context": [],
            "follow_up_question": None,
            "planner_source": "model",
        }


class RetrievalOnlyLLM(FakeLLMClient):
    def generate_plan(self, **kwargs):
        self.called = True
        self.last_plan_source = "model"
        return {
            "task_type": "retrieval",
            "reason": "retrieve evidence without tool execution",
            "steps": [],
            "domain": "retrieval",
            "action": "search",
            "needs_more_context": False,
            "missing_context": [],
            "follow_up_question": None,
            "planner_source": "model",
        }


class CareerEventExtractingLLM(RetrievalOnlyLLM):
    def __init__(self) -> None:
        super().__init__()
        self.extract_career_events_calls = []

    def extract_career_events(self, **kwargs):
        self.extract_career_events_calls.append(kwargs)
        return [
            {
                "event_type": "interview_feedback",
                "title": "Canva backend interview feedback",
                "summary": "Canva feedback said to prepare system design fundamentals.",
            }
        ]


def test_agent_service_degrades_gracefully_when_plan_step_prerequisites_missing(
    isolated_runtime,
) -> None:
    # User has no candidate seeded; planner still wants get_candidate_profile.
    # The agent must not crash — it should degrade to a graceful answer with
    # plan preserved and tool_trace empty.
    fake_llm = PlannerRequestingMissingCandidateLLM()
    service = AgentService(llm_client=fake_llm)

    result = service.respond("brand-new-user", "随便问一句")

    # Router miss -> IntentGateway: message is too unclear for career domain,
    # so it should return true-fallback without planner escalation.
    assert fake_llm.called is False
    assert result.plan is not None
    assert result.plan.task_type == "fallback"
    assert result.stage == "fallback"
    assert result.tool_trace == []
    assert isinstance(result.answer, str) and result.answer


def test_agent_service_applies_structured_filters_from_user_message(
    isolated_runtime,
) -> None:
    # Router hits job_search; _build_tool_payload should extract location +
    # work_type slots from the natural-language message and pass them as
    # filters into the retrieval layer, so every returned source respects
    # the constraints.
    fake_llm = FakeLLMClient()
    service = AgentService(llm_client=fake_llm)

    result = service.respond("filter-user", "帮我找 Sydney 的 intern 岗位")

    assert fake_llm.called is False
    assert result.plan is not None
    assert result.plan.task_type == "job_search"
    assert result.tool_trace == ["search_jobs"]
    assert result.sources, "filter query should still return some sources"
    for source in result.sources:
        location = str(getattr(source, "location", "") or "").lower()
        work_type = str(getattr(source, "work_type", "") or "").lower()
        assert "sydney" in location, f"expected Sydney, got {location!r}"
        assert "intern" in work_type, f"expected intern, got {work_type!r}"


def test_agent_service_search_jobs_uses_summarize_job_search(isolated_runtime) -> None:
    fake_llm = FakeLLMClient()
    CandidateService().create_candidate(name="Search Summarizer User")
    JobService().create_job(title="Rust Systems Engineer")
    memory = MemoryService()
    memory.save_turn("search-summarizer-user", "上一轮：偏好外企", "好的，记住了。")
    service = AgentService(llm_client=fake_llm, memory_service=memory)

    result = service.respond("search-summarizer-user", "帮我找 Rust 系统开发岗位")

    assert result.answer == "fake-job-search-summary"
    assert len(fake_llm.summarize_job_search_calls) == 1
    call = fake_llm.summarize_job_search_calls[0]
    assert call["message"] == "帮我找 Rust 系统开发岗位"
    assert call["memory_context"] == ["上一轮：偏好外企", "好的，记住了。"]
    assert isinstance(call["jobs"], list)
    assert len(call["jobs"]) >= 1
    job_titles = [job["title"] for job in call["jobs"]]
    assert "Rust Systems Engineer" in job_titles
    source_titles = [source.title for source in result.sources]
    assert "Rust Systems Engineer" in source_titles
    assert result.llm_trace.model_dump() == {
        "planner_source": "router",
        "job_search_summary_source": "model",
        "generate_source": "not_used",
    }


def test_agent_resume_summary_formats_resume_answer_not_default_tool_message(
    isolated_runtime,
) -> None:
    candidate = CandidateService().create_candidate(
        name="Resume Summary User",
        user_id="resume-summary-user",
    )
    ResumeService().create_resume(
        candidate_id=int(candidate["id"]),
        title="Backend Resume",
        content=(
            "Backend intern project: built Python FastAPI APIs and optimized SQL queries. "
            "Implemented service monitoring and improved reliability."
        ),
        version="v1",
    )
    service = AgentService(llm_client=FakeLLMClient())

    result = service.respond("resume-summary-user", "总结一下我的简历")

    assert result.plan is not None
    assert result.plan.task_type == "resume_analysis"
    assert result.tool_trace == ["get_resume_by_id"]
    assert "工具执行完成。" not in result.answer
    assert "简历总结" in result.answer
    assert "整体定位" in result.answer


def test_agent_resume_summary_empty_content_returns_clear_prompt(
    isolated_runtime,
) -> None:
    candidate = CandidateService().create_candidate(
        name="Empty Resume User",
        user_id="empty-resume-user",
    )
    ResumeService().create_resume(
        candidate_id=int(candidate["id"]),
        title="Empty Resume",
        content="",
        version="v1",
    )
    service = AgentService(llm_client=FakeLLMClient())

    result = service.respond("empty-resume-user", "总结一下我的简历")

    assert result.plan is not None
    assert result.plan.task_type == "resume_analysis"
    assert result.tool_trace == ["get_resume_by_id"]
    assert result.answer == "我没有读取到可总结的简历内容，请上传或粘贴简历。"


def test_agent_resume_optimize_cleans_parsed_resume_noise(
    isolated_runtime,
) -> None:
    candidate = CandidateService().create_candidate(
        name="Parsed Resume User",
        user_id="parsed-resume-user",
    )
    ResumeService().create_resume(
        candidate_id=int(candidate["id"]),
        title="Resume parsed from image",
        content=(
            "# Parsed Resume\n"
            "Name: 陈XX\n"
            "Email: test@example.com\n"
            "Phone: 18948770463\n"
            "## Summary\n"
            "具备扎实的数据分析与后端开发能力，熟悉 Python、SQL、FastAPI。\n"
            "## Project\n"
            "负责搭建数据处理 API，并优化查询性能。"
        ),
        version="v1",
    )
    service = AgentService(llm_client=FakeLLMClient())

    result = service.respond("parsed-resume-user", "优化简历")

    assert result.plan is not None
    assert result.plan.task_type == "resume_analysis"
    assert result.tool_trace == ["get_resume_by_id"]
    assert "Parsed Resume" not in result.answer
    assert "Email:" not in result.answer
    assert "Phone:" not in result.answer
    assert "优先优化 3 项" in result.answer
    assert "改写示例" in result.answer


def test_agent_job_match_planning_can_replan_loop_steps(isolated_runtime) -> None:
    class ReplanLLM(FakeLLMClient):
        def __init__(self) -> None:
            super().__init__()
            self._issued = False

        def decide_react_action(self, **kwargs):
            self.observe_calls.append(kwargs)
            last_observation = kwargs.get("last_observation") or {}
            current_step = str(last_observation.get("step") or "")
            if current_step == "search_jobs" and not self._issued:
                self._issued = True
                return {
                    "action": "replan_strategy",
                    "reason": "skip candidate step, go straight to resume match",
                    "observation_summary": "",
                    "tool_name": "",
                    "planned_tools": ["match_resume_to_jobs"],
                }
            return {
                "action": "continue",
                "reason": "continue",
                "observation_summary": "",
                "tool_name": "",
                "planned_tools": [],
            }

    fake_llm = ReplanLLM()
    candidate = CandidateService().create_candidate(name="Loop User", user_id="loop-user")
    from app.services.resume_service import ResumeService

    ResumeService().create_resume(
        candidate_id=int(candidate["id"]),
        title="Loop Resume",
        content="Python FastAPI backend APIs and SQL projects",
        version="v1",
    )
    JobService().create_job(title="Python FastAPI Backend Engineer")
    service = AgentService(llm_client=fake_llm)

    result = service.respond("loop-user", "结合我的情况推荐适合投的岗位")

    assert result.plan is not None
    assert result.plan.task_type == "job_match_planning"
    assert "search_jobs" in result.tool_trace
    assert "match_resume_to_jobs" in result.tool_trace
    assert fake_llm.observe_calls, "observe loop should run for job_match_planning"
    assert result.loop_trace
    assert any(item.get("decider_action") == "continue" for item in result.loop_trace)
    assert any("skip candidate step" in str(item.get("decider_reason", "")) for item in result.loop_trace)


def test_agent_can_disable_observe_loop_via_settings(isolated_runtime) -> None:
    class ReplanAlwaysLLM(FakeLLMClient):
        def decide_next_action(self, **kwargs):
            self.observe_calls.append(kwargs)
            return {
                "decision": "replan",
                "reason": "force loop",
                "steps": ["search_jobs"],
            }

    old = settings.agent_enable_observe_loop
    settings.agent_enable_observe_loop = False
    try:
        fake_llm = ReplanAlwaysLLM()
        candidate = CandidateService().create_candidate(name="Loop Off User", user_id="loop-off-user")
        from app.services.resume_service import ResumeService

        ResumeService().create_resume(
            candidate_id=int(candidate["id"]),
            title="Loop Off Resume",
            content="Python FastAPI backend APIs and SQL projects",
            version="v1",
        )
        JobService().create_job(title="Python FastAPI Backend Engineer")
        service = AgentService(llm_client=fake_llm)

        result = service.respond("loop-off-user", "结合我的情况推荐适合投的岗位")
    finally:
        settings.agent_enable_observe_loop = old

    assert result.plan is not None
    assert result.plan.task_type == "job_match_planning"
    assert fake_llm.observe_calls == []
    assert result.loop_trace == []


def test_agent_loop_stops_on_no_progress_when_replan_repeats_same_search(
    isolated_runtime,
) -> None:
    class RepeatSearchLLM(FakeLLMClient):
        def decide_next_action(self, **kwargs):
            self.observe_calls.append(kwargs)
            if kwargs.get("current_step") == "search_jobs":
                return {
                    "decision": "replan",
                    "reason": "retry same search",
                    "steps": ["search_jobs"],
                }
            return {"decision": "continue", "reason": "continue", "steps": []}

    fake_llm = RepeatSearchLLM()
    candidate = CandidateService().create_candidate(
        name="NoProgress User",
        user_id="no-progress-user",
    )
    from app.services.resume_service import ResumeService

    ResumeService().create_resume(
        candidate_id=int(candidate["id"]),
        title="NoProgress Resume",
        content="Python FastAPI backend APIs",
        version="v1",
    )
    JobService().create_job(title="Python FastAPI Backend Engineer")
    service = AgentService(llm_client=fake_llm)

    result = service.respond("no-progress-user", "结合我的情况推荐适合投的岗位")

    assert result.plan is not None
    assert result.plan.task_type == "job_match_planning"
    # should avoid runaway loops even when observer keeps asking to rerun
    assert result.tool_trace.count("search_jobs") <= 2


def test_agent_interview_prep_uses_react_loop_and_trace(
    isolated_runtime,
) -> None:
    fake_llm = FakeLLMClient()
    candidate = CandidateService().create_candidate(name="Interview Loop User", user_id="interview-loop-user")
    ResumeService().create_resume(
        candidate_id=int(candidate["id"]),
        title="Interview Resume",
        content="Data analyst intern with Python SQL dashboard projects",
        version="v1",
    )
    service = AgentService(llm_client=fake_llm)

    result = service.respond("interview-loop-user", "我想准备数据分析岗面试")

    assert result.plan is not None
    assert result.plan.task_type == "interview_prep"
    assert "get_candidate_profile" in result.tool_trace
    assert fake_llm.observe_calls
    assert result.loop_trace
    assert "面试准备计划" in result.answer
    assert "简历总结：" not in result.answer


def test_agent_stops_gracefully_when_tool_returns_error_result(isolated_runtime) -> None:
    class BrokenRegistry(ToolRegistry):
        def __init__(self) -> None:
            super().__init__(
                tools=[
                    ToolDefinition(
                        name="search_jobs",
                        description="broken search",
                        input_model=SearchJobsToolInput,
                        handler=lambda payload: [],
                    )
                ]
            )

        def run(self, name: str, payload: dict) -> dict:
            _ = (name, payload)
            return {"ok": False, "tool_name": "search_jobs", "data": None, "error": "boom"}

    fake_llm = FakeLLMClient()
    service = AgentService(llm_client=fake_llm, tool_registry=BrokenRegistry())

    result = service.respond("broken-tool-user", "帮我找一些 Python backend 岗位")

    assert result.plan is not None
    assert result.plan.task_type == "job_search"
    assert result.tool_trace == []
    assert result.tool_used is None
    assert result.answer.startswith("fake-generate:")


def test_chat_routes_to_interview_history_tool(isolated_runtime) -> None:
    candidate = CandidateService().create_candidate(name="Interview History User", user_id="iv-history-user")
    InterviewService().create_interview(
        candidate_id=int(candidate["id"]),
        company="Atlassian",
        job_title="Backend Intern",
        interview_round="hr",
        result="pending",
    )
    fake_llm = FakeLLMClient()
    service = AgentService(llm_client=fake_llm)

    result = service.respond("iv-history-user", "我最近面试反馈怎么样？")

    assert fake_llm.called is False
    assert result.plan is not None
    assert result.plan.task_type == "interview_history"
    assert result.tool_trace == ["get_interview_feedback"]
    assert result.tool_used == "get_interview_feedback"
    assert result.sources
    assert result.sources[0].type == "interview_feedback"
    assert "Atlassian" in result.answer


def test_chat_strategy_no_response_query_routes_to_career_insights(
    isolated_runtime,
) -> None:
    candidate = CandidateService().create_candidate(
        name="Strategy Query User",
        user_id="strategy-query-user",
    )
    from app.services.application_service import ApplicationService

    ApplicationService().create_application(
        candidate_id=int(candidate["id"]),
        company="Canva",
        job_title="Backend Intern",
        status="applied",
    )
    InterviewService().create_interview(
        candidate_id=int(candidate["id"]),
        company="Atlassian",
        job_title="Backend Grad",
        interview_round="tech1",
        result="rejected",
        feedback="need stronger system design examples",
    )
    fake_llm = PlannerAwareLLMClient()
    service = AgentService(llm_client=fake_llm)

    result = service.respond(
        "strategy-query-user",
        "我投了很多没回音，结合我的投递和面试反馈，给我一个两周行动策略",
    )

    assert result.plan is not None
    assert result.plan.task_type == "career_insights"
    assert result.tool_trace == ["get_career_insights"]


def test_chat_routes_to_career_insights_tool(isolated_runtime) -> None:
    candidate = CandidateService().create_candidate(
        name="Career Insight User",
        user_id="career-insight-user",
    )
    from app.services.application_service import ApplicationService

    ApplicationService().create_application(
        candidate_id=int(candidate["id"]),
        company="Canva",
        job_title="Backend Intern",
        status="applied",
    )
    InterviewService().create_interview(
        candidate_id=int(candidate["id"]),
        company="Atlassian",
        job_title="Backend Grad",
        interview_round="tech1",
        result="rejected",
        feedback="need stronger system design examples",
    )
    fake_llm = PlannerAwareLLMClient()
    service = AgentService(llm_client=fake_llm)

    result = service.respond(
        "career-insight-user",
        "结合我的投递和面试反馈，我下一步该准备什么？",
    )

    assert fake_llm.called is False
    assert result.plan is not None
    assert result.plan.task_type == "career_insights"
    assert result.tool_trace == ["get_career_insights"]
    assert result.tool_used == "get_career_insights"
    assert result.plan.diagnostic_plan is not None
    assert [step["tool_name"] for step in result.plan.tool_chain] == ["get_career_insights"]
    planner_events = [
        item
        for item in result.plan.resolver_trace
        if item.get("resolver") == "diagnostic_planner"
    ]
    assert planner_events[-1]["status"] in {"applied", "fallback"}
    assert {source.type for source in result.sources} >= {
        "application",
        "interview_feedback",
    }
    assert "初步诊断：" in result.answer
    assert "下一步" in result.answer
    assert "system design" in result.answer
    assert "主要风险" in result.answer
    assert "推荐行动" in result.answer


def test_agent_retrieval_can_use_indexed_career_profile_source(
    isolated_runtime,
) -> None:
    candidate = CandidateService().create_candidate(
        name="Indexed Profile User",
        user_id="indexed-profile-user",
    )
    InterviewService().create_interview(
        candidate_id=int(candidate["id"]),
        company="Canva",
        job_title="Backend Intern",
        interview_round="tech1",
        result="rejected",
        feedback="system design fundamentals",
    )
    AgentService(llm_client=FakeLLMClient()).respond(
        "indexed-profile-user",
        "结合我的投递和面试反馈，我下一步该准备什么？",
    )
    service = AgentService(llm_client=RetrievalOnlyLLM())

    result = service.respond("indexed-profile-user", "system design fundamentals")

    assert result.sources
    profile_sources = [
        source for source in result.sources if source.type == "career_profile"
    ]
    assert profile_sources
    assert "system design fundamentals" in profile_sources[0].snippet


def test_agent_retrieval_can_use_indexed_career_event_source(
    isolated_runtime,
) -> None:
    candidate = CandidateService().create_candidate(
        name="Indexed Event User",
        user_id="indexed-event-user",
    )
    InterviewService().create_interview(
        candidate_id=int(candidate["id"]),
        company="Atlassian",
        job_title="Backend Grad",
        interview_round="tech1",
        result="rejected",
        feedback="system design fundamentals",
    )
    AgentService(llm_client=FakeLLMClient()).respond(
        "indexed-event-user",
        "结合我的投递和面试反馈，我下一步该准备什么？",
    )
    service = AgentService(llm_client=RetrievalOnlyLLM())

    result = service.respond("indexed-event-user", "Atlassian system design fundamentals")

    assert result.sources
    assert result.sources[0].type == "career_event"
    assert "system design fundamentals" in result.sources[0].snippet


def test_agent_syncs_llm_extracted_message_events_for_later_retrieval(
    isolated_runtime,
) -> None:
    service = AgentService(llm_client=CareerEventExtractingLLM())

    service.respond(
        "message-memory-user",
        "Canva backend 面试没过，反馈是 system design fundamentals 要补。",
    )
    result = service.respond(
        "message-memory-user",
        "Canva system design fundamentals",
    )

    assert result.sources
    assert result.sources[0].type == "career_event"
    assert "system design fundamentals" in result.sources[0].snippet


def test_agent_skips_message_event_extraction_for_regular_job_search(
    isolated_runtime,
) -> None:
    fake_llm = CareerEventExtractingLLM()
    JobService().create_job(title="Sydney Backend Intern")
    service = AgentService(llm_client=fake_llm)

    service.respond("message-skip-user", "帮我找悉尼后端实习")

    assert fake_llm.extract_career_events_calls == []


def test_agent_runs_message_event_extraction_for_obvious_interview_update(
    isolated_runtime,
) -> None:
    fake_llm = CareerEventExtractingLLM()
    service = AgentService(llm_client=fake_llm)

    service.respond(
        "message-extract-user",
        "Canva backend 面试没过，反馈是 system design fundamentals 要补。",
    )

    assert len(fake_llm.extract_career_events_calls) == 1
