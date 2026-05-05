from app.services.autonomous_agent_service import AutonomousAgentService


def test_system_prompt_prefers_search_over_goal_for_job_hunting_phrase() -> None:
    service = AutonomousAgentService()

    prompt = service._build_system_prompt(user_id="u1", goals=[], summary="", user_profile="{}")

    assert "我想找" in prompt
    assert "search_jobs" in prompt
    assert "set_goal" in prompt
    assert "只有当用户明确要求设定目标" in prompt


def test_system_prompt_includes_recommendation_chain_when_resume_exists() -> None:
    service = AutonomousAgentService()

    prompt = service._build_system_prompt(user_id="u1", goals=[], summary="", user_profile="{}")

    assert "get_candidate_profile" in prompt
    assert "get_resume_by_id" in prompt
    assert "search_jobs" in prompt
    assert "match_resume_to_jobs" in prompt

