# 智能求职辅导 Agent：项目现状与路线图

## 1. 当前项目定位

当前项目已经不是一个纯概念性的 PRD，而是一个已经完成核心后端底座的 Agent MVP 雏形。

它目前最准确的定位是：

`一个具备 Agent 编排、短期记忆、检索增强、SQLite 持久化与 ChromaDB 检索能力的求职辅导后端系统`

这意味着项目已经进入“能持续迭代真实业务流”的阶段，而不只是方案设计阶段。

## 2. 已完成内容

### 2.1 后端骨架

已经完成基于 `FastAPI` 的后端基础结构，核心入口位于：

- `app/main.py`
- `app/api/`
- `app/services/`
- `app/db/`
- `app/llm/`

当前已经具备基础路由：

- `GET /health`
- `POST /chat`
- `GET /candidates`
- `GET /jobs`

### 2.2 Agent 主链路

`/chat` 已经不是固定 mock 接口，而是接入了最小 Agent 编排流程：

1. 接收用户问题
2. 读取短期记忆
3. 调用检索服务获取证据
4. 调用 LLM fallback 生成回答
5. 回写本轮对话到记忆

核心文件：

- `app/api/chat.py`
- `app/services/agent_service.py`
- `app/llm/client.py`

### 2.3 短期记忆系统

短期记忆已经从进程内内存升级为 SQLite 持久化。

当前能力包括：

- 按 `user_id` 保存对话轮次
- 多实例重启后仍能读取最近消息
- 自动保留最近 N 条消息，避免上下文无限膨胀

核心文件：

- `app/services/memory_service.py`
- `app/db/session.py`

### 2.4 检索层

检索层已经接入 `ChromaDB`，不是单纯的关键词 mock。

当前实现包括：

- 本地岗位样例数据写入 Chroma collection
- 本地 deterministic embedding function
- 检索结果召回
- 轻量 rerank，提升小样本排序质量

核心文件：

- `app/services/retrieval_service.py`
- `data/job_postings.json`

### 2.5 数据层

当前 SQLite 中已经初始化了基础表：

- `conversation_turns`
- `candidates`
- `job_postings`

并且已经有最小服务层支持候选人与岗位数据读写：

- `app/services/candidate_service.py`
- `app/services/job_service.py`

### 2.6 测试基础

当前已经建立了基础测试体系，覆盖：

- app 接口行为
- memory 持久化行为
- retrieval 检索行为

测试文件：

- `tests/test_app.py`
- `tests/test_memory_service.py`
- `tests/test_retrieval_service.py`

当前验证命令：

```bash
python3 -m pytest tests/test_app.py tests/test_memory_service.py tests/test_retrieval_service.py -v
```

## 3. 当前架构理解

可以把整个项目理解为 5 层结构。

### 3.1 API 层

位置：

- `app/api/`

职责：

- 接收 HTTP 请求
- 参数校验
- 调用 service
- 返回响应

这一层不承载复杂业务逻辑。

### 3.2 编排层

位置：

- `app/services/agent_service.py`

职责：

- 作为 Agent 主控入口
- 串联记忆、检索、模型调用
- 组织“问题 -> 证据 -> 回答 -> 记忆”的主链路

这是当前项目的核心调度层。

### 3.3 能力层

位置：

- `app/services/memory_service.py`
- `app/services/retrieval_service.py`
- `app/services/candidate_service.py`
- `app/services/job_service.py`

职责：

- `memory_service`：短期记忆管理
- `retrieval_service`：岗位数据检索与 Chroma 查询
- `candidate_service`：候选人数据读写
- `job_service`：岗位数据读写

### 3.4 模型层

位置：

- `app/llm/`

职责：

- 统一模型调用入口
- 承担 fallback 响应逻辑
- 后续承接真实 OpenAI API 调用

### 3.5 存储层

位置：

- `SQLite`
- `ChromaDB`
- `data/`

职责：

- SQLite：结构化业务数据、对话记忆
- ChromaDB：岗位向量检索
- data：本地数据文件和持久化数据目录

## 4. 对照 PRD 的完成情况

### 4.1 已经落地的方向

- Agent 主问答接口
- 短期记忆
- 检索增强基础能力
- 候选人与岗位基础数据管理雏形
- 后端服务架构

### 4.2 已有架构预留但未完全落地

- 长期职业画像
- 关键事件沉淀
- 模块化 MCP Server
- 更完整的 Agent 规划与推理
- 多模态输入输出

### 4.3 尚未开始或尚未完成的重点业务流

- 简历、项目经历、投递记录、面试反馈的数据模型
- 简历优化完整链路
- 面试复盘完整链路
- React 前端

补充说明：

- `POST /candidates`
- `POST /jobs`
- `POST /resumes`

这些基础写入接口现在已经存在，因此这一部分不再属于“尚未开始”。当前真正未完成的重点，已经转向更完整的数据模型、更多求职场景闭环，以及产品化前端。

## 5. 对照简历表述的完成情况

### 5.1 可以较稳地写“已完成”的内容

- FastAPI 后端骨架设计
- Agent 主链路雏形
- SQLite 短期记忆持久化
- ChromaDB 检索层
- 候选人 / 岗位基础数据层

### 5.2 可以写“已完成基础架构，正在增强”的内容

- 分层记忆架构
- 检索增强生成
- 智能规划与推理
- 模块化工程设计

### 5.3 暂时不建议写成“已完成”的内容

- 真正模块化 MCP Server
- React 前端页面
- 多模态输入与语音播报
- 长期记忆与关键事件抽取
- 完整 ReAct / CoT / 自我一致性

## 6. 新版开发路线

后续开发的终局目标不变，仍然是：`做真 Agent，而不是继续堆硬编码 workflow。`

但执行顺序需要调整。

当前项目最需要修正的问题，不是“方向错了”，而是“过早把终局架构当前线化”。也就是说，在单场景闭环还没有跑顺、工具边界和结果质量还没有稳定之前，就过早把大量精力投入到了 planner、动态路由、Agent 编排和系统化抽象上。

这里有一个需要明确写下来的“醒悟点”：

- 之前的问题，不是因为我们想做 Agent 这件事本身错了，而是因为让 planner 过早站到了第一决策层
- 在当前阶段，明显业务场景应该先走稳定、可测、可解释的规则入口，把闭环结果先做实
- planner 在这个阶段仍然保留，但职责应当退到灰区问题和兜底补充，而不是主导所有请求

这次调整因此不是“回退成硬编码 workflow”，而是一次实现顺序的纠偏：

- 终局仍然是 Agent
- 但阶段 A / B 的代码执行策略应当优先保证闭环稳定，再把 planner 逐步抬回主线
- 如果一个能力在拿掉 planner 后仍然成立，那它才值得优先进入当前主线

新的路线图因此采用一条新的主线：

`先验证单场景闭环 -> 再沉淀稳定能力 -> 再收口成 Agent -> 最后做产品化扩展`

### 6.0 新的总原则

当前底座继续保留，不推翻：

- tools
- tool registry
- retrieval
- memory
- profile
- planner / executor 骨架
- trace

但从现在开始，近期 2~3 个阶段不再以 planner 为主线，而以“单场景闭环验证”为主线。

这不是放弃 Agent 方向，而是重新调整实现顺序：

- 终局仍然是 Agent
- 近期重点不再是强化 planner
- 近期重点是证明一个真实业务闭环可以稳定产出高质量结果

这里增加四条新原则：

1. 先证明单场景有效，再抽象成通用 Agent 能力
2. planner 不是起点，而是稳定能力之上的调度层
3. 任何抽象都必须服务于已验证闭环，不能为了 Agent 感而提前系统化
4. 如果拿掉 planner，这一步依然有价值，它才值得现在做

后续每一步都用下面四个问题判断是否应该进入主线：

- 这一步是否让单场景结果更稳定？
- 这一步是否让输出更可解释、可评估？
- 这一步是否沉淀了未来 Agent 可复用的能力边界？
- 如果暂时拿掉 planner，这一步是否仍然值得做？

如果这些问题大部分回答都是否定的，那这一步就不应该放在当前主线里。

### 阶段 A：闭环验证期

目标：

- 只选一个最核心的业务场景
- 跑通输入 -> 检索或工具 -> 理由 -> 输出的完整链路
- 让结果稳定、可解释、可演示、可测试

当前建议聚焦场景：

- `岗位搜索 + 推荐理由`

该闭环当前对应的真实产品背景，是 `University of Sydney Career Hub`。因此这一阶段默认产品语境不是“无限开放的全局求职搜索”，而是优先围绕 `Sydney / University of Sydney` 相关岗位机会建立 `search first, then refine` 的稳定体验。

这一阶段的重点不是“像不像 Agent”，而是“结果有没有用”。

具体要求：

- 用户输入一个求职问题，系统能稳定返回相关岗位
- 返回结果不只是列表，还要有推荐理由
- 推荐理由必须尽量建立在检索证据之上，而不是纯口头生成
- API 输出结构要稳定，方便测试和后续复用
- 至少有一条可以稳定演示的 happy path

这一阶段明确不追求：

- 通用 planner
- 多步 ReAct
- 复杂动态工具路由
- MCP 标准化输出
- 多场景统一调度

当前状态判断：

- `岗位搜索 + 推荐理由` 这条闭环已经基本跑通：
  - 明显 query 已切到 `router-first`
  - `job_search` 已按 `search first, then refine` 执行
  - 已加入 `Sydney / University of Sydney` 默认语境增强
  - 推荐结果已带结构化理由，不再只是岗位列表或匹配分数
- 因此阶段 A 可以视为基本完成，当前更适合进入阶段 B：把已经验证有效的边界、contract 和可观测性沉淀下来

### 阶段 B：能力沉淀期

目标：

- 把闭环中验证有效的部分沉淀成稳定能力
- 先固定边界，再谈调度

这一阶段重点沉淀的能力包括：

- retrieval 的输出结构
- `search_jobs` 等核心 tool 的输入输出 contract
- response schema
- 推荐理由的生成方式
- profile / memory 如何参与搜索和解释

这一阶段的核心思想是：

不是先定义一个宏大的 Agent 抽象，再让业务去适配它；
而是先把已经被验证过的业务能力整理成清晰边界，再让 Agent 来调度这些能力。

具体要求：

- 核心 tool 的返回字段稳定
- 核心场景的回答格式稳定
- 测试开始围绕“结果质量”和“结构 contract”而不是围绕内部流程
- 能明确区分哪些逻辑属于 retrieval，哪些属于 tool，哪些属于 answer synthesis

当前状态判断：

- 现在已经进入这一阶段的起点，当前优先沉淀的内容应包括：
  - 用户级 candidate / resume 绑定边界
  - `search_jobs` 的 query augmentation 规则
  - 推荐理由输出 contract
  - `/chat` 返回中的 `plan / tool_trace / source trace` 可观测性

### 阶段 C：Agent 收口期

目标：

- 在稳定能力边界之上，重新引入 planner / replanning / routing
- 把系统从“闭环能力集合”收口成“模型主导、工具执行”的 Agent

这个阶段才是真正开始强化 Agent 特性的阶段。

planner 在这一阶段的职责应当是：

- 判断当前问题需要哪些能力
- 选择工具
- 组织多步执行
- 在必要时进行 replanning
- 做结果整合和总结

这一阶段的前提条件：

- 至少一个核心场景已经稳定
- tools 的输入输出结构已经固定
- response contract 已经明确
- 可以清楚评估 planner 带来的增益，而不是把所有问题都归因到模型本身

只有满足这些前提，planner 的输出质量问题才值得被当作主问题来解决。

### 阶段 D：长期记忆与个性化增强

目标：

- 让长期记忆真正影响建议质量，而不只是作为附加信息存在

这一阶段应重点建设：

- 长期职业画像
- 技能强弱项总结
- 岗位偏好与职业方向偏好
- 历史关键事件和阶段性目标

这一阶段的价值在于：

- 让系统从“能回答问题”升级成“能持续陪跑”

注意：

- 记忆增强应该服务于已经验证过的业务场景
- 不应在场景质量尚不稳定时过早堆长期记忆抽象

### 阶段 E：扩核心求职场景

目标：

- 在第一个闭环稳定后，逐步扩展更多高价值求职场景

建议顺序：

1. 岗位匹配
2. 简历优化
3. 面试复盘

每个场景都应形成结构化输出：

- 结果
- 理由
- 缺口
- 下一步建议

这里的原则是：

- 每次只扩一个场景
- 每个新场景都先完成闭环验证，再进入能力沉淀和 Agent 收口

### 阶段 F：产品化扩展

目标：

- 在 Agent 主链路和核心场景稳定后，再推进产品化与工程化扩展

包括：

- MCP Server 化
- React 前端
- 多模态输入输出

这里的优先顺序不再由“看起来先进”决定，而由“是否服务于稳定闭环与可演示价值”决定。

## 7. 新的推荐优先级

如果从“最适合当前项目状态，也最有助于最终做成真 Agent”的角度排序，建议优先级改为：

1. 做实一个单场景闭环，优先 `岗位搜索 + 推荐理由`
2. 固定 retrieval / tool / response 的稳定边界
3. 让输出结果可解释、可评估、可测试
4. 在稳定边界之上重新收口 planner / routing / replanning
5. 让长期记忆真正参与高质量结果生成
6. 扩展第二、第三个核心求职场景
7. 再做 MCP、前端、多模态等产品化扩展

## 8. 一句话总结

当前项目下一阶段的重点，不是继续强化 planner，而是先用一个高质量单场景闭环纠正实现顺序，再在稳定能力边界之上重新收口成真 Agent。
