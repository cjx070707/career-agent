# Agent Evaluation Strategy

> 适用范围：Career Agent（ReAct 自主 agent 架构）  
> 最后更新：2026-05-05（v2：Adzuna mock、意图边界修复、断言精度迭代）

---

## 为什么要测 Agent 质量

Agent 和传统软件不同——输出是概率性的，没有"唯一正确答案"。  
但这不意味着质量不可测。我们把可测的维度拆成三层，每层有独立的指标和跑法。

---

## 三个评估维度

### 维度 1：工具调用准确性（Tool Selection Accuracy）

**测什么**：给定用户输入，agent 有没有调对工具、顺序对不对。

**为什么重要**：工具调错了，答案无论措辞多好都是错的。这是最基础的 gate。

**实现**：`evals/run_eval.py` + `evals/dataset.jsonl`

每个 case 定义 `expect.tool_trace_prefix` / `expect.tool_trace_contains` / `expect.tool_trace_equals`：

```json
{
  "id": "gap-with-resume",
  "message": "帮我分析简历和 TikTok 的差距",
  "expect": {
    "tool_trace_prefix": ["analyze_gap"],
    "answer_contains_any": ["差距", "技能", "建议"]
  }
}
```

**指标**：`pass_rate`（目标 ≥ 0.85）

**运行**：
```bash
# 标准运行（需要后端已启动）
python3 evals/run_eval.py --dataset evals/dataset.jsonl

# 使用 Adzuna mock（搜索结果不依赖外部 API，适合 CI）
EVAL_USE_ADZUNA_MOCK=1 python3 evals/run_eval.py
```

---

### 维度 2：答案质量（Answer Quality — LLM-as-Judge）

**测什么**：答案的整体质量——是否有用、有没有幻觉、语气是否合适。

**为什么用 LLM-as-judge**：
- 答案没有唯一模板，字符串匹配覆盖不全
- 人工评估规模上不去
- LLM 对"这个回答对求职学生有没有帮助"有可靠判断

**维度拆解（Judge Rubric）**：

| 维度 | 满分 | 评分标准 |
|------|------|----------|
| 工具使用合理性 | 5 | 调了正确工具、没有多余调用 |
| 答案针对性 | 5 | 直接回答了用户问题，没有答非所问 |
| 无幻觉 | 5 | 没有编造岗位、技能、公司信息 |
| 语气适合场景 | 5 | coaching 语气，不是机器人式罗列 |

**合格门槛**：各维度平均分 ≥ 3.5 / 5，且"无幻觉"单项 ≥ 4。

**实现**：`evals/run_judge_eval.py`

```bash
python3 evals/run_judge_eval.py --dataset evals/dataset.jsonl
```

---

### 维度 3：轨迹合理性（Trajectory Quality）

**测什么**：多步推理链是否合理——有没有冗余工具调用、有没有正确利用前一步的返回值。

**举例**：
- ✅ 合理轨迹：`analyze_gap` → 发现无简历 → 给出上传引导
- ❌ 冗余轨迹：`get_candidate_profile` → `search_jobs` → `get_candidate_profile`（重复调用）

**现阶段做法**：在 LLM-as-judge 的 prompt 里加 `loop_trace` 上下文，让 judge 同时评估轨迹合理性。

**长期**：构建 trajectory golden set，对每个 multi-step case 定义允许的工具调用序列范围。

---

## Offline vs Online

| | Offline Eval | Online Signals |
|---|---|---|
| **数据来源** | `dataset.jsonl` golden set | 真实用户行为 |
| **速度** | 快，可 CI 集成 | 慢，需要积累 |
| **覆盖** | 你想到的场景 | 你想不到的场景 |
| **指标** | pass_rate, judge scores | 简历上传率、后续追问率、目标设定转化率 |
| **用途** | 发布前 gate、prompt 改动验证 | 长期质量监控 |

**当前项目**：Offline eval 作为每次大改动前的必跑 gate，Online 指标暂未接入，下阶段补。

---

## 现有 Dataset 覆盖范围（37 cases）

| 场景分类 | Case 数量 | 状态 |
|----------|-----------|------|
| 岗位搜索（多种表达） | 6 | ✅ |
| 候选人画像查询 | 1 | ✅ |
| 无简历时请求匹配 | 1 | ✅ |
| 带简历推荐岗位（含 compound match） | 2 | ✅ |
| Career insights | 2 | ✅ |
| 闲聊 fallback | 1 | ✅ |
| 灰色地带（模糊意图） | 4 | ✅ |
| Gap 分析（无简历/有简历） | 2 | ✅ |
| 纯闲聊不调工具 | 1 | ✅ |
| 目标设定 | 1 | ✅ |
| 多轮对话（goal/resume/insights/search/log） | 5 | ✅ |
| 简历 + 应用 + 面试查询 | 4 | ✅ |
| 负向 case（拒绝/边界） | 4 | ✅ |

**基线**（2026-05-05，qwen3.5-plus-2026-04-20，thinking off）：30/37 通过，pass_rate = 81%

---

## 运行顺序建议

```
1. python3 evals/run_eval.py           # 工具路由 + 关键词检查（快，<2min）
2. python3 evals/run_judge_eval.py     # LLM-as-judge 质量评估（慢，需 API key）
3. 对比 evals/reports/ 下前后两次报告
```

---

## Case 编写规范

### 确定性检查（`dataset.jsonl`）
适合：有明确预期工具调用、有必须出现的关键词的场景

```json
{
  "id": "gap-no-resume",
  "user_id": "eval-gap-noresume",
  "message": "帮我分析简历和 TikTok 的差距",
  "seed": {},
  "expect": {
    "tool_trace_prefix": ["analyze_gap"],
    "answer_contains_any": ["上传", "Cmd+V", "📎", "简历"]
  }
}
```

### 质量评估（`judge_dataset.jsonl`）
适合：没有唯一正确答案、需要整体质量判断的场景

```json
{
  "id": "judge-gap-guidance",
  "user_id": "eval-gap-noresume",
  "message": "帮我分析简历和 TikTok 的差距",
  "seed": {},
  "judge_criteria": [
    "回答是否明确说明无法在没有简历的情况下做 gap 分析",
    "是否给出了具体的上传方式（Cmd+V 或 📎）",
    "语气是否友好、不是冷冰冰的报错"
  ]
}
```

---

## 已知局限

1. **Judge 本身不稳定**：LLM-as-judge 在边界 case 上打分不一致，建议多跑几次取平均。
2. **Golden set 偏向已知场景**：eval 通过不代表没有 corner case，需要定期用真实用户 query 补充 case。
3. **Seed 数据隔离**：多个 case 共用 user_id 可能产生状态污染，每次完整 eval 应从干净 DB 启动。
4. **Adzuna 外部依赖**：默认模式下搜索类 case 的 sources 结果受实时 API 影响。CI 环境建议用 `EVAL_USE_ADZUNA_MOCK=1` 隔离。
5. **关键词硬匹配兜底**：classifier 目前有基于关键词的后处理规则（"我想找" → job_search）以弥补 LLM 意图边界不稳定的问题。这是技术债，后续应通过 few-shot 优化 prompt 替代。
