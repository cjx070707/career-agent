# Roadmap

## Completed

### Phase 1: ChatPlan Schema And Profile Safety

Phase 1 expanded the planning schema so the agent can carry richer task semantics without breaking the existing `/chat` contract. It also added safeguards so third-party career questions do not pollute the current user's profile.

### Phase 1.5: IntentRouter Semantic Alignment

Phase 1.5 aligned router output with the structured fields used later in the pipeline, including `task_type`, `domain`, `action`, and `plan_type`. The router remains responsible for high-confidence semantic routing, not final tool ordering.

### Phase 2A: Context And Tool Resolvers

Phase 2A added `ContextRequirementResolver` and `ToolResolver`. The context resolver decides what information is required and when to ask a follow-up; the tool resolver maps the semantic plan to available tools and makes `tool_chain` the execution source of truth when present.

### Phase 3A: Rule-Based Diagnosis Engine

Phase 3A added a deterministic `CareerDiagnosisEngine` behind the existing `get_career_insights` tool. It returns a fixed-shape diagnosis with evidence, confidence, priority, and recommended actions while preserving existing career insight payload fields.

## Not Implemented Yet

### Phase 3B: LLM-Assisted Diagnostic Planner

Phase 3B is not implemented. This phase would add LLM-assisted diagnostic planning on top of deterministic evidence, likely producing hypotheses and deciding what evidence to collect next.

### Phase 4: ReAct Planning Upgrade

Phase 4 is not implemented. This phase would upgrade planning and execution toward a fuller bounded ReAct loop, including richer observe/replan behavior while staying inside the existing tool and trace boundaries.

### Phase 5: Structured Reports And Presentation Layer

Phase 5 is not implemented. This phase would add structured report outputs, frontend cards, and deeper presentation support without changing the core agent boundaries prematurely.
