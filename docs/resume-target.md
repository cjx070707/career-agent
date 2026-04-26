# 简历北极星（Resume Target v1）

本文件定义项目完成后**简历上可以写的 6 条技术声明**。每条附面试验收标准。

每次完成一个 milestone 回来审这个文件，问三个问题：

1. 这条做到多少了？
2. 这个词还是我想用的吗？
3. 有没有什么我实际做出来的、比这个词更有信号的东西，值得换进来？

---

## 条 1｜双层记忆架构

> 设计短期会话缓存（SQLite 持久化，按用户分流）+ 长期职业画像（结构化字段 + 关键事件向量索引）的双层记忆架构，实现跨会话上下文继承与长期偏好沉淀。

**面试验收：**
- 能演示同一用户跨多轮偏好继承（"上次你说关注 FastAPI 方向"）
- 能说出短期记忆是 SQLite `conversation_turns`，长期画像是 `career_profiles` + `career_events`（向量化）
- 能解释"为什么投递记录不向量化"——因为投递是结构化查询，向量化无意义

**用词注意：** 说"双层"不说"分层"（Hierarchical Memory 有严格学术定义，指 MemGPT 式 main/external 分层，我们的形态是多实体分库，不是同一实体的分级缓存）

## 条 2｜MCP-ready 模块化工具层

> 设计 MCP-ready 模块化工具层，按业务域封装候选人档案、简历、岗位检索、投递记录、面试反馈与职业画像工具，统一通过 Pydantic schema + ToolRegistry 声明式注册；Agent 通过 Router/Planner 自动选择调用，形成可复用、可扩展、未来可薄适配为 MCP Server 的工具边界。

**面试验收：**
- 能解释工具注册是声明式的（Pydantic schema + ToolRegistry），新增工具不需要改 Agent 主流程
- 能演示 Router/Planner 自动选择 `search_jobs`、`get_applications`、`get_interview_feedback`、`get_career_insights` 等工具
- 能说清"MCP-ready 工具模块化"和"真正 MCP 协议接入"的区别：当前主线先稳定内部工具边界，外部 MCP client 接入属于可选薄适配

**用词注意：** 当前不要说"已接入 MCP 协议"或"外部 MCP 客户端可直接调用"，除非真的实现 MCP Server；可以说"MCP-ready 工具模块化"或"具备 MCP Server 薄适配边界"。真正 MCP Server 属于未来可选协议适配，不是当前产品主链路。

## 条 3｜双层决策 + 可观测规划

> 设计 Router-first + Planner-fallback 的双层决策架构：高置信度意图走规则路由，灰区查询由 LLM Planner 接管；Planner 输出经契约护栏（工具白名单、步骤顺序、步长上限）验证，违规自动降级；plan / tool_trace / llm_trace 字段对外可观测。

**面试验收：**
- 能画出 Router → Planner → Executor → Summarizer 的链路图
- 能说出护栏的三条规则（白名单、顺序、步长）和降级策略（2 次重试 → fallback_plan）
- 能解释"为什么不全部让 LLM 决策"——对明显意图走 LLM 是浪费延迟和 token，不可解释不可测试
- 能展示 `llm_trace.planner_source` 在 `router/model/fallback` 之间的分布

**用词注意：** 不说"ReAct"（我们是 Plan-then-Execute，不是 Think→Act→Observe 循环）。不说"自我一致性"（Self-Consistency 是多次独立采样 + 多数投票，我们做的是契约护栏 + 降级）。这两个词有严格学术定义，简历上用了面试会被追问。

## 条 4｜混合召回 RAG

> 基于 ChromaDB 向量召回 + BM25 lexical 的 RRF 融合 + 轻量 rerank，覆盖岗位 JD 与关键事件两类语料，返回 matched_terms 与 reason 等 grounded evidence，降低幻觉并提升可解释性。

**面试验收：**
- 能解释 RRF（Reciprocal Rank Fusion）的公式和为什么比单路召回好
- 能说出 `matched_terms` 和 `reason` 的生成逻辑（lexical overlap + 结构化上下文拼接）
- 能演示一个 query 的完整召回链路：Chroma 向量 → rerank → reason → source

**用词注意：** 只有真做了 BM25 + 向量融合才能说"混合召回"。如果最终只做了"向量 + rerank"，要改成"向量召回 + 轻量 rerank"

## 条 5｜图像输入 + 多端交互

> 集成 GPT-4V 直接解析简历/JD 截图输出结构化字段，减少 OCR 中间态；React 搭建 Query（单次任务）+ Chat（持续陪跑）双页面前端，支持多场景求职交互切换。

**面试验收：**
- 能演示截图上传 → 结构化字段输出的完整链路
- 能说清"为什么用 GPT-4V 而不是 OCR pipeline"——GPT-4V 能直接理解版式和语义，OCR 只抽文字还需要后处理
- React 双页面能独立运行和演示

**用词注意：** 如果最终用的是 OCR pipeline 而非 GPT-4V，则不能说"多模态"，改说"多源输入支持"。"多模态"在 AI 语境里指模型端直接处理 text+image 等不同输入形态；本项目当前只规划图片多模态，不规划语音播报。

## 条 6｜工程基建与评测

> FastAPI + React 前后端分离 + ToolRegistry 声明式工具注册（Pydantic schema + metadata export）；自建 evals 评测框架覆盖 16+ 回归用例（路由 / 规划 / 答案质量 / 结构化字段约束），支撑版本迭代的可量化对比。

**面试验收：**
- 能跑一遍 eval harness 并解读报告
- 能说出几个有代表性的 eval 断言类型（`plan_task_type`、`source_field_all_contain`、`answer_contains_any`）
- 能解释 eval 和 unit test 的区别——eval 走完整 /chat 端到端链路，unit test 隔离单个模块

---

## 可选升级路径（不在当前简历声明范围，但项目架构已支持）

| 升级方向 | 切入点 | 工程量 |
|---|---|---|
| Plan-Act → ReAct | `_should_continue_after_step` 从规则判断改为 LLM observe 判断 | ~3 天 |
| 单 Agent → Multi-Agent | `AgentService` 拆为 N 个 sub-agent + Orchestrator 调度 | ~5 天 |
| CoT 显式推理 | Planner prompt 加 chain-of-thought 并把推理过程存入 `llm_trace` | ~2 天 |

这些升级路径不需要推翻现有底座。能力层（ToolRegistry / RetrievalService / MemoryService）不用动，只换决策层。
