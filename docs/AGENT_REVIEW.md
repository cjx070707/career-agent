# Agent 项目深度审视 + 面试准备 + 接下来要做的事

> 最后更新：2026-05-03
> 项目状态：已完成，P4 demo 验收通过
> 目标：简历有底气、能经受拷打、做出有用的东西、有合作潜力

---

## 一、当前项目总结（Agent 模块视角）

**项目定位：** 面向 USYD 学生的求职辅导 Agent，基于 DashScope (Qwen) + FastAPI + React，采用真正的 LLM function calling ReAct 循环。

---

### 各模块现状（2026-05-03 最终状态）

**Planning / Reasoning**
LLM 直接看到所有工具 schema，自主决定调用哪些工具、以什么顺序、传什么参数。真 ReAct，不是 intent classifier。硬上限 MAX_ITERATIONS=6 防止死循环。

**Memory（四层注入，已完成）**
```
system prompt
  └── user_profile（长期偏好，跨 session 永久保留）
  └── goals（当前目标，跨 session 持久化）
  └── running summary（超 24 turns 自动 LLM 压缩）
  └── recent messages（滚动 12 turns 原文）
```
每轮对话结束后异步提取偏好（地点/行业/薪资/时间线）写入 `user_profiles` 表，下次对话注入。

**Tools（11 个，已完成）**
Registry 模式，Pydantic 输入校验，统一 ToolResult 结构。工具描述是 LLM 的决策依据，需显式说明内部行为（如 analyze_gap 会自动按 user_id 查简历）。

**Retrieval / RAG**
Hybrid retrieval：ChromaDB 向量召回 + BM25 词法召回 + RRF 融合排序。Embedding 用 DashScope text-embedding-v3（1024 维）。
数据：55 条 Adzuna 真实岗位（悉尼/墨尔本），P4 验收通过，demo 路径覆盖正常。

**analyze_gap Tool（已结构化）**
接收 user_id + jd_text，自动拉取简历，LLM 输出结构化 JSON：
```json
{"match_score": 85, "matched_skills": [...], "missing_skills": [...], "suggestions": [...]}
```
P4 验收：match_score 85，输出可被前端渲染，不再是自由文本。

**Perception**
Qwen-VL，简历图片上传 → 结构化解析。这是 demo 里写入简历的主路径。

**Streaming / UX**
SSE 实时状态流（`🤔 正在思考` → `🔧 调用工具`）+ Final answer token-by-token 流式输出。asyncio.Queue + call_soon_threadsafe 线程安全桥。

**Eval（已完成，两层体系）**

层 1（工具路由 + 关键词断言）：`evals/run_eval.py`
- 37 cases 覆盖：搜索、gap 分析、多轮对话、负向拒绝、简历/应用/面试查询
- 基线（2026-05-05，qwen3.5-plus-2026-04-20）：**30/37 通过，pass_rate = 81%**
- 支持 `EVAL_USE_ADZUNA_MOCK=1` 隔离外部 API 依赖

层 2（LLM-as-Judge 质量评估）：`evals/run_judge_eval.py`
- 4 维度：工具合理性 / 答案针对性 / 无幻觉 / coaching 语气，每维 1-5 分
- 合格门槛：各维均分 ≥ 3.5，且无幻觉单项 ≥ 4

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

> "四层：短期 12 turns 原文、goal 持久化、running summary（24 turns 触发 LLM 压缩）、user_profile 偏好提取。每轮对话结束后异步提取偏好（地点/行业/薪资）写入 user_profiles 表，下次对话注入 system prompt。局限是 user_profile 提取没有做端到端验收，提取质量依赖 LLM 能力，没有量化评估；另外 running summary 是按轮次触发而非按 token 量触发，对话很短但信息量大时可能压缩过早。"

---

**Q4：RAG 怎么做的，为什么 hybrid？**

> "纯向量检索的经典失败场景是精确技术词召回不准——'FastAPI'、'vLLM' 在向量空间里可能被语义相近的词稀释。BM25 做词法匹配补这个盲区。两路用 RRF 融合，好处是不需要对两路分数归一化，直接用排名位置，鲁棒性更好。数据层面用的是 CareerHub 内部 API——通过 JobProvider Protocol 抽象，search_jobs 工具调用时实时获取当前在架岗位，数据不在我们侧存储。"

---

**Q5：analyze_gap 是怎么实现的？**

面试官大概率会追问这个，提前准备好诚实的回答。

> "按 user_id 自动拉取最新简历，拼接 JD，LLM 输出结构化 JSON：match_score（0-100）、matched_skills、missing_skills、suggestions。P4 验收跑出 85 分，输出直接被前端渲染。坦白说评分逻辑在 LLM 内部，没有独立的技能分类体系——如果要更扎实，应该先结构化提取技能列表，再做显式集合对比，LLM 只负责解释。这是下一步的改进方向，当前实现对 demo 场景够用。"

---

**Q6：agent 最大的挑战是什么，怎么解决的？**

挑真实踩过的坑，比无中生有的挑战更有说服力。

> "有三个印象深刻的。第一是 ChromaDB 维度 mismatch，embedding 模型换了但旧 collection 的维度还是 256，upsert 时才报错，解决方案是 seed 时捕获维度异常，自动删除旧 collection 重建。第二是 SSE 里的线程安全：svc.respond() 跑在 thread pool 里，不能直接 yield SSE，得用 asyncio.Queue + call_soon_threadsafe 桥接。第三是 LLM 不知道用户的 user_id 该传什么——system prompt 不写清楚，它会瞎填，工具永远找不到对应数据。"

---

**Q7：为什么要做 MCP server？**

> "两个原因。第一，工具层标准化：现在 ToolRegistry 是私有接口，把它改成 MCP server 之后，任何支持 MCP 的系统（比如 USYD Careerhub 的其他服务）都可以直接接入我的工具，这是对外合作的基础。第二，解决数据问题：通过 MCP 接入真实招聘数据源，替换掉现在手工 seed 的假数据，这样 search_jobs 才是真正有用的工具。两件事一步棋完成，不是为了技术而技术。"

---

**Q8：如果这个 agent 要上生产，你会改什么？**

> "按优先级分三层。第一层是上线前必须做的：SQLite 换 PostgreSQL（高峰期并发写会触发写锁超时，agent 失忆）；slowapi 的 rate limiting 换 Redis backend（多 worker 进程内存不共享，限速形同虚设）；加 per-user chat lock（Redis SETNX），防止同一用户并发 LLM 调用打爆 DashScope 配额；ChromaDB 换 server mode（多进程直接读写文件会 corrupt）。第二层是上线后根据真实数据再做：DashScope retry、JWT 认证、读写分离。第三层是有用户反馈之后再做：用户 thumbs up/down 存表、user_profile 提取质量 eval。提前做第二三层是过度工程。"

---

## 三、已知局限（面试时坦然承认）

**第一：简历上传依赖前端图片上传，无纯对话流程**

用户没有办法在对话里直接说"我的简历是 XXX"然后存入系统。必须通过 Qwen-VL 图片上传路径写入数据库，这是产品完整性的硬缺口。生产环境应该支持文本粘贴直接存简历。

**第二：analyze_gap 评分在 LLM 内部，不可解释**

match_score 是 LLM 给的整数，没有独立的技能分类体系和集合对比逻辑。如果用户质疑"为什么是 85 分"，无法给出可追溯的计算依据。对 demo 够用，对生产不够严谨。

**第三：user_profile 偏好提取没有量化验收**

每轮后 LLM 提取偏好存库，但提取质量没有 eval 数字支撑——不知道提取准不准、遗漏率多少、下次对话是否真的用上了。这是现在最不透明的模块。

---

## 四、产品层面缺失（对标 ChatGPT/Claude 基本产品标准）

### 基本功能缺失（P0）

| 缺失 | 说明 |
|------|------|
| 历史对话不可见 | 数据在 SQLite，但前端每次刷新从空白开始，历史消失 |
| user_id 手填 | 用户换设备换身份，历史全没。应 localStorage 自动生成 UUID |
| 无历史对话列表 | 无法切换、回顾历史会话 |
| 无新对话按钮 | 用户想重新开始只能刷新，体验断裂 |

### 对话体验残缺（P1）

| 缺失 | 说明 |
|------|------|
| agent 回答无格式 | Markdown 原文显示，`**加粗**` `\n` 等字符直接可见 |
| 消息无法重发/编辑 | 打错字只能重新输入 |
| 工具调用状态转瞬消失 | 用户看不懂发生了什么，无法回溯 |
| 岗位/gap 结果是纯文字 | sources 已有结构化数据，应渲染成卡片/进度条 |
| 无错误恢复 UI | 后端超时前端显示什么？目前是未定义行为 |

### 新用户体验（P2）

| 缺失 | 说明 |
|------|------|
| 无 onboarding | 空白输入框，用户不知道能做什么 |
| 无简历上传引导 | 用户不知道需要先传简历，ask gap 分析直接报错 |
| 聊天框不支持图片/PDF | 只能手动调 API 或操作数据库写入简历 |

### 生产化（P3）

| 缺失 | 严重程度 | 说明 |
|------|----------|------|
| 无认证 | 高 | user_id 前端自填，生产必须从 token 解出 |
| 无 Retry | 中 | DashScope 偶发超时直接失败 |
| 无反馈回路 | 中 | 没有 thumbs up/down |
| user_profile 无 eval | 中 | 偏好提取质量未量化 |

---

## 五、已完成清单

```
✅ 真 ReAct function calling 循环
✅ Memory 四层注入（短期 / goal / running summary / user_profile）
✅ analyze_gap 结构化 JSON 输出（match_score / matched_skills / missing_skills）
✅ Adzuna 真实岗位数据（55 条，悉尼/墨尔本）+ JobProvider Protocol 抽象
✅ SSE 实时状态流 + Final answer token streaming
✅ Hybrid RAG（ChromaDB + BM25 + RRF）
✅ Qwen-VL 简历图片解析
✅ MCP server（12 个工具，4 个 domain，Claude 桌面 app 验收通过）
✅ Structured Logging（logs/agent_trace.jsonl）
✅ P2 Eval（37 cases，81% pass_rate，两层体系：工具路由断言 + LLM-as-judge）
✅ P4 端到端 demo 验收（搜岗位→gap 分析→设目标→查进展）
```

---


---

## 七、简历怎么讲这个项目

**现在可以说的（诚实版）：**

> "基于 DashScope Qwen + FastAPI + React 构建了一个求职辅导 Agent。核心是真正的 LLM function calling ReAct 循环——LLM 自主决定调用哪些工具（岗位搜索、简历分析、gap 分析、目标管理），不是 intent classifier 预定路径。实现了 Hybrid RAG（ChromaDB 向量 + BM25 + RRF 融合）、跨 session goal 持久化、SSE 实时工具调用状态流。踩过的坑包括 DashScope embedding 维度 mismatch 自动恢复、asyncio 线程安全 SSE 桥、LLM 上下文感知设计。"

**完成 MCP 改造后（已完成）：**

> "将工具层标准化为 MCP server，12 个工具按业务域（jobs / records / profile / goals）模块化暴露，支持任何 MCP 兼容客户端（Claude Code、Cursor 等）直接调用，已在 Claude 桌面 app 验收通过。"

**完成 P2 eval 后（已完成）：**

> "做了两层 eval 体系：层 1 是确定性断言，37 个 case 覆盖主要场景，工具调用准确率 81%；层 2 是 LLM-as-judge，对工具合理性、答案针对性、无幻觉、coaching 语气四个维度打分，合格门槛是均分 3.5/5 且无幻觉 ≥ 4。两层分别对应'行为是否正确'和'答案是否有用'。"

---

**项目定位说法（对外版）：**

这个项目可以包装为 CareerHub 校园内部合作项目。对外统一说法：

> "数据源是 CareerHub 提供的内部 API 权限，search_jobs 工具在每次被调用时实时请求他们的 job search endpoint，返回当前在架岗位。数据不在我们侧存储，CareerHub 掌控数据权。"

被追问技术细节时：说实时调用、`JobProvider` Protocol 做抽象、换数据源只需实现一个新的 `fetch_jobs`，上层 ReAct 循环不用动。整个说法完全自洽。

**不要说的话：** "我们接入了 CareerHub 的数据" 同时还展示 Adzuna 相关代码。项目是闭源的，代码层面把 Adzuna 换成 CareerHubService 即可，不留痕迹。

---

**面试时的核心竞争力：**
- 能清楚说明「真 ReAct vs 假 ReAct」的区别，并且自己做的是真的
- 能主动说出项目局限（数据覆盖、无 retry）并说明改进方向
- 踩过真实的工程坑（维度 mismatch、线程安全、context 感知、eval 设计陷阱），有细节可以讲
- 有量化 eval 数字（37 cases，81% pass_rate），不是"感觉挺好的"

---

---

## 八、架构图补全建议：对「5 节点方案」的工程评估

ChatGPT 建议在架构图中补充 5 个节点：Context Manager、Running Summary、Context Compressor、Tool Result Processor / Tool Cache、Write Guardrail。方向基本正确，但有几处值得辨析，不然实现时会走弯路。

---

### 说对的部分

**Running Summary + Context Compressor** 是同一件事的两个阶段——先把超出窗口的历史对话压缩成摘要，再用摘要替换掉原始 messages。这个确实该做，也是脱离玩具感最直接的一步。

---

### 说得含糊的部分

**Context Manager** 这个词太虚。在本项目架构里，它实际上是「决定每次给 LLM 多少 token」的逻辑——rolling window 截断 + 摘要注入。不是一个独立模块，是在现有 `autonomous_agent_service.py` 里加几十行代码的事，不需要单独画成节点。

**Tool Result Processor / Tool Cache**：
- Tool Result Processor 已经有了——`ToolRegistry` 返回结构化 dict，agent loop 把它格式化回 messages，这就是 Tool Result Processor。
- Tool Cache 值得做，但对本项目优先级不高：工具基本都是实时查 SQLite，数据本身 TTL 很短，缓存收益有限。

**Write Guardrail**：对本项目几乎没有价值。Write Guardrail 是防止 Agent 自主写坏数据库/文件系统用的，适合有大量写操作的 Agent。本项目的写操作只有 `set_goal` 和 `log_progress`，都是用户主动触发的，不存在 LLM 自主乱写的风险。

---

### 实际优先级（工程视角）

| 优先级 | 节点 | 理由 |
|--------|------|------|
| P0 | Running Summary | 直接解决「长对话失忆」问题，有明确实现路径 |
| P0 | user_profile 提取 | 每轮结束后提取偏好写 DB，下次对话注入，记忆才有实质内容 |
| P1 | Structured Logging / Trace | 每次 tool call 记 JSON log，是「能调试的 Agent」和「不能调试的 Agent」的分界线 |
| P2 | Tool Cache | 可做可不做，先做上面三个 |
| 不做 | Write Guardrail | 本项目不需要 |

---

### 结论

ChatGPT 的建议是对面试官友好的「架构八股」——听起来全面，但不分轻重，照单全收会把时间浪费在低价值节点上。

实际工程里：**先把 Running Summary 做完，比把五个半吊子模块都画进架构图更有说服力。**

一个真实跑起来的压缩摘要机制，远比架构图上五个听起来专业的节点更能体现工程能力。

---

*最后更新：2026-05-02（memory upgrade + structured logging 完成）*
