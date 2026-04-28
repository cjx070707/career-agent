# Demo Script

## Case 1: Resume Summary Missing Resume

**用户输入**

`总结一下我的简历`

**预期链路**

`IntentRouter` routes to resume summary semantics. `ContextRequirementResolver` requires resume context, marks it missing, and returns a follow-up. No tool should execute.

**预期输出重点**

The answer should ask the user to provide or upload resume information. It should not invent a resume summary.

**面试时怎么讲**

This shows context gating: the agent can recognize the task, but it refuses to act without the required evidence.

## Case 2: Job Match Missing JD

**用户输入**

`帮我看看这个岗位适不适合我`

**预期链路**

`IntentRouter` routes to job matching semantics. `ContextRequirementResolver` requires resume and job detail; when the JD is missing, it asks for the job description or link instead of running matching tools blindly.

**预期输出重点**

The answer should clearly ask for the target job description. Tool execution should be blocked until the critical context is available.

**面试时怎么讲**

This demonstrates that job matching is evidence-based. The agent separates "I know what you want" from "I have enough data to do it."

## Case 3: Search Data Analyst Jobs

**用户输入**

`帮我找几个数据分析岗位`

**预期链路**

`IntentRouter` routes to job search. `ContextRequirementResolver` derives `job_query` from the message. `ToolResolver` selects `search_jobs`, and `PlanExecutor` runs it.

**预期输出重点**

The answer should include relevant job results and grounded source snippets. `tool_chain` and `executed_steps` should include `search_jobs`.

**面试时怎么讲**

This shows the normal happy path: intent routing, context resolution, controlled tool selection, retrieval, and answer formatting.

## Case 4: Applications Have No Progress

**用户输入**

`我投了很多岗位但一直没进展，下一步怎么办？`

**预期链路**

`IntentRouter` routes to career strategy or career insights. `ToolResolver` selects `get_career_insights`. The tool aggregates profile, applications, interviews, and feedback, then calls `CareerDiagnosisEngine`.

**预期输出重点**

The answer should include a short diagnosis summary, evidence-backed risk areas, and next actions. If applications exist but interviews do not, the likely bottleneck is `resume_positioning`; if the data is weaker, confidence should stay lower.

**面试时怎么讲**

This shows Phase 3A: deterministic diagnosis with evidence and confidence, not an LLM making unsupported claims.

## Case 5: Third-Party Friend Advice

**用户输入**

`我朋友想找 Java 后端岗位，你觉得他该怎么准备？`

**预期链路**

`IntentRouter` identifies third-party advice semantics. `ContextRequirementResolver` should not require the current user's resume or profile. `ToolResolver` should not call current-user profile tools such as `get_candidate_profile`.

**预期输出重点**

The key behavior is profile isolation: the current user's profile should not be read or updated for the friend's situation. Any answer should stay generic rather than pretending the friend has the current user's background.

**面试时怎么讲**

This demonstrates profile anti-pollution. The agent distinguishes advice about the current user from advice about another person.
