# 架构文档｜高校求职辅导 Agent

> 本文件是项目的**架构北极星**。描述目标状态，而不只是当前状态。
> 任何 AI 工具或开发者在修改代码前，应先读这份文件理解设计意图。

---

## 一、核心设计原则

**LLM 是大脑，工具是手，规则不做决策。**

当前 Agent 领域最常见的误区是用关键词规则模拟语言理解——系统越复杂，规则越多，覆盖越差。本项目的目标架构反其道而行：

- 意图理解交给 LLM，不交给 if-else
- 工具调用序列由 LLM 在执行过程中动态决定，不预先规划
- 规则只做两件事：极端简单的快捷路径（greeting / capability help），以及执行层的安全边界（工具白名单、步长上限）

这不是为了"agent 感"，而是因为规则树在自然语言变体面前天花板极低，LLM 驱动的方案才能真正泛化。

---

## 二、目标架构总览

```
用户消息 + 对话历史（最近 N 轮）+ 用户状态（has_resume / has_candidate 等）
                          │
                          ▼
              ┌─────────────────────┐
              │  快捷路由（规则）     │  ← 仅处理 greeting / capability help
              │  命中 → 直接返回     │    两种极端简单场景，无需 LLM
              └──────────┬──────────┘
                         │ miss（绝大多数请求）
                          ▼
              ┌─────────────────────┐
              │  LLM Intent         │  ← 一次结构化输出调用
              │  Classifier         │    输入：消息 + 对话历史 + 用户状态
              │                     │    输出：task_type / steps / missing_context
              └──────────┬──────────┘
                         │
                          ▼
              ┌─────────────────────┐
              │  Context Resolver   │  ← 检查必要上下文是否具备
              │                     │    缺失 → 追问用户，不执行工具
              └──────────┬──────────┘
                         │ 上下文具备
                          ▼
              ┌─────────────────────┐
              │  ReAct 执行循环      │  ← LLM 驱动，不是预规划序列
              │                     │
              │  loop {             │
              │    observe          │  ← 看当前已有信息 + 上一步工具结果
              │    → scratchpad     │  ← LLM 推理：够了吗？下一步是什么？
              │    → act / finish   │  ← 调用工具 or 终止循环
              │    → 看结果         │
              │  }                  │
              │                     │
              │  安全边界：          │
              │  MAX_STEPS=8        │
              │  工具白名单          │
              └──────────┬──────────┘
                         │
                          ▼
              ┌─────────────────────┐
              │  统一输出层          │  ← 所有任务类型共用同一输出协议
              │                     │    结论 → 证据 → 行动建议
              └─────────────────────┘
```

---

## 三、模块职责边界

### 3.1 保留不变的模块

这些模块在重构中**不需要改动**，架构已经稳定：

| 模块 | 文件 | 职责 |
|---|---|---|
| MemoryService | `app/services/memory_service.py` | 短期对话缓存 + 跨会话记忆 |
| ProfileService | `app/services/profile_service.py` | 用户偏好与画像持久化 |
| RetrievalService | `app/services/retrieval_service.py` | ChromaDB + BM25 + RRF 混合召回 |
| ToolRegistry | `app/tools/registry.py` | 声明式工具注册，Pydantic schema 验证 |
| 所有 Tool 实现 | `app/tools/` | get_resume / search_jobs / match_resume_to_jobs 等 |
| CareerEventService | `app/services/career_event_service.py` | 关键事件提取与索引 |

### 3.2 被替换的模块

这些模块是旧架构的遗留，目标架构中将被移除或合并：

| 模块 | 现状 | 目标处理 |
|---|---|---|
| `app/routing/intent_router.py` | 1200 行关键词规则路由 | 删除，职责转移至 LLM Intent Classifier |
| `app/routing/intent_gateway.py` | 二级规则路由 + planner 转接 | 删除，职责转移至 LLM Intent Classifier |
| `app/routing/intent_signals.py` | 关键词信号定义 | 删除 |

### 3.3 新增的模块

| 模块 | 文件（目标） | 职责 |
|---|---|---|
| LLM Intent Classifier | `app/routing/llm_intent_classifier.py` | 一次结构化 LLM 调用，直接输出 task_type / steps / missing_context，替代全部规则路由层 |

### 3.4 需要升级的模块

| 模块 | 当前状态 | 目标状态 |
|---|---|---|
| PlanExecutor | bounded ReAct，步骤来自预规划序列 | 真正 LLM 驱动：每步由 LLM 观察后自主决定下一步 |
| ResponseFormatter | 各任务类型格式不统一 | 统一输出协议：结论 / 证据 / 行动三段结构 |
| AgentService | 三段路由逻辑（router → gateway → planner） | 简化为：快捷路由 → LLM Classifier → ReAct Loop |

---

## 四、/chat 请求流（目标状态）

```
POST /chat { user_id, message }
  │
  ├─ 1. 加载记忆 + 更新画像（不变）
  │
  ├─ 2. 快捷路由检查
  │     greeting / capability_help → 直接返回，无 LLM 调用
  │
  ├─ 3. LLM Intent Classifier
  │     输入：message + recent_turns + user_state + available_tools
  │     输出：ChatPlan { task_type, steps, missing_context, needs_more_context }
  │
  ├─ 4. Context Resolver（不变）
  │     missing_context 不为空 → 返回 follow_up_question，终止
  │
  ├─ 5. ReAct 执行循环（升级）
  │     LLM 每步观察 → scratchpad 推理 → 决定行动
  │     循环直到 LLM 判断信息充分 or 触达安全边界
  │
  ├─ 6. 统一输出层（新增）
  │     所有 task_type 走同一输出协议
  │     结论（1-2句）→ 证据（来自工具数据）→ 行动建议（具体可执行）
  │
  └─ 7. 保存记忆，返回 AgentResult（不变）
```

---

## 五、LLM Intent Classifier 设计规格

**定位**：替代 IntentRouter + IntentGateway + LLM Planner 三层，合并为单次调用。

**输入**：
```python
{
  "message": str,               # 当前用户消息
  "recent_turns": List[str],    # 最近 N 轮对话（含 AI 回复）
  "user_state": {               # 用户数据状态
    "has_resume": bool,
    "has_candidate": bool,
    "has_job_detail": bool,
  },
  "available_tools": List[str], # 当前可用工具名列表
}
```

**输出**（强制 JSON schema）：
```python
{
  "task_type": str,             # resume_analysis / job_match / job_search /
                                 # career_insights / interview_prep / fallback
  "steps": List[str],           # 建议工具调用序列（ReAct loop 可偏离）
  "needs_more_context": bool,
  "missing_context": List[str], # resume / job_detail / target_role 等
  "follow_up_question": str | None,
  "reasoning": str,             # scratchpad，不对用户展示，用于 llm_trace
}
```

**实现要点**：
- 使用 JSON mode 或 function calling 强制结构化输出
- Prompt 包含 few-shot 示例覆盖主要 task_type
- 输出 schema 校验失败时降级为 `task_type=fallback`，不抛 500
- `reasoning` 字段写入 `llm_trace`，可观测

---

## 六、ReAct 执行循环设计规格

**定位**：LLM 驱动的动态工具调用循环，替代预规划步骤序列执行。

**每次迭代**：
```
输入：message + 对话历史 + 已调用工具及其结果 + 可用工具列表
LLM scratchpad：
  "我现在知道：[已有信息摘要]"
  "我还需要：[缺失信息]"
  "因此我应该：[下一步行动]"
LLM 输出：
  { "action": "call_tool" | "finish", "tool": str | None, "reason": str }
```

**安全边界**（不变）：
- `MAX_STEPS = 8`：超出强制终止
- 工具白名单：LLM 只能选 ToolResolver 允许的工具
- 工具重复保护：同一工具连续调用 > 2 次，强制跳过

**与当前 execute_react_loop 的区别**：
- 当前：步骤来自预规划序列，LLM 只做"继续/重规划/追问"三选一
- 目标：每步由 LLM 基于完整观察自主决定调用哪个工具，或直接回答

---

## 七、统一输出协议

所有 task_type 的最终回答遵循同一结构，不区分 formatter 实现路径：

```
【结论】
1-2 句，直接回答用户问题。

【证据】
来自工具数据的具体支撑，不泛泛而谈。
例：简历中 FastAPI + 3 个月后端实习，与岗位要求高度匹配。

【行动建议】
具体可执行的下一步，不超过 3 条。
例：① 本周投递 Atlassian Backend Intern ② 补充简历中系统设计项目描述
```

---

## 八、当前实现状态 vs 目标状态

| 层 | 当前状态 | 目标状态 | 优先级 |
|---|---|---|---|
| 意图识别 | 关键词规则树（IntentRouter + Gateway） | LLM Intent Classifier | P0 |
| ReAct 循环 | Bounded，步骤预规划 | LLM 完全驱动 | P1 |
| 输出协议 | 各 task_type 各自为政 | 统一三段式 | P1 |
| 记忆系统 | ✅ 已完成 | 不变 | — |
| 工具层 | ✅ 已完成 | 不变 | — |
| Hybrid RAG | ✅ 已完成 | 不变 | — |
| Eval harness | ✅ 已完成 | 扩充量化指标 | P2 |
| 多模态输入 | ✅ 已完成 | 不变 | — |
