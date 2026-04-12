# Career Agent Backend Design

## Goal

Build a backend-first scaffold for the Career Agent MVP using the agreed top-level structure under `app/`, with clear seams for API routes, services, LLM integration, database wiring, and future MCP expansion.

## Scope

This design covers only the backend foundation:

- FastAPI application entrypoint
- Minimal route layer for health, chat, candidates, and jobs
- Service layer placeholders for agent orchestration, memory, and retrieval
- LLM client and prompt placeholders
- Database base/session placeholders
- Environment/config bootstrap
- README, requirements, and tests

Frontend scaffolding is intentionally deferred.

## Architecture

The backend uses a thin route layer and a focused service layer. Routes own request/response handling. Services own application behavior. Database and LLM concerns are isolated so the MVP can evolve without rewriting the app entrypoint.

`mcp_server.py` is included as a placeholder to preserve the long-term architecture, but it is not the runtime entrypoint for the MVP.

## Directory Structure

```text
app/
  api/
  db/
  llm/
  schemas/
  services/
  __init__.py
  env.py
  main.py
  mcp_server.py
```

## Responsibilities

- `app/api`: FastAPI routers only
- `app/db`: database base path and session helpers
- `app/llm`: model client wrapper and prompt constants
- `app/schemas`: Pydantic schemas for chat, candidate, and job payloads
- `app/services`: backend business logic and Agent-oriented orchestration
- `app/env.py`: settings loader
- `app/main.py`: app factory and router registration
- `app/mcp_server.py`: placeholder entrypoint for future MCP-compatible tool serving

## Initial Behavior

- `GET /health` returns service status
- `POST /chat` returns a mocked Agent response through `AgentService`
- `GET /candidates` returns an empty list placeholder
- `GET /jobs` returns an empty list placeholder

## Testing

The first tests verify:

- FastAPI app can be imported
- health endpoint responds successfully
- chat endpoint returns the mocked Agent response shape

## Notes

- No production business logic is implemented yet
- No real database writes are required in this scaffold
- No real OpenAI calls are made in this scaffold
