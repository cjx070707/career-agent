# Career Agent

Backend-first scaffold for a job coaching Agent application.

## Run

```bash
python3 -m uvicorn app.main:app --reload
```

## Environment

Configure an OpenAI-compatible provider through environment variables:

```bash
export OPENAI_API_KEY="your_api_key"
export OPENAI_BASE_URL="https://your-compatible-provider/v1"
export DEFAULT_MODEL="your_model_name"
```

For example, this project can use any provider that supports an OpenAI-compatible
`/responses` endpoint.

## Test

```bash
python3 -m pytest tests/test_app.py -v
```
