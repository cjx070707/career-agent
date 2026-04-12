# Career Agent Backend Scaffold Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Build a backend-first FastAPI scaffold for the Career Agent MVP under the agreed `app/` structure.

**Architecture:** The backend starts with a thin routing layer, lightweight service placeholders, and isolated LLM and database modules. The scaffold is intentionally minimal but runnable so future Agent, memory, retrieval, and MCP work can land without restructuring.

**Tech Stack:** Python, FastAPI, Pydantic, pytest, httpx

---

### Task 1: Add scaffold tests

**Files:**
- Create: `tests/test_app.py`

- [ ] **Step 1: Write the failing test**

```python
from fastapi.testclient import TestClient

from app.main import app


client = TestClient(app)


def test_health_endpoint_returns_ok():
    response = client.get("/health")

    assert response.status_code == 200
    assert response.json() == {"status": "ok"}


def test_chat_endpoint_returns_mock_agent_response():
    response = client.post("/chat", json={"message": "hello"})

    assert response.status_code == 200
    assert response.json()["answer"] == "Career Agent backend scaffold is ready."
```

- [ ] **Step 2: Run test to verify it fails**

Run: `pytest tests/test_app.py -v`
Expected: FAIL because `app.main` does not exist yet.

- [ ] **Step 3: Write minimal implementation**

Create the FastAPI app, route modules, chat schema, and minimal `AgentService`.

- [ ] **Step 4: Run test to verify it passes**

Run: `pytest tests/test_app.py -v`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add tests/test_app.py app docs requirements.txt README.md
git commit -m "feat: scaffold career agent backend"
```

### Task 2: Add agreed backend structure placeholders

**Files:**
- Create: `app/__init__.py`
- Create: `app/api/__init__.py`
- Create: `app/api/health.py`
- Create: `app/api/chat.py`
- Create: `app/api/candidates.py`
- Create: `app/api/jobs.py`
- Create: `app/db/__init__.py`
- Create: `app/db/base.py`
- Create: `app/db/session.py`
- Create: `app/llm/__init__.py`
- Create: `app/llm/client.py`
- Create: `app/llm/prompts.py`
- Create: `app/schemas/__init__.py`
- Create: `app/schemas/chat.py`
- Create: `app/schemas/candidate.py`
- Create: `app/schemas/job.py`
- Create: `app/services/__init__.py`
- Create: `app/services/agent_service.py`
- Create: `app/services/memory_service.py`
- Create: `app/services/retrieval_service.py`
- Create: `app/env.py`
- Create: `app/main.py`
- Create: `app/mcp_server.py`
- Modify: `README.md`
- Modify: `requirements.txt`

- [ ] **Step 1: Implement placeholders with clear responsibilities**

Each file should contain only enough code to support imports, endpoint wiring, and future extension.

- [ ] **Step 2: Keep runtime behavior minimal**

Avoid real DB calls, real model calls, or premature MCP behavior.

- [ ] **Step 3: Verify the app imports and route registration**

Run: `pytest tests/test_app.py -v`
Expected: PASS

- [ ] **Step 4: Commit**

```bash
git add app README.md requirements.txt
git commit -m "chore: add backend module placeholders"
```

### Task 3: Move the PRD into docs

**Files:**
- Modify: `docs/prd-career-agent.md`

- [ ] **Step 1: Move the existing PRD into `docs/`**

Run: `mv prd-career-agent.md docs/prd-career-agent.md`

- [ ] **Step 2: Verify the file exists at the new path**

Run: `ls docs`
Expected: includes `prd-career-agent.md`

- [ ] **Step 3: Commit**

```bash
git add docs/prd-career-agent.md
git commit -m "docs: move career agent prd into docs"
```
