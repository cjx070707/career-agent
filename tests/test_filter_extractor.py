"""Unit tests for the query slot extractor.

Stage B contract: the extractor is a pure function that turns a free-form
user message into structured retrieval filters (location / work_type) that
the `search_jobs` tool can forward to the retrieval layer. Router does not
call the planner; the extractor is router-side logic.
"""

from app.routing.filter_extractor import extract_filters


def test_extract_filters_returns_empty_when_no_signal() -> None:
    assert extract_filters("帮我找一些岗位") == {}
    assert extract_filters("what about backend roles") == {}


def test_extract_filters_detects_sydney_en_and_zh() -> None:
    assert extract_filters("帮我找 Sydney 的 intern") == {
        "location": "Sydney",
        "work_type": "intern",
    }
    assert extract_filters("悉尼有哪些后端实习") == {
        "location": "Sydney",
        "work_type": "intern",
    }


def test_extract_filters_detects_melbourne_and_remote() -> None:
    assert extract_filters("Melbourne fulltime roles") == {
        "location": "Melbourne",
        "work_type": "fulltime",
    }
    assert extract_filters("墨尔本的兼职岗") == {
        "location": "Melbourne",
        "work_type": "parttime",
    }
    assert extract_filters("remote data analyst intern") == {
        "location": "Remote (AU)",
        "work_type": "intern",
    }


def test_extract_filters_detects_graduate_variants() -> None:
    assert extract_filters("Sydney graduate program") == {
        "location": "Sydney",
        "work_type": "graduate",
    }
    assert extract_filters("Sydney 校招岗位") == {
        "location": "Sydney",
        "work_type": "graduate",
    }
    assert extract_filters("应届 data 岗位") == {"work_type": "graduate"}


def test_extract_filters_work_type_priority_picks_intern_over_graduate() -> None:
    # When both intern and graduate keywords appear, pick the one the user
    # emphasised by listing it first in the message.
    assert extract_filters("intern 或 graduate 都可以") == {"work_type": "intern"}
    assert extract_filters("graduate 或 intern 都可以") == {"work_type": "graduate"}


def test_extract_filters_is_case_insensitive_for_english() -> None:
    assert extract_filters("SYDNEY FULL-TIME ROLES") == {
        "location": "Sydney",
        "work_type": "fulltime",
    }


def test_extract_filters_location_only_when_work_type_missing() -> None:
    assert extract_filters("Sydney 附近有什么 data 岗") == {"location": "Sydney"}


def test_extract_filters_work_type_only_when_location_missing() -> None:
    assert extract_filters("有哪些 data analyst intern") == {"work_type": "intern"}
