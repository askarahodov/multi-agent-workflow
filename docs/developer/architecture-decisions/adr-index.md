# Architecture Decision Records Index

This directory contains Architecture Decision Records (ADRs) documenting significant architectural decisions for the Multi-Agent Workflow System.

## ADR List

| ID | Title | Status | Date | Supersedes |
|----|-------|--------|------|------------|
| [001](001-hermes-independence.md) | Hermes Independence | Accepted | 2025-01-15 | - |
| [010](ADR-010-multi-agent-orchestration.md) | Multi-Agent Orchestration | Accepted | 2025-02-20 | - |
| [011](ADR-011-agent-runtime-loop.md) | Agent Runtime Loop | Accepted | 2025-02-25 | - |
| [012](ADR-012-tool-registry.md) | Tool Registry | Accepted | 2025-03-01 | - |
| [013](ADR-013-mvp-core-subsystems.md) | MVP Core Subsystems | Accepted | 2025-03-10 | - |
| [014](ADR-014-cross-subsystem-integration.md) | Cross-Subsystem Integration | Accepted | 2025-03-15 | - |
| [015](ADR-015-management-api-auth.md) | Management API Authentication | Accepted | 2025-03-20 | - |
| [016](ADR-016-sdlc-template-automation.md) | SDLC Template Automation | Accepted | 2025-03-25 | - |

## ADR Template

When creating a new ADR, use this template:

```markdown
---
adr: NNN
title: Short Title
status: Proposed | Accepted | Rejected | Superseded
date: YYYY-MM-DD
authors: [Author Names]
supersedes: [ADR-XXX] (if applicable)
superseded_by: [ADR-YYY] (if applicable)
tags: [tag1, tag2]
---

# ADR-NNN: Title

## Context

[Describe the forces at play: technological, political, social, project local.
This section describes the situation that led to this decision.]

## Decision

[Describe the decision in full sentences with active voice.
"This decision..." not "Decided to..."]

## Consequences

### Positive
- [Benefit 1]
- [Benefit 2]

### Negative
- [Drawback 1]
- [Drawback 2]

### Neutral
- [Observation 1]

## Alternatives Considered

### Alternative 1: [Name]
[Description]
**Pros:** [...]
**Cons:** [...]

### Alternative 2: [Name]
[Description]
**Pros:** [...]
**Cons:** [...]

## Implementation Notes

[Optional: Technical details, migration path, rollback plan]

## References

- [Link to related issue/PR]
- [Link to documentation]
- [Link to external resources]
```

## Creating a New ADR

```bash
# Determine next number
ls docs/architecture-decisions/ | grep -E '^[0-9]{3}-' | sort -V | tail -1

# Create new file
cat > docs/architecture-decisions/018-new-decision.md << 'EOF'
---
adr: 018
title: New Decision Title
status: Proposed
date: 2025-10-16
authors: [Your Name]
tags: [tag1, tag2]
---

# ADR-018: New Decision Title

## Context
...

## Decision
...

## Consequences
...

## Alternatives Considered
...

## Implementation Notes
...

## References
...
EOF
```

## ADR Statuses

| Status | Meaning |
|--------|---------|
| `Proposed` | Under discussion, not yet decided |
| `Accepted` | Agreed upon, being implemented |
| `Rejected` | Decided against |
| `Superseded` | Replaced by newer ADR |

## Reading ADRs

- **Chronological:** Sort by date (filename prefix)
- **By Topic:** Use tags to find related decisions
- **Current Architecture:** Read all `Accepted` ADRs

## Cross-References

ADRs reference each other using relative links:
- `[ADR-010](./ADR-010-multi-agent-orchestration.md)`
- See [ADR-014](./ADR-014-cross-subsystem-integration.md) for integration patterns

---

*Last updated: 2025-10-16 | Total ADRs: 9*