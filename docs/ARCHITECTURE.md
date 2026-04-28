# Architecture

## Current Scope

This project is a controlled Career Coaching Agent. It is designed for a narrow career-coaching domain rather than open-ended autonomous work: user input is routed into explicit task semantics, context requirements are checked before tool execution, tools are selected from a bounded registry, and the final answer is formatted through a stable `/chat` response contract.

The current implemented phases are Phase 1, Phase 1.5, Phase 2A, and Phase 3A. Phase 3B, Phase 4, and Phase 5 are intentionally not implemented yet.

## `/chat` Main Flow

1. `POST /chat` receives `user_id` and `message`.
2. `AgentService.respond()` loads recent memory and updates safe profile/event signals.
3. `IntentRouter` tries to produce a structured `ChatPlan` for high-confidence intents.
4. If routing cannot confidently plan the request, the LLM planner fallback attempts to produce a compatible plan.
5. `ContextRequirementResolver` checks what context the plan needs, what is missing, and whether the agent should ask a follow-up question.
6. If required context is missing, the agent returns the follow-up and executes no tools.
7. `ToolResolver` maps the resolved plan and context to a bounded `tool_chain`.
8. `PlanExecutor` executes the resolved tool order. A non-empty resolver `tool_chain` takes priority over legacy `plan.steps`; `plan.steps` remains available for compatibility and debug.
9. `CareerDiagnosisEngine` may run inside `get_career_insights` and returns deterministic diagnosis data as part of that tool payload.
10. `ResponseFormatter` converts tool payloads into a user-facing answer and sources while preserving the `chat.v1` top-level response shape.

## Module Boundaries

### Router

`app/routing/intent_router.py` handles high-confidence rule routing. Its job is to translate obvious user intents into task semantics such as `task_type`, `domain`, `action`, and `plan_type`. It should not decide low-level tool order.

### LLM Planner Fallback

The LLM planner is used only when the router cannot confidently produce a plan. It must return a contract-compatible plan and remains guarded by validation and fallback behavior. It does not own final tool execution priority.

### ContextRequirementResolver

`app/resolvers/context_requirement_resolver.py` centralizes required context decisions. It decides whether a request needs resume data, job details, job query, target role, profile, applications, or interviews. It also protects third-party advice from requiring or polluting the current user's profile.

### ToolResolver

`app/resolvers/tool_resolver.py` maps the semantic plan to a bounded list of available tools. It distinguishes critical and optional tools, emits resolver traces, and prevents legacy `steps=[]` from suppressing a non-empty resolver `tool_chain`.

### PlanExecutor

`app/services/plan_executor.py` executes the tool names it receives. It should stay close to execution mechanics: validating inputs, invoking registered tools, collecting outputs, and returning traceable results. It should not duplicate routing, context, or diagnosis policy.

### CareerDiagnosisEngine

`app/services/career_diagnosis_engine.py` is the Phase 3A deterministic diagnosis layer. It produces one fixed-shape diagnosis with `bottleneck_type`, `diagnosis_summary`, `confidence`, `priority`, `evidence`, and `recommended_actions`. It is rule-based only and is called from `get_career_insights`.

### ResponseFormatter

`app/services/response_formatter.py` turns tool payloads into natural-language answers and source lists. For `get_career_insights`, it adds a short diagnosis sentence based on the diagnosis payload. It does not change the `/chat` top-level schema and does not introduce `structured_report`.

## Why This Is A Controlled Agent Pipeline

The current system is not a simple linear workflow because routing, fallback planning, context gating, tool resolution, bounded execution, memory, and response formatting are separate decisions with observable traces. The agent can adapt the execution path based on the user's intent and available context.

It is also not an open autonomous agent. Tool choice is bounded by `ToolResolver`, context checks are centralized, tool execution is constrained by `PlanExecutor`, and `/chat` keeps the stable `chat.v1` response contract. That is the main design principle: agent-like planning and tool use, but under explicit product and safety boundaries.
