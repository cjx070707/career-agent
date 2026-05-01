# 下一阶段计划｜从 Chatbot 到真正的 Agent

> 写作时间：2026-05-01 | 最后更新：2026-05-01  
> 背景：项目投递 AI 开发岗位，需要对当前项目做诚实评估，并规划真正有含金量的演进路径。

---

## 一、当前项目的诚实评估

### 现在本质上是什么

一个**结构化 LLM Pipeline**，不是 Agent。

执行路径是固定的：

```
用户消息 → 意图分类（LLM）→ 固定工具链 → LLM 生成回答
```

ReAct loop 的**结构**存在，但决策是假的。意图分类器已经提前决定好了走哪条工具链，LLM 在 loop 里只是沿着预定义路径确认"continue"或"finish"，从未真正改变过执行路径。

区别在于：**谁在真正做决定**。现在是意图分类器在决定，LLM 只是执行。真正的 agent 是 LLM 看到所有可用工具后自主决定调哪个、调几次、什么顺序。

### 为什么不是 Agent

真正的 Agent 核心特征是**自主性**：

| 特征 | 真正的 Agent | 当前项目 |
|---|---|---|
| 目标分解 | 自主拆解复杂目标为子任务 | 无，意图分类后走固定流水线 |
| 动态规划 | 根据中间结果调整计划 | 工具链预定义，不动态调整 |
| 跨轮次推理 | 上一轮的结果影响下一轮的行动策略 | 仅有对话记忆，无目标追踪 |
| 处理意外 | 工具失败时自主重规划 | fallback 到静态错误信息 |
| 自主决策 | LLM 真正决定做什么，不做什么 | LLM 确认人类预定义的路径 |

### 面试官的看法（有经验的 agent 工程师）

> "工程质量不错，RAG 和工具调用用得比较规范，streaming 缺失但可以理解是 demo 阶段。但本质上这是一个带固定流水线的结构化 chatbot。Resolver + ToolChain 的设计表现出系统思维，但没有体现真正的 agent 能力。适合 AI 应用工程师岗位，agent 工程师岗位边缘。"

能过的岗位：
- AI 应用开发（LLM 集成、工具调用、RAG 落地）✅ 有竞争力
- AI 工程师（初级） ✅ 有竞争力
- Agent 工程师（初级） ⚠️ 边缘，看公司标准
- Agent 工程师（中级+） ❌ 不够

---

## 二、为什么这个问题需要真正的 Agent

### 当前问题不需要 Agent

"用户问求职问题，系统回答" —— 这个问题本身用 chatbot 就够了，因为每次交互都是独立的 Q&A，没有跨轮次的状态依赖。

**Agent 真正有价值的条件**：任务需要多步骤、有状态、中间结果不确定、需要动态调整。

### 求职场景里真正需要 Agent 的任务

> 用户说："我想三个月内拿到后端实习 offer"

Agent 需要自主完成：

1. 分析当前简历 gap（调用工具）
2. 搜索目标岗位 JD 并提取要求（调用工具）
3. 对比 gap，生成每周行动计划（推理 + 生成）
4. 下周跟进："上周你说要补 Docker，做了吗？" （跨会话记忆 + 目标追踪）
5. 根据用户反馈调整计划（动态调整）

这才是 Agent：有目标、有跨会话记忆、有状态追踪、中间结果影响后续行动。

**这个问题用 chatbot 做不了**，因为：
- chatbot 没有持久目标，每次对话都是独立的
- chatbot 不知道"上次说要做什么"和"有没有做到"
- chatbot 不能根据用户进展动态调整长期计划

---

## 三、main 分支完成情况

### ✅ Phase F-1｜SSE 流式输出
`/chat` 端点改为 `StreamingResponse`，`run_in_executor` 保证事件循环不阻塞，三条 SSE 事件（status / answer / done）正常工作。`/chat/sync` 保留供 eval 使用。

### ✅ Phase F-2｜真实 Embedding
接入 DashScope `text-embedding-v3`（1024 维），替换原来的 MD5 hash 假向量。实现了分批调用（每批 10 条避免超限）和维度不匹配时自动重建 collection 的逻辑。

### ⏭ Phase F-3｜PDF 简历解析（暂缓）
vision_client 已接好，用户可直接上传图片。PDF 解析本质是"PDF → 图片 → vision"，工程价值有限，等 agent 分支稳定后按需补。

### ⏭ Phase F-4｜Gap Analysis（并入 agent 分支）
不作为独立 pipeline 实现。在 agent 架构里作为一个工具（tool）实现，由 LLM 自主决定何时调用，比固定 pipeline 含金量更高。

### ⏭ Phase F-5｜Eval 量化数字（agent 分支完成后统一跑）

---

## 四、真正 Agent 版本（分支 `feature/autonomous-agent`）

### 核心架构：工具调用驱动，不是意图分类驱动

**当前假 agent 路径：**
```
意图分类（LLM）→ 预定义 tool chain → LLM 生成回答
```
LLM 在 ReAct loop 里走的是意图分类器已经决定好的路，从未真正自主。

**新 agent 路径：**
```
加载上下文（目标 + 历史）
    ↓
LLM 看到：所有工具描述 + 当前目标状态 + 对话历史 + 用户消息
    ↓
LLM 自主决定：调哪个工具 / 调几次 / 什么顺序 / 还是直接回答
    ↓
执行工具 → 结果返回 LLM → LLM 再次决策（真 ReAct）
    ↓
最终回答
```

### Agent 工具列表（LLM 从中自主选择）

| 工具 | 功能 |
|---|---|
| `search_jobs` | 语义搜索匹配岗位 |
| `get_resume` | 读取用户简历 |
| `analyze_gap` | 简历 vs JD gap 分析 |
| `get_goals` | 查询当前求职目标和计划 |
| `set_goal` | 设定或更新求职目标 |
| `log_progress` | 记录本周进展（投了几家、面试结果等）|

### 目标持久化（新增 DB 表）

```sql
goals (
  id, user_id, goal_text, deadline,
  status, plan_json, created_at, updated_at
)
goal_progress (
  id, goal_id, note, created_at
)
```

每次对话开始前，agent 先查 `goals` 表，把目标状态注入 system prompt。这是跨会话记忆的核心。

### 典型 agent 行为

**第一次对话：**
> 用户：我想三个月内拿到 fintech 后端实习
> Agent：自主调用 `set_goal` → `get_resume` → `search_jobs` → `analyze_gap` → 输出分阶段计划

**第三次对话：**
> 用户：最近有点迷茫
> Agent：查 `get_goals`（目标存在，第二周应投3家）→ 主动问"上周计划投3家，实际怎么样了？" → 根据回答调 `log_progress` 或调整计划

这是 chatbot 做不到的：chatbot 没有持久目标，不能主动追问，不能根据真实进展更新计划。

### 实施阶段

**A-1**：`goals` / `goal_progress` 表 + `GoalService`  
**A-2**：工具注册表 + 真正的 function calling 循环（替换意图分类路径）  
**A-3**：跨会话目标感知（每次对话注入目标状态到 system prompt）  
**A-4**：`analyze_gap` 工具实现  
**A-5**：多轮 eval + 量化数字写入 README

现有 `RetrievalService`、`ResumeService`、`MemoryService` 全部保留作数据层，新 agent 直接调用，不重写。

---

## 五、执行顺序（更新后）

```
main 分支（已完成）:
  ✅ F-1 Streaming  ✅ F-2 真实 Embedding

feature/autonomous-agent 分支:
  A-1 Goal 持久化 → A-2 真 Function Calling 循环
  → A-3 跨会话目标感知 → A-4 Gap Analysis tool
  → A-5 Eval 数字
```

---

## 六、开发纪律（必须遵守）

之前项目推进中出现了反复打地鼠、屎山代码积累的问题，根本原因是：改了一个地方没想清楚连锁效应，然后用下一个 fix 去补上一个 fix。以下是接下来必须遵守的原则。

### 原则一：Phase 串行，验收后才能进入下一个

每个 Phase 做完 → 跑 eval → 通过 → commit → 才能动下一个。不能 F-1 没测完就跑去做 F-2。

### 原则二：改之前先描述影响范围，确认再动手

每次动代码之前，先说清楚：
- 涉及哪些文件
- 不涉及哪些文件（边界在哪里）
- 是否影响现有 eval 结果

确认没问题再动手，不靠猜测推进。

### 原则三：遇到 bug 先读日志找根因，不靠猜

之前很多问题是猜一个方向改代码，不对再猜下一个，结果越改越乱。以后遇到问题：

```
读日志 → 确定根因 → 描述根因 → 确认 → 一次改对
```

不允许"先试试看"。

### 原则四：新功能上线前先写期望行为

新功能实现之前，先用一句话写清楚"这个功能的期望行为是什么"，对应的 eval case 是什么。功能做完立刻验证，不靠感觉判断对不对。

### 原则五：不做没有明确目的的改动

每次改动必须能回答："这个改动解决了什么问题？"如果答案是模糊的，就不动。

---

## 七、简历怎么讲这个项目（改进后）

**改进前能说的**：
> "用 FastAPI + LLM 构建了一个求职辅导 chatbot，集成了 RAG 检索和工具调用。"

**main 分支（当前可说的）**：
> "构建了一个求职辅导 AI 系统，实现了 SSE 流式输出、基于 DashScope text-embedding-v3 的语义检索（1024 维，hybrid BM25 + 向量 RRF 融合排序）。系统有完整 eval 框架，multi-turn 通过率 100%。"

**完成 agent 分支后能说的**：
> "在此基础上实现了基于 function calling 的真正自主 Agent：LLM 自主决定调用哪些工具（岗位搜索、简历分析、gap 分析、目标管理），跨会话追踪求职目标，根据真实进展动态调整计划。这是 chatbot 无法实现的能力——它需要持久目标状态、跨轮次主动推理、和真正的 LLM 自主决策。"

---

*最后更新：2026-05-01*
