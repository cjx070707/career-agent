# Career Agent

Backend-first scaffold for a job coaching Agent application.

## Run

```bash
python3 -m uvicorn app.main:app --reload
```

After the server starts:

- API docs: `http://127.0.0.1:8000/docs`
- Stage B demo page: `http://127.0.0.1:8000/demo/`

## React Web App

The React app lives in `web/` and provides two product views over the existing
`POST /chat` contract:

- `Chat`: continuous conversation with answer, sources, plan, and trace panels
- `Query`: single-task workspace for job search, career diagnosis, and history checks

Run it in development with the FastAPI server running on port 8000:

```bash
cd web
npm install
npm run dev
```

Vite serves the app on `http://127.0.0.1:5173` and proxies `/chat` to FastAPI.

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

- `contract_version`: `"chat.v1"`, stable response contract identifier
- `answer`: string, the final user-facing reply
- `memory_used`: boolean, whether any prior turn influenced this reply
- `tool_used`: string | null, the last tool that produced `answer`
- `tool_trace`: string[], ordered names of tools that actually ran
- `sources[]`: list of grounded evidence items
  - `type`: string, e.g. `"job_posting"`, `"application"`, or `"interview_feedback"`
  - `title`: string
  - `snippet`: string, evidence text (for search, contains `命中关键词：...`)
  - `company`: string | null
  - `location`: string | null
  - `work_type`: string | null
  - `posted_at`: string | null
  - `url`: string | null
- `plan`: routed plan summary
  - `task_type`: one of `job_search`, `job_match`, `job_match_planning`,
    `candidate_profile`, `application_history`, `interview_history`,
    `career_insights`, `fallback`
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

### MCP-ready tool metadata

Tools are registered through `ToolRegistry` with Pydantic input schemas. The
registry can export MCP-ready metadata for each tool:

- `name`
- `description`
- `category`
- `input_schema`

This is an internal metadata/schema export for future thin MCP Server adaptation;
the project does not currently claim external MCP client support.

### Application Records API

`POST /applications` — create an application record:

- `candidate_id`: int, required
- `company`: string, required
- `job_title`: string, required
- `status`: string, required (e.g. `"applied"`, `"interviewing"`, `"offered"`, `"rejected"`)
- `note`: string, optional

`GET /applications?user_id={id}&limit={n}` — list applications for a user.

`PATCH /applications/{application_id}` — update status and/or note.

The `get_applications` tool is automatically invoked when the user asks about their
application history (e.g. "我最近投了哪些岗位？"). Results appear in `sources[]` with
`type="application"`.

### Interview Records API

`POST /interviews` — create an interview feedback record:

- `candidate_id`: int, required
- `company`: string, required
- `job_title`: string, required
- `interview_round`: string, required (e.g. `"hr"`, `"oa"`, `"tech1"`, `"final"`)
- `result`: string, required (e.g. `"pending"`, `"passed"`, `"rejected"`)
- `feedback`: string, optional

`GET /interviews?user_id={id}&limit={n}` — list recent interview feedback for a user.

`PATCH /interviews/{interview_id}` — update result and optionally feedback.

The `get_interview_feedback` tool is automatically invoked when the user asks about
recent interview feedback (e.g. "我最近面试反馈怎么样？"). Results appear in
`sources[]` with `type="interview_feedback"`.

### Vision Resume Image API (MVP)

`POST /vision/resume-image` — parse one resume screenshot/image into structured JSON:

- multipart file field: `file`
- accepted types: `image/png`, `image/jpeg`, `image/webp`
- max file size: 5MB

Current MVP scope:

- only supports resume image parsing
- parsed result can be saved into existing `resumes` table via `POST /vision/resume-image/save`
- save requires an existing candidate resolved by `user_id`
- save endpoint does not re-run vision parsing
- no image persistence
- no automatic candidate/resume creation
- no `/chat` agent integration

`POST /vision/resume-image/save` request body:

- `user_id`: string, required
- `parsed`: parsed resume JSON from `/vision/resume-image`
- `title`: string, optional (defaults to `"Resume parsed from image"`)
- `version`: string, optional (defaults to `"vision-v1"`)

### Career Insights Tool

The `get_career_insights` tool is automatically invoked when the user asks for a
career status diagnosis that combines profile, application, and interview signals
(e.g. "结合我的投递和面试反馈，我下一步该准备什么？").

The tool refreshes persisted long-term profile fields and returns an aggregation of:

- `profile`: target role, skill keywords, and focus notes
- `application_summary`: recent application records and status counts
- `interview_summary`: recent interview records, result counts, and feedback highlights
- `suggestions`: deterministic next-step suggestions derived from the available data

The refreshed `career_profiles` fields include:

- `application_patterns`
- `interview_weaknesses`
- `next_focus_areas`

After refresh, the career profile summary is indexed into retrieval as a
`career_profile` source so later answers can cite profile evidence.
Structured application and interview records are also synced into `career_events`
and indexed as `career_event` sources.
When planner LLM credentials are configured, concrete career events mentioned in
free-text chat messages are extracted into the same `career_events` store and
indexed as `career_event` retrieval evidence; extraction failures degrade to no-op.

### search_jobs tool payload

`search_jobs` uses hybrid retrieval: ChromaDB vector recall is combined with
BM25 lexical recall through Reciprocal Rank Fusion (RRF), then the existing
rerank and structured filters are applied.

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

Vision resume parsing can use a dedicated model/endpoint (falls back to planner settings if unset):

```bash
export VISION_MODEL="qwen3-vl-flash-2026-01-22"
export VISION_API_KEY="your_api_key"
export VISION_BASE_URL="https://your-compatible-provider/v1"
```

If these variables are missing, the project falls back to deterministic local behavior
for planning and job-search summarization.

## Test

Full suite without live model dependencies:

```bash
env -u OPENAI_API_KEY -u OPENAI_BASE_URL -u DEFAULT_MODEL -u PLANNER_API_KEY -u PLANNER_BASE_URL -u PLANNER_MODEL python3 -m pytest -q
```

Eval harness against a running server (19 cases, includes filter, career insights, and memory-isolation assertions):

```bash
python3 evals/run_eval.py --base-url http://127.0.0.1:8000
```

Frontend smoke test (Playwright, mocked `/chat`, no backend required):

```bash
cd web
npm run test:e2e
```
