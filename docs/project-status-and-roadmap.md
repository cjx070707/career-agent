# 智能求职辅导 Agent：项目现状与路线图

## 1. 项目定位

面向 University of Sydney Career Hub 场景的智能求职辅导 Agent 后端系统。

当前形态：FastAPI 后端 + ChromaDB 检索 + SQLite 持久化 + LLM 编排 + 静态 demo 页。

产品语境：默认围绕 Sydney / USYD 相关岗位机会，`search first, then refine`。

## 2. 核心原则

在任何时候决定"下一步做什么"，都用这四个问题过滤：

1. 这一步是否让单场景结果更稳定？
2. 这一步是否让输出更可解释、可评估？
3. 这一步是否沉淀了未来 Agent 可复用的能力边界？
4. 如果暂时拿掉 planner，这一步是否仍然值得做？

大部分回答为否的，不进主线。

补充三条工程原则：

- 先证闭环再抽象——不为了 Agent 感而提前系统化
- planner 不是起点——它是稳定能力之上的调度层
- 终局仍然是 Agent——当前的规则路由和 Plan-Act 是阶段性选型，不是终点

## 3. 架构总览

```
API 层          app/api/             HTTP 入口、参数校验
编排层          app/services/agent_service.py
                  ├─ IntentRouter          高置信度意图 → 规则路由
                  ├─ LLM Planner           灰区意图 → 模型规划
                  ├─ FilterExtractor       用户消息 → 结构化过滤 slot
                  └─ PlanExecutor          顺序执行 tool steps
能力层          app/services/
                  ├─ MemoryService         短期记忆 (SQLite)
                  ├─ ProfileService        用户偏好 + query 增强
                  ├─ RetrievalService      ChromaDB 向量召回 + rerank + metadata 过滤
                  ├─ CandidateService      候选人读写
                  ├─ ResumeService         简历读写
                  └─ JobService            岗位读写
工具层          app/tools/ + ToolRegistry  声明式注册，Pydantic schema 验证
模型层          app/llm/client.py          planner / summarizer / generate + 契约护栏
存储层          SQLite + ChromaDB + data/
评测层          evals/                     16 条回归用例 + 结构化断言
演示层          demo/                      静态 HTML/JS 单页
```

## 4. 已完成能力清单

每项标注状态（✅ 完成 / ⚠️ 部分完成 / ❌ 未开始）和对应简历条目（见 `docs/resume-target.md`）。

### 4.1 决策与规划

| 能力 | 状态 | 代码入口 | 简历条 |
|---|---|---|---|
| Router-first 规则路由 | ✅ | `app/routing/intent_router.py` | #3 |
| LLM Planner 灰区接管 | ✅ | `app/llm/client.py` `generate_plan` | #3 |
| 契约护栏（白名单/顺序/步长） | ✅ | `app/llm/client.py` `_validate_plan_contract` | #3 |
| 违规降级（2 次重试 → fallback） | ✅ | `app/llm/client.py` `_validated_plan` | #3 |
| 工具执行失败静默降级 | ✅ | `app/services/agent_service.py` `_execute_plan` | #3 |
| plan / tool_trace / llm_trace 可观测 | ✅ | `app/services/agent_service.py` | #3 |
| 结构化过滤 slot 抽取 (location/work_type) | ✅ | `app/routing/filter_extractor.py` | #4 |
| ReAct observe 环节（工具结果反馈重规划） | ❌ | — | 升级路径 |
| Multi-Agent Orchestrator | ❌ | — | 升级路径 |

### 4.2 检索与数据

| 能力 | 状态 | 代码入口 | 简历条 |
|---|---|---|---|
| ChromaDB 向量召回 | ✅ | `app/services/retrieval_service.py` | #4 |
| 轻量 rerank（lexical overlap scoring） | ✅ | `retrieval_service._rerank` | #4 |
| metadata 结构化过滤（location/work_type） | ✅ | `retrieval_service._apply_filters` | #4 |
| 结构化理由生成（matched_terms + reason） | ✅ | `retrieval_service._reason_text` | #4 |
| 44 条 USYD 结构化岗位语料 | ✅ | `data/job_postings.json` | #4 |
| 数据校验脚本 | ✅ | `scripts/ingest_jobs.py` | #6 |
| BM25 lexical 召回 | ❌ | — | #4 |
| RRF 融合（BM25 + 向量） | ❌ | — | #4 |
| 关键事件向量索引 | ❌ | — | #1 |

### 4.3 记忆与画像

| 能力 | 状态 | 代码入口 | 简历条 |
|---|---|---|---|
| SQLite 短期记忆（按 user_id 分流） | ✅ | `app/services/memory_service.py` | #1 |
| 用户偏好 profile + query augment | ✅ | `app/services/profile_service.py` | #1 |
| 长期职业画像（career_profiles 表） | ❌ | — | #1 |
| 关键事件抽取与沉淀 | ❌ | — | #1 |

### 4.4 工具与数据模型

| 能力 | 状态 | 代码入口 | 简历条 |
|---|---|---|---|
| get_candidate_profile | ✅ | `app/tools/candidate_tools.py` | #2 |
| get_resume_by_id | ✅ | `app/tools/candidate_tools.py` | #2 |
| search_jobs（含结构化 filter） | ✅ | `app/tools/job_tools.py` | #2 |
| match_resume_to_jobs | ✅ | `app/services/match_service.py` | #2 |
| ToolRegistry 声明式注册 | ✅ | `app/services/tool_registry.py` | #2, #6 |
| 投递记录数据模型 + API + 工具 (get_applications) | ✅ | `app/services/application_service.py` `app/tools/application_tools.py` | #2 |
| 面试反馈数据模型 + 工具 | ❌ | — | #2 |
| MCP 协议 SDK 接入 | ❌ | — | #2 |

### 4.5 工程基建

| 能力 | 状态 | 代码入口 | 简历条 |
|---|---|---|---|
| FastAPI 后端骨架 | ✅ | `app/main.py` | #6 |
| /chat 稳定 response contract | ✅ | `app/schemas/chat.py` | #6 |
| 静态 demo 单页（HTML/JS） | ✅ | `demo/` | #6 |
| evals 评测框架（16 条回归用例） | ✅ | `evals/` | #6 |
| source_field_all_contain 严格断言 | ✅ | `evals/run_eval.py` | #6 |
| React 双页面前端 | ❌ | — | #5, #6 |
| GPT-4V 图像输入 | ❌ | — | #5 |
| TTS 语音播报 | ❌ | — | #5 |

## 5. 从现状到简历北极星的任务清单

按**依赖关系**排列，不按"阶段"排列。每项标注解锁哪条简历声明。

### 5.1 无依赖（可并行）

| 任务 | 简历条 | 工程量 | 验收标准 |
|---|---|---|---|
| BM25 lexical 召回 + RRF 融合 | #4 | ~3 天 | eval 中至少 2 条 case 的召回质量因融合而提升 |
| ~~投递记录数据模型 + 服务 + 工具~~ | ~~#1, #2~~ | ~~完成~~ | ✅ `POST /applications` + `GET` + `PATCH` + `get_applications` 工具 + router 命中 |
| 面试反馈数据模型 + 服务 + 工具 | #1, #2 | ~5 天 | `POST /interviews` + `get_interview_feedback` 工具可用 |
| MCP 协议 SDK 接入 | #2 | ~3 天 | 外部 MCP 客户端能连上并调用 `search_jobs` |
| React 双页面（Query + Chat） | #5, #6 | ~2 周 | 前端能独立运行、调 /chat、展示 sources |

### 5.2 有依赖

| 任务 | 依赖 | 简历条 | 工程量 | 验收标准 |
|---|---|---|---|---|
| 长期职业画像存储 + 向量化 | 面试反馈模型 | #1 | ~5 天 | 画像字段能参与 query augment 并在回答中可见 |
| 关键事件抽取（LLM 提取 + 向量入库） | 长期画像 | #1, #4 | ~3 天 | 关键事件可被向量检索命中 |
| GPT-4V 图像输入（简历/JD 截图解析） | React 前端 | #5 | ~5 天 | 截图上传 → 结构化字段输出完整链路 |
| TTS 语音播报 | React 前端 | #5 | ~3 天 | 回答可语音播放 |

### 5.3 可选升级（不影响简历声明，但增强技术深度）

| 任务 | 依赖 | 工程量 | 说明 |
|---|---|---|---|
| ReAct observe 环节 | 5.1 基本完成 | ~3 天 | `_should_continue_after_step` 改为 LLM 判断 |
| Multi-Agent 拆分 + Orchestrator | ReAct | ~5 天 | AgentService 拆 N 个 sub-agent |
| CoT 显式推理链 | 无 | ~2 天 | Planner prompt 加 chain-of-thought |
| /chat contract 版本化 + schema 快照 | 无 | ~2 天 | `contract_version` 字段 + pytest schema snapshot |

## 6. 简历对照表

左列 = `docs/resume-target.md` 的 6 条声明；中列 = §4 能力清单的汇总状态；右列 = §5 任务清单的剩余工作。

| 简历条 | 当前完成度 | 还需要做什么 |
|---|---|---|
| #1 双层记忆 | 45% — 短期记忆 ✅，profile augment ✅，投递记录 ✅；长期画像 ❌，关键事件 ❌ | 面试反馈数据模型 → 长期画像 → 关键事件抽取 |
| #2 MCP 工具层 | 60% — 5 个工具 ✅（含 get_applications），ToolRegistry ✅；MCP 协议 ❌，面试反馈工具 ❌ | MCP SDK 接入 + 面试反馈工具 |
| #3 双层决策 + 可观测 | **90%** — Router ✅，Planner ✅，护栏 ✅，降级 ✅，trace ✅ | 基本完成，可打磨 |
| #4 混合召回 RAG | 60% — 向量召回 ✅，rerank ✅，metadata filter ✅，reason ✅；BM25 ❌，RRF ❌ | BM25 + RRF 融合 |
| #5 图像输入 + 多端交互 | **0%** — React ❌，GPT-4V ❌，TTS ❌ | React 双页面 → GPT-4V → TTS |
| #6 工程基建与评测 | 70% — FastAPI ✅，evals 16 条 ✅，ToolRegistry ✅；React ❌，MCP 导出 ❌ | React + MCP 导出 |

## 7. 架构升级路径

本节不是"现在要做"，而是"以后想做时翻到这里就知道从哪下手"。

### 7.1 Plan-Act → ReAct

当前 `_execute_plan` 是一次性拿到全部 steps 再顺序执行。升级成 ReAct 只需要在每步执行后加一个 LLM observe 环节：

- **切入点**：`AgentService._should_continue_after_step`
- **改法**：从规则判断改为调用 `LLMClient.observe(step, result, state)`，由模型决定继续/停止/重新规划
- **不需要动**：ToolRegistry、RetrievalService、MemoryService、ProfileService

### 7.2 单 Agent → Multi-Agent

当前 `AgentService` 是单 agent。升级路径：

- **切入点**：把 `AgentService` 拆为 `SearchAgent`、`ResumeAgent`、`InterviewAgent` 等 sub-agent
- **新增**：`OrchestratorAgent` 负责分发请求到对应 sub-agent
- **不需要动**：ToolRegistry（每个 sub-agent 拿自己的工具子集）、Memory、Retrieval、LLMClient

### 7.3 为什么现有架构支持升级

因为**能力层和决策层是分开的**：

```
决策层（可替换）: Router / Planner / ReAct observe / Orchestrator
    ↕ 只通过 plan steps + tool payloads 通信
能力层（稳定）:   ToolRegistry / RetrievalService / MemoryService
```

决策层怎么换都行，能力层不用改。这是整个项目的核心架构约束。

## 8. 一句话总结

项目当前是一个底座稳固、决策层可插拔的求职辅导 Agent 后端。近期目标是把简历北极星（`docs/resume-target.md`）上每一条都做到面试抗打；终局目标是在稳定能力边界之上收口成真 Agent。
