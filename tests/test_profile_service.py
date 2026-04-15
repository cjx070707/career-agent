from app.services.profile_service import ProfileService


def test_profile_service_updates_role_and_skills_from_message(isolated_runtime) -> None:
    service = ProfileService()

    service.update_from_message("user-1", "我想走 Python FastAPI 后端方向")
    profile = service.get_profile("user-1")

    assert profile["target_role_preference"] == "backend"
    assert "python" in profile["skill_keywords"]
    assert "fastapi" in profile["skill_keywords"]


def test_augment_job_query_adds_usyd_defaults_for_sydney_search(isolated_runtime) -> None:
    service = ProfileService()

    query = service.augment_job_query(
        "user-1",
        "帮我找一些悉尼大学附近的数据分析实习",
    )

    lowered = query.lower()
    assert "sydney" in lowered
    assert "university of sydney" in lowered or "usyd" in lowered
    assert "data" in lowered or "analyst" in lowered
