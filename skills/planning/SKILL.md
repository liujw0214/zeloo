---
name: planning
class: workflow
description: >-
  Software implementation planning with optional file-based persistence. Use
  when asked to plan, when unresolved architecture or scope decisions need a
  durable record, or when multi-phase implementation needs recovery state.
platforms: [cli, tui, api]
toolsets: [terminal, file]
---

# Planning

## Core Principle
```
Context window = RAM (volatile, limited)
Filesystem     = Disk (persistent, unlimited)
→ Persist only state that would be costly to reconstruct.
```

Planning exists to reduce implementation risk and preserve necessary state. Scale it to unresolved decisions, dependency depth, and continuity needs rather than file count or tool activity alone.

## Procedure

1. Run the *Goal Quality Gate* on the stated goal
2. Pick the path per *When to Plan*: full plan, flat list, or skip
3. For a full plan, scaffold `.plan/` via `init-plan.sh`
4. Write the plan per the *Plan Template*, applying the quality, sizing, and task rules
5. Run the *Verify* checklist against the finished plan
6. Continue authorized implementation unless *Execution Handoff* identifies a material choice

## Goal Quality Gate

Run this gate before *When to Plan* — a weak goal wastes tokens and produces an unverifiable result. Answer:

1. **What concrete thing will be true when this is done?**
2. **What evidence will prove it?**
3. **What quantitative or binary threshold defines success?**
4. **What scope boundaries matter?**
5. **What should cause the agent to stop and ask?**

## When to Plan

- **Full plan** (`.plan/` directory): multi-phase work crossing sessions
- **Flat list** (inline checklist): clear multi-step work in one session
- **Skip the plan**: direct implementation with clear scope and acceptance criteria

## Planning Files

Scaffold `.plan/` directory with:
```bash
bash "$SKILL_DIR/scripts/init-plan.sh" "Feature Name"
```

Creates `.plan/task_plan.md` and adds `.plan/` to `.gitignore`.

## Plan Template

```markdown
# Plan: [Feature/Task Name]

## Approach
[1-3 sentences: what and why]

## Scope
- **In**: [what's included]
- **Out**: [what's explicitly excluded]

## Key Decisions
[Decisions likeliest to change on review]

## File Structure
| File | Action | Responsibility |
|------|--------|----------------|

## Next Step
[one line: the phase and task to resume on]

## Phase 1: [Name]
**Status**: pending | in_progress | complete

**Tasks**:
- [ ] [Verb-first atomic task]

**Verify**: [specific test or command]

## Deferred to Implementation
- [Things intentionally left unspecified]

## Open Questions
- [Only genuinely blocking unknowns]
```

## Plan Quality Rules

- Keep phase state current
- No placeholders in tasks — concrete code patterns, commands, file paths
- Type-consistency check across all tasks
- No gold-plating — build exactly what the spec requires
- Front-load high-variance decisions

## Phase Sizing Rules

Every phase must be **context-safe**:
- End in one coherent, independently verifiable capability
- Fit in available context
- Name dependencies whose failure would block the phase
- Split only when each part has a meaningful verification boundary

## Task Rules

Write every task as if the implementer has zero context:
- **Atomic**: one independently verifiable action
- **Verb-first**: "Add...", "Create...", "Refactor...", "Verify..."
- **Concrete**: name specific files, endpoints, components
- **Ordered**: respect dependencies
- **Verifiable**: include at least one validation task per phase

## Decision Authority

**Claude decides (technical):** language, framework, architecture, libraries, file structure, naming conventions, test strategy

**User decides (experience-affecting):** scope tradeoffs, UX choices, data model decisions that constrain future options

## Clarifying Questions

Ask only about decisions in the "user decides" category. Batch material unknowns, make reasonable assumptions for everything else.
