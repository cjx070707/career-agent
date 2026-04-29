# Multi-Turn Eval Probe — Findings

date: 2026-04-29
methodology: static code trace (ContextRequirementResolver / IntentRouter / ToolResponseFormatter / AgentService 四层逐路径追踪)
probe dataset: evals/dataset.multi_turn.jsonl — 5 cases × 2 turns
raw report: evals/reports/multi_turn_latest.md

> 沙箱缺 Python 依赖无法冷启 uvicorn，故改为全量静态代码追踪，每条 case 精确模拟执行路径。结论等效于真实跑探针。

---

## 失败汇总

| case | turn | failed check | 诊断桶 |
| --- | --- | --- | --- |
| resume-optimization-two-turn | turn 2 | answer_contains_all["结论","证据","行动"] | ResponseFormatter 未统一 |
| interview-prep-two-turn | turn 2 | answer_contains_all["结论","证据","行动"] | ResponseFormatter 未统一 |
| third-party-then-self | turn 1 | answer_contains_any["PM","产品经理",...] | 第三方路由回答为空壳 |

通过：job-match-two-turn（2/2 turn）、career-insights-two-turn（2/2 turn）

---

## 桶 1 — ResponseFormatter 未统一（2 条，占比最高）

**对应 case：** resume-optimization turn 2 / interview-prep turn 2

**现象：** turn 2 回答不含"结论/证据/行动"。

**根因（精确到代码行）：**

`_format_interview_prep_answer`（agent_service.py:718）返回编号步骤（1/2/3）格式：
```
面试准备计划（后端开发）：
1. 先用 你已有的项目经历 组织一段 90 秒自我介绍...
2. 技术准备分三块...
3. 本周执行...
```

`format_tool_answer("get_resume_by_id", ...)`（response_formatter.py:66）返回分节文本：
```
简历总结：...
整体定位：...
核心技能/关键词：...
经历或项目亮点：...
风险/缺口：...
下一步优化建议：...
```

两条路径都**没有统一输出协议**，也都不包含"结论/证据/行动"字样。此外 resume-optimization turn 2 还有第二个问题：

resume turn 2 还触发了 **Resolver 没接住补充信息** bug：用户 inline 粘贴简历内容，但 `ContextRequirementResolver._has_context("resume", ...)` 只检查 `user_state["has_resume"] = resume_service.has_resume(user_id)`（数据库标志位），不检查当前消息是否包含简历原文。结果 needs_more_context 仍然 True，系统再次追问简历——工具根本没跑，ResponseFormatter 连被调用的机会都没有。两个问题叠加，turn 2 完全没有到达输出层。

**对应下一步：Phase 5（输出层统一）+ 单点 Resolver 修复（半天）**

---

## 桶 2 — 第三方路由回答为空壳（1 条）

**对应 case：** third-party-then-self turn 1

**现象：** "我朋友想转 PM，他怎么准备？" → 答案是能力介绍，不含"PM/产品经理"。

**根因（精确到代码行）：**

IntentRouter（intent_router.py:86）`is_third_party=True` 时产出：
```python
task_type="fallback", steps=[], plan_type="third_party_advice"
```

AgentService（agent_service.py:134）检测到 `task_type=="fallback" and not steps` → 进入 fallback 分支，取 `fallback_type="none"` → 调用 `_format_router_fallback_answer()`，返回固定字符串"我可以帮你找岗位..."。

**这条路径从未触及 LLM generate。** 第三方问题实际上需要 LLM 基于消息内容回答，但路由把它扔进了能力介绍的 dead-end。

修复估计：半天。在 `_format_router_fallback_answer` 之前检测 `plan_type=="third_party_advice"`，改为调用 `llm_client.generate(message, memory_context)` 即可。或直接在 AgentService 的 fallback 分支加一条：
```python
if fallback_type == "none" and plan.plan_type == "third_party_advice":
    answer = self.llm_client.generate(message, memory_context=[...], evidence=[])
```

---

## 桶 3 — 观察到但未列入硬 FAIL 的信号

**career-insights turn 2 replan 未触发（Case 3，软失败）**

turn 2 消息"我的目标是 backend intern"进来后，系统路由到 fallback + LLM generate，**未重新触发 career_insights** 诊断。

当前行为：turn 2 → 普通对话，断言靠"简历"/"backend"的宽松 contains_any 过关。
探针原意：检测 Loop 是否随新上下文做策略级 replan。结论：**Loop 没有跨轮 replan 能力**，Phase 3B/4 的跨轮策略感知未实现。

这条案例的断言太宽松，没有暴露为硬 FAIL，但信号已经记录。

---

## 各桶计数

| 桶 | 硬 FAIL turn 数 | 占比 |
| --- | --- | --- |
| ResponseFormatter 未统一（Phase 5） | 2 | 40% |
| 第三方路由空壳（单点修复） | 1 | 20% |
| Resolver 不接 inline 内容（单点修复） | 1（与 Phase 5 桶叠加） | 20% |
| Loop 跨轮 replan 缺失（Phase 3B/4） | 0 硬 FAIL（软信号） | - |

---

## 下一个 Phase 决策

**占比最高的桶 = Phase 5 输出层统一**，且第三方路由修复是半天级别的单点修复，可以 inline 完成。

推荐执行顺序：

1. **inline 修复（半天）：**
   - `AgentService` fallback 分支：`plan_type=="third_party_advice"` 时调用 `llm_client.generate` 而非 `_format_router_fallback_answer`。
   - `ContextRequirementResolver._has_context("resume", ...)` 增加一条：若当前 message 长度超过阈值且含简历关键词，视为有 inline resume → `needs_more_context=False`，继续执行 resume 分析路径。

2. **Phase 5（主力工作）：** 统一 ResponseFormatter 输出协议，让 resume_analysis / interview_prep / career_insights 三条路径都产出结构化"结论/证据/行动"三段。

3. **Phase 3B/4（如果 Phase 5 后重跑仍暴露跨轮 replan 软失败，再写计划）：** 跨轮策略感知目前 0 硬 FAIL，先不动。

---

## 规则

本计划到此为止。Phase 5 实施计划在本文件写完之后、下次执行前另立文档。
