# 简历演进记录

> 本文件记录项目简历条目的前后变化、改动原因，以及每次改动后的面试验收标准。
> 每完成一个 Phase，回来更新这份文件。

---

## 基本信息

**项目名称**：高校求职辅导 Agent
**时间跨度**：2026.02 – 2026.05
**角色**：核心成员

---

## v1｜初始版本（2026-04 之前）

### 原文

**技术栈**：FastAPI、Python、React、SQLite、ChromaDB、BM25、RRF、RAG、Pydantic、Agent、Qwen-VL、OpenAI-compatible API

**背景介绍**：面向高校求职平台与高校学生场景开发智能 Agent，围绕简历、岗位 JD、投递记录、面试反馈与长期画像等私域数据，解决岗位筛选低效、简历优化缺乏针对性、面试复盘难沉淀等问题，提升个性化求职辅导效率与服务标准化程度。

**责任和技术实现**：

1. **记忆与职业画像建模**：设计短期会话缓存 + 长期职业画像的 Memory-augmented Agent 架构，基于 SQLite 持久化多轮对话、投递记录、面试反馈与职业关键事件，并通过画像摘要与事件索引支持跨会话个性化辅导。

2. **模块化 MCP server 工具调用层**：基于 Pydantic schema + ToolRegistry 构建声明式工具注册机制，将候选人档案、简历检索、岗位搜索、投递记录与面试反馈等能力封装为可路由工具，支持 Agent 按任务自动选择并调用工具。

3. **Router-first 规划链路**：构建 Router-first + Planner-fallback 双层决策架构，高置信度请求由规则路由快速命中，复杂查询由 LLM Planner 生成执行计划，并通过工具白名单、步骤顺序与步长上限提升规划稳定性。

4. **Hybrid Retrieval RAG**：基于 ChromaDB 向量召回 + BM25 lexical 召回 + RRF 融合构建混合检索链路，覆盖岗位 JD、职业画像与关键事件等语料，并通过 matched terms、reason 与 source 字段增强回答可解释性。

5. **多模态与工程化闭环**：集成 Qwen-VL 支持简历截图解析与结构化保存，结合 React 构建 Query / Chat 双页面；同时搭建单元测试、集成测试、Playwright E2E 与 eval harness，覆盖路由、工具调用、答案质量与 schema contract。

---

### v1 存在的问题

**第2点**："MCP server"说法有歧义。MCP 现在特指 Anthropic 的 Model Context Protocol，如果没有真正实现该协议，面试时会被追问，解释起来被动。

**第3点**：这是最大的雷。"Router-first + Planner-fallback 双层决策"如实描述了当时的实现——1200 行关键词规则树。任何有 agent 经验的面试官会立刻判断这是 workflow，不是 agent。而且这个实现经过测试证明有明显的覆盖漏洞（对自然语言变体路由失败率高）。

**无量化数据**：五个技术点全是"设计了"、"构建了"，没有任何指标。AI 岗位面试官会主动追问，答不上来是减分项。

---

## v2｜目标版本（Phase A+B+C 完成后）

### 改动说明

- **第2点**：去掉"MCP server"，改为"模块化工具调用层 + MCP-ready 边界"，准确描述实际实现
- **第3点**：核心改动，替换为 LLM-driven ReAct 推理引擎，反映真实的目标架构
- **技术栈**：加入 ReAct
- **全文**：补充量化指标（Phase D 完成后填入）

### 改后版本

**技术栈**：FastAPI、Python、React、SQLite、ChromaDB、BM25、RRF、RAG、Pydantic、ReAct、Qwen-VL、OpenAI-compatible API

**背景介绍**：面向高校求职平台与高校学生场景开发智能 Agent，围绕简历、岗位 JD、投递记录、面试反馈与长期画像等私域数据，以 LLM 推理驱动工具调用替代传统规则编排，解决岗位筛选低效、简历优化缺乏针对性、面试复盘难沉淀等问题，提升个性化求职辅导效率与服务标准化程度。

**责任和技术实现**：

1. **记忆与职业画像建模**：设计短期会话缓存 + 长期职业画像的 Memory-augmented Agent 架构，基于 SQLite 持久化多轮对话、投递记录、面试反馈与职业关键事件，并通过画像摘要与事件索引支持跨会话个性化辅导。

2. **模块化工具调用层**：基于 Pydantic schema + ToolRegistry 构建声明式工具注册机制，将候选人档案、简历检索、岗位搜索、投递记录与面试反馈等能力封装为可路由工具，具备 MCP Server 薄适配边界；支持 Agent 按任务自动选择并调用工具。

3. **LLM-driven ReAct 推理引擎**：以 LLM 替代规则树作为核心编排层，构建真正由 LLM 驱动的 ReAct 执行循环；LLM 在每次工具调用后观察返回结果，通过 scratchpad 推理当前信息是否充分，自主决定下一步行动（继续调用 / 动态 replan / 生成回答）；去除硬编码 IntentRouter 与 IntentGateway 层，意图理解与执行规划合并为单次结构化输出调用，路由准确率从 __% 提升至 __%（Phase D 填入）。

4. **Hybrid Retrieval RAG**：基于 ChromaDB 向量召回 + BM25 lexical 召回 + RRF 融合构建混合检索链路，覆盖岗位 JD、职业画像与关键事件等语料，并通过 matched terms、reason 与 source 字段增强回答可解释性。

5. **多模态与工程化闭环**：集成 Qwen-VL 支持简历截图解析与结构化保存，结合 React 构建 Query / Chat 双页面；搭建单元测试、集成测试、Playwright E2E 与 eval harness，覆盖路由、工具调用、答案质量与 schema contract；multi-turn eval 通过率 __%（Phase D 填入）。

---

## 面试验收标准（v2 版本）

完成 Phase A+B+C 后，应能在面试中清晰回答以下问题：

**关于第3点（ReAct 推理引擎）**
- 你的 agent 如何决定调用哪个工具？
  → LLM 在每步观察已有工具结果，scratchpad 推理后决定下一步，不是预规划序列
- 你有没有做过路由准确率的量化测试？
  → 有 eval harness，multi-turn eval 覆盖 7 条双轮用例，Phase A 前后准确率对比数据
- 为什么不用 LangChain？
  → 手写编排逻辑，对 ReAct 工作原理有更深的理解和控制

**关于第4点（Hybrid RAG）**
- RRF 的原理是什么？
  → Reciprocal Rank Fusion，每个文档的最终分 = Σ 1/(k + rank_i)，k 通常取 60
- 为什么混合召回比单路好？
  → 向量召回擅长语义相似，BM25 擅长关键词精确匹配，两者互补，RRF 避免了分数量纲不一致的问题

**关于 Eval Harness**
- 你的 eval 和 unit test 有什么区别？
  → Eval 走完整 /chat 端到端链路，验证系统级行为；unit test 隔离单个模块

---

## 待填入的量化指标（Phase D 完成后）

| 指标 | v1（规则树） | v2（LLM Classifier） |
|---|---|---|
| 路由准确率 | __% | __% |
| multi-turn eval 通过率 | __% | __% |
| 平均响应延迟（P50） | __ ms | __ ms |
| intent miss 率 | __% | __% |

---

## 版本历史

| 版本 | 日期 | 主要变化 |
|---|---|---|
| v1 | 2026-04 之前 | 初始版本，Router-first 规则树架构 |
| v2 | Phase A+B+C 完成后 | LLM-driven ReAct，量化指标，去除 MCP server 歧义 |
