# 开发难题与解决方案

> 记录项目从 router-first chatbot 演进到真正 Agent 过程中遇到的真实技术问题。
> 用于面试时展示工程判断力——每个问题都有"第一反应（错的）"和"真正根因"。

---

## 架构阶段一：Router + Planner（假 Agent）

### 1. 意图分类器是个陷阱

**现象**：最初用 LLM 做意图分类，把用户输入分成"搜岗位"、"gap 分析"、"查目标"等几类，再走对应的固定工具链。代码跑通了，演示效果也不错。

**问题暴露**：用户说"帮我找几个 fintech 实习，顺便看看我的简历够不够"——这是复合意图，分类器只能选一个分支，另一半需求直接丢失。更根本的问题：**LLM 在 ReAct loop 里只是在沿着分类器决定好的路径走，从未真正自主决策过**。

**反思**：Intent classifier 把 agent 退化成了 router。它有两个不可修复的缺陷：
1. 分类粒度固定，无法处理用户意图的组合和模糊性
2. 工具链是人写死的，LLM 没有动态规划能力

**解法**：废弃意图分类器，把所有工具 schema 直接交给 LLM，让它通过 function calling 自主决定调哪些工具、调几次、什么顺序。这才是真 ReAct——LLM 是决策者，不是执行者。

**代价**：latency 略增（少一次分类调用，但多了工具调用的 round trip）。收益：真正的自主性，复合意图自然拆解。

---

### 2. SSE 里的 asyncio 线程安全问题

**现象**：`/chat` 端点返回 SSE 流，`svc.respond()` 在 thread pool 里同步跑。工具调用时想实时推状态事件（"🔧 调用工具：search_jobs"），但从线程里直接 `yield` 或操作 asyncio 对象会报错或静默失败。

**第一反应（错的）**：把 `respond()` 改成 async。但 `respond()` 里有同步的 LLM 调用和数据库操作，改成 async 会阻塞事件循环。

**真正根因**：asyncio 不是线程安全的——在 thread pool 里直接操作 asyncio 对象（Queue、Future）会有 race condition。

**解法**：`asyncio.Queue` 作为跨线程通道，thread pool 里通过 `loop.call_soon_threadsafe(queue.put_nowait, event)` 推状态事件，async 的 SSE 生成器从 queue 里消费。这是标准的 asyncio + threading 桥接模式。

---

### 3. LLM 不知道该用哪个 user_id

**现象**：工具需要 `user_id` 参数才能查到对应用户的数据，但 LLM 经常传错——传 `"user"`、`"unknown"`、或者直接不传，导致工具返回空数据。

**第一反应（错的）**：在每个工具的参数里把 `user_id` 改成可选项，做 fallback。这会让工具语义变模糊，而且 LLM 仍然不知道该填什么。

**真正根因**：LLM 不知道当前用户是谁，因为没有人告诉它。这是 context 缺失问题，不是工具参数设计问题。

**解法**：在 system prompt 里明确写 `"当前用户的 user_id 为：{user_id}，调用任何需要 user_id 的工具时必须使用此值"`。LLM 拿到明确指令后，user_id 传递准确率接近 100%。

---

## 架构阶段二：Hybrid RAG

### 4. 纯向量检索对精确技术词不准

**现象**：用户搜 "FastAPI intern"，向量检索召回了很多 "Python web framework" 相关岗位，但有一条完全匹配的岗位（title 里有 "FastAPI"）排在第 8 位。

**根因**：`text-embedding-v3` 对 "FastAPI" 这类专有技术词的向量表示被"Python"、"web"、"API" 等更通用词语稀释了，语义相近但词面不匹配的结果排名更高。

**解法**：加 BM25 词法召回（精确词面匹配），两路结果用 RRF（Reciprocal Rank Fusion）融合。RRF 的优点是不需要对两路分数归一化，直接用排名位置计算，鲁棒性强。融合后 "FastAPI" 精确匹配的岗位稳定排在前 3。

---

### 5. ChromaDB embedding 维度 mismatch

**现象**：从 256 维 embedding 切换到 DashScope `text-embedding-v3`（1024 维）后，upsert 数据时报 `InvalidDimensionException`。旧 collection 的维度元数据是 256，新 embedding 是 1024，ChromaDB 在写入时才检查维度，不是在初始化时。

**第一反应（错的）**：手动删 ChromaDB 数据目录。但这需要人工操作，重新 deploy 时还会复现。

**解法**：在 `RetrievalService` 初始化时加异常捕获——upsert 时捕获 `InvalidDimensionException`，自动删除旧 collection 重建，然后重试。这样维度变更是自愈的，不需要手动干预。

---

## 架构阶段三：Memory 升级

### 6. 滚动窗口会让 Agent 失忆

**现象**：用户在第 1 轮说"我不想去外企，只看 startup"，聊了 7 轮之后，Agent 给他推荐了 Amazon 实习。滚动 6 轮窗口把第 1 轮的偏好丢弃了，Agent 完全不记得。

**根因**：6 轮滚动窗口是短期记忆，不是长期记忆。对"长期陪伴求职"这个产品定位，这是根本性的设计缺陷，不是参数调优能修的。

**解法一（Running Summary）**：超过窗口阈值（24 turns）时，用 LLM 把旧对话压缩成摘要存入 `conversation_summaries` 表。下次对话把摘要注入 system prompt，相当于"记得聊过什么，但不记得原话"。解决了"长对话失忆"问题。

**解法二（user_profile 提取）**：每轮对话结束后，独立跑一次 LLM 调用，从对话里提取偏好信号（偏好地点、行业、工作类型、薪资范围、回避因素等），写入 `user_profiles` 表。下次对话把 user_profile 注入 system prompt，形成真正的跨 session 用户画像。

**两者分工**：Running Summary 保留"对话脉络"，user_profile 保留"用户是谁"。两者结合才构成完整的长期记忆。

---

### 7. user_profile 提取的 LLM 调用不能在主循环里

**现象**：最初把 user_profile 提取放在 `respond()` 最后，导致用户等待时间增加约 3-5 秒——每次对话结束都要多等一次 LLM 调用。

**根因**：profile 提取是"对这次对话的后处理"，不影响本轮回答，不应该阻塞主响应链路。

**解法**：profile 提取改为异步/后台执行，主响应链路在 `respond()` 返回后就结束，profile 提取在后台静默完成。用户感知到的响应时间不变。

---

## 架构阶段四：工具层与 LLM 交互

### 8. Qwen 无法解析 JSON Schema 里的 $ref

**现象**：`search_jobs` 有一个嵌套参数 `filters: {location, work_type}`。实际调用中，Qwen 把 `filters` 传成了 JSON 字符串 `"{\"location\": \"Sydney\"}"` 而不是 object，导致 Pydantic 校验失败。LLM 看到工具报错后重试，`search_jobs` 被连续调用 3 次。

**诊断过程**：在 agent 循环里加了 LLM 调用追踪，打印每次传给 LLM 的 arguments。发现前两次调用的工具参数格式就是错的——不是 LLM 行为问题，是参数校验失败导致的正常重试。

**根因**：Pydantic 的 `model_json_schema()` 对嵌套 model 会生成 `$defs` + `$ref` 引用。Qwen 不能解析 `$ref`，把它当成普通字符串类型，所以把 object 序列化成了 JSON 字符串。

**解法**：两步。第一步，在 `_build_tool_schemas()` 里递归展开所有 `$defs`/`$ref` 成 inline schema。第二步，把 `filters.location`/`filters.work_type` 展平为顶层参数——彻底规避嵌套 object，Qwen 对 flat 参数的处理是可靠的。

**结果**：工具调用从 3 次降为 1 次。

---

### 9. LLM 跳过工具输出幻觉内容

**现象**：用户搜悉尼软件实习，agent 有时不调 `search_jobs`，直接输出 Atlassian、Canva 等公司名。这些是 LLM 训练数据里的知名公司，不是数据库里的真实岗位。

**第一反应（错的）**：在 system prompt 加"求职问题必须调工具"。这是 prompt 打地鼠，换个问法还会绕过。

**真正根因**：工具描述是 **LLM 和工具之间的接口契约**。`search_jobs` 的描述是 `"Search jobs using a natural language query."` ——LLM 看到这个描述，无法判断"我需要调这个工具"还是"我直接从训练数据回答就行"。它选了后者，因为它确实"知道" Sydney 有哪些科技公司。

LLM 不知道两件事：① 这个工具连接的是实时数据库；② 它的训练数据里没有当前岗位信息，用训练数据回答一定是错的。

**解法**：把工具描述改成明确传达这两个信息：`"Search the live job postings database for real, current openings. You MUST call this tool — your training data does not contain current listings and will be fabricated."`

**结果**：所有求职查询场景均调 `search_jobs`，不再产生幻觉岗位。

---

### 12. Running Summary 的触发时机设计

**问题**：什么时候压缩历史对话？有两个选项：
1. 每轮结束后都跑一次摘要更新
2. 超过阈值才触发

**方案 1 的问题**：每轮都多一次 LLM 调用，latency 增加，而且大多数对话根本到不了需要压缩的长度，这些调用全部白费。

**方案 2 的设计**：设定 `ARCHIVE_THRESHOLD = 24 turns`。窗口内保留最近 12 轮原文（`WINDOW_SIZE = 12`），超出 24 轮的旧记录才压缩进摘要。这样：
- 短对话（< 24 轮）：零额外开销
- 长对话：最多每 12 轮触发一次压缩，摊薄成本

**踩过的坑**：最初 WINDOW_SIZE=6、ARCHIVE_THRESHOLD=14，太激进，普通的求职咨询 3-4 轮就开始压缩，摘要质量差（信息太少压缩意义不大）。调大参数后体验正常。

---

### 13. MCP Server 工具标准化

**背景**：ToolRegistry 是项目私有接口，外部系统无法复用这些工具。

**问题**：如果 USYD CareerHub 想集成，或者用户想在 Claude 桌面 app 里直接调用，私有接口需要写适配层，每个接入方都要重新对接。

**解法**：把 ToolRegistry 暴露为 MCP server。每个 ToolDefinition 的 `name`、`description`、`input_model` 直接映射成 MCP tool schema，handler 映射成 MCP tool handler。

**好处**：任何 MCP 兼容客户端（Claude Code、Cursor、其他 LLM 框架）都可以直接调用，不需要知道内部实现。Claude 桌面 app 验收：`mcp__career-agent__get_goals` 真实调用返回 SQLite 数据，工具调用链路完整。

**工程决策**：工具按业务域分模块（jobs / records / profile / goals），不是一个大文件。每个 domain 单独的 MCP module，方便未来按需暴露或隐藏部分工具。

---

### 14. 前端 SSE 解析错误

**现象**：后端 `/chat` 返回 SSE 流，前端偶尔拿不到完整回答，或者看到 `[object Object]` 而不是文字内容。

**根因**：前端用 `response.json()` 解析 SSE 响应——`response.json()` 等待整个响应体结束再解析，跟 SSE 的流式传输根本不兼容。SSE 需要用 `response.body` 的 `ReadableStream` 逐行读取。

**解法**：把 `sendChat` 里的 `response.json()` 改成 `ReadableStream` reader，按换行符切分，每行解析成 SSE 事件对象。`status` 事件更新状态指示器，`answer` 事件填充回答内容，`done` 事件关闭流。

---

### 15. DashScope 用 OpenAI 兼容模式的坑

**背景**：DashScope 提供 OpenAI 兼容接口（`/compatible-mode/v1`），可以用 OpenAI SDK 或直接 `requests` 调用。

**踩过的坑**：

1. **thinking 模式和 tool_calls 不兼容**：Qwen3 系列支持 `thinking` 参数，但开启 thinking 时不支持 function calling，`tool_calls` 永远是空的。需要在所有 function calling 请求里显式 `disable_thinking`。

2. **`content: None` 的处理**：LLM 决定调工具时，assistant message 的 `content` 是 `null`。OpenAI 规范允许这样，但如果不显式处理，直接把 `None` 序列化进 messages 再传给 DashScope 会报参数错误。

3. **超时行为**：DashScope 偶发请求挂住不超时（连接成功但不返回），不是 TCP 层超时，需要在 `requests.post` 里同时设置 `connect timeout` 和 `read timeout`。

---

## 工程决策记录

### 10. 为什么 JobProvider 用 Protocol 而不是 ABC

**背景**：接入 Adzuna API 时定义 `JobProvider` 接口，未来换 CareerHub 或其他数据源。

**选择 Protocol**：结构子类型——任何有 `fetch_jobs` 方法的类自动满足接口，不需要显式继承。未来接入新数据源不需要修改任何现有代码。ABC 需要显式继承，对外部适配器更侵入。

---

### 12. Agent Eval 的设计陷阱

**背景**：写 P2 eval 时，最直觉的做法是断言 `tool_trace` 里包含预期工具名，5 个场景跑一遍，输出通过率。

**第一轮失败（67%）的真实原因**：

1. **记忆污染**：3 个问法共用同一个 `user_id`，第 1 轮调用把结果存进了对话历史，第 2、3 轮 LLM 直接从记忆里回答，不再调工具。这让 eval 结果随运行顺序变化——不是 agent 变差，是测试设计有问题。

2. **get_goals 场景的逻辑悖论**：测 `get_goals` 时用了无目标的干净用户，LLM 说"你没有设定目标"，答案是对的（quality 5/5），但 `tool_trace` 为空，工具断言失败。根因：当 agent 已从 system prompt 中获得所需信息时，调工具是冗余的——这是正确行为，eval 逻辑错了。

3. **只断言工具调没调是 toy**：`tool_trace` 断言只能告诉你"工具被触发了"，不能告诉你"回答有没有用"。加入 LLM-as-judge 后，才能区分"调了工具但回答垃圾"和"没调工具但从上下文回答正确"两种情况。

**解法**：
- 每个 phrase 用独立 `user_id`，完全隔离记忆
- get_goals 场景先 seed 一个目标再测查询
- 双指标：`tool_trace` 断言 + LLM-as-judge 质量分

**最终结果**：14/15 = 93% 工具准确率，4.2/5 答案质量

**教训**：eval 的设计比写 eval 更难。错误的 eval 比没有 eval 更危险——它给你虚假的信心。

---

### 11. $ref 展开 vs 手写工具 Schema

**背景**：修复 Qwen $ref 解析 bug，有两个选项：
1. 在 `_build_tool_schemas()` 里递归展开 `$defs`/`$ref`
2. 手写每个工具的 JSON Schema，绕过 Pydantic

**选方案 1**：Pydantic input model 是唯一真相来源。手写 schema 造成双重维护——每次修改 model 都要同步手写 schema，迟早出现不一致。展开逻辑写一次，所有工具受益。

---

### 13. 工具描述必须暴露内部行为，不能只描述输出

**现象**：P4 端到端验收时，用户发送含 JD 的 gap 分析请求，LLM 没有调 `analyze_gap`，而是要求用户"请粘贴你的简历文本"。

**第一反应（错的）**：加 prompt 规则"遇到 JD 必须调 analyze_gap"——这是打地鼠。

**真正根因**：`analyze_gap` 的 description 只说了"对比简历与 JD，给出匹配度评分"，没有说"会自动通过 user_id 查找用户最新简历"。LLM 不知道调这个工具能找到简历，出于保险选择先问用户要简历，而不是盲目调一个可能失败的工具。这是 LLM 的理性决策，不是 bug。

**次要根因**：同一个 `user_id` 前一轮对话里出现过"找不到简历"的失败记录，LLM 读到历史后直接放弃调工具。记忆里的失败状态影响了当前决策。

**解法**：
- 在 description 里显式写明："此工具会自动通过 user_id 查找用户最新简历，无需用户提供简历内容，直接调用即可。"
- demo 验收用干净的 user_id，避免历史失败状态污染当前对话

**教训**：工具描述是 LLM 的决策依据，不是给人看的注释。内部实现细节（"自动查简历"）如果不写进 description，LLM 永远不知道。**工具描述 = LLM 的 API 文档，漏掉一个关键行为等于接口文档缺页。**

---

### 14. Demo 验收暴露的前置条件盲区

**现象**：P4 走完整 demo 路径时，gap 分析返回"找不到简历"。resume 明明已经通过 `/resumes` 接口写入，但 `analyze_gap` 查不到。

**根因**：`/resumes` 接口需要传 `candidate_id`，而 `analyze_gap` 内部按 `candidates.user_id` 反查简历。两张表的关联靠 `candidates.user_id`，但写入简历时用的是 `candidate_id: 1`（一个已有候选人），不是 `user_id: demo_user` 对应的候选人。数据写进去了，但关联关系断了。

**解法**：先在 `candidates` 表里插入 `user_id = demo_user` 的记录，拿到正确的 `candidate_id` 后再写 resume，确保关联完整。

**更深层的问题**：这个 demo 有一个未被正式处理的前置条件——**用户必须事先有简历**。目前没有通过对话自然上传简历的流程，需要直接操作数据库或调 API 写入。这是已知产品缺陷，面试时坦然承认。

---

*最后更新：2026-05-02（P4 demo 验收完成，项目收尾）*
