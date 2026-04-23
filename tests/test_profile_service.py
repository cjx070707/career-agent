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


def test_update_from_message_detects_full_stack_and_data_roles(isolated_runtime) -> None:
    service = ProfileService()

    fullstack = service.update_from_message("user-fs", "我想做 full-stack 全栈方向的岗位")
    assert fullstack["target_role_preference"] == "full-stack"

    data = service.update_from_message("user-da", "想找一份 data analyst 实习，做 pandas 分析")
    assert data["target_role_preference"] == "data"
    assert "pandas" in data["skill_keywords"]

    ai = service.update_from_message("user-ai", "对 AI / ML 机器学习方向感兴趣")
    assert ai["target_role_preference"] == "ai/ml"

    devops = service.update_from_message("user-do", "想做 devops 方向，熟悉 docker 和 kubernetes")
    assert devops["target_role_preference"] == "devops"
    assert "docker" in devops["skill_keywords"]
    assert "kubernetes" in devops["skill_keywords"]


def test_extract_skill_keywords_recognizes_broader_stack(isolated_runtime) -> None:
    service = ProfileService()

    profile = service.update_from_message(
        "user-skills",
        "熟悉 TypeScript, Go, Rust, Docker, Kubernetes, AWS, GCP, Pandas, PyTorch",
    )

    for keyword in (
        "typescript",
        "go",
        "rust",
        "docker",
        "kubernetes",
        "aws",
        "gcp",
        "pandas",
        "pytorch",
    ):
        assert keyword in profile["skill_keywords"], f"{keyword} missing"


def test_augment_job_query_keeps_work_type_signals_for_intern_and_graduate(
    isolated_runtime,
) -> None:
    service = ProfileService()

    intern_query = service.augment_job_query("user-wt", "帮我找悉尼 AI 实习岗位")
    graduate_query = service.augment_job_query("user-wt", "我想找 graduate program 岗位")

    assert "intern" in intern_query.lower()
    assert "internship" in intern_query.lower()
    assert "graduate" in graduate_query.lower()
