# 项目现状 + 下一步计划

> 最后更新：2026-05-02
> 当前分支：main

---

## 一、已完成

### 核心 Agent 架构
- ✅ **真 ReAct function calling 循环**（`app/services/autonomous_agent_service.py`）
  LLM 看到所有工具 schema，自主决定调哪个工具、调几次、什么顺序。不是意图分类器，不是固定工具链。
- ✅ **ToolRegistry**（`app/tools/registry.py`）
  Pydantic 输入校验，统一 ToolResult 结构，11 个工具注册。
- ✅ **Hybrid RAG**（ChromaDB 向量 + BM25 + RRF 融合）
- ✅ **SSE 实时状态流 + Final answer token streaming**
  `🤔 正在思考` → `🔧 调用工具：xxx` → token by token 打字效果
- ✅ **Qwen-VL 简历图片解析**

### Memory（四层注入）
- ✅ **短期记忆**：SQLite 滚动 12 turns 原文
- ✅ **Goal 持久化**：`goals` / `goal_progress` 表，跨 session 目标感知
- ✅ **Running Summary**：超过 24 turns 自动压缩，注入 system prompt
- ✅ **user_profile 偏好提取**：每轮结束后 LLM 提取偏好，跨 session 持久化

### 工具（11 个）
- ✅ `search_jobs`（Adzuna 真实岗位数据，55 条，含悉尼/墨尔本）
- ✅ `analyze_gap`（结构化 JSON 输出：match_score / matched_skills / missing_skills / suggestions）
- ✅ `get_resume` / `match_resume_to_jobs`
- ✅ `get_goals` / `set_goal` / `log_progress` / `update_goal_status`
- ✅ `get_applications` / `get_interview_feedback`
- ✅ `get_candidate_profile` / `get_career_insights`

### MCP Server
- ✅ **12 个工具**按 domain 模块化暴露（jobs / records / profile / goals）
- ✅ Claude 桌面 app 验收通过

### 工程化
- ✅ **Structured Logging**：JSONL 写入 `logs/agent_trace.jsonl`（llm_call / tool_call / agent_turn）
- ✅ **`docs/CHALLENGES.md`**：15 个真实踩坑记录，面试素材

---

## 二、已知缺陷（面试时坦然承认）

| 缺陷 | 严重程度 |
|------|----------|
| 岗位数据覆盖有限（Adzuna 55 条，非实时拉取） | 高 |
| 无 eval 数字（无法量化"工具调用准确率"） | 中 |
| DashScope 调用无 retry（偶发超时直接失败） | 中 |
| 无认证（user_id 前端自填） | 低 |

---

## 三、接下来要做的事（按优先级）

### P2：最小 eval（5 个核心场景）
**价值**：有数字才能在面试里说"工具调用准确率 X%"。这是目前技术含金量的最大空缺。

5 个场景：
1. 搜岗位 → `search_jobs` 被调用，结果含真实公司名
2. gap 分析 → `analyze_gap` 被调用，返回 `match_score` 整数
3. 设目标 → `set_goal` 被调用，DB 有记录
4. 查目标 → `get_goals` 返回数据
5. 闲聊 → 不调用任何工具，直接回答

**产出**：`scripts/eval_agent.py`，输出通过率（如 `5/5 = 100%`）

> **注意**：只断言 `tool_trace` 是 toy。必须加 LLM-as-judge 对答案质量打 1-5 分，产出格式才有面试价值：
> `search_jobs: 工具调用 3/3，答案质量 4.3/5`

---

### P3：解决 demo 数据覆盖问题（P2 之后）
**现状**：`search_jobs` 只检索静态 ChromaDB 快照（55 条 Adzuna 数据）。demo 时若 query 命中率低，技术故事直接塌掉。这是目前最高风险点。

**目标**：查询时实时从 Adzuna 拉一页数据，与 ChromaDB 结果合并返回。demo 永远有真实数据。

**改动**：`app/tools/job_tools.py` 的 `_search()` — 先调 `AdzunaService.fetch_jobs()`，结果注入 context，ChromaDB 结果补充。

---

### P4：固定演示路径（不是代码，是验收）
P2 + P3 完成后，走一遍完整场景确认无幻觉、无超时、响应流畅：

1. 上传简历（Qwen-VL 解析）
2. 搜悉尼后端实习 → 返回真实 Adzuna 岗位
3. 选一个岗位做 gap 分析 → 返回 match_score + suggestions
4. 设目标（截止日期 + 目标描述）
5. 第二条对话查目标进展

全程 ≤ 5 分钟，每步结果可信。**做完这一步，项目才算真正结束。**

---

### Retry（延后，上线后再做）
DashScope 偶发超时在 demo 阶段不是高频痛点。等真实用户上线后再加指数退避。

---

## 四、不做的事

| 方向 | 原因 |
|------|------|
| Write Guardrail | 写操作只有 set_goal/log_progress，用户主动触发 |
| Tool Cache | 工具实时查 SQLite，缓存收益低 |
| 认证系统 | 非核心，不影响技术含金量 |
| Docker | 等核心功能稳定后再做 |
