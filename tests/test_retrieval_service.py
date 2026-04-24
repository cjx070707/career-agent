from pathlib import Path

from app.db.session import init_db
from app.env import settings
from app.services.job_service import JobService
from app.services.retrieval_service import RetrievalResult, RetrievalService


def test_search_with_reasons_includes_matched_terms_and_reason_text(tmp_path: Path) -> None:
    service = RetrievalService(
        persist_directory=tmp_path / "chroma_reasons",
        collection_name="reason_jobs",
    )

    hits = service.search_with_reasons("python fastapi backend")

    assert hits
    assert hits[0].title == "Backend Engineer Intern"
    assert hits[0].type == "job_posting"
    assert set(hits[0].matched_terms) >= {"python", "fastapi", "backend"}
    assert "命中关键词" in hits[0].reason


def test_search_with_reasons_caps_terms_and_filters_noisy_domain_words(
    tmp_path: Path,
) -> None:
    service = RetrievalService(
        persist_directory=tmp_path / "chroma_reason_caps",
        collection_name="reason_caps_jobs",
    )

    hit = service._to_reasoned_hit(
        "python fastapi backend engineer intern sql rest api cloud",
        service.search("python fastapi backend internship")[0],
    )

    assert "python" in hit.matched_terms
    assert "backend" in hit.matched_terms
    assert len(hit.matched_terms) <= 3
    assert "命中关键词" in hit.reason
    assert "engineer" not in hit.reason
    assert "intern" not in hit.matched_terms


def test_matched_terms_skip_generic_role_nouns(tmp_path: Path) -> None:
    service = RetrievalService(
        persist_directory=tmp_path / "chroma_generic_role_nouns",
        collection_name="generic_role_nouns_jobs",
    )

    hit = service._to_reasoned_hit(
        "python fastapi backend software developer role position work job team",
        service.search("python fastapi backend internship")[0],
    )

    for noise in (
        "software",
        "developer",
        "role",
        "position",
        "work",
        "job",
        "team",
    ):
        assert noise not in hit.matched_terms, f"{noise} should be filtered"
    assert set(hit.matched_terms) <= {"python", "fastapi", "backend"}


def test_reason_text_uses_generic_overlap_fallback(tmp_path: Path) -> None:
    service = RetrievalService(
        persist_directory=tmp_path / "chroma_generic_reason",
        collection_name="generic_reason_jobs",
    )

    reason = service._reason_text(
        "engineer intern",
        service.search("backend fastapi python internship")[0],
        matched_terms=[],
    )

    assert "低信号" in reason or "语义向量" in reason
    assert "公司：" in reason


def test_reason_text_uses_semantic_fallback_without_lexical_overlap(
    tmp_path: Path,
) -> None:
    service = RetrievalService(
        persist_directory=tmp_path / "chroma_semantic_reason",
        collection_name="semantic_reason_jobs",
    )

    reason = service._reason_text(
        "golang kubernetes distributed-systems",
        service.search("backend fastapi python internship")[0],
        matched_terms=[],
    )

    assert "语义向量" in reason
    assert "标题及摘要的相关性" in reason
    assert "命中关键词" not in reason


def test_retrieval_service_ranks_backend_fastapi_role_first(tmp_path: Path) -> None:
    service = RetrievalService(
        persist_directory=tmp_path / "chroma_rank",
        collection_name="rank_jobs",
    )

    results = service.search("backend fastapi python internship")

    assert results
    titles = [result.title for result in results]
    assert "Backend Engineer Intern" in titles
    assert all(result.type == "job_posting" for result in results)


def test_retrieval_service_keeps_zero_score_hits_after_scored_results(
    tmp_path: Path,
) -> None:
    service = RetrievalService(
        persist_directory=tmp_path / "chroma_filter",
        collection_name="filter_jobs",
    )

    results = service.search("llm tool orchestration backend platform")

    assert results
    titles = [result.title for result in results]
    assert titles[0] == "AI Platform Backend Engineer"
    assert any("Backend" in title for title in titles)
    assert any("Intern" in title for title in titles)


def test_retrieval_service_matches_content_terms_without_job_keywords(tmp_path: Path) -> None:
    service = RetrievalService(
        persist_directory=tmp_path / "chroma_content",
        collection_name="content_jobs",
    )

    results = service.search("react typescript ui components")

    assert results
    assert results[0].title == "Frontend Engineer Intern"


def test_search_preserves_chroma_hits_for_chinese_query_with_zero_lexical_overlap(
    tmp_path: Path,
) -> None:
    service = RetrievalService(
        persist_directory=tmp_path / "chroma_chinese_zero_lex",
        collection_name="chinese_zero_lex_jobs",
    )

    results = service.search("找后端实习岗位")

    assert results
    assert all(result.type == "job_posting" for result in results)


def test_search_preserves_chroma_hits_when_english_query_has_no_corpus_token_overlap(
    tmp_path: Path,
) -> None:
    service = RetrievalService(
        persist_directory=tmp_path / "chroma_k8s_zero_lex",
        collection_name="k8s_zero_lex_jobs",
    )

    results = service.search("kubernetes helm sre")

    assert results
    assert all(result.type == "job_posting" for result in results)


def test_rerank_keeps_zero_score_candidates_after_scored_block_in_original_order(
    tmp_path: Path,
) -> None:
    service = RetrievalService(
        persist_directory=tmp_path / "chroma_mixed_rerank",
        collection_name="mixed_rerank_jobs",
    )
    candidates = [
        RetrievalResult(
            type="job_posting",
            title="Frontend Engineer Intern",
            snippet="React, TypeScript, component libraries, UI implementation.",
        ),
        RetrievalResult(
            type="job_posting",
            title="AI Platform Backend Engineer",
            snippet="Backend services for LLM products and platform APIs.",
        ),
        RetrievalResult(
            type="job_posting",
            title="Site Reliability Engineer",
            snippet="Observability, incident response, and production operations.",
        ),
        RetrievalResult(
            type="job_posting",
            title="Backend Engineer Intern",
            snippet="Python, FastAPI, REST APIs, SQL, and basic cloud exposure.",
        ),
    ]

    reranked = service._rerank("backend fastapi", candidates)

    assert [result.title for result in reranked] == [
        "Backend Engineer Intern",
        "AI Platform Backend Engineer",
        "Frontend Engineer Intern",
        "Site Reliability Engineer",
    ]


def test_retrieval_service_builds_persistent_chroma_collection(tmp_path: Path) -> None:
    service = RetrievalService(
        persist_directory=tmp_path / "chroma",
        collection_name="test_jobs",
    )

    results = service.search("python fastapi api")

    expected_count = service.document_count()
    assert expected_count >= 3
    assert results
    assert (tmp_path / "chroma").exists()

    reloaded_service = RetrievalService(
        persist_directory=tmp_path / "chroma",
        collection_name="test_jobs",
    )
    reloaded_results = reloaded_service.search("tool orchestration retrieval")

    assert reloaded_service.document_count() == expected_count
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


def test_retrieval_service_uses_job_postings_file_setting(tmp_path: Path) -> None:
    custom_payload = """
[
  {
    "type": "job_posting",
    "title": "Custom USYD Role",
    "snippet": "Custom snippet for config path test."
  }
]
""".strip()
    custom_file = tmp_path / "custom_jobs.json"
    custom_file.write_text(custom_payload, encoding="utf-8")

    original = settings.job_postings_file
    settings.job_postings_file = str(custom_file)
    try:
        service = RetrievalService(
            persist_directory=tmp_path / "chroma_custom_path",
            collection_name="custom_path_jobs",
        )
    finally:
        settings.job_postings_file = original

    results = service.search("custom usyd role")
    assert results
    assert results[0].title == "Custom USYD Role"


def test_search_with_reasons_filter_by_location_only(tmp_path: Path) -> None:
    service = RetrievalService(
        persist_directory=tmp_path / "chroma_filter_loc",
        collection_name="filter_loc_jobs",
    )

    hits = service.search_with_reasons(
        "data analyst", filters={"location": "Melbourne"}
    )

    assert hits
    for hit in hits:
        assert hit.location is not None
        assert "melbourne" in hit.location.lower()


def test_search_with_reasons_filter_by_work_type_only(tmp_path: Path) -> None:
    service = RetrievalService(
        persist_directory=tmp_path / "chroma_filter_wt",
        collection_name="filter_wt_jobs",
    )

    hits = service.search_with_reasons(
        "engineer", filters={"work_type": "intern"}
    )

    assert hits
    for hit in hits:
        assert hit.work_type is not None
        assert "intern" in hit.work_type.lower()


def test_search_with_reasons_filter_by_location_and_work_type(tmp_path: Path) -> None:
    service = RetrievalService(
        persist_directory=tmp_path / "chroma_filter_both",
        collection_name="filter_both_jobs",
    )

    hits = service.search_with_reasons(
        "data", filters={"location": "Sydney", "work_type": "intern"}
    )

    assert hits
    for hit in hits:
        assert hit.location is not None and "sydney" in hit.location.lower()
        assert hit.work_type is not None and "intern" in hit.work_type.lower()


def test_search_with_reasons_empty_filters_is_passthrough(tmp_path: Path) -> None:
    service = RetrievalService(
        persist_directory=tmp_path / "chroma_filter_empty",
        collection_name="filter_empty_jobs",
    )

    without = service.search_with_reasons("backend fastapi python")
    with_empty = service.search_with_reasons(
        "backend fastapi python", filters={}
    )
    with_none = service.search_with_reasons("backend fastapi python", filters=None)

    assert [h.title for h in without] == [h.title for h in with_empty]
    assert [h.title for h in without] == [h.title for h in with_none]


def test_search_with_reasons_filter_returns_empty_when_no_match(tmp_path: Path) -> None:
    service = RetrievalService(
        persist_directory=tmp_path / "chroma_filter_nomatch",
        collection_name="filter_nomatch_jobs",
    )

    hits = service.search_with_reasons(
        "engineer", filters={"location": "Auckland"}
    )

    assert hits == []


def test_reasoned_hit_preserves_structured_metadata(tmp_path: Path) -> None:
    custom_payload = """
[
  {
    "type": "job_posting",
    "title": "Structured Metadata Role",
    "snippet": "Backend intern role with FastAPI and SQL.",
    "company": "USYD CareerHub Partner",
    "location": "Sydney",
    "work_type": "intern",
    "posted_at": "2026-04-01",
    "url": "https://usyd-careerhub.internal/job/structured-role",
    "tags": ["backend", "python", "fastapi"]
  }
]
""".strip()
    custom_file = tmp_path / "structured_jobs.json"
    custom_file.write_text(custom_payload, encoding="utf-8")

    original = settings.job_postings_file
    settings.job_postings_file = str(custom_file)
    try:
        service = RetrievalService(
            persist_directory=tmp_path / "chroma_structured_hit",
            collection_name="structured_hit_jobs",
        )
    finally:
        settings.job_postings_file = original

    hit = service.search_with_reasons("backend fastapi intern")[0]
    assert hit.company == "USYD CareerHub Partner"
    assert hit.location == "Sydney"
    assert hit.work_type == "intern"
    assert hit.posted_at == "2026-04-01"
    assert hit.url == "https://usyd-careerhub.internal/job/structured-role"
    assert hit.tags == ["backend", "python", "fastapi"]
