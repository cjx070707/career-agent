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
3. Click one of the three preset example buttons above the message area, or type
   your own. Suggested starters:
   - `帮我找一些 Python backend 岗位`
   - `结合我的情况推荐适合投的岗位`
   - `我适合投哪些岗位`

## API Contract

The Stage B `/chat` contract is frozen at these fields. The demo only reads these.

`POST /chat` request body:

- `user_id`: string, required
- `message`: string, required

`POST /chat` response body (all fields always present):

- `answer`: string, the final user-facing reply
- `memory_used`: boolean, whether any prior turn influenced this reply
- `tool_used`: string | null, the last tool that produced `answer`
- `tool_trace`: string[], ordered names of tools that actually ran
- `sources[]`: list of grounded evidence items
  - `type`: string, e.g. `"job_posting"`
  - `title`: string
  - `snippet`: string, evidence text (for search, contains `命中关键词：...`)
  - `company`: string | null
  - `location`: string | null
  - `work_type`: string | null
  - `posted_at`: string | null
  - `url`: string | null
- `plan`: routed plan summary
  - `task_type`: one of `job_search`, `job_match`, `job_match_planning`,
    `candidate_profile`, `fallback`
  - `reason`: string, why this plan was chosen
  - `steps`: string[], planned tool names
  - `needs_more_context`: boolean
  - `missing_context`: string[]
  - `follow_up_question`: string | null
  - `planner_source`: `"router"` or `"model"` or `"fallback"`
- `llm_trace`: where each LLM-bearing step ended up running
  - `planner_source`: `"router"` / `"model"` / `"fallback"` / `"not_used"`
  - `job_search_summary_source`: `"model"` / `"fallback"` / `"not_used"`
  - `generate_source`: `"model"` / `"fallback"` / `"not_used"`

The `search_jobs` tool accepts:

- `query`: string, required — natural language search text
- `filters`: optional object — structured slots extracted from the user message
  - `location`: string | null (e.g. `"Sydney"`, `"Melbourne"`, `"Remote (AU)"`)
  - `work_type`: string | null (e.g. `"intern"`, `"graduate"`, `"fulltime"`, `"parttime"`)

When filters are present, the retrieval layer does a full-collection sweep and
applies case-insensitive substring matching on job metadata **after** reranking,
so results always satisfy the requested constraints.

### Application Records API

`POST /applications` — create an application record:

- `candidate_id`: int, required
- `company`: string, required
- `job_title`: string, required
- `status`: string, required (e.g. `"applied"`, `"interviewing"`, `"offered"`, `"rejected"`)
- `note`: string, optional

`GET /applications?candidate_id={id}&limit={n}` — list applications for a candidate.

`PATCH /applications/{application_id}` — update status and/or note.

The `get_applications` tool is automatically invoked when the user asks about their
application history (e.g. "我最近投了哪些岗位？"). Results appear in `sources[]` with
`type="application"`.

### search_jobs tool payload

The tool response payload (visible via `tool_trace` + `sources`) carries:

- `type`, `title`, `snippet`: same as source
- `company`, `location`, `work_type`, `posted_at`, `url`, `tags`: structured job metadata
- `matched_terms`: string[], lowercase key tokens that grounded the ranking
- `reason`: string, short Chinese justification mirrored into `sources[*].snippet`

## Job Dataset Ingestion

The local corpus is maintained in `data/job_postings.json` (JSON array) and can
be validated/re-written by:

```bash
python3 scripts/ingest_jobs.py --input data/job_postings.json --output data/job_postings.json
```

You can also pass a `.jsonl` input file; the script validates each row and
prints summary stats (`total`, `work_type`, `location`).

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

Full suite without live model dependencies:

```bash
env -u OPENAI_API_KEY -u OPENAI_BASE_URL -u DEFAULT_MODEL -u PLANNER_API_KEY -u PLANNER_BASE_URL -u PLANNER_MODEL python3 -m pytest -q
```

Eval harness against a running server (16 cases, includes filter constraint assertions):

```bash
python3 evals/run_eval.py --base-url http://127.0.0.1:8000
```
