# 项目现状 + 下一步计划

> 最后更新：2026-05-02
> 当前分支：feature/memory-upgrade

---

## 一、已完成（全部在 main / feature/memory-upgrade 分支）

### 核心 Agent 架构
- ✅ **真 ReAct function calling 循环**（`app/services/autonomous_agent_service.py`）
  LLM 看到所有工具 schema，自主决定调哪个工具、调几次、什么顺序。不是意图分类器，不是固定工具链。
- ✅ **ToolRegistry**（`app/tools/registry.py`）
  Pydantic 输入校验，统一 ToolResult 结构，11 个工具注册在内。
- ✅ **Hybrid RAG**（ChromaDB 向量 + BM25 + RRF 融合）
- ✅ **SSE 实时状态流**（`🤔 正在思考` → `🔧 调用工具：xxx`）
- ✅ **Qwen-VL 简历图片解析**

### Memory
- ✅ **短期记忆**：SQLite 滚动 12 turns（6 个来回）原文
- ✅ **Goal 持久化**：`goals` / `goal_progress` 表，跨 session 目标感知，注入 system prompt
- ✅ **Running Summary**：超过 24 turns 自动用 LLM 压缩旧记录，存 `conversation_summaries`，注入 system prompt
- ✅ **user_profile 偏好提取**：每轮结束后 LLM 提取偏好（地点/行业/工作类型/薪资/时间线/回避），存 `user_profiles`，下次对话注入

### 工具
- ✅ `search_jobs`（hybrid RAG 检索，假数据）
- ✅ `get_resume` / `match_resume_to_jobs`
- ✅ `analyze_gap`（v1，简历 + JD → LLM 自由文本分析）
- ✅ `get_goals` / `set_goal` / `log_progress` / `update_goal_status`
- ✅ `get_applications` / `get_interview_feedback`
- ✅ `get_candidate_profile` / `get_career_insights`

### MCP Server
- ✅ **12 个工具**按 domain 模块化暴露（jobs / records / profile / goals）
- ✅ Claude 桌面 app 验收通过（`mcp__career-agent__get_goals` 真实调用返回 SQLite 数据）

### 工程化
- ✅ **Structured Logging**：`app/utils/trace_logger.py`，JSONL 写入 `logs/agent_trace.jsonl`
  记录三类事件：llm_call / tool_call / agent_turn，含耗时和错误

### 验收脚本
- `.venv/bin/python scripts/verify_memory_upgrade.py`（17 项）
- `.venv/bin/python scripts/verify_trace_logger.py`（17 项）

---

## 二、已知缺陷（面试时要能坦然承认）

| 缺陷 | 严重程度 |
|------|----------|
| 岗位数据是假的（手工 seed，不是真实市场） | 高 |
| analyze_gap 输出是自由文本，无结构化 match_score | 高 |
| Final answer 不流式（analyze_gap 等重工具 30s 后文字一次性出现） | 中 |
| 没有 eval 数字（无法量化"通过率"） | 中 |
| DashScope 调用无 retry（偶发超时直接失败） | 中 |
| 无认证（user_id 是前端自填字符串） | 低 |

---

## 三、接下来要做的事（按优先级）

### P0：analyze_gap 结构化输出
**现状**：`app/services/gap_service.py` 是纯 prompt → 自由文本。

**目标**：改成三步输出 JSON：
```json
{
  "match_score": 72,
  "matched_skills": ["Python", "FastAPI", "SQL"],
  "missing_skills": ["Docker", "Kubernetes"],
  "suggestions": ["补 Docker 基础", "做一个容器化部署的项目"]
}
```

**改动文件**：`app/services/gap_service.py`，新增 prompt 让 LLM 输出 JSON，加 `json.loads()` 解析，fallback 到旧版文本。
**验收脚本**：`scripts/verify_gap_structured.py`

---

### P1：真实岗位数据（Adzuna API）
**现状**：`search_jobs` 检索手工 seed 的几十条假数据。

**目标**：接入 Adzuna Australia Jobs API（免费，有 Sydney/Melbourne 数据），替换 seed 数据，搜出真实市面岗位。

**API 文档**：https://developer.adzuna.com/
**改动文件**：`app/services/job_service.py` 或新建 `app/services/adzuna_service.py`
**验收**：搜"Sydney fintech backend intern"，结果来自真实 Adzuna，不是假数据。

---

### P2：最小 eval（5 个核心场景）
**目标**：有数字才能在面试和 README 里说"通过率 X%"。

5 个场景：
1. 搜岗位 → `search_jobs` 被调用
2. gap 分析 → `analyze_gap` 被调用，返回 match_score
3. 设目标 → `set_goal` 被调用，DB 有记录
4. 查目标 → `get_goals` 返回数据
5. 闲聊 → 不调用任何工具，直接回答

**验收脚本**：`scripts/eval_agent.py`

---

### P3：工程化补全
- DashScope 调用加 Retry（指数退避 2-3 次，`app/llm/client.py`）
- Final answer streaming（stream=True + SSE token 推送）

---

## 四、不做的事

| 方向 | 原因 |
|------|------|
| Write Guardrail | 本项目写操作只有 set_goal/log_progress，用户主动触发，不需要防护 |
| Tool Cache | 工具基本实时查 SQLite，缓存收益低 |
| 认证系统 | 非核心，不影响技术含金量 |
| Docker / 反馈机制 | 等核心功能稳定后再做 |
