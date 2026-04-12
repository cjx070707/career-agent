from pathlib import Path

from app.db.session import init_db
from app.env import settings
from app.services.job_service import JobService
from app.services.retrieval_service import RetrievalService


def test_retrieval_service_ranks_backend_fastapi_role_first(tmp_path: Path) -> None:
    service = RetrievalService(
        persist_directory=tmp_path / "chroma_rank",
        collection_name="rank_jobs",
    )

    results = service.search("backend fastapi python internship")

    assert results
    assert results[0].title == "Backend Engineer Intern"
    assert all(result.type == "job_posting" for result in results)


def test_retrieval_service_filters_irrelevant_roles(tmp_path: Path) -> None:
    service = RetrievalService(
        persist_directory=tmp_path / "chroma_filter",
        collection_name="filter_jobs",
    )

    results = service.search("llm tool orchestration backend platform")

    assert results
    titles = [result.title for result in results]
    assert "AI Platform Backend Engineer" in titles
    assert "Frontend Engineer Intern" not in titles


def test_retrieval_service_matches_content_terms_without_job_keywords(tmp_path: Path) -> None:
    service = RetrievalService(
        persist_directory=tmp_path / "chroma_content",
        collection_name="content_jobs",
    )

    results = service.search("react typescript ui components")

    assert results
    assert results[0].title == "Frontend Engineer Intern"


def test_retrieval_service_builds_persistent_chroma_collection(tmp_path: Path) -> None:
    service = RetrievalService(
        persist_directory=tmp_path / "chroma",
        collection_name="test_jobs",
    )

    results = service.search("python fastapi api")

    assert service.document_count() == 3
    assert results
    assert (tmp_path / "chroma").exists()

    reloaded_service = RetrievalService(
        persist_directory=tmp_path / "chroma",
        collection_name="test_jobs",
    )
    reloaded_results = reloaded_service.search("tool orchestration retrieval")

    assert reloaded_service.document_count() == 3
    assert reloaded_results
    assert reloaded_results[0].title == "AI Platform Backend Engineer"


def test_new_jobs_are_auto_indexed_into_chroma(tmp_path: Path) -> None:
    db_path = tmp_path / "jobs.db"
    chroma_path = tmp_path / "chroma"
    settings.db_path = str(db_path)
    settings.chroma_persist_directory = str(chroma_path)
    settings.chroma_collection_name = "auto_index_jobs"
    init_db(str(db_path))

    service = JobService()
    service.create_job(title="Vector Retrieval Backend Engineer")

    retrieval = RetrievalService(
        persist_directory=chroma_path,
        collection_name="auto_index_jobs",
    )
    results = retrieval.search("vector retrieval backend")

    assert results
    assert results[0].title == "Vector Retrieval Backend Engineer"
