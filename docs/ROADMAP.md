# 实施路线图｜高校求职辅导 Agent

> 本文件定义从当前状态到目标架构的实施顺序。
> 每个 Phase 附有验收标准，完成前不进入下一个。

---

## 当前状态快照（2026-04-29）

**已完成，稳定，不动：**
- 双层记忆系统（短期对话缓存 + 长期职业画像）
- 模块化工具层（ToolRegistry + Pydantic schema 声明式注册）
- Hybrid RAG（ChromaDB + BM25 + RRF 混合召回）
- 多模态输入（Qwen-VL 简历截图解析）
- Eval harness（multi-turn eval runner + 7 条双轮测试 + 断言框架）
- 全套单元测试 + E2E 测试基础设施

**存在问题，需要重构：**
- 意图识别：1200 行关键词规则树（IntentRouter + IntentGateway），覆盖率差，对自然语言变体天花板极低
- ReAct 循环：步骤预规划，LLM 只做有限决策，不是真正 LLM 驱动
- 输出层：各 task_type 格式不统一，无法保证"结论/证据/行动"三段结构

**已做的应急修复（2026-04-29）：**
- Fix 1：ContextRequirementResolver 增加 inline 简历识别
- Fix 2：第三方建议路由走 LLM generate 而非能力列表
- Fix 3：intent_signals 补全词序变体、提升关键词覆盖

---

## Phase A｜LLM Intent Classifier ✅ 已完成（2026-04-29）

**目标**：用一次 LLM 结构化输出调用替代 IntentRouter + IntentGateway + LLM Planner 三层规则树。

**要做的事：**

1. 新建 `app/routing/llm_intent_classifier.py`
   - 接收：message + recent_turns + user_state + available_tools
   - 调用 LLM（JSON mode / function calling），输出 ChatPlan 兼容结构
   - 包含 `reasoning` 字段（scratchpad，写入 llm_trace，不对用户展示）
   - 输出 schema 校验失败时降级为 fallback，不抛 500

2. 编写分类器 prompt
   - 覆盖所有 task_type 的 few-shot 示例（至少 2 例/类型）
   - 包含对话历史理解示例（follow-up 消息如何利用上下文）
   - 明确说明何时 needs_more_context=True

3. 修改 `app/services/agent_service.py`
   - 快捷路由（greeting / capability_help）保留规则处理，其余全部走 Classifier
   - 删除 intent_router / intent_gateway 调用链

4. 删除文件
   - `app/routing/intent_router.py`
   - `app/routing/intent_gateway.py`
   - `app/routing/intent_signals.py`

**验收标准：**
- [ ] 跑 `evals/run_multi_turn_eval.py`，7 条双轮用例全部通过
- [ ] "我的简历该怎么更强" → task_type=resume_analysis，不追问 JD
- [ ] "有什么岗位适合我?" → 走推荐链路，不追问 JD
- [ ] "就匹配当前平台的就可以" → 走 job_match_planning，不超时
- [ ] "我该如何提升" → task_type=career_insights，不超时
- [ ] 所有 38 条 intent_router 单元测试改写为 Classifier 测试，通过率 ≥ 95%

**验收结果**：7/7 multi-turn eval passed，6 个核心 case 行为符合预期。

---

## Phase B｜统一输出协议（P1）

**目标**：所有 task_type 的最终回答遵循同一三段结构，消除 ResponseFormatter 碎片化。

**要做的事：**

1. 重写 `app/services/response_formatter.py`
   - 所有 format_* 方法输出统一结构：结论 → 证据 → 行动建议
   - 不区分 task_type 的特殊格式路径

2. 更新 Formatter 相关的 eval 断言
   - 现有断言 `answer_contains_all: ["结论", "证据", "行动"]` 应全部通过

3. 更新 ResponseFormatter 的 LLM prompt（如果使用 LLM 生成格式化文本）

**验收标准：**
- [ ] resume_analysis / interview_prep / career_insights 三条路径回答均包含结论/证据/行动
- [ ] multi-turn eval 中 `answer_contains_all["结论","证据","行动"]` 断言全部通过
- [ ] 用户看不出任何格式退化

**估计工程量**：1-2 天

---

## Phase C｜真正 LLM 驱动的 ReAct 循环（P1）

**目标**：PlanExecutor 的每步由 LLM 基于完整观察自主决定，而不是执行预规划序列。

**要做的事：**

1. 升级 `app/services/plan_executor.py`
   - `execute_react_loop` 改为：每步给 LLM 完整的 (message + 已有工具结果 + 可用工具列表)
   - LLM 输出：`{ action: "call_tool" | "finish", tool: str, reasoning: str }`
   - 删除"预规划步骤序列"概念，LLM 自主决定下一步
   - 保留安全边界：MAX_STEPS=8，工具白名单，重复保护

2. 升级 ReAct decider prompt
   - 包含 scratchpad 格式："我现在知道 X，还缺 Y，因此下一步做 Z"
   - 示例覆盖：多步推理、提前终止、上下文不足时追问

**验收标准：**
- [ ] "帮我找适合我的岗位"：agent 自主完成 profile → resume → search → match 四步，不需要预规划序列
- [ ] loop_trace 中每步有 reasoning 字段
- [ ] 不因 LLM 自主决策导致死循环（MAX_STEPS 保护生效）

**估计工程量**：3-4 天

---

## Phase D｜Eval 量化指标提取（P2）

**目标**：把 eval harness 跑出来的数据变成简历可写的数字。

**要做的事：**

1. 在 eval runner 中记录并输出：
   - 路由准确率（task_type 命中率）
   - Phase A 前后路由准确率对比
   - multi-turn 通过率
   - 平均响应延迟

2. 生成 `evals/reports/metrics_summary.md`，记录关键数字

3. 把数字写入简历（见 `docs/resume/RESUME_EVOLUTION.md`）

**验收标准：**
- [ ] 能用一句话表达：路由准确率从 X% 提升至 Y%
- [ ] multi-turn eval 通过率 ≥ 90%

**估计工程量**：0.5 天

---

## 不做的事（明确排除）

以下方向在当前阶段不进入主线，原因是工程成本高但简历价值边际收益低：

| 方向 | 排除原因 |
|---|---|
| Multi-Agent / Orchestrator | 当前单 Agent 问题未解决，过早抽象 |
| Self-Consistency（多次采样投票） | 成本高，当前用例不需要 |
| 显式 CoT 对用户展示 | 产品体验负担，当前不做 |
| 完整 MCP Server 协议接入 | 非核心，工具层已 MCP-ready |

---

## 执行顺序

```
A（LLM Classifier）→ B（输出协议）→ C（ReAct 升级）→ D（指标提取）
```

A 是前置，没有 A 就没有 B/C 的意义。B 和 C 可以并行。D 在 A+B+C 完成后做。
