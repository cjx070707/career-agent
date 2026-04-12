from app.services.profile_service import ProfileService


def test_profile_service_updates_role_and_skills_from_message(isolated_runtime) -> None:
    service = ProfileService()

    service.update_from_message("user-1", "我想走 Python FastAPI 后端方向")
    profile = service.get_profile("user-1")

    assert profile["target_role_preference"] == "backend"
    assert "python" in profile["skill_keywords"]
    assert "fastapi" in profile["skill_keywords"]
