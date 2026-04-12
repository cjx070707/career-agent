# Dotenv Support Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Let the project load local `.env` values for OpenAI-compatible provider settings without adding a new dependency.

**Architecture:** Keep `Settings` as the single config entry and add a tiny `.env` loader in `app/env.py`. Load `.env` from the project root, merge it with process env, and keep process env taking precedence.

**Tech Stack:** Python, pytest, pydantic

---

### Task 1: Add failing tests for `.env` loading

**Files:**
- Create: `tests/test_env.py`

- [ ] **Step 1: Write the failing test**

```python
assert settings.openai_api_key == "from-dotenv"
```

- [ ] **Step 2: Run test to verify it fails**

Run: `python3 -m pytest tests/test_env.py -v`
Expected: FAIL because `.env` values are not loaded yet.

- [ ] **Step 3: Write minimal implementation**

```python
def load_dotenv_values(...) -> dict[str, str]:
    ...
```

- [ ] **Step 4: Run test to verify it passes**

Run: `python3 -m pytest tests/test_env.py -v`
Expected: PASS

### Task 2: Run focused regression tests

**Files:**
- Modify: `app/env.py`
- Test: `tests/test_env.py`
- Test: `tests/test_llm_client.py`

- [ ] **Step 1: Run regression tests**

Run: `python3 -m pytest tests/test_env.py tests/test_llm_client.py -v`
Expected: PASS
