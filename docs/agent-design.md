# Agent 设计原则

> 本文件回答"为什么这么设计"，是写给所有参与开发的人（包括 AI 工具）的设计哲学文档。
> 读完这份文档，你应该能判断任何一个新功能"符不符合这个项目的设计方向"。

---

## 一、这个项目想做什么

**一句话**：一个真正由 LLM 驱动的垂直求职 Agent，不是 workflow。

区别很重要：

| Workflow | Agent |
|---|---|
| 执行预先定义好的步骤序列 | LLM 在执行过程中动态决定下一步 |
| 规则决定路径 | LLM 理解意图并推理 |
| 新场景要改代码 | 新场景改 prompt |
| 对自然语言变体脆弱 | 对自然语言变体鲁棒 |

当前代码库（2026-04-29 之前）是 workflow 伪装成 agent。规则树路由、预规划步骤序列、碎片化的 formatter——这些都是 workflow 的特征。重构目标是把"LLM 驱动"从口号变成代码现实。

---

## 二、三条核心原则

### 原则 1：LLM 做决策，规则做边界

**LLM 负责**：理解意图、决定调用哪个工具、判断信息是否充分、生成回答

**规则负责**：
- 极端简单场景的快捷路径（greeting、capability help）
- 执行层的安全边界（工具白名单、步长上限、重复保护）

**不允许**：用规则树模拟 LLM 的语言理解能力（即：不允许出现 `if "简历" in message and "更强" in message` 这类逻辑作为主路由）

### 原则 2：观察驱动，不预规划

ReAct 的核心不是"先规划再执行"，而是"执行一步，观察结果，再决定下一步"。

这意味着：
- 不允许在请求开始时就锁定完整的工具调用序列
- 每次工具调用后，LLM 要重新评估：我现在知道什么，还缺什么，下一步该做什么
- LLM 可以在任意时刻决定"信息已经足够，直接回答"

### 原则 3：输出有结构，证据有来源

所有回答遵循：**结论 → 证据 → 行动建议**

- 结论：直接回答用户问题，1-2 句
- 证据：必须来自工具返回的真实数据，不允许 LLM 凭空生成
- 行动建议：具体可执行，不超过 3 条

这个结构的意义：可解释、可验证、可测试（eval 断言可直接检查）。

---

## 三、ReAct 循环详解

ReAct = Reasoning + Acting，核心是 **"先想再做"** 的迭代循环。

### 每次迭代的结构

```
[输入给 LLM]
当前用户问题：{message}
对话历史：{recent_turns}
已调用工具及结果：
  - get_candidate_profile → { name: 张三, target_role: backend intern, ... }
  - get_resume_by_id → { skills: [Python, FastAPI], experience: 3个月后端实习, ... }
可用工具：[search_jobs, match_resume_to_jobs, get_career_insights, ...]

[LLM scratchpad]
我现在知道：用户是 USYD 后端实习生，有 Python/FastAPI 技能，3 个月实习经验
我还需要：候选岗位列表才能做匹配
因此下一步：调用 search_jobs 搜索 Sydney backend intern 岗位

[LLM 输出]
{ "action": "call_tool", "tool": "search_jobs", "reasoning": "需要获取候选岗位..." }
```

### 什么时候终止

LLM 自主判断。一般情况：
- 已有足够数据可以直接回答 → `{ "action": "finish" }`
- 触达 MAX_STEPS=8 → 强制终止，用已有数据生成最佳回答

### 什么时候追问用户

LLM 判断缺少关键上下文（不是工具数据，而是用户输入本身），例如：
- 用户没有提供简历，也没有上传过 → 追问简历
- 用户说"帮我准备面试"但没说目标岗位 → 追问岗位

这个判断**不由规则决定**，由 LLM 在每次迭代中评估。

---

## 四、LLM Intent Classifier 详解

### 它解决什么问题

旧的 IntentRouter + IntentGateway 是 1200 行关键词匹配规则，对语言变体极其脆弱。用户说"我的简历该怎么更强"，系统就不知道这是简历优化请求。

Classifier 用 LLM 替代这 1200 行，一次调用完成意图识别 + 上下文判断 + 步骤建议。

### 它不是什么

- 不是完整的规划器（不需要规划出完整执行序列，那是 ReAct 循环的事）
- 不是 LLM Planner 的替代（LLM Planner 是旧架构的产物，新架构不存在 Planner 这个角色）
- 不会直接决定工具调用（工具调用由 ReAct 循环的每步迭代决定）

### 输出的 steps 字段的意义

Classifier 输出的 `steps` 是**建议**，不是命令。ReAct 循环拿到这个建议作为初始参考，但每步都可以偏离——因为 LLM 在看到工具结果后可能会改变判断。

---

## 五、什么不应该出现在这个项目里

以下模式出现时，应该发出警告并重构：

**反模式 1：关键词路由**
```python
# ❌ 禁止
if "简历" in message and any(kw in message for kw in ("优化", "提升", "更强")):
    task_type = "resume_analysis"
```
正确做法：这个判断交给 LLM Classifier。

**反模式 2：硬编码步骤序列**
```python
# ❌ 禁止
steps = ["get_candidate_profile", "get_resume_by_id", "search_jobs", "match_resume_to_jobs"]
for step in steps:
    execute(step)
```
正确做法：步骤由 ReAct 循环的每次迭代动态决定。

**反模式 3：task_type 特殊 formatter**
```python
# ❌ 禁止
if task_type == "resume_analysis":
    return format_resume_answer(result)
elif task_type == "interview_prep":
    return format_interview_answer(result)
```
正确做法：所有 task_type 走统一输出协议。

---

## 六、技术决策记录

### 为什么不用 LangChain / LlamaIndex

这个项目手写 agent 编排逻辑，不依赖 LangChain 等框架。原因：

1. 框架抽象掩盖了 agent 的真实工作原理，不利于面试时的深度讲解
2. 框架的 opinionated 结构限制了自定义 ReAct 循环的设计自由度
3. 手写的代码是面试里最好的话题材料

### 为什么选择垂直域而不是通用 Agent

求职场景天然限制了工具集（resume / jobs / applications / interviews），使得 ReAct 循环可以被充分验证和测试。通用 Agent 工具集开放，eval 难度极高，学生项目不适合做。

垂直 Agent 在行业里本身是有价值的研究和工程方向，不是通用 Agent 的降级版。

### 为什么有 Eval Harness

没有 eval，所有架构改动都是盲目的。Eval harness 的存在让每次重构都可以量化：改了之后比改之前好多少。这也是这个项目和大多数学生项目最大的区别之一。
