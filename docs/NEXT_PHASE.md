# 项目现状 + 下一步计划

> 最后更新：2026-05-06
> 当前分支：main
> **项目状态：生产就绪（中间件 + 前端 UX 已合并 main）**

---

## 一、已完成

### 核心 Agent 架构
- ✅ **真 ReAct function calling 循环**（`app/services/autonomous_agent_service.py`）
  LLM 看到所有工具 schema，自主决定调哪个工具、调几次、什么顺序。不是意图分类器，不是固定工具链。
- ✅ **ToolRegistry**（`app/tools/registry.py`）
  Pydantic 输入校验，统一 ToolResult 结构，11 个工具注册。
- ✅ **Hybrid RAG**（ChromaDB 向量 + BM25 + RRF 融合）
- ✅ **SSE 实时状态流 + Final answer token streaming**
  `🤔 正在思考` → `🔧 调用工具：xxx` → token by token 打字效果
- ✅ **Qwen-VL 简历图片解析**（前端上传 → 解析 → 存库）

### Memory（四层注入）
- ✅ **短期记忆**：SQLite 滚动 12 turns 原文
- ✅ **Goal 持久化**：`goals` / `goal_progress` 表，跨 session 目标感知，注入 system prompt
- ✅ **Running Summary**：超过 24 turns 自动 LLM 压缩，存 `conversation_summaries`，注入 system prompt
- ✅ **user_profile 偏好提取**：每轮结束后 LLM 提取偏好（地点/行业/薪资/时间线），存 `user_profiles`，跨 session 注入

### 工具（11 个）
- ✅ `search_jobs`（Adzuna 真实岗位数据，55 条，含悉尼/墨尔本）
- ✅ `analyze_gap`（结构化 JSON 输出：match_score / matched_skills / missing_skills / suggestions，自动按 user_id 查简历）
- ✅ `get_resume` / `match_resume_to_jobs`
- ✅ `get_goals` / `set_goal` / `log_progress` / `update_goal_status`
- ✅ `get_applications` / `get_interview_feedback`
- ✅ `get_candidate_profile` / `get_career_insights`

### MCP Server
- ✅ **12 个工具**按 domain 模块化暴露（jobs / records / profile / goals）
- ✅ Claude 桌面 app 验收通过

### 工程化
- ✅ **Structured Logging**：JSONL 写入 `logs/agent_trace.jsonl`（llm_call / tool_call / agent_turn）
- ✅ **P2 Eval**：`scripts/eval_agent.py`，5 场景 × 3 问法 × LLM-as-judge
  工具调用准确率 **14/15 = 93%**，答案质量均分 **4.2/5**
- ✅ **`docs/CHALLENGES.md`**：14 个真实踩坑记录，面试素材

### 验收
- ✅ **P4 端到端 demo 验收**：搜岗位 → gap 分析（match_score 85）→ 设目标 → 查进展，全程通畅

### 生产中间件（`feature/production-middleware` → main）
- ✅ **CORS** middleware
- ✅ **X-Request-ID**：每请求唯一 UUID，贯穿日志链路
- ✅ **结构化请求日志**：JSON lines，method / path / status / latency / request_id
- ✅ **全局异常处理**：统一错误格式，不泄露 stack trace，含 request_id
- ✅ **Rate limiting**（slowapi，20 req/min per IP，待换 Redis backend）

### 前端 UX（`feature/frontend-ux` → main）
- ✅ **localStorage user_id**：自动生成 8 位 hex id，跨 session 稳定，不再 hardcode `demo-user`
- ✅ **对话历史加载**：`GET /conversations/{user_id}` 接口 + 前端 mount 时加载最近 12 条
- ✅ **New Chat 按钮**：侧边栏一键清空，开启新会话
- ✅ **react-markdown 渲染**：agent 回复支持标题、列表、代码块、加粗，流式 token 实时渲染
- ✅ **聊天框图片粘贴**：Cmd+V 粘贴简历截图触发 Qwen-VL 解析，内联状态提示
- ✅ **Enter 发送**：Shift+Enter 换行，纯 Enter 提交
- ✅ **自动滚动到底部**

---

## 二、已知缺陷（面试时坦然承认）

| 缺陷 | 严重程度 |
|------|----------|
| 无简历引导流：新用户无简历时 agent 无法 gap 分析，缺乏明确引导 | 高 |
| 岗位数据 55 条静态快照，非实时拉取，覆盖有限 | 高 |
| **投递/面试记录只能通过 REST API 写入，agent 无对话写入工具** | 高 |
| **工具路由依赖 description 文字质量，无系统性保障；description 改动需靠 eval 回归兜底** | 中 |
| **工具执行结果不沉淀为结构化状态：agent 靠重读 messages 历史推断已知事实，缺 AgentState 承载 known_facts（待 5.0 修复）** | 中 |
| **user_id 由 LLM 从 system prompt 记忆后填入工具参数，存在填错或漏填风险；应由 AgentState 注入（待 5.0 修复）** | 中 |
| DashScope 调用无 retry（偶发超时直接失败） | 中 |
| user_profile 偏好提取未端到端验收 | 中 |
| 无认证（user_id localStorage 自填，可被伪造） | 低 |
| Eval `sources_nonempty` 断言已移除，Adzuna 集成质量未端到端验证 | 低 |

---

## 三、生产部署方案

> 流量基准：CareerHub 场景，DAU 500-3000，高峰 200-1000 并发，AI chat 每天数百到数千次。

### Phase 1：测试上线（单服务器，能撑初期流量）

**架构：**
```
Nginx（反向代理 + SSL 终止）
  └── gunicorn -w 4 -k uvicorn.workers.UvicornWorker
        └── FastAPI app
Redis（分布式限速 + per-user chat lock）
PostgreSQL（替换 SQLite，处理并发写）
ChromaDB server（HTTP mode，单独进程，多 worker 共享）
```

**必须在上线前完成的 P0 改动：**

| 改动 | 原因 | 不做的后果 |
|------|------|-----------|
| SQLite → PostgreSQL | 并发写串行，高峰期写锁超时导致 agent 失忆 | 数据丢失 |
| slowapi Redis backend | 多 worker 内存不共享，限速形同虚设 | 限速失效，DashScope 被打爆 |
| per-user chat lock（Redis） | 防止同一用户并发 LLM 调用耗尽 DashScope 配额 | 高峰期大面积 429 |
| ChromaDB server mode | 多进程直接读写同一文件会 corrupt | 向量库损坏 |

**已完成的中间件（已合并 main）：**
- ✅ CORS
- ✅ X-Request-ID（每请求唯一 UUID，贯穿日志链路）
- ✅ 结构化请求日志（JSON lines，method/path/status/latency/request_id）
- ✅ 全局异常处理（统一错误格式，不泄露 stack trace）
- ✅ Rate limiting（slowapi，20 req/min，待换 Redis backend）

### Phase 2：流量验证后再做

等真实数据上来再决定，不提前优化：
- 读写分离（PostgreSQL replica 承接 memory 读）
- 对话历史异步写入（不阻塞 LLM 调用路径）
- DashScope 调用加 retry（指数退避 2-3 次）
- 用户认证（JWT，user_id 从 token 解出）

---

## 四、下一步（简历引导流）

产品当前最大断层：新用户没有简历 → `analyze_gap` 返回废话或报错 → 用户不知道下一步。
核心 demo 路径（搜岗位 → gap 分析）因此无法完整走通。

**要做的三件事：**

1. **Empty state 入口**：新用户第一次打开，empty state 里加"上传简历开始"按钮，点击触发简历上传流程
2. **Agent 主动引导**：`analyze_gap` 工具检测到 user 无简历时，在回复里明确说明："请先上传简历（Cmd+V 粘贴截图或点击按钮）"，不再返回模糊答案
3. **Chat composer 简历入口**：输入框下方加一个 `📎 上传简历` 小按钮，不占主界面空间，点击触发图片/PDF 选择

预计改动量：前端 ~50 行，后端 `analyze_gap` 工具描述调整 ~5 行。

---

## 五、待做：架构升级

### 5.0 AgentState（所有升级的地基）

> **优先级：最高，约 1 天。5.1 / 5.2 / 5.3 均依赖此层。**

**当前问题**

ReAct 循环里的执行状态是一堆散落的局部变量——`messages: list`、`tool_trace: list`、`iteration: int`——活在单次 HTTP 请求里，请求结束全部消失。没有类型，没有结构，不可暂停，不可恢复，不可在组件间传递。

这不是状态机，是临时变量伪装成状态。后续所有升级（task_family 路由、memory 检索注入、write tools、human-in-the-loop）都需要一个地方承载中间状态，必须先建这个地基。

**设计**

```python
# ── 原子事实：agent 在执行中推断 / 发现的信息 ─────────────────
@dataclass
class Fact:
    key: str            # e.g. "user_has_resume", "target_location"
    value: Any
    source: str         # "tool:get_resume" | "user_message" | "memory"
    confidence: float   # 0-1

@dataclass
class MissingInfo:
    key: str            # e.g. "resume_content", "target_jd"
    required_for: str   # 哪个工具 / 决策依赖它
    resolution: str     # "call:get_resume" | "ask_user"

# ── 约束：agent 必须遵守的边界 ────────────────────────────────
@dataclass
class Constraint:
    type: str           # "location" | "work_type" | "scope" | "budget"
    value: Any
    source: str         # "user_profile" | "user_message" | "system"
    hard: bool          # True = 硬约束（不得违反），False = 软偏好

# ── 记忆：检索了什么、注入了什么 ─────────────────────────────
@dataclass
class MemoryFragment:
    type: str           # "goal" | "profile_field" | "career_event"
    content: Any
    relevance_score: float
    injected: bool      # 是否实际注入了 system prompt

# ── 决策链：每一步做了什么决定，替换自由文本 reasoning_chain ──
@dataclass
class StepDecision:
    iteration: int
    known_fact_keys: List[str]      # 此刻已知事实的 key 列表
    missing_info_keys: List[str]    # 此刻仍缺的信息 key 列表
    decision: Literal["call_tool", "ask_user", "answer", "stop"]
    tool_called: Optional[str]
    tool_args: Optional[dict]
    tool_result_ok: Optional[bool]
    next_action: str
    stop_reason: Optional[str]      # "max_iter" | "answer_ready" | "need_user_input" | "error"

# ── AgentState 主体 ───────────────────────────────────────────
@dataclass
class AgentState:
    # 身份
    user_id: str
    session_id: str
    task_family: str            # 来自 Fast Gate Tier 2

    # 任务理解
    known_facts: List[Fact]
    missing_info: List[MissingInfo]
    constraints: List[Constraint]

    # 记忆
    retrieved_memory: List[MemoryFragment]
    memory_trace: List[str]     # 检索了哪些 collection

    # 执行
    messages: List[Message]
    tool_trace: List[ToolCall]
    decision_trace: List[StepDecision]
    iteration: int

    # 状态
    status: Literal["running", "awaiting_user", "done", "error"]
    next_action: str
    stop_reason: Optional[str]
```

**为什么不用 `reasoning_chain: List[str]`**

自由文本字段的本质是把 LLM 的 CoT 输出换了个地方存，不可查询、不可过滤、不能被后续逻辑消费。`StepDecision` 是可编程的结构化状态：

- 查"iteration 2 时 agent 还缺什么" → `decision_trace[1].missing_info_keys`
- 查"agent 为什么停" → `stop_reason`
- `known_facts` 里已有 `user_has_resume=True`，后续 iteration 跳过重复调 `get_resume`
- `missing_info` 非空时可以程序化插入补全工具，不依赖 LLM 重新推理

**改动点**

- 新建 `app/agent/state.py`，定义上述 dataclass
- `autonomous_agent_service.py` 的 `respond()` 开头初始化 `AgentState`，循环内读写 state 而不是散落变量
- agent_trace 写入时直接序列化 `AgentState`，替换现有的手动拼字段

**验收标准**

- 每次 `/chat` 请求结束后，`logs/agent_trace.jsonl` 里能看到完整的 `decision_trace`，每条含 `iteration` / `known_fact_keys` / `missing_info_keys` / `stop_reason`
- `known_facts` 中出现 `user_has_resume` 后，后续 iteration 不再调 `get_resume`
- `constraints` 中的 `location=Sydney` 在整个 ReAct 循环内保持，不因工具结果而被覆盖

---

### 5.1 分层路由（Fast Gate + 轻量 LLM + ReAct）

> **优先级：高，约 2-3 天**

**背景**

当前架构是 LLM Intent Classifier → ReAct，两个重 LLM 调用在做重叠的决策。参考 RouteLLM（Berkeley, 2024）和 Compound AI Systems（Zaharia et al., 2024）的分层路由思路，改为三层：

```
Tier 1: 硬规则（0ms）
  → 纯问候 / 明确越界关键词 → 直接返回，不进任何 LLM

Tier 2: 轻量 LLM（200-500ms，qwen-turbo 级）
  → 规则没命中的 → 三分类：career / chitchat / out_of_scope
  → 不做细粒度意图分类，只做 in/out 判断

Tier 3: 完整 ReAct（3-10s）
  → 只有 career 才进来，删掉现有 LLM Intent Classifier
```

**改动点**
- 新增 `app/routing/fast_gate.py`：硬规则 + 轻量 LLM 三分类
- 删除 `respond()` 里的 `LLMIntentClassifier` 调用
- 删除 `llm_intent_classifier.py` 里的关键词硬匹配规则（`implicit_search_markers` 等）
- routing prompt 加 few-shot 示例覆盖意图边界（"我想找实习" → career search，不是 goal-setting）
- ReAct system prompt 加显式 scratchpad 指令（第一步推理，再决策工具）

**为什么关键词规则要删**
`implicit_search_markers` 是用规则绕过了 prompt 没写好的问题，不是真正的修复。根因是 routing prompt 缺少边界示例，加三条 few-shot 就能泛化，不需要穷举关键词。

**验收标准**
- "你好" / "谢谢" → 0 LLM 调用直接返回
- 代码题 / 数学题 → 轻量 LLM 拦截，不进 ReAct
- "我想找一份实习" → 轻量 LLM 判断 career → ReAct 调 `search_jobs`，不调 `set_goal`
- 正常求职问题 → 轻量 LLM 通过 → ReAct，全程只有一次重 LLM 决策

---

### 5.2 待做：对话写入投递 / 面试记录

> **优先级：高，约 1-2 天**

### 背景

当前投递记录（`applications`）和面试反馈（`interviews`）只有只读工具（`get_applications` / `get_interview_feedback`），写入只能通过 REST API。用户说"我今天投了 Canva"，agent 没有工具把这条数据存进去。

`CareerEventService` 已经实现了从消息提取事件的逻辑（`sync_from_message`），但没有接进主流程。

### 要做的两件事

**第一件：加写入工具（照 `set_goal` 模式复制）**

```python
log_application(company, job_title, status, note=None)
log_interview(company, job_title, round, result, feedback=None)
```

- 在 `app/tools/` 下新增，注册进 `ToolRegistry`
- agent 就能在对话中调用，用户说"投了 X"时自动写入

**第二件：把 CareerEventService 接进 post-turn 背景任务**

```python
# respond() 的 post-turn 部分加一行
self.career_event_service.sync_from_message(user_id, message)
```

从消息里自动提取职业事件并向量化存入 ChromaDB，支持后续语义检索。

### 验收标准

- 用户说"我今天投了 Canva 后端实习，状态是已投"，agent 调 `log_application`，DB 里出现这条记录
- 用户说"我 Atlassian 一面被拒，反馈是 system design 差"，agent 调 `log_interview`，DB 里出现这条记录
- 用户下一轮问"我投了哪些公司"，agent 调 `get_applications` 能查到刚才写入的记录

---

### 5.3 Memory 架构升级（三阶段）

> **前置依赖：5.1 Fast Gate 完成后才能落地 Phase 1（task_family 由 Tier 2 分类结果提供）**

**当前问题**

每次请求不管问什么，goals / running_summary / user_profile / 12 轮对话原文全量塞进 system prompt。用户问"帮我搜个 Python 实习"，"你上次说想去金融行业"照样注入。三个后果：

1. Token 浪费——无关记忆挤压工具结果空间
2. 注意力稀释——LLM 从一堆不相关信息里找关键片段，命中率下降
3. 扩展性差——用户用满 3 个月，goals 20 条、profile 很长，全量注入撑爆 context

---

#### Phase 1：Memory Context Budget（约 1-2 天）

> **优先级：高，改动小，收益直接**

目标不是立刻重构检索，而是先控制上下文污染。

**改动点**

- `build_context()` 加硬上限：Core Memory 固定 ≤ 500 tokens
- goals 不再全量注入，只取 `status=active` 的最近 3 条
- user_profile 从单 JSON blob 拆成结构化字段：`preferred_location` / `preferred_industry` / `salary_expectation` / `timeline`
- `build_context()` 接收 `task_family`（来自 Fast Gate Tier 2 分类），按 task_family 选择性注入：

  | task_family | 注入字段 |
  |-------------|---------|
  | `career_search` | preferred_location, preferred_industry |
  | `goal_tracking` | active goals（≤3条）, timeline |
  | `gap_analysis` | preferred_industry, salary_expectation |
  | `chitchat` | 不注入任何 profile 字段 |

- agent_trace 记录本轮注入了哪些 memory 字段及 token 数，方便调试

**验收标准**
- 搜岗位请求：system prompt 里不出现用户的 goal 列表
- goal 追踪请求：profile 的薪资字段不注入
- 单轮 system prompt token 数 ≤ 800（工具 schema 另算）

---

#### Phase 2：System-Level Memory Retrieval（约 3-4 天）

> **优先级：中，等 Phase 1 稳定后做**

给 memory 加 embedding，在 ReAct 启动前系统自动检索相关片段注入，agent 无感知。不做成工具——agent 不一定知道什么时候该查记忆，暴露成 tool 会增加工具选择负担。

**设计**

```
用户消息 → embedding → 检索 memory store（ChromaDB memory_* collections）
                                ↓
                  top-k 结果经 relevance gate（score > threshold）
                                ↓
                       注入 system prompt（替代全量注入）
```

**Memory Store 分层**

| Collection | 存什么 | 写入时机 |
|------------|--------|---------|
| `memory_goals` | 每条 goal embed 一次 | set_goal 时 |
| `memory_profile` | 每个 profile 维度 embed 一条 | update_profile 时 |
| `memory_career_events` | 投递/面试事件（见 5.2） | log_application / log_interview 时 |

**改动点**
- `memory_service.py` 新增 `retrieve_relevant(query, task_family, top_k=3)` 方法
- 每种 memory 类型加 metadata：`type` / `tags` / `timestamp` / `status`（active/archived）
- 用 metadata filter（`status=active`）+ semantic search 双重过滤，不让过期记忆进来
- `build_context()` 调用 `retrieve_relevant()` 替换原来的全量拼接

**relevance gate**：cosine similarity < 0.3 的片段不注入，避免低相关噪声

**验收标准**
- 用户问求职搜索类问题，只注入 preferred_location / preferred_industry，不注入已完成的 goal
- 用户问目标进展，只注入 active goals，不注入无关的 salary 偏好
- ChromaDB `memory_goals` collection 存在，set_goal 后可查到对应向量

---

#### Phase 3：Memory Writer 治理（约 2 天）

> **与 5.2 共享实现，在 5.2 write tools 完成后做**

5.2 解决"agent 能写入投递/面试记录"，Phase 3 解决"写入质量治理"。

**问题**：CareerEventService 从消息里 LLM 抽取事件，置信度参差不齐。"我可能要投 Canva" 和 "我今天投了 Canva" 被同等对待写入。

**改动点**
- 写入前加置信度评分：LLM 抽取时同时输出 `confidence: high/medium/low`
- `low` 置信度不自动写入，在回复里让用户确认
- 去重逻辑：同一 company + job_title + round 存在时 update 而不是 insert
- 过期标记：goal 状态变为 `completed/abandoned` 时，对应 `memory_goals` 向量打 `status=archived`，检索时自动过滤

**验收标准**
- "我可能要投 Canva" → 不写入，agent 回复里提示"需要确认吗？"
- "我今天投了 Canva 后端实习" → 直接写入，confidence=high
- 已完成的 goal 不再出现在 Phase 2 检索结果里

---

## 六、已决定不做的事

| 方向 | 决策理由 |
|------|---------|
| P3 实时 Adzuna 拉取 | demo 路径可控，55 条覆盖已验证够用；实时调用增加延迟和外部依赖，demo 阶段代价大于收益 |
| Retry | demo 阶段超时偶发，等真实用户上线后再加指数退避 |
| Write Guardrail | 写操作只有 set_goal/log_progress，用户主动触发，无防护必要 |
| Tool Cache | 工具实时查 SQLite，缓存收益低 |
| 认证系统 | 非核心，不影响技术含金量 |
| Docker | 等核心功能稳定后再做 |
