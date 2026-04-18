# Career Agent

Backend-first scaffold for a job coaching Agent application.

## Run

```bash
python3 -m uvicorn app.main:app --reload
```

After the server starts:

- API docs: `http://127.0.0.1:8000/docs`
- Stage B demo page: `http://127.0.0.1:8000/demo/`

## Demo

The demo is a single static page served by FastAPI itself. It only depends on the
current `POST /chat` contract and renders:

- `answer`
- `plan`
- `sources`
- `tool_trace`
- `llm_trace`

Default demo flow:

1. Open `http://127.0.0.1:8000/demo/`
2. Use any `user_id`
3. Try messages like:
   - `帮我找一些 Python backend 岗位`
   - `结合我的情况推荐适合投的岗位`
   - `我适合投哪些岗位`

## Environment

Configure an OpenAI-compatible provider through environment variables:

```bash
export OPENAI_API_KEY="your_api_key"
export OPENAI_BASE_URL="https://your-compatible-provider/v1"
export DEFAULT_MODEL="your_model_name"
```

Planner and job-search summarizer can also use a dedicated compatible endpoint:

```bash
export PLANNER_API_KEY="your_api_key"
export PLANNER_BASE_URL="https://your-compatible-provider/v1"
export PLANNER_MODEL="your_model_name"
```

If these variables are missing, the project falls back to deterministic local behavior
for planning and job-search summarization.

## Test

Focused Stage B verification:

```bash
python3 -m pytest tests/test_stage_b_contracts.py tests/test_retrieval_service.py tests/test_tools.py tests/test_app.py tests/test_agent_service.py tests/test_llm_client.py -q
```

Full suite without live model dependencies:

```bash
env -u OPENAI_API_KEY -u OPENAI_BASE_URL -u DEFAULT_MODEL -u PLANNER_API_KEY -u PLANNER_BASE_URL -u PLANNER_MODEL python3 -m pytest -q
```
