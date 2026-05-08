# Evals

两层质量评估体系，覆盖工具路由准确性和答案整体质量。详细策略见 [`docs/EVAL_STRATEGY.md`](../docs/EVAL_STRATEGY.md)。

---

## 层 1 — 工具路由 + 关键词检查（快速，< 2 min）

验证 agent 调了正确的工具、答案包含必要内容。适合每次 prompt 改动后快速回归。

### 运行

```bash
# 1. 干净 DB（避免 case 间状态污染）
rm -f data/*.db

# 2. 启动后端
.venv/bin/uvicorn app.main:app --port 8000

# 3. 跑 eval（标准模式）
python3 evals/run_eval.py

# 3b. CI 模式：用 mock 隔离 Adzuna 外部依赖（推荐）
EVAL_USE_ADZUNA_MOCK=1 python3 evals/run_eval.py

# 可选 flags
#   --base-url http://127.0.0.1:8000   (default)
#   --dataset  evals/dataset.jsonl     (default)
#   --out-dir  evals/reports           (default)
#   --fail-threshold 0.8               (default; pass_rate 低于此值 exit 1)
```

### 报告
- `evals/reports/latest.md`  — 人类可读
- `evals/reports/latest.json` — 机器可读

---

## 层 2 — LLM-as-Judge 质量评估（慢，需 API）

对每条 case 的答案让 LLM 打分，评估工具合理性、针对性、无幻觉、语气。  
适合大改动（system prompt 重写、新工具上线）前的质量基线检查。

### 评分维度

| 维度 | 满分 | 合格线 |
|------|------|--------|
| tool_appropriateness | 5 | ≥ 3.5 avg |
| answer_relevance | 5 | ≥ 3.5 avg |
| no_hallucination | 5 | **≥ 4**（单独门槛） |
| tone_fit | 5 | ≥ 3.5 avg |

### 运行

```bash
# OPENAI_API_KEY 需要设置（复用项目的 DashScope key）
export OPENAI_API_KEY=your_key
export OPENAI_BASE_URL=https://dashscope.aliyuncs.com/compatible-mode/v1

python3 evals/run_judge_eval.py

# 可选 flags
#   --judge-model qwen-plus            (default: env JUDGE_MODEL 或 qwen-plus)
#   --case-ids gap-no-resume chitchat-no-tool  (只跑指定 case)
#   --fail-threshold 0.75              (default)
```

### 报告
- `evals/reports/judge_latest.md`
- `evals/reports/judge_latest.json`

---

## Dataset 格式（`dataset.jsonl`）

每行一个 JSON object：

- `id`: 唯一 case id
- `user_id`: 传入 `/chat`
- `message`: 用户输入
- `seed`（可选）: 执行前预置数据
  - `candidates`: `[{"name": str, "user_id": str}]`
  - `resumes`: `[{"user_id": str, "title": str, "content": str, "version": str}]`
  - `jobs`: `[{"title": str}]`
  - `applications`: `[{"user_id": str, "company": str, "job_title": str, "status": str, "note": str}]`
  - `interviews`: `[{"user_id": str, "company": str, "job_title": str, "interview_round": str, "result": str, "feedback": str}]`
  - `warmup_messages`: `[str]` — 主消息前先发这些热身消息
- `expect`: 对 `/chat` 响应的断言
  - `tool_trace_prefix`: list，匹配 tool_trace 的开头
  - `tool_trace_equals`: list，精确匹配 tool_trace
  - `plan_task_type`: string 或 list
  - `planner_source`: string 或 list
  - `plan_needs_more_context`: bool
  - `plan_missing_context_contains`: 要求 plan.missing_context 包含这些子串
  - `sources_nonempty` / `sources_empty`: bool
  - `source_type`: 每个 source 必须是这个类型
  - `source_types_include`: 跨所有 source 必须包含的类型
  - `source_snippet_contains_any`: 至少一个 snippet 包含其中一项
  - `source_field_contains`: `{"field": "location", "any": ["Sydney"]}`
  - `source_field_all_contain`: `[{"field": "location", "any": ["Sydney"]}]`
  - `llm_trace_allowed`: `{llm_trace字段: 允许值列表}`
  - `answer_contains_any`: 答案必须包含其中至少一项
  - `answer_contains_all`: 答案必须包含全部
  - `answer_not_contains`: 答案不能包含任何一项

---

## 当前 Dataset 覆盖（37 cases）

| 场景 | ID 示例 | 层 |
|------|---------|-----|
| 岗位搜索（多种表达） | search-basic, search-chinese-only | 层 1 |
| 隐式 Sydney 过滤 | search-sydney-default-implicit | 层 1 |
| 精确过滤（city + work_type） | search-sydney-intern-filter | 层 1 |
| 无简历时求匹配 | missing-resume | 层 1 |
| 带简历推荐（含完整 match 链路） | recommend-with-resume | 层 1 |
| Career insights | career-insights-actionable | 层 1 |
| 闲聊 fallback | fallback-general | 层 1 |
| 灰色地带（模糊意图） | gray-career-plan, gray-compound-search-match | 层 1 |
| Gap 分析（无简历） | gap-no-resume | 层 1 + 2 |
| Gap 分析（有简历） | gap-with-resume | 层 1 + 2 |
| 纯闲聊不调工具 | chitchat-no-tool | 层 1 + 2 |
| 目标设定 | goal-set-flow | 层 1 + 2 |
| 多轮对话 | multi-goal-then-query, multi-log-progress 等 | 层 1 |
| 简历/申请/面试查询 | resume-direct-query, application-status-query | 层 1 |
| 负向 case | negative-unrelated-code, negative-non-sydney 等 | 层 1 |

**基线**（2026-05-05）：30/37 pass，pass_rate = 81%

---

## 原则

- **软断言**：检查行为契约，不检查精确措辞（措辞随 LLM 版本漂移）
- **非 CI 强制门**：手动在重要改动前跑，对比前后报告
- **状态隔离**：每次完整 eval 从干净 DB 启动，避免 case 间状态污染
- **Judge 不稳定性**：LLM-as-judge 有随机性，边界 case 建议多跑几次取平均
