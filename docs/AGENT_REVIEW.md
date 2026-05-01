# Agent 项目深度审视 + 面试准备 + 接下来要做的事

> 写作时间：2026-05-01
> 目标：简历有底气、能经受拷打、做出有用的东西、有合作潜力

---

## 一、当前项目总结（Agent 模块视角）

**项目定位：** 面向 USYD 学生的求职辅导 Agent，基于 DashScope (Qwen) + FastAPI + React，采用真正的 LLM function calling ReAct 循环。

---

### 各模块现状

**Planning / Reasoning**
LLM 直接看到所有工具 schema，自主决定调用哪些工具、以什么顺序、传什么参数。这是真 ReAct，不是 intent classifier 预先决定路径再走固定链。硬上限 MAX_ITERATIONS=6 防止死循环。

**Memory**
两层：Short-term 是 SQLite 滚动存储最近 6 轮对话，每次请求注入 messages 列表。Long-term 是 Goal 持久化，用户设定的求职目标跨 session 保留，并在 system prompt 里注入当前目标状态，agent 会主动跟进进展。

⚠️ **这是整个项目最水的模块。** 6 轮滚动窗口是 LangChain 入门教程第一章的标准实现。对一个定位「长期陪伴求职」的 agent，memory 设计和产品定位是矛盾的——用户说过的偏好、历史行为、隐性信号，全部在第 7 轮之后消失。Goal tracking 是加分项，但本质是 SQLite 里的 to-do list，不是真正的 agent memory。没有 semantic/episodic memory，没有用户偏好建模，没有跨 session 的行为归纳。

**Tools**
Registry 模式，Pydantic 做输入校验，工具返回统一的 `ToolResult` 结构。现有工具：`get_goals / set_goal / log_progress / update_goal_status / search_jobs / get_resume / analyze_gap / get_candidate_profile / get_applications / get_interviews / match_resume_to_jobs`。LLM 读 tool error dict 后会自行解释给用户，不会崩溃。

**Retrieval / RAG**
Hybrid retrieval：ChromaDB 向量召回 + BM25 词法召回 + RRF 融合排序。Embedding 用 DashScope text-embedding-v3（1024 维），踩过维度 mismatch 的坑并做了自动恢复。

⚠️ **数据是假的。** RAG 技术实现是真实的，但检索的是手工 seed 进去的几十条假岗位数据。用户搜「Sydney data science intern」，结果来自手写样本，不是真实市场。这是整个项目最大的产品硬伤，技术上的 hybrid retrieval 含金量被数据的空洞性大幅抵消。

**analyze_gap Tool**
接收 user_id + jd_text，自动拉取简历，调 LLM 输出匹配度、已匹配技能、差距、建议。

⚠️ **实现是浅的。** 本质是 `llm.simple_chat(system="你是gap分析专家", user=简历+JD)`，没有结构化评分模型，没有技能分类体系，没有可量化的 match score 计算逻辑。包了一层 tool 接口，看起来是个功能，但懂的人一眼看穿是一个 prompt。输出是自由文本，无法被下游程序消费。

**Perception**
集成 Qwen-VL，支持简历图片上传 → 结构化解析（姓名、教育、技能、项目经历提取）。

**Streaming / UX**
SSE 实时推状态事件（`🤔 正在思考` → `🔧 调用工具：analyze_gap`），asyncio.Queue + call_soon_threadsafe 做线程安全桥。最终 answer 一次性输出（非流式）。

---

## 二、面试准备（以面试官视角模拟）

---

**Q1：介绍一下你的 agent 架构。**

> "核心是一个 ReAct 循环。每次用户发消息，系统先从 DB 拉取 goal 状态和最近 6 轮对话注入 system prompt，然后把所有工具 schema 传给 LLM，让它自主决定调用哪些工具。工具结果 append 回 messages，LLM 继续决策，直到它产出 final answer 或触发 6 次上限。"

考点：面试官想听到你知道这不是 chain，是 loop。

---

**Q2：为什么用 function calling 而不是 intent classifier？**

> "Intent classifier 本质是把 agent 退化成 router：先分类意图，再走预设工具链。它有两个根本问题：一是分类错了整条链就错了，二是用户意图模糊或复合时（比如'帮我看看这个 JD 适不适合我，顺便找几个类似的岗位'），固定链根本走不通。Function calling 让 LLM 直接看到所有工具能力，根据当前上下文动态决策，复合意图自然就拆成多步工具调用了。代价是多一点 latency，但收益是真正的自主性。"

---

**Q3：你的 memory 是怎么设计的，有什么局限？**

主动说出局限，不要等面试官挖，主动坦诚反而加分。

> "分两层。Short-term 是滚动 6 轮对话历史，每次请求都注入，解决多轮理解问题。Long-term 是 goal persistence，用户的求职目标跨 session 保存，agent 每次知道用户在追什么目标。但坦白说，这个 memory 是整个项目最薄弱的地方——6 轮窗口对长期陪伴型 agent 来说太短了，用户的隐性偏好（比如偏好远程、不想去外企）没有被提取和存储，下次对话完全丢失。如果要做 semantic memory，我会考虑每轮对话结束后提取关键偏好信号存进 user profile，或者用向量库做长期记忆检索。"

---

**Q4：RAG 怎么做的，为什么 hybrid？**

> "纯向量检索的经典失败场景是精确技术词召回不准——'FastAPI'、'vLLM' 在向量空间里可能被语义相近的词稀释。BM25 做词法匹配补这个盲区。两路用 RRF 融合，好处是不需要对两路分数归一化，直接用排名位置，鲁棒性更好。不过现在有个产品层面的局限：检索的岗位数据是手工 seed 的样本，不是真实爬取的，下一步计划通过 MCP 接入真实数据源来解决这个问题。"

---

**Q5：analyze_gap 是怎么实现的？**

面试官大概率会追问这个，提前准备好诚实的回答。

> "现在的实现是：拉取用户简历，拼接 JD，用一个专门设计的 system prompt 让 LLM 做对比分析，输出匹配度、已匹配技能、差距和建议。坦白说这是一个重度依赖 LLM 能力的实现，没有独立的评分模型或技能分类体系。如果要做得更扎实，应该先做技能提取（结构化为技能列表），再做显式的集合对比，最后 LLM 只负责解释和建议，这样输出是可量化、可程序消费的。这是接下来的改进方向。"

---

**Q6：agent 最大的挑战是什么，怎么解决的？**

挑真实踩过的坑，比无中生有的挑战更有说服力。

> "有三个印象深刻的。第一是 ChromaDB 维度 mismatch，embedding 模型换了但旧 collection 的维度还是 256，upsert 时才报错，解决方案是 seed 时捕获维度异常，自动删除旧 collection 重建。第二是 SSE 里的线程安全：svc.respond() 跑在 thread pool 里，不能直接 yield SSE，得用 asyncio.Queue + call_soon_threadsafe 桥接。第三是 LLM 不知道用户的 user_id 该传什么——system prompt 不写清楚，它会瞎填，工具永远找不到对应数据。"

---

**Q7：为什么要做 MCP server？**

> "两个原因。第一，工具层标准化：现在 ToolRegistry 是私有接口，把它改成 MCP server 之后，任何支持 MCP 的系统（比如 USYD Careerhub 的其他服务）都可以直接接入我的工具，这是对外合作的基础。第二，解决数据问题：通过 MCP 接入真实招聘数据源，替换掉现在手工 seed 的假数据，这样 search_jobs 才是真正有用的工具。两件事一步棋完成，不是为了技术而技术。"

---

**Q8：如果这个 agent 要上生产，你会改什么？**

> "主要四件事。第一，memory 重设计：现在 6 轮窗口太短，需要做用户偏好提取 + semantic memory。第二，接真实数据：现在岗位数据是假的，通过 MCP 接公开招聘 API。第三，context 管理：messages 无限增长会超 context window，需要超长对话摘要截断。第四，observability：现在没有 LLM call tracing，出问题只能靠 print，应该接结构化日志。"

---

## 三、最水的三个部分（必须能在面试中坦然承认）

**第一水：Memory**

6 轮滚动窗口是教程级实现。没有 semantic memory，没有用户偏好建模，没有跨 session 行为归纳。对「长期陪伴求职」这个产品定位，memory 是最核心的能力，也是现在最空洞的地方。

面试官问「你怎么记住用户跨 session 的偏好」，现在只能回答「通过 goals 表记录目标」——这个回答在懂的人耳朵里是减分的。

**第二水：analyze_gap 实现**

本质是 `llm.simple_chat(system="你是gap专家", user=简历+JD)`，输出是自由文本。没有结构化评分、没有技能分类体系、没有可量化的 match score。包了一层 tool 接口，但核心是一个 prompt。

**第三水：岗位数据是假的**

Hybrid RAG 的技术实现是真的，但跑在手工 seed 的几十条样本上。这是产品层面最大的硬伤——用户真实搜索会发现岗位结果和市场脱节。

---

## 四、其他缺失问题

### 技术层面

| 缺失 | 严重程度 | 说明 |
|------|----------|------|
| Final answer 不流式 | 高 | analyze_gap 等重工具 30s 后文字全部出现，体验差 |
| Context 无上限增长 | 高 | 多轮对话后 messages 超长，token 超限会直接报错 |
| 无 Observability | 中 | 没有 LLM call tracing，生产排查靠猜 |
| 无 Reflection | 中 | Agent 回答后不知道自己答没答对，无自我纠错 |
| 无 Retry | 中 | DashScope 偶发超时直接失败 |
| 死代码 AgentService | 低 | 旧的 planner→executor→generator 链还在，迷惑读代码的人 |

### 产品 + 工程化层面

**没有真实数据源。** search_jobs 检索的是假数据，用户体验到的「搜索」是无效的。

**产品场景未打磨。** 用户第一次来怎么 onboard？没有简历怎么引导？目标是全职还是实习，agent 的策略有区别吗？这些场景没有设计。

**没有认证。** user_id 是前端自填字符串，没有鉴权。真实合作的第一个问题就是用户数据隔离。

**没有反馈回路。** 用户觉得回答好不好，没有任何采集机制，agent 无法迭代。

---

## 五、接下来要做的事（按优先级）

---

### P0：写 README + 清理死代码（可以在 push 之前做）

- README 写架构决策、踩坑记录、诚实承认的局限，不写假数字
- 隔离或删除旧 AgentService（旧的 planner→executor→generator 链）
- 这两件事让项目「看起来是认真做的」

---

### P1：MCP server 改造（核心，解决工具标准化 + 真实数据两个问题）

**第一步：把 ToolRegistry 改造成 MCP server（优先）**

现有 ToolRegistry 已经是很好的抽象基础，每个 ToolDefinition 有 name、description、input_model、handler，天然对应 MCP tool 的 schema。

改造思路：
- 引入 `mcp` Python SDK（`pip install mcp`）
- 把每个 ToolDefinition 注册为 MCP tool
- 暴露 stdio transport（本地调用）或 HTTP/SSE transport（远程集成）
- AutonomousAgentService 通过 MCP 协议调工具，而不是直接调 registry

改造后的能力：
- 任何支持 MCP 的 agent / client（Claude Code、其他 LLM 框架）都能直接调用这些工具
- USYD Careerhub 如果要集成，不需要改你的代码，直接接 MCP
- 面试时能说「工具层是标准化的 MCP 接口，不是私有 API」

**第二步：通过 MCP 接入真实数据源（接着做，解决假数据问题）**

目标：替换 search_jobs 的假数据，接入真实澳洲招聘数据。

调研方向：
- Seek.com.au 是否有公开 API 或第三方 MCP wrapper
- GitHub Jobs / LinkedIn Jobs 公开接口
- 实在没有合适的 MCP server，自己写一个轻量爬虫包装成 MCP server（Seek 搜索结果解析）

改造后：用户搜「Sydney fintech backend intern」，结果是真实的市面岗位。这是产品从玩具变成有用工具的分界线。

---

### P2：补最水的技术短板

**Memory 重设计**

每轮对话结束后，提取关键偏好信号（工作地点偏好、行业偏好、薪资范围、时间线等），存进 user_profile 表。下次对话时注入 system prompt，agent 才能真正「记住你」。

```
对话结束 → LLM 提取偏好信号 → 写入 user_profile
下次对话 → 读取 user_profile → 注入 system prompt
```

**analyze_gap 结构化**

改成三步：
1. 从简历和 JD 各提取技能列表（结构化 JSON）
2. 做显式集合对比（intersection / difference）
3. LLM 只负责解释差距和给建议

这样输出有 match_score（可量化）、matched_skills（列表）、missing_skills（列表），可以被前端渲染成卡片，不只是一段文字。

---

### P3：工程化补全

- Final answer streaming（LLM stream=True + SSE token 逐字推送）
- Context 截断策略（messages 超过阈值时保留 system prompt + 最近 N 轮 + 当前）
- DashScope 调用加 Retry（指数退避 2-3 次）
- 结构化日志（每次 LLM call 记 latency、model、tool_called）

---

### P4：合作潜力基础设施

- Docker Compose 一键启动
- 基本认证（user_id 从 token 解，不是前端自填）
- 用户反馈机制（thumbs up/down 存表，为后续 RLHF 做准备）

---

## 六、执行顺序总览

```
现在（已完成）：
  ✅ 真 ReAct function calling 循环
  ✅ Goal 持久化 + 跨 session 目标感知
  ✅ analyze_gap 工具（v1，prompt 版）
  ✅ Hybrid RAG（ChromaDB + BM25 + RRF）
  ✅ SSE 实时状态流
  ✅ UX bug 修复（前端 SSE 解析、system prompt bug）

接下来：
  → P0：README + 清理死代码 → push to GitHub
  → P1a：ToolRegistry 改造成 MCP server
  → P1b：MCP 接入真实招聘数据
  → P2a：Memory 重设计（user profile 提取）
  → P2b：analyze_gap 结构化输出
  → P3：工程化（streaming answer / retry / 日志）
  → P4：合作基础设施（Docker / 认证 / 反馈）
```

---

## 七、简历怎么讲这个项目

**现在可以说的（诚实版）：**

> "基于 DashScope Qwen + FastAPI + React 构建了一个求职辅导 Agent。核心是真正的 LLM function calling ReAct 循环——LLM 自主决定调用哪些工具（岗位搜索、简历分析、gap 分析、目标管理），不是 intent classifier 预定路径。实现了 Hybrid RAG（ChromaDB 向量 + BM25 + RRF 融合）、跨 session goal 持久化、SSE 实时工具调用状态流。踩过的坑包括 DashScope embedding 维度 mismatch 自动恢复、asyncio 线程安全 SSE 桥、LLM 上下文感知设计。"

**完成 MCP 改造后可以加的：**

> "将工具层标准化为 MCP server，接入真实澳洲招聘数据，使 search_jobs 从假数据变为真实市场结果。"

**面试时的核心竞争力：**
- 能清楚说明「真 ReAct vs 假 ReAct」的区别，并且自己做的是真的
- 能主动说出项目最水的地方（memory 最浅、analyze_gap 是个 prompt、数据假）并说明改进方向
- 踩过真实的工程坑（维度 mismatch、线程安全、context 感知），有细节可以讲

---

*最后更新：2026-05-01*
