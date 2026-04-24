from app.services.profile_service import ProfileService
from app.services.application_service import ApplicationService
from app.services.candidate_service import CandidateService
from app.services.interview_service import InterviewService
from app.db.session import get_connection, init_db


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


def test_profile_service_refreshes_long_term_profile_from_records(
    isolated_runtime,
) -> None:
    candidate = CandidateService().create_candidate(
        name="Long Profile User",
        user_id="long-profile-user",
    )
    ApplicationService().create_application(
        candidate_id=int(candidate["id"]),
        company="Canva",
        job_title="Backend Intern",
        status="applied",
    )
    ApplicationService().create_application(
        candidate_id=int(candidate["id"]),
        company="Atlassian",
        job_title="Backend Grad",
        status="interview",
    )
    InterviewService().create_interview(
        candidate_id=int(candidate["id"]),
        company="Atlassian",
        job_title="Backend Grad",
        interview_round="tech1",
        result="rejected",
        feedback="need stronger system design examples",
    )
    service = ProfileService()

    profile = service.refresh_from_career_records("long-profile-user")

    assert profile["application_patterns"] == "applied: 1; interview: 1"
    assert profile["interview_weaknesses"] == "need stronger system design examples"
    assert profile["next_focus_areas"] == "need stronger system design examples"


def test_augment_job_query_includes_persisted_long_term_profile_signals(
    isolated_runtime,
) -> None:
    candidate = CandidateService().create_candidate(
        name="Query Profile User",
        user_id="query-profile-user",
    )
    InterviewService().create_interview(
        candidate_id=int(candidate["id"]),
        company="Canva",
        job_title="Backend Intern",
        interview_round="tech1",
        result="rejected",
        feedback="system design fundamentals",
    )
    service = ProfileService()
    service.refresh_from_career_records("query-profile-user")

    query = service.augment_job_query("query-profile-user", "帮我找 backend 岗位")

    assert "system design fundamentals" in query


def test_init_db_adds_long_term_profile_columns_to_existing_table(
    isolated_runtime,
) -> None:
    db_path = isolated_runtime["db_path"]
    with get_connection(str(db_path)) as connection:
        connection.execute("DROP TABLE career_profiles")
        connection.execute(
            """
            CREATE TABLE career_profiles (
                user_id TEXT PRIMARY KEY,
                target_role_preference TEXT NOT NULL DEFAULT '',
                skill_keywords TEXT NOT NULL DEFAULT '',
                career_focus_notes TEXT NOT NULL DEFAULT '',
                updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            )
            """
        )

    init_db(str(db_path))

    with get_connection(str(db_path)) as connection:
        columns = {
            row["name"]
            for row in connection.execute("PRAGMA table_info(career_profiles)").fetchall()
        }
    assert {"application_patterns", "interview_weaknesses", "next_focus_areas"} <= columns
