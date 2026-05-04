# 项目现状 + 下一步计划

> 最后更新：2026-05-04
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
| DashScope 调用无 retry（偶发超时直接失败） | 中 |
| user_profile 偏好提取未端到端验收 | 中 |
| 无认证（user_id localStorage 自填，可被伪造） | 低 |

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

## 五、已决定不做的事

| 方向 | 决策理由 |
|------|---------|
| P3 实时 Adzuna 拉取 | demo 路径可控，55 条覆盖已验证够用；实时调用增加延迟和外部依赖，demo 阶段代价大于收益 |
| Retry | demo 阶段超时偶发，等真实用户上线后再加指数退避 |
| Write Guardrail | 写操作只有 set_goal/log_progress，用户主动触发，无防护必要 |
| Tool Cache | 工具实时查 SQLite，缓存收益低 |
| 认证系统 | 非核心，不影响技术含金量 |
| Docker | 等核心功能稳定后再做 |
