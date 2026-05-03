# 项目现状 + 下一步计划

> 最后更新：2026-05-03
> 当前分支：main
> **项目状态：已完成（P4 demo 验收通过）**

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
- ✅ **Qwen-VL 简历图片解析**（前端上传 → 解析 → 存库）

### Memory（四层注入）
- ✅ **短期记忆**：SQLite 滚动 12 turns 原文
- ✅ **Goal 持久化**：`goals` / `goal_progress` 表，跨 session 目标感知，注入 system prompt
- ✅ **Running Summary**：超过 24 turns 自动 LLM 压缩，存 `conversation_summaries`，注入 system prompt
- ✅ **user_profile 偏好提取**：每轮结束后 LLM 提取偏好（地点/行业/薪资/时间线），存 `user_profiles`，跨 session 注入

### 工具（11 个）
- ✅ `search_jobs`（Adzuna 真实岗位数据，55 条，含悉尼/墨尔本）
- ✅ `analyze_gap`（结构化 JSON 输出：match_score / matched_skills / missing_skills / suggestions，自动按 user_id 查简历）
- ✅ `get_resume` / `match_resume_to_jobs`
- ✅ `get_goals` / `set_goal` / `log_progress` / `update_goal_status`
- ✅ `get_applications` / `get_interview_feedback`
- ✅ `get_candidate_profile` / `get_career_insights`

### MCP Server
- ✅ **12 个工具**按 domain 模块化暴露（jobs / records / profile / goals）
- ✅ Claude 桌面 app 验收通过

### 工程化
- ✅ **Structured Logging**：JSONL 写入 `logs/agent_trace.jsonl`（llm_call / tool_call / agent_turn）
- ✅ **P2 Eval**：`scripts/eval_agent.py`，5 场景 × 3 问法 × LLM-as-judge
  工具调用准确率 **14/15 = 93%**，答案质量均分 **4.2/5**
- ✅ **`docs/CHALLENGES.md`**：14 个真实踩坑记录，面试素材

### 验收
- ✅ **P4 端到端 demo 验收**：搜岗位 → gap 分析（match_score 85）→ 设目标 → 查进展，全程通畅

---

## 二、已知缺陷（面试时坦然承认）

| 缺陷 | 严重程度 |
|------|----------|
| 简历写入需要通过前端图片上传或 API，无纯对话上传流程 | 高 |
| 岗位数据 55 条静态快照，非实时拉取，覆盖有限 | 高 |
| DashScope 调用无 retry（偶发超时直接失败） | 中 |
| user_profile 偏好提取未端到端验收 | 中 |
| 无认证（user_id 前端自填） | 低 |

---

## 三、已决定不做的事

| 方向 | 决策理由 |
|------|---------|
| P3 实时 Adzuna 拉取 | demo 路径可控，55 条覆盖已验证够用；实时调用增加延迟和外部依赖，demo 阶段代价大于收益 |
| Retry | demo 阶段超时偶发，等真实用户上线后再加指数退避 |
| Write Guardrail | 写操作只有 set_goal/log_progress，用户主动触发，无防护必要 |
| Tool Cache | 工具实时查 SQLite，缓存收益低 |
| 认证系统 | 非核心，不影响技术含金量 |
| Docker | 等核心功能稳定后再做 |
