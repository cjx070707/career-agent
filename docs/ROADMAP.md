# 实施路线图（历史记录）

> 这个文件记录各 Phase 的完成情况。当前任务和下一步计划见 `NEXT_PHASE.md`。

---

## Phase A｜LLM Intent Classifier → 废弃，直接跳过

原计划用 LLM 替换规则树意图分类器。
**实际**：直接重写为真 ReAct function calling 循环，意图分类器整条路线全部废弃。

---

## Phase B｜统一输出协议 ✅ 已完成

所有 task_type 回答遵循"结论 → 证据 → 行动"三段结构。

---

## Phase C｜真正 LLM 驱动的 ReAct 循环 ✅ 已完成

**完成**：`AutonomousAgentService`，LLM 看到所有工具 schema，自主决定调哪个工具、调几次、什么顺序。真正的 function calling，不是预规划工具链。

---

## Phase D｜Eval 量化指标 ✅ 已完成

multi-turn 7/7 (100%)，路由准确率 7/7 (100%)。

---

## Phase E｜对话层重构与性能优化 ✅ 已完成

- 删除空转 LLM 调用（career_diagnostic_planner / career_event sync）
- career_insights 响应时间从 27s 降至 < 8s
- 删除 agent_service 中残留的关键词硬覆盖规则

---

## Phase F｜Goal 持久化 + 真 ReAct Agent ✅ 已完成

- `goals` / `goal_progress` 表 + `GoalService`
- `get_goals` / `set_goal` / `log_progress` / `update_goal_status` 工具
- 跨 session 目标感知，注入 system prompt
- analyze_gap 工具（v1 prompt 版）
- SSE 实时工具调用状态流

---

## Phase G｜MCP Server ✅ 已完成

- 12 个工具，4 个 domain（jobs / records / profile / goals）
- FastMCP stdio transport
- Claude 桌面 app 验收通过

---

## Phase H｜Memory 升级 + Structured Logging ✅ 已完成（2026-05-02）

分支：`feature/memory-upgrade`

- **Running Summary**：超 24 turns 自动压缩，存 `conversation_summaries`，注入 system prompt
- **user_profile 提取**：每轮提取偏好，存 `user_profiles`，下次注入，真正跨 session 记忆
- **Structured Logging**：`logs/agent_trace.jsonl`，llm_call / tool_call / agent_turn 三类事件

验收：`scripts/verify_memory_upgrade.py`（17/17）、`scripts/verify_trace_logger.py`（17/17）

---

## 接下来

见 `NEXT_PHASE.md`。
