from app.services.agent_service import AgentService
from app.services.candidate_service import CandidateService
from app.services.job_service import JobService


class FakeLLMClient:
    def __init__(self) -> None:
        self.called = False

    def generate_plan(self, **kwargs):
        self.called = True
        return {
            "task_type": "job_search",
            "reason": "planned by fake llm",
            "steps": ["search_jobs"],
            "needs_more_context": False,
        }

    def generate(self, message: str, memory_context: list[str], evidence: list[str]) -> str:
        return f"fake-generate:{message}"
def test_agent_service_uses_llm_layer_to_build_plan(isolated_runtime) -> None:
    fake_llm = FakeLLMClient()
    CandidateService().create_candidate(name="Planner User")
    JobService().create_job(title="Python FastAPI Backend Engineer")
    service = AgentService(llm_client=fake_llm)

    result = service.respond("planner-user", "帮我找一些 Python backend 岗位")

    assert fake_llm.called is True
    assert result.plan is not None
    assert result.plan.task_type == "job_search"
    assert result.plan.reason == "planned by fake llm"
    assert result.tool_trace == ["search_jobs"]
