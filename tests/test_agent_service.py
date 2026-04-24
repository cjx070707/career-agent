from app.services.agent_service import AgentService
from app.services.interview_service import InterviewService
from app.services.candidate_service import CandidateService
from app.services.job_service import JobService
from app.services.memory_service import MemoryService


class FakeLLMClient:
    def __init__(self) -> None:
        self.called = False
        self.summarize_job_search_calls = []
        self.last_plan_source = "not_used"
        self.last_job_search_summary_source = "not_used"
        self.last_generate_source = "not_used"

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


def test_agent_service_uses_llm_layer_for_gray_query(isolated_runtime) -> None:
    fake_llm = FakeLLMClient()
    CandidateService().create_candidate(name="Planner User")
    JobService().create_job(title="Python FastAPI Backend Engineer")
    service = AgentService(llm_client=fake_llm)

    result = service.respond("planner-user", "你觉得我下一步职业方向应该怎么考虑")

    assert fake_llm.called is True
    assert result.plan is not None
    assert result.plan.task_type == "job_search"
    assert result.plan.reason == "planned by fake llm"
    assert result.tool_trace == ["search_jobs"]
    assert result.llm_trace.model_dump() == {
        "planner_source": "model",
        "job_search_summary_source": "model",
        "generate_source": "not_used",
    }


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
            "task_type": "job_search",
            "reason": "retrieve evidence without tool execution",
            "steps": [],
            "needs_more_context": False,
            "missing_context": [],
            "follow_up_question": None,
            "planner_source": "model",
        }


def test_agent_service_degrades_gracefully_when_plan_step_prerequisites_missing(
    isolated_runtime,
) -> None:
    # User has no candidate seeded; planner still wants get_candidate_profile.
    # The agent must not crash — it should degrade to a graceful answer with
    # plan preserved and tool_trace empty.
    fake_llm = PlannerRequestingMissingCandidateLLM()
    service = AgentService(llm_client=fake_llm)

    result = service.respond("brand-new-user", "随便问一句")

    assert fake_llm.called is True
    assert result.plan is not None
    assert result.plan.task_type == "candidate_profile"
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
    fake_llm = FakeLLMClient()
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
    assert {source.type for source in result.sources} >= {
        "application",
        "interview_feedback",
    }
    assert "下一步" in result.answer
    assert "system design" in result.answer


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
    assert result.sources[0].type == "career_profile"
    assert "system design fundamentals" in result.sources[0].snippet
