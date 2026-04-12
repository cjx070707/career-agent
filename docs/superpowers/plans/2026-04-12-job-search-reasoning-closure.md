# Job Search Reasoning Closure Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Build a stable `岗位搜索 + 推荐理由` closure where `search_jobs` returns structured reasons and `/chat` turns those reasons into a concise, grounded recommendation.

**Architecture:** Keep planner behavior unchanged for now. Strengthen the `search_jobs` path only: retrieval computes matched terms and a deterministic reason, the tool returns a stable contract, and `AgentService` uses a job-search-specific LLM summarizer with a deterministic fallback. This gives one strong demo path without expanding workflow-style branching.

**Tech Stack:** FastAPI, SQLite, ChromaDB, Pydantic, pytest, OpenAI-compatible chat completions

---

## File Structure

- Modify: `app/services/retrieval_service.py`
  - Add a reason-building helper for ranked job hits.
  - Expose a `search_with_reasons()` method that returns stable structured search results for tool use.
- Modify: `app/tools/job_tools.py`
  - Return `matched_terms` and `reason` for each `search_jobs` result.
- Modify: `app/llm/prompts.py`
  - Add a dedicated prompt for job-search summarization.
- Modify: `app/llm/client.py`
  - Add `summarize_job_search()` plus deterministic fallback.
- Modify: `app/services/agent_service.py`
  - Route `search_jobs` results through the new summarizer instead of title-only formatting.
- Modify: `tests/test_retrieval_service.py`
  - Cover retrieval explanations.
- Modify: `tests/test_tools.py`
  - Cover `search_jobs` tool contract.
- Modify: `tests/test_llm_client.py`
  - Cover job-search summarizer model path and fallback path.
- Modify: `tests/test_agent_service.py`
  - Cover `/chat` search path using structured reasons and summarization.

### Task 1: Stabilize `search_jobs` Result Contract

**Files:**
- Modify: `app/services/retrieval_service.py`
- Modify: `app/tools/job_tools.py`
- Test: `tests/test_retrieval_service.py`
- Test: `tests/test_tools.py`

- [ ] **Step 1: Write the failing retrieval explanation test**

```python
def test_retrieval_service_search_with_reasons_includes_matched_terms(tmp_path: Path) -> None:
    service = RetrievalService(
        persist_directory=tmp_path / "chroma_reason",
        collection_name="reason_jobs",
    )

    results = service.search_with_reasons("python fastapi backend")

    assert results
    top_hit = results[0]
    assert top_hit["title"] == "Backend Engineer Intern"
    assert set(top_hit["matched_terms"]) >= {"python", "fastapi", "backend"}
    assert "命中关键词" in top_hit["reason"]
```

- [ ] **Step 2: Run the retrieval test to verify it fails**

Run: `python3 -m pytest tests/test_retrieval_service.py::test_retrieval_service_search_with_reasons_includes_matched_terms -v`

Expected: FAIL with `AttributeError: 'RetrievalService' object has no attribute 'search_with_reasons'`

- [ ] **Step 3: Implement `search_with_reasons()` in `app/services/retrieval_service.py`**

```python
def search_with_reasons(self, query: str) -> list[dict[str, object]]:
    results = self.search(query)
    return [self._to_reasoned_hit(query, result) for result in results]

def _to_reasoned_hit(self, query: str, result: RetrievalResult) -> dict[str, object]:
    matched_terms = sorted(
        (self._tokenize(query) & self._tokenize(f"{result.title} {result.snippet}"))
        - {"job", "jobs", "role", "roles", "engineer", "intern"}
    )
    reason = (
        f"命中关键词：{', '.join(matched_terms[:3])}。"
        if matched_terms
        else "与查询语义相近，并且标题与摘要相关。"
    )
    return {
        "type": result.type,
        "title": result.title,
        "snippet": result.snippet,
        "matched_terms": matched_terms[:5],
        "reason": reason,
    }
```

- [ ] **Step 4: Run the retrieval test to verify it passes**

Run: `python3 -m pytest tests/test_retrieval_service.py::test_retrieval_service_search_with_reasons_includes_matched_terms -v`

Expected: PASS

- [ ] **Step 5: Write the failing tool contract test**

```python
def test_search_jobs_tool_returns_reasoned_results(isolated_runtime) -> None:
    JobService().create_job(title="Python FastAPI Backend Engineer")
    registry = build_default_tool_registry()

    result = registry.run("search_jobs", {"query": "python fastapi backend"})

    assert result["ok"] is True
    top_hit = result["data"][0]
    assert top_hit["title"] == "Python FastAPI Backend Engineer"
    assert "matched_terms" in top_hit
    assert "reason" in top_hit
    assert "python" in top_hit["matched_terms"]
```

- [ ] **Step 6: Run the tool test to verify it fails**

Run: `python3 -m pytest tests/test_tools.py::test_search_jobs_tool_returns_reasoned_results -v`

Expected: FAIL because the returned dict only contains `type`, `title`, and `snippet`

- [ ] **Step 7: Update `app/tools/job_tools.py` to use `search_with_reasons()`**

```python
def build_job_tools() -> list[ToolDefinition]:
    retrieval_service = RetrievalService()
    return [
        ToolDefinition(
            name="search_jobs",
            description="Search jobs using a natural language query.",
            input_model=SearchJobsToolInput,
            handler=lambda payload: retrieval_service.search_with_reasons(payload.query),
        )
    ]
```

- [ ] **Step 8: Run the tool tests to verify the contract**

Run: `python3 -m pytest tests/test_tools.py::test_search_jobs_tool_returns_reasoned_results tests/test_tools.py::test_search_jobs_and_match_tools_return_structured_results -v`

Expected: PASS

### Task 2: Add a Dedicated Job-Search Summarizer to `LLMClient`

**Files:**
- Modify: `app/llm/prompts.py`
- Modify: `app/llm/client.py`
- Test: `tests/test_llm_client.py`

- [ ] **Step 1: Write the failing summarizer model-path test**

```python
def test_summarize_job_search_uses_chat_completions_when_configured(isolated_runtime, monkeypatch) -> None:
    monkeypatch.setattr(settings, "openai_api_key", "sk-test-key")
    monkeypatch.setattr(settings, "openai_base_url", "https://api.test/v1")

    class Stub(LLMClient):
        def _post_responses(self, url, api_key=None, payload=None, **kwargs):
            assert url.endswith("/chat/completions")
            assert "job search" in payload["messages"][0]["content"].lower()
            return {"choices": [{"message": {"content": "推荐 3 个岗位，其中第一个最贴近 Python FastAPI 背景。"}}]}

    client = Stub()
    out = client.summarize_job_search(
        message="帮我找 Python backend 岗位",
        memory_context=["想找后端岗位"],
        jobs=[
            {
                "title": "Python FastAPI Backend Engineer",
                "snippet": "Build backend APIs with Python and FastAPI.",
                "matched_terms": ["python", "fastapi", "backend"],
                "reason": "命中关键词：python, fastapi, backend。",
            }
        ],
    )

    assert "Python FastAPI" in out
```

- [ ] **Step 2: Run the summarizer test to verify it fails**

Run: `python3 -m pytest tests/test_llm_client.py::test_summarize_job_search_uses_chat_completions_when_configured -v`

Expected: FAIL with `AttributeError: 'LLMClient' object has no attribute 'summarize_job_search'`

- [ ] **Step 3: Add a dedicated prompt in `app/llm/prompts.py`**

```python
JOB_SEARCH_SUMMARY_PROMPT = (
    "You summarize job search results for a career agent. "
    "Answer in the same language as the user. "
    "Use the provided matched terms and reasons. "
    "Mention the top 1-3 jobs only. "
    "Do not invent evidence that is not present."
)
```

- [ ] **Step 4: Implement `summarize_job_search()` and fallback in `app/llm/client.py`**

```python
def summarize_job_search(
    self,
    message: str,
    memory_context: list[str],
    jobs: list[dict[str, object]],
) -> str:
    if self.is_configured():
        try:
            payload = {
                "model": self.model,
                "messages": [
                    {"role": "system", "content": JOB_SEARCH_SUMMARY_PROMPT},
                    {
                        "role": "user",
                        "content": json.dumps(
                            {
                                "message": message,
                                "memory_context": memory_context,
                                "jobs": jobs[:3],
                            },
                            ensure_ascii=False,
                        ),
                    },
                ],
            }
            chat_payload = self._post_responses(
                self._chat_completions_url(),
                api_key=settings.openai_api_key,
                payload=payload,
                timeout=45.0,
            )
            return self._extract_chat_completion_text(chat_payload).strip()
        except (ValueError, httpx.HTTPError, RuntimeError):
            pass
    return self._fallback_job_search_summary(jobs)

def _fallback_job_search_summary(self, jobs: list[dict[str, object]]) -> str:
    if not jobs:
        return "我暂时没有找到相关岗位。"
    top_jobs = jobs[:3]
    parts = [
        f"{job['title']}（{job['reason']}）"
        for job in top_jobs
    ]
    return "我找到这些较相关的岗位：" + "；".join(parts) + "。"
```

- [ ] **Step 5: Run the summarizer model-path test to verify it passes**

Run: `python3 -m pytest tests/test_llm_client.py::test_summarize_job_search_uses_chat_completions_when_configured -v`

Expected: PASS

- [ ] **Step 6: Write the failing fallback test**

```python
def test_summarize_job_search_falls_back_to_structured_text(isolated_runtime, monkeypatch) -> None:
    monkeypatch.setattr(settings, "openai_api_key", "sk-test-key")

    class Boom(LLMClient):
        def _post_responses(self, *args, **kwargs):
            raise ValueError("boom")

    client = Boom()
    out = client.summarize_job_search(
        message="帮我找岗位",
        memory_context=[],
        jobs=[
            {
                "title": "Backend Engineer Intern",
                "snippet": "Python FastAPI APIs",
                "matched_terms": ["backend", "python"],
                "reason": "命中关键词：backend, python。",
            }
        ],
    )

    assert "Backend Engineer Intern" in out
    assert "命中关键词" in out
```

- [ ] **Step 7: Run the fallback test to verify it passes**

Run: `python3 -m pytest tests/test_llm_client.py::test_summarize_job_search_falls_back_to_structured_text -v`

Expected: PASS

### Task 3: Route `search_jobs` Answers Through the Summarizer

**Files:**
- Modify: `app/services/agent_service.py`
- Test: `tests/test_agent_service.py`

- [ ] **Step 1: Write the failing agent-service integration test**

```python
class SearchSummaryLLMClient:
    def __init__(self) -> None:
        self.plan_called = False
        self.summary_jobs = None

    def generate_plan(self, **kwargs):
        self.plan_called = True
        return {
            "task_type": "job_search",
            "reason": "planned by fake llm",
            "steps": ["search_jobs"],
            "needs_more_context": False,
            "missing_context": [],
            "follow_up_question": None,
        }

    def summarize_job_search(self, message, memory_context, jobs):
        self.summary_jobs = jobs
        return "这是整理后的岗位推荐。"

def test_agent_service_uses_job_search_summary_for_search_results(isolated_runtime) -> None:
    fake_llm = SearchSummaryLLMClient()
    CandidateService().create_candidate(name="Planner User")
    JobService().create_job(title="Python FastAPI Backend Engineer")
    service = AgentService(llm_client=fake_llm)

    result = service.respond("planner-user", "帮我找一些 Python backend 岗位")

    assert fake_llm.plan_called is True
    assert fake_llm.summary_jobs is not None
    assert result.answer == "这是整理后的岗位推荐。"
    assert result.sources[0].title == "Python FastAPI Backend Engineer"
```

- [ ] **Step 2: Run the integration test to verify it fails**

Run: `python3 -m pytest tests/test_agent_service.py::test_agent_service_uses_job_search_summary_for_search_results -v`

Expected: FAIL because `AgentService` still uses the title-only `search_jobs` formatter

- [ ] **Step 3: Update `app/services/agent_service.py` to special-case `search_jobs` synthesis**

```python
if plan.steps:
    tool_trace, execution_state = self._execute_plan(user_id, message, plan.steps)
    final_tool_name = tool_trace[-1] if tool_trace else None
    final_result = execution_state.get("last_result")

    if final_tool_name == "search_jobs":
        answer = self.llm_client.summarize_job_search(
            message=message,
            memory_context=[turn.content for turn in recent_turns],
            jobs=final_result or [],
        )
    else:
        answer = self._format_tool_answer(final_tool_name, final_result)
```

- [ ] **Step 4: Keep `_extract_sources()` unchanged and simplify `_format_tool_answer()`**

```python
if tool_name == "search_jobs":
    if not tool_result:
        return "我暂时没有找到相关岗位。"
    return "岗位搜索已完成。"
```

- [ ] **Step 5: Run the agent-service integration test to verify it passes**

Run: `python3 -m pytest tests/test_agent_service.py::test_agent_service_uses_job_search_summary_for_search_results -v`

Expected: PASS

### Task 4: Run the Focused Regression Suite for the Search Closure

**Files:**
- Test: `tests/test_retrieval_service.py`
- Test: `tests/test_tools.py`
- Test: `tests/test_llm_client.py`
- Test: `tests/test_agent_service.py`

- [ ] **Step 1: Run the focused regression suite**

Run: `python3 -m pytest tests/test_retrieval_service.py tests/test_tools.py tests/test_llm_client.py tests/test_agent_service.py -v`

Expected: PASS for all tests

- [ ] **Step 2: Manual verification against `/chat`**

Run:

```bash
python3 -m uvicorn app.main:app --reload
```

Then send a request such as:

```bash
curl -X POST http://127.0.0.1:8000/chat \
  -H "Content-Type: application/json" \
  -d '{"user_id":"demo-user","message":"帮我找一些 Python backend 岗位"}'
```

Expected response characteristics:

- `plan.task_type` is `job_search`
- `tool_trace` includes `search_jobs`
- `sources` includes at least one relevant job
- `answer` contains a recommendation sentence, not only a comma-separated title list

- [ ] **Step 3: Checkpoint the work**

If this directory is later initialized as a git repo, use:

```bash
git add app/services/retrieval_service.py app/tools/job_tools.py app/llm/prompts.py app/llm/client.py app/services/agent_service.py tests/test_retrieval_service.py tests/test_tools.py tests/test_llm_client.py tests/test_agent_service.py docs/superpowers/plans/2026-04-12-job-search-reasoning-closure.md
git commit -m "feat: close the job search recommendation loop"
```

## Self-Review

- Spec coverage: this plan covers one and only one closure, `岗位搜索 + 推荐理由`
- Placeholder scan: no `TODO` / `TBD` / “similar to above” shortcuts remain
- Type consistency: the plan uses the same names throughout: `search_with_reasons`, `matched_terms`, `reason`, `summarize_job_search`

## Execution Handoff

Plan complete and saved to `docs/superpowers/plans/2026-04-12-job-search-reasoning-closure.md`. Two execution options:

1. **Subagent-Driven (recommended)** - I dispatch a fresh subagent per task, review between tasks, fast iteration
2. **Inline Execution** - Execute tasks in this session using executing-plans, batch execution with checkpoints

Which approach?
