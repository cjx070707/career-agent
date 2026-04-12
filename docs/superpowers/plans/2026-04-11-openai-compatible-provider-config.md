# OpenAI Compatible Provider Config Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Wire the planner client to read OpenAI-compatible provider configuration from environment variables so the project can call a real provider such as SiliconFlow + Kimi.

**Architecture:** Keep the planner flow unchanged and only add provider configuration support. The client should read `OPENAI_API_KEY`, `OPENAI_BASE_URL`, and `DEFAULT_MODEL`, then send planner requests to the configured compatible endpoint.

**Tech Stack:** Python, httpx, pytest

---

### Task 1: Add failing tests for provider config usage

**Files:**
- Modify: `tests/test_llm_client.py`

- [ ] **Step 1: Write the failing test**

```python
assert request_url == "https://example.com/v1/responses"
```

- [ ] **Step 2: Run test to verify it fails**

Run: `python3 -m pytest tests/test_llm_client.py::test_generate_plan_uses_configured_base_url -v`
Expected: FAIL because the client still hardcodes the OpenAI URL.

- [ ] **Step 3: Write minimal implementation**

```python
response = httpx.post(f"{settings.openai_base_url}/responses", ...)
```

- [ ] **Step 4: Run test to verify it passes**

Run: `python3 -m pytest tests/test_llm_client.py::test_generate_plan_uses_configured_base_url -v`
Expected: PASS

### Task 2: Document compatible provider environment setup

**Files:**
- Modify: `app/env.py`
- Modify: `.env.example`
- Modify: `README.md`

- [ ] **Step 1: Keep the same tests as driver**

- [ ] **Step 2: Run planner-focused regression**

Run: `python3 -m pytest tests/test_llm_client.py tests/test_agent_service.py tests/test_app.py -v`
Expected: PASS
