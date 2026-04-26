# Evals

Lightweight quality harness for the Stage B `/chat` contract. Independent from
unit tests: this is an opinionated baseline for answer quality and routing
behavior, not a hard gate.

## How to run

1. Start with a clean local state (recommended, so seeds don't collide with
   previous runs):

   ```bash
   rm -f data/*.db
   rm -rf data/chroma
   ```

2. Start the server:

   ```bash
   python3 -m uvicorn app.main:app --reload
   ```

3. In another terminal, run the harness:

   ```bash
   python3 evals/run_eval.py
   ```

   Useful flags:

   - `--base-url http://127.0.0.1:8000` (default)
   - `--dataset evals/dataset.jsonl` (default)
   - `--out-dir evals/reports` (default)
   - `--fail-threshold 0.8` (default; exit 1 if pass_rate is below)

4. Read the report:

   - `evals/reports/latest.md` (human-readable)
   - `evals/reports/latest.json` (machine-readable)

## Dataset format (`dataset.jsonl`)

One JSON object per line. Top-level fields:

- `id`: unique case id
- `user_id`: passed into `/chat`
- `message`: user input
- `seed` (optional): data to create before calling `/chat`
  - `candidates`: `[{"name": str, "user_id": str}]`
  - `resumes`: `[{"user_id": str, "title": str, "content": str, "version": str}]`
    — resolved to `candidate_id` by matching `user_id` from `seed.candidates`
  - `jobs`: `[{"title": str}]`
  - `applications`: `[{"user_id": str, "company": str, "job_title": str,
    "status": str, "note": str}]` — resolved to `candidate_id` by matching
    `user_id` from `seed.candidates`
  - `interviews`: `[{"user_id": str, "company": str, "job_title": str,
    "interview_round": str, "result": str, "feedback": str}]` — resolved to
    `candidate_id` by matching `user_id` from `seed.candidates`
  - `warmup_messages`: `[str]` — each posted to `/chat` before the main message
- `expect`: checks applied to the `/chat` response. Supported keys:
  - `plan_task_type`: string or list of allowed strings
  - `planner_source`: string or list
  - `plan_needs_more_context`: bool
  - `plan_missing_context_contains`: list of required substrings in
    `plan.missing_context`
  - `tool_trace_prefix`: list, matches the beginning of `tool_trace`
  - `tool_trace_equals`: list, exact match
  - `sources_nonempty` / `sources_empty`: bool
  - `source_type`: every source must be this type
  - `source_types_include`: required source types across all sources
  - `source_snippet_contains_any`: at least one snippet contains one of these
  - `source_field_contains`: object like
    `{"field": "location", "any": ["Sydney", "USYD"]}`
  - `llm_trace_allowed`: mapping of `llm_trace.<field>` -> allowed values
  - `answer_contains_any`: answer must include at least one of these
  - `answer_contains_all`: answer must include every listed string
  - `answer_not_contains`: answer must include none of these

## Philosophy

- **Soft assertions**: we check behavior, not exact strings. Wording may drift
  between LLM calls and fallbacks; the contract should not.
- **Not a CI gate**: run manually before risky changes, compare reports.
- **Reproducible seeds**: each case is self-contained. Start from a clean DB to
  avoid cross-case leakage (especially for the "missing resume" case, which
  depends on per-user ownership).

## Reports

`evals/reports/latest.md` and `latest.json` are regenerated on every run.
They are gitignored by default; only this README and the dataset are tracked.
