from app.schemas.tool import MatchResumeToJobsToolInput, SearchJobsToolInput
from app.resolvers.tool_resolver import ToolResolver
from app.services.plan_executor import PlanExecutor
from app.tools.base import ToolDefinition
from app.tools.registry import ToolRegistry

JOB_MATCH_PLAN = {
    "task_type": "job_match_planning",
    "domain": "job_match",
    "action": "recommend",
}


class AskForContextDecider:
    def decide_react_action(self, **kwargs):
        _ = kwargs
        return {
            "action": "ask_for_context",
            "reason": "missing_job_detail",
            "observation_summary": "need explicit JD",
        }


def test_execute_react_loop_stops_on_ask_for_context() -> None:
    registry = ToolRegistry(
        tools=[
            ToolDefinition(
                name="search_jobs",
                description="search",
                input_model=SearchJobsToolInput,
                    handler=lambda payload: [{"title": "Backend Engineer", "snippet": str(payload.query)}],
            ),
            ToolDefinition(
                name="match_resume_to_jobs",
                description="match",
                    input_model=MatchResumeToJobsToolInput,
                    handler=lambda payload: [{"title": "Backend Engineer", "snippet": str(payload.resume_id)}],
            ),
        ]
    )
    executor = PlanExecutor(
        tool_registry=registry,
        llm_client=AskForContextDecider(),
        max_loop_steps=8,
        max_step_repeat=2,
    )

    trace, state, loop_trace = executor.execute_react_loop(
        user_id="u1",
        message="帮我看看适不适合",
        initial_steps=["search_jobs", "match_resume_to_jobs"],
        task_type="job_match_planning",
        build_payload=lambda user_id, message, step, state: {"query": message}
        if step == "search_jobs"
        else {"resume_id": 1},
        should_continue_after_step=lambda step, result, state: True,
    )

    assert trace == ["search_jobs"]
    assert state["_missing_context"] == []
    assert loop_trace
    assert loop_trace[-1]["decider_action"] == "ask_for_context"
    assert state["_loop_control"]["terminated_by"] == "ask_for_context"


class SwitchToolDecider:
    def __init__(self, *, tool_to_front: str) -> None:
        self.tool_to_front = tool_to_front
        self.calls = 0

    def decide_react_action(self, **kwargs):
        _ = kwargs
        self.calls += 1
        return {
            "action": "switch_tool",
            "tool_name": self.tool_to_front,
            "reason": "prioritize_matching",
            "observation_summary": "reordered queue",
        }


def test_execute_react_loop_switch_tool_reorders_remaining_queue() -> None:
    registry = ToolRegistry(
        tools=[
            ToolDefinition(
                name="search_jobs",
                description="search",
                input_model=SearchJobsToolInput,
                handler=lambda payload: [{"title": "Backend", "snippet": str(payload.query)}],
            ),
            ToolDefinition(
                name="match_resume_to_jobs",
                description="match",
                input_model=MatchResumeToJobsToolInput,
                handler=lambda payload: {"matches": []},
            ),
        ]
    )
    resolver = ToolResolver()
    allowed = resolver.executor_allowed_tool_order(
        plan=JOB_MATCH_PLAN,
        available_tools=registry.list_tool_names(),
    )
    decider = SwitchToolDecider(tool_to_front="match_resume_to_jobs")
    executor = PlanExecutor(
        tool_registry=registry,
        llm_client=decider,
        max_loop_steps=8,
        max_step_repeat=2,
    )

    trace, state, loop_trace = executor.execute_react_loop(
        user_id="u1",
        message="combine",
        initial_steps=["search_jobs", "match_resume_to_jobs"],
        task_type="job_match_planning",
        build_payload=lambda user_id, message, step, state: {"query": message}
        if step == "search_jobs"
        else {"resume_id": 1},
        should_continue_after_step=lambda step, result, state: True,
        replan_budget=2,
        whitelist_executor_tools=allowed,
        validate_replan_chain=lambda proposed, exec_trace: resolver.normalize_executor_replan_chain(
            plan=JOB_MATCH_PLAN,
            proposed_tools=list(proposed),
            available_tools=registry.list_tool_names(),
            executed_trace=list(exec_trace),
        ),
    )

    assert trace == ["search_jobs", "match_resume_to_jobs"]
    assert state["_loop_control"]["switch_count"] == 1
    assert any(ev.get("decider_action") == "switch_tool" for ev in loop_trace)
    assert state["_loop_control"]["terminated_by"] == "finish"


def test_execute_react_loop_switch_tool_rejected_for_unknown_tool() -> None:
    registry = ToolRegistry(
        tools=[
            ToolDefinition(
                name="search_jobs",
                description="search",
                input_model=SearchJobsToolInput,
                handler=lambda payload: [{"title": "Backend", "snippet": str(payload.query)}],
            ),
            ToolDefinition(
                name="match_resume_to_jobs",
                description="match",
                input_model=MatchResumeToJobsToolInput,
                handler=lambda payload: {"matches": []},
            ),
        ]
    )

    class BadSwitch:
        def decide_react_action(self, **kwargs):
            return {
                "action": "switch_tool",
                "tool_name": "not_a_registered_tool",
                "reason": "bad",
                "observation_summary": "",
            }

    resolver = ToolResolver()
    allowed = resolver.executor_allowed_tool_order(
        plan=JOB_MATCH_PLAN,
        available_tools=registry.list_tool_names(),
    )
    executor = PlanExecutor(
        tool_registry=registry,
        llm_client=BadSwitch(),
        max_loop_steps=8,
        max_step_repeat=2,
    )

    trace, _, loop_trace = executor.execute_react_loop(
        user_id="u1",
        message="combine",
        initial_steps=["search_jobs", "match_resume_to_jobs"],
        task_type="job_match_planning",
        build_payload=lambda user_id, message, step, state: {"query": message}
        if step == "search_jobs"
        else {"resume_id": 1},
        should_continue_after_step=lambda step, result, state: True,
        replan_budget=2,
        whitelist_executor_tools=allowed,
        validate_replan_chain=lambda proposed, exec_trace: resolver.normalize_executor_replan_chain(
            plan=JOB_MATCH_PLAN,
            proposed_tools=list(proposed),
            available_tools=registry.list_tool_names(),
            executed_trace=list(exec_trace),
        ),
    )

    assert len(trace) == 2
    assert any(ev.get("guardrail_decision") == "rejected" for ev in loop_trace)


class ReplannerOnce:
    def __init__(self) -> None:
        self.once = False

    def decide_react_action(self, **kwargs):
        remaining = kwargs.get("available_tools") or []
        _ = kwargs
        if not self.once and remaining:
            self.once = True
            return {
                "action": "replan_strategy",
                "planned_tools": ["match_resume_to_jobs"],
                "reason": "skip_duplicate_search",
                "observation_summary": "narrow plan",
            }
        return {
            "action": "continue",
            "reason": "go_on",
            "observation_summary": "",
        }


def test_execute_react_loop_replan_strategy_rewrites_remaining_queue() -> None:
    registry = ToolRegistry(
        tools=[
            ToolDefinition(
                name="search_jobs",
                description="search",
                input_model=SearchJobsToolInput,
                handler=lambda payload: [{"title": "Backend", "snippet": str(payload.query)}],
            ),
            ToolDefinition(
                name="match_resume_to_jobs",
                description="match",
                input_model=MatchResumeToJobsToolInput,
                handler=lambda payload: {"matches": [{"job_title": "X", "match_score": "0.5"}]},
            ),
        ]
    )
    resolver = ToolResolver()
    allowed = resolver.executor_allowed_tool_order(
        plan=JOB_MATCH_PLAN,
        available_tools=registry.list_tool_names(),
    )
    executor = PlanExecutor(
        tool_registry=registry,
        llm_client=ReplannerOnce(),
        max_loop_steps=8,
        max_step_repeat=2,
    )

    trace, state, loop_trace = executor.execute_react_loop(
        user_id="u1",
        message="combine",
        initial_steps=["search_jobs", "match_resume_to_jobs"],
        task_type="job_match_planning",
        build_payload=lambda user_id, message, step, state: {"query": message}
        if step == "search_jobs"
        else {"resume_id": 1},
        should_continue_after_step=lambda step, result, state: True,
        replan_budget=2,
        whitelist_executor_tools=allowed,
        validate_replan_chain=lambda proposed, exec_trace: resolver.normalize_executor_replan_chain(
            plan=JOB_MATCH_PLAN,
            proposed_tools=list(proposed),
            available_tools=registry.list_tool_names(),
            executed_trace=list(exec_trace),
        ),
    )

    assert trace[-1] == "match_resume_to_jobs"
    assert any(ev.get("replanned_chain") for ev in loop_trace)


def test_execute_react_loop_budget_exhaust_after_first_strategy_move_with_zero_budget() -> None:
    registry = ToolRegistry(
        tools=[
            ToolDefinition(
                name="search_jobs",
                description="search",
                input_model=SearchJobsToolInput,
                handler=lambda payload: [{"title": "Backend", "snippet": str(payload.query)}],
            ),
            ToolDefinition(
                name="match_resume_to_jobs",
                description="match",
                input_model=MatchResumeToJobsToolInput,
                handler=lambda payload: {"matches": []},
            ),
        ]
    )

    resolver = ToolResolver()
    allowed = resolver.executor_allowed_tool_order(
        plan=JOB_MATCH_PLAN,
        available_tools=registry.list_tool_names(),
    )
    executor = PlanExecutor(
        tool_registry=registry,
        llm_client=SwitchToolDecider(tool_to_front="match_resume_to_jobs"),
        max_loop_steps=8,
        max_step_repeat=2,
    )

    trace, state, loop_trace = executor.execute_react_loop(
        user_id="u1",
        message="combine",
        initial_steps=["search_jobs", "match_resume_to_jobs"],
        task_type="job_match_planning",
        build_payload=lambda user_id, message, step, state: {"query": message}
        if step == "search_jobs"
        else {"resume_id": 1},
        should_continue_after_step=lambda step, result, state: True,
        replan_budget=0,
        whitelist_executor_tools=allowed,
        validate_replan_chain=lambda proposed, exec_trace: resolver.normalize_executor_replan_chain(
            plan=JOB_MATCH_PLAN,
            proposed_tools=list(proposed),
            available_tools=registry.list_tool_names(),
            executed_trace=list(exec_trace),
        ),
    )

    assert trace == ["search_jobs"]
    assert state["_loop_control"]["terminated_by"] == "budget_exhausted"
    assert any(ev.get("decider_reason") == "budget_exhausted" for ev in loop_trace)
