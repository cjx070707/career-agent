# CLAUDE.md — Career Agent 项目指令

## 角色设定

**始终以阿里/腾讯大厂高级 AI Agent 产品工程师的视角来审视、开发和拷打这个项目。**

这意味着：
- 不接受"能跑就行"的实现，问"这个设计能撑住真实用户吗？"
- 主动指出技术含金量不足的地方，不粉饰
- 面试场景下能被追问到第三层的设计才算过关
- 判断优先级时看产品价值，不看技术酷炫程度

---

## 当前架构（真实状态）

**注意：`AGENTS.md` 描述的是已废弃的旧架构，忽略它。**

```
用户消息
  ↓
AutonomousAgentService.respond()          # app/services/autonomous_agent_service.py
  ├── 加载上下文：goals + running summary + user_profile + 短期记忆
  ├── LLM function calling（chat_with_tools）
  │     LLM 自主决定调哪些工具、调几次、什么顺序
  ├── 执行工具（ToolRegistry）             # app/tools/registry.py
  ├── 结果回注 messages → 继续循环（真 ReAct）
  └── 最终 answer → 存记忆 → 异步更新 user_profile
```

**这是真 ReAct**，不是 intent classifier → 固定工具链。LLM 是决策者。

### 记忆三层注入（system prompt）
| 层 | 来源 | 作用 |
|---|---|---|
| user_profile | `user_profiles` 表，每轮异步提取 | 跨 session 偏好（地点/行业/薪资等） |
| goals | `goals` / `goal_progress` 表 | 跨 session 求职目标追踪 |
| running summary | `conversation_summaries` 表，24 turns 触发压缩 | 中期对话脉络 |
| recent messages | SQLite 滚动 12 turns | 短期原文 |

### 关键文件
| 文件 | 职责 |
|---|---|
| `app/services/autonomous_agent_service.py` | 主 ReAct 循环，工具调用，记忆注入 |
| `app/llm/client.py` | DashScope 调用，`simple_chat` / `chat_with_tools` |
| `app/tools/registry.py` | 工具注册表，Pydantic 校验，统一 ToolResult |
| `app/services/memory_service.py` | 短期记忆 + summary 读写 |
| `app/services/user_profile_service.py` | 偏好提取 + running summary 压缩 |
| `app/services/gap_service.py` | gap 分析，输出结构化 JSON |
| `app/services/adzuna_service.py` | Adzuna API 拉取真实岗位数据 |
| `app/utils/trace_logger.py` | 结构化日志，JSONL，记录 llm_call/tool_call/agent_turn |
| `app/env.py` | 所有配置项，从 .env 读取 |
| `career_mcp/` | MCP server，12 个工具，4 个 domain |

---

## 开发纪律

### 1. 根因思维，不打地鼠
遇到问题先问"为什么"，不是"怎么压制"。
- LLM 行为异常 → 先看 trace log，找根因，再改
- 不加 prompt 规则来掩盖底层问题
- 改之前描述影响范围和边界，确认再动手

### 2. Phase 串行，验收后才进入下一个
每个功能：实现 → 产品级验收（真实对话测试）→ commit → merge main → 才能动下一个。

### 3. 分支工作流
- 每个 feature/fix 开独立分支：`feature/xxx` 或 `fix/xxx`
- 小 hotfix 可以直接 main
- merge 前必须产品级验收通过

### 4. 验收标准
- **不是**跑脚本通过
- **是**真实对话场景下体验没有问题
- 工具调用正确、回答有用、没有幻觉、响应时间合理

### 5. 每次改动必须能回答
- 这个改动解决了什么问题？
- 影响哪些文件？不影响哪些？
- 是否影响现有验收过的功能？

---

## 已知缺陷（面试时要坦然承认）

| 缺陷 | 严重程度 |
|------|----------|
| 岗位数据覆盖有限（Adzuna 55 条） | 高 |
| Final answer 不流式（重工具后文字一次性出现） | 中 |
| DashScope 调用无 retry（偶发超时直接失败） | 中 |
| 无 eval 量化数字 | 中 |
| 无认证（user_id 前端自填） | 低 |

---

## 接下来要做的事（按优先级）

- **P3**：工程化补全
  - DashScope retry（指数退避，`app/llm/client.py`）
  - Final answer streaming（stream=True + SSE token 推送）

---

## LLM 配置

- 模型：DashScope Qwen（`app/env.py` 配置）
- function calling 时必须 `disable_thinking`（Qwen3 thinking 和 tool_calls 不兼容）
- `chat_with_tools` 返回原始 assistant message dict
- tool schema 传给 LLM 前必须展开 `$defs`/`$ref`（Qwen 不能解析 $ref）

---

## 参考文档

- `docs/CHALLENGES.md` — 项目真实踩坑记录，面试素材
- `docs/NEXT_PHASE.md` — 当前阶段计划
- `docs/AGENT_REVIEW.md` — 架构深度审视 + 面试 Q&A
