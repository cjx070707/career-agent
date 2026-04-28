# AGENTS.md

## Project Direction

This repository is for a Controlled Vertical Career Agent.

It is not an open-ended autonomous agent, and it is not a place to add broad workflow machinery for every new idea. All implementation should serve the existing product path:

`IntentRouter -> Structured Planner -> ContextRequirementResolver -> Diagnostic Planner -> ToolResolver -> Bounded ReAct Executor -> Response Composer -> Profile Update`

Use these source documents as the product reference:

- `docs/controlled-vertical-career-agent-prd.md`
- `docs/controlled-vertical-career-agent-plan-map.md`

## Anti-Mess Rules

1. Do not create a chain of new folders or files for a small feature.
   Prefer changing existing modules first. Extract a new file only when the responsibility is stable and reused in more than one place.

2. Do not rewrite the architecture from scratch.
   New capability should enter through compatible wrappers, resolvers, validators, or optional schema fields. Keep `AgentService.respond()`, `chat.v1`, traces, and existing tests working.

3. Keep LLM responsibility bounded.
   The LLM may produce task semantics. It must not directly own low-level tool order. Tool selection belongs in `ToolResolver`.

4. Keep context checks centralized.
   Required and optional context such as resume, job detail, target role, current skills, applications, and interview feedback should be handled by `ContextRequirementResolver`, not scattered across routes and executors.

5. Do not make high-confidence diagnostic claims without evidence.
   Career diagnosis must include evidence, confidence, priority, and recommended actions. If evidence is insufficient, return `insufficient_evidence` or ask a follow-up question.

6. Preserve backward compatibility.
   Add fields to `ChatPlan` and `ChatResponse` as optional first. Do not break existing contracts, traces, or tests while introducing structured planning or structured reports.

7. Work by phase.
   Phase 1 should not secretly implement Phase 5. Phase 2 should not casually rewrite the executor. Stay within the phase described by the plan map unless the user explicitly changes scope.

8. Before editing code, answer these privately:
   - Which PRD phase does this belong to?
   - Can this fit into an existing file or module?
   - What test or contract proves the old path still works?

9. File budget:
   A single phase should normally add no more than 2-3 production code files. If more are needed, explain why the responsibilities cannot live in existing modules.

10. Tests should prove behavior, not class names.
    Prioritize contract, resolver, diagnosis, replan, and profile anti-pollution behavior from the PRD.

## Default Implementation Style

- Keep edits narrow and compatible.
- Reuse existing router, planner, registry, service, trace, and test patterns.
- Prefer Pydantic validators and explicit resolver results over ad hoc string checks.
- Add observability when a resolver, diagnostic decision, or replan changes behavior.
- Avoid speculative abstractions. Add structure only when it removes real duplication or protects a product boundary.

