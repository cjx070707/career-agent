from evals.run_eval import _apply_eval_source_mock


def test_eval_harness_injects_sources_when_enabled_and_missing(monkeypatch) -> None:
    monkeypatch.setenv("EVAL_USE_ADZUNA_MOCK", "1")
    body = {
        "tool_trace": ["search_jobs"],
        "sources": [],
    }
    expect = {
        "sources_nonempty": True,
        "source_field_contains": {"field": "location", "any": ["Sydney"]},
    }

    patched = _apply_eval_source_mock(body, expect)

    assert patched["sources"]
    assert "Sydney" in patched["sources"][0]["location"]

