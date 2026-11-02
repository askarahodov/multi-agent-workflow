# ADR-001: Remove Hermes Implementation Ties

- **Status:** Proposed (architect) — pending review (`sdlc-reviewer`) and security gate (`sdlc-security`).
- **Date:** 2026-10-12
- **Author:** `sdlc-architect` (task `t_2fea0aed`)
- **Deciders:** project owner (human release gate), `sdlc-architect`, `sdlc-security`, `sdlc-release`
- **Supersedes:** ADR-010 §4 (AD-1 Kanban-as-backbone), ADR-010 §5.1 (spawn contract), ADR-010 §7 (workspace isolation convention), ADR-010 §13.1 (orchestration tooling), and the prescriptive Hermes recipes in `docs/research/01-autonomous-dev-patterns-report.md` and `tools/agent-orchestration/README.md`.
- **Related:** `docs/wiki/Hermes-Dependency-Inventory.md` (research input), `docs/architecture.md`, `CONTRIBUTING.md`.

---

## 1. Context and Problem

The product (Multi-Agent Workflow Platform) must have **no implementation relationship to Hermes**. The dependency inventory (`t_ceb4fb15`) confirms:

- **Product subsystems are already Hermes-independent**: zero `[Hh]ermes` references in `services/orchestration-server/`, `services/agent-management/`, `services/runtime-hardening/`, `services/quality-gates/`, or `apps/frontend/`.
- **All coupling is in dev/coordination tooling** under `tools/agent-orchestration/` (4 tooling files + 2 supporting scripts/tests) and in planning documentation (ADR-010, research report, README) that mandates Hermes as the coordination backbone.
- **No Hermes Python library imports exist**. Coupling is entirely to the Hermes **CLI** (`hermes kanban …`, `hermes -p <profile> chat …`) and the **on-disk board layout/schema** (`~/.hermes/kanban/boards/me/kanban.db`, `attachments/*/metadata.json`).

The goal is to eliminate these implementation ties while **preserving the required external behavior**: task DAG lifecycle, git worktree isolation, structured handoffs, review gates, hotspot detection, and observability.

---

## 2. Decision

**Replace the Hermes Kanban coordination backbone with a self-owned, generic Coordination Abstraction Layer (CAL)** that:

1. **Owns its own durable store** (SQLite, same schema concepts, no Hermes dependency).
2. **Exposes a stable internal CLI/API** (`cal kanban …`, `cal workspace …`, `cal hotspot …`) consumed by tooling.
3. **Retains the proven semantics**: atomic task claim, DAG promotion, review lifecycle, worktree isolation, artifacts, heartbeats, reclaim, diagnostics.
4. **Does not require Hermes at runtime**. The Hermes CLI, gateway, dispatcher, and profile system become optional external consumers, not implementation dependencies.

The existing `tools/agent-orchestration/` modules are **refactored in place** to depend on CAL instead of Hermes. Planning docs are updated to describe CAL as the authoritative coordination layer.

---

## 3. Rationale

| Criterion | Hermes (current) | CAL (proposed) |
|-----------|------------------|----------------|
| **Implementation ownership** | External project; we don't control schema, CLI, or dispatcher | We own the schema, CLI, and scheduler; no upstream breaking changes |
| **Product independence** | Violated — product tooling shells out to `hermes` CLI | Satisfied — zero Hermes calls in product or tooling |
| **Schema stability** | Hermes may change `kanban.db` schema, attachment metadata, CLI flags | Fixed by us; versioned migrations if needed |
| **Runtime dependency** | Requires Hermes gateway + dispatcher + profiles installed | Single binary/CLI (`cal`); no gateway, no systemd unit |
| **Observability** | `hermes kanban diag/watch/stats` | `cal diag/watch/stats` (same semantics, our code) |
| **Worktree convention** | Hard-coded `<repo>/.worktrees/<task-id>`, branch `<project-slug>/<task-id>` | Configurable convention; default same for compatibility |
| **Migration effort** | N/A (status quo) | Bounded: 4 tooling files + 2 scripts + 3 docs (per inventory) |
| **Risk** | Upstream changes break our tooling silently | We control the contract; testable in isolation |

**Key insight**: The *behavior* (task DAG, worktrees, handoffs) is a requirement. The *implementation* (Hermes) is not. We re-host the behavior under our ownership.

---

## 4. Architecture

### 4.1 High-Level Structure

```
┌─────────────────────────────────────────────────────────────────┐
│                     Coordination Abstraction Layer (CAL)        │
├─────────────────────────────────────────────────────────────────┤
│  ┌─────────────┐  ┌─────────────┐  ┌─────────────┐              │
│  │  cal kanban │  │ cal workspace│  │ cal hotspot │  ← Internal CLI (subcommands)  │
│  └──────┬──────┘  └──────┬──────┘  └──────┬──────┘              │
│         │                │                │                      │
│         ▼                ▼                ▼                      │
│  ┌─────────────────────────────────────────────────┐            │
│  │              CAL Core Library (Python)           │            │
│  │  • Task DAG + lifecycle (SQLite, WAL)           │            │
│  │  • Workspace manager (git worktree abstraction)  │            │
│  │  • Artifact store (files + metadata.json)        │            │
│  │  • Hotspot index (completion metadata → files)   │            │
│  │  • Scheduler (dispatch loop, reclaim, heartbeats)│            │
│  └─────────────────────────────────────────────────┘            │
│         │                │                │                      │
│         ▼                ▼                ▼                      │
│  ┌─────────────┐  ┌─────────────┐  ┌─────────────┐              │
│  │  cal.db     │  │ .worktrees/ │  │ artifacts/  │  ← On-disk contracts (owned) │
│  └─────────────┘  └─────────────┘  └─────────────┘              │
└─────────────────────────────────────────────────────────────────┘
                              │
                              ▼
┌─────────────────────────────────────────────────────────────────┐
│                    Tooling Consumers (refactored)               │
│  tools/agent-orchestration/agent_orchestration/              │
│    ├── kanban_tools.py      → imports CAL, no subprocess        │
│    ├── agent_workspace.py   → imports CAL workspace manager     │
│    └── scripts/             →                                   │
│         ├── spawn-agent.sh  → calls `cal kanban spawn …`        │
│         └── detect-hotspots.py → imports CAL hotspot index      │
└─────────────────────────────────────────────────────────────────┘
```

### 4.2 Component Responsibilities

| Component | Responsibility | Replaces |
|-----------|----------------|----------|
| `cal kanban` | Task CRUD, DAG, lifecycle, artifacts, diagnostics | `hermes kanban` |
| `cal workspace` | Worktree create/cleanup/status, branch naming | `agent_workspace.py` + `spawn-agent.sh` git logic |
| `cal hotspot` | Scan completions, index hotspots, detect collisions | `detect-hotspots.py` |
| `cal scheduler` | Dispatcher loop: claim → spawn worker → monitor → reclaim | Hermes gateway dispatcher |
| `cal.db` | SQLite store: tasks, deps, events, runs, comments, attachments | `~/.hermes/kanban/boards/me/kanban.db` |
| `artifacts/<task>/metadata.json` | Hotspot, changed_files, timestamp, summary | Same schema, new location |

### 4.3 Data Contracts (unchanged semantics, new ownership)

- **Task ID format**: `t_[a-z0-9]+` (retained for compatibility)
- **States**: `triage → todo → ready → running → (review \| done \| blocked \| scheduled)`
- **DAG**: parent → child promotion on `complete`
- **Artifacts**: `artifacts/<task-id>/metadata.json` with `hotspot[]`, `changed_files[]`, `timestamp`, `summary`
- **Worktree path**: `<repo>/.worktrees/<task-id>` (configurable)
- **Branch name**: `<project-slug>/<task-id>` (configurable)

### 4.4 Migration Strategy

| Phase | Action | Files Affected |
|-------|--------|----------------|
| **1. CAL Core** | Implement `cal` CLI + core library (SQLite schema, task DAG, workspace manager, artifact store, hotspot index, scheduler) | New: `tools/cal/` |
| **2. Refactor Tooling** | Rewrite `kanban_tools.py`, `agent_workspace.py`, `spawn-agent.sh`, `detect-hotspots.py` to use CAL | 4 tooling files |
| **3. Update Docs** | Replace Hermes references in ADR-010, research report, README with CAL equivalents | 3 doc files |
| **4. Cutover** | Point `multi-agent-workflow` board to CAL store; deprecate Hermes board | Config + 1-time data migration |
| **5. Verify** | Run pilot feature through full pipeline; confirm zero Hermes calls | Test/integration |

---

## 5. Affected Files (from inventory)

### Hard Coupling (implementation) — **Must Change**

1. `tools/agent-orchestration/agent_orchestration/kanban_tools.py` — replace `subprocess.run(["hermes", "kanban", ...])` with CAL library calls
2. `tools/agent-orchestration/agent_orchestration/agent_workspace.py` — replace `KANBAN_DB_PATH` reads + git worktree logic with CAL workspace manager
3. `tools/agent-orchestration/scripts/spawn-agent.sh` — replace `hermes -p $PROFILE chat -q "work kanban task $TASK_ID"` with `cal kanban spawn --task $TASK_ID --profile $PROFILE`
4. `tools/agent-orchestration/scripts/detect-hotspots.py` — replace DB/attachment scans with CAL hotspot index

### Transitive — **Update Imports**

5. `tools/agent-orchestration/demo_orchestration.py` — update imports
6. `tools/agent-orchestration/test_orchestration.py` — update imports + tests

### Structural Documentation — **Rewrite**

7. `docs/adr/ADR-010-multi-agent-orchestration.md` — replace AD-1 (Kanban-as-backbone) with CAL equivalent; update §5.1 spawn contract, §7 workspace convention, §13.1 tooling
8. `docs/research/01-autonomous-dev-patterns-report.md` — replace Hermes CLI recipes with CAL CLI recipes
9. `tools/agent-orchestration/README.md` — document CAL as the orchestration approach

### Incidental — **No Change Needed**

10. `docs/reviews/*.md`, `services/runtime-hardening/reports/coverage.xml` — path strings only; ignore

---

## 6. Non-Functional Requirements

| Category | Requirement |
|----------|-------------|
| **Security** | No secrets in `cal.db`, artifacts, or CLI output. `cal` runs as same host user; worktree isolation is not a security boundary. |
| **Performance** | Dispatcher loop ≤ 60 s interval (match Hermes). `cal.db` WAL mode for concurrent readers. |
| **Reliability** | Atomic task claim (SQLite transaction). Reclaim on heartbeat stale > 1 h or PID gone. Protocol violation = clean exit without terminal call → auto-requeue. |
| **Scalability** | Single-host, single-store (v1 bound). ≤ 19 parallel workers. |
| **Observability** | `cal diag --severity error --json`, `cal stats`, `cal watch`, `cal runs <id>` — parity with Hermes CLI. |
| **Maintainability** | CAL is a standalone module with its own tests. Tooling imports CAL, no subprocess shell-outs. |

---

## 7. Decisions

| ID | Problem | Selected Option | Rationale |
|----|---------|-----------------|-----------|
| **AD-1** | Coordination substrate ownership | Self-owned CAL (SQLite + CLI + scheduler) | Eliminates Hermes implementation tie; retains proven semantics; bounded migration |
| **AD-2** | Task lifecycle & DAG | Retain Hermes semantics exactly (states, promotion, reclaim) | Zero behavioral change for consumers; only implementation shifts |
| **AD-3** | Workspace isolation | CAL workspace manager (git worktree abstraction) | Same `<repo>/.worktrees/<task-id>` convention; configurable for future |
| **AD-4** | Worker spawn contract | `cal kanban spawn --task <id> --profile <name>` (subprocess) | Replaces `hermes -p … chat …`; profile resolution delegated to CAL |
| **AD-5** | Artifact & hotspot schema | Identical `metadata.json` (hotspot, changed_files, timestamp) | Drop-in for `detect-hotspots.py` and downstream consumers |
| **AD-6** | Observability CLI | `cal diag/watch/stats/runs` parity with Hermes | Operator workflows unchanged |
| **AD-7** | Migration | In-place refactor + 1-time `cal migrate --from-hermes --board me` | No parallel run; atomic cutover after verification |

---

## 8. Rejected Alternatives

| Decision | Option | Rejection Reason |
|----------|--------|------------------|
| AD-1 | Keep Hermes, add adapter layer | Adapter still shells out to Hermes CLI; doesn't remove implementation tie |
| AD-1 | Replace with Temporal/Redis/Celery | Over-engineered; SQLite + dispatcher already proven; adds ops burden |
| AD-1 | Use GitHub Issues/Projects as backbone | No atomic claim, no worktree integration, no structured handoffs |
| AD-2 | Redesign task states/DAG | Unnecessary churn; current model works and is understood |
| AD-3 | Drop worktree isolation | Reintroduces write-write collisions (observed failure mode) |
| AD-4 | Keep `hermes -p … chat …` spawn | Defeats the purpose; Hermes remains a runtime dependency |
| AD-7 | Run Hermes and CAL in parallel | Dual durable stores = split brain risk; no benefit |

---

## 9. Risks

| ID | Risk | Severity | Likelihood | Mitigation | Blocking |
|----|------|----------|------------|------------|----------|
| R1 | CAL scheduler has subtle behavioral differences vs Hermes dispatcher | High | Medium | Exhaustive integration tests mirroring ADR-010 acceptance criteria (§13.2) before cutover | Yes |
| R2 | Data migration from `~/.hermes/kanban/boards/me/kanban.db` loses history | High | Low | `cal migrate` reads Hermes DB schema directly; dry-run + verification step | Yes |
| R3 | Profile resolution (model, provider, toolsets) moves into CAL — divergence from Hermes profiles | Medium | Medium | CAL reads `~/.hermes/profiles/<name>/config.yaml` directly; no Hermes runtime needed | No |
| R4 | MCP servers (`mcp-hermes`, `mcp-tmux`) expect Hermes environment | Medium | Low | MCP servers are optional; CAL doesn't require them. Document as external. | No |
| R5 | Operator muscle memory (`hermes kanban …` vs `cal …`) | Low | High | Alias `hermes-kanban` → `cal` during transition; update runbooks | No |
| R6 | `cal.db` corruption = loss of all coordination state | High | Low | Backup cron (`cal backup`), `cal repair`, treat as critical asset (same as Hermes) | No |

---

## 10. Consequences

**Positive**
- Product achieves true Hermes implementation independence.
- Coordination layer is fully owned, testable, and versioned by us.
- No external runtime dependency (gateway, dispatcher, systemd unit) for coordination.
- Schema, CLI, and behavior changes are under our control.

**Negative / Costs**
- New code to build and maintain: `tools/cal/` (~2-3 kLOC estimated).
- One-time migration of task history from Hermes board.
- Operators must learn `cal` CLI (mitigated by parity + alias).
- ADR-010 becomes partially obsolete; will be superseded by ADR-001 and a new CAL ADR.

**Neutral**
- Product subsystem code unchanged (already independent).
- 19-profile catalog, MCP servers, git worktree convention, review gates — all preserved.

---

## 11. Acceptance Criteria (verifiable)

- [ ] `tools/cal/` exists with `cal` CLI (`kanban`, `workspace`, `hotspot`, `scheduler`, `migrate`, `diag`, `stats`, `watch`, `runs`, `backup`, `repair`).
- [ ] `kanban_tools.py`, `agent_workspace.py`, `spawn-agent.sh`, `detect-hotspots.py` import `cal` and contain **zero** `hermes` subprocess calls or `~/.hermes/kanban` path references.
- [ ] `cal migrate --from-hermes --board me` imports all tasks, deps, events, runs, comments, attachments from `~/.hermes/kanban/boards/me/kanban.db` into `cal.db` with fidelity (counts match).
- [ ] Pilot feature (e.g., "destination mapping for mixed bundles") runs end-to-end on CAL: task creation → worktree → implementation → test → review → complete → child promotion; **zero Hermes CLI invocations**.
- [ ] All ADR-010 acceptance criteria (§13.2) pass on CAL: worktree isolation, reclaim, protocol violation detection, review gate, hotspot detection, observability, no secrets.
- [ ] ADR-010, research report, and README updated to reference CAL; no prescriptive Hermes commands remain.
- [ ] Security gate: spot-check `cal.db`, artifacts, CLI output for secrets/PII — none found.

---

## 12. Implementation Sequence

1. **CAL Core** (`tools/cal/`)
   - `cal/db.py` — SQLite schema, migrations, connection pool
   - `cal/models.py` — Task, Dep, Event, Run, Comment, Attachment dataclasses
   - `cal/kanban.py` — Task CRUD, DAG, lifecycle, artifacts, diagnostics
   - `cal/workspace.py` — Worktree manager (create, cleanup, status, branch naming)
   - `cal/hotspot.py` — Hotspot index, collision detection
   - `cal/scheduler.py` — Dispatcher loop, spawn, heartbeat monitor, reclaim
   - `cal/cli.py` — Typer/Click CLI with all subcommands
   - `cal/migrate.py` — Hermes DB → CAL DB import
2. **Refactor Tooling** (in-place)
   - `kanban_tools.py` → import `cal.kanban`
   - `agent_workspace.py` → import `cal.workspace`
   - `spawn-agent.sh` → `cal kanban spawn …`
   - `detect-hotspots.py` → import `cal.hotspot`
3. **Update Docs**
   - ADR-010: replace AD-1, §5.1, §7, §13.1; add "Superseded by ADR-001" banner
   - Research report: replace Hermes recipes with CAL recipes
   - README: document CAL
4. **Migration & Cutover**
   - `cal migrate --from-hermes --board me --dry-run` → verify counts
   - `cal migrate --from-hermes --board me` → execute
   - Point `multi-agent-workflow` coordination to CAL store
5. **Verification**
   - Run pilot feature through full pipeline
   - Execute ADR-010 §13.2 acceptance criteria as integration tests

---

## 13. Appendix — CAL CLI Sketch

```bash
# Task lifecycle (parity with hermes kanban)
cal kanban create "Implement X" --assignee sdlc-developer --workspace worktree --parent <id> --project multi-agent-workflow
cal kanban show <task-id>
cal kanban list --filter "parents:<id>"
cal kanban promote <task-id> --reason "Parent completed"
cal kanban complete <task-id> --summary "..." --metadata '{"changed_files": [...]}' --artifacts /abs/path/report.md
cal kanban request-review <task-id> --summary "..." --metadata '{}'
cal kanban block <task-id> --kind dependency --reason "..."

# Workspace
cal workspace create <task-id> [--branch <name>] [--repo <path>]
cal workspace status <task-id>
cal workspace cleanup <task-id>

# Hotspot
cal hotspot scan [--window-days 7] [--format json|text|summary]
cal hotspot report <task-id>

# Scheduler / observability
cal scheduler start  # runs dispatcher loop (systemd unit in prod)
cal diag --severity error --json
cal stats
cal watch
cal runs <task-id>

# Migration / maintenance
cal migrate --from-hermes --board me [--dry-run]
cal backup --output /path/cal.db.bak
cal repair
```

---

*End of ADR-001.*