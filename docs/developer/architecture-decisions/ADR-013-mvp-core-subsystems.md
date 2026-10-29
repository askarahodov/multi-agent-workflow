# ADR-013: MVP v1 Core Subsystems — Kanban, Memory, Schedules

**Status:** Proposed
**Date:** 2026-10-12
**Author:** sdlc-architect (task t_8cf664ab)
**Related:** GAP-ANALYSIS.md (G3), PRD §8, §9, §10, §11, §19, `docs/domain-architecture.json`, ADR-102 (ownership)

---

## 1. Context and Problem

PRD §19 (v1 core) mandates these subsystems as **mandatory for MVP v1**:

| Subsystem | PRD Ref | GAP-ANALYSIS Status |
|-----------|---------|---------------------|
| Kanban Board | §8 | **MISSING** (product) — only dev meta-tool exists |
| Chats | §9 | **MISSING** |
| Memory | §10 | **MISSING** |
| Schedules / Cron | §11 | **MISSING** |
| Teams | §5.1 | **MISSING** |

`docs/domain-architecture.json` already specifies all 23 entities including these. The entity spec is complete; **code models and endpoints are absent**.

This ADR covers the **minimum viable implementation** for v1: **Kanban, Memory, Schedules**. Chats and Teams are deferred (higher complexity, lower blocking factor for SDLC runs).

---

## 2. Requirements (PRD §8, §10, §11, §19)

### 2.1 Kanban (§8)
- Per-project board, user/PLANNER task creation
- Workflow Run link, assignee, dependencies, priorities, subtasks
- Attempt history, comments/artifacts, errors/blockers
- Check status, transition log, auto-update from runs
- **Manual move cannot bypass server** (server-owned transitions)

### 2.2 Memory (§10)
- Levels: agent, task, project, workflow, global
- Write/search/update/delete/version/keyword
- SQLite FTS5 for v1 (no vector DB)
- **Memory must not be higher-priority than instructions** (safety)

### 2.3 Schedules / Cron (§11)
- Create schedule (cron expression), one-shot
- Target: workflow run / agent / project
- On/off, history, timezone
- Missed/skip/concurrency/retry policy

---

## 3. Architectural Decision

### 3.1 Ownership (extends ADR-102)

| Domain | Owner Module | Rationale |
|--------|--------------|-----------|
| **Kanban Board / Task / Subtask / Dependency / Comment / Artifact** | `orchestration-server` | Orchestration owns workflow execution; Kanban is the human-facing view of runs/tasks |
| **Memory (all levels)** | `agent-management` | Memory is agent-centric; tied to AgentInstance, ModelProfile, ToolPolicy |
| **ScheduledJob** | `orchestration-server` | Triggers workflow runs; Orchestration owns run creation |
| **Team** | `orchestration-server` | Project-scoped; Orchestration owns Project/Workspace |

### 3.2 New Models (in respective modules)

#### Orchestration Server — `orchestration_server/models.py` additions
```python
class KanbanBoard(Base):
    id: UUID
    project_id: UUID (FK)
    name: str
    columns_json: dict  # [{"id": "backlog", "name": "Backlog"}, ...]
    created_at, updated_at

class KanbanTask(Base):
    id: UUID
    board_id: UUID (FK)
    column_id: str
    title: str
    description: str
    assignee_id: UUID | None  # AgentInstance or human
    priority: int
    workflow_run_id: UUID | None (FK)
    parent_task_id: UUID | None (FK)  # subtasks
    depends_on: list[UUID]  # dependencies
    order: int
    created_at, updated_at

class KanbanComment(Base):
    id: UUID
    task_id: UUID (FK)
    author_id: UUID  # human or agent
    content: str
    artifacts_json: list[dict]
    created_at

class ScheduledJob(Base):
    id: UUID
    project_id: UUID (FK)
    name: str
    cron_expr: str | None  # None = one-shot
    target_type: str  # "workflow_run" | "agent" | "project"
    target_id: UUID
    payload_json: dict  # input for run/agent
    timezone: str
    enabled: bool
    missed_policy: str  # "skip" | "run_once" | "run_all"
    concurrency_policy: str  # "forbid" | "allow" | "queue"
    retry_policy_json: dict
    next_run_at: datetime | None
    last_run_at: datetime | None
    created_at, updated_at

class Team(Base):
    id: UUID
    project_id: UUID (FK)
    name: str
    members_json: list[dict]  # [{"user_id": "...", "role": "..."}]
    created_at
```

#### Agent Management — `agent_management/models.py` additions
```python
class MemoryEntry(Base):
    id: UUID
    level: str  # "agent" | "task" | "project" | "workflow" | "global"
    scope_id: UUID  # agent_instance_id / task_id / project_id / workflow_id / NULL
    key: str
    value_json: dict
    version: int
    tags: list[str]
    created_by: UUID  # agent_instance_id or human
    created_at, updated_at
    # FTS5 virtual table for search
```

### 3.3 API Endpoints (per ADR-101 `/api/v1/` prefix via Gateway)

#### Kanban (Orchestration → Gateway → `/api/v1/kanban/`)
```
GET    /api/v1/projects/{project_id}/kanban/board
GET    /api/v1/projects/{project_id}/kanban/tasks
POST   /api/v1/projects/{project_id}/kanban/tasks
PATCH  /api/v1/kanban/tasks/{task_id}          # move column, update fields
POST   /api/v1/kanban/tasks/{task_id}/comments
GET    /api/v1/kanban/tasks/{task_id}/history
POST   /api/v1/kanban/tasks/{task_id}/subtasks
POST   /api/v1/kanban/tasks/{task_id}/dependencies
```

#### Memory (Agent Management → Gateway → `/api/v1/memory/`)
```
POST   /api/v1/memory/entries
GET    /api/v1/memory/entries?level=&scope_id=&q=
PATCH  /api/v1/memory/entries/{id}
DELETE /api/v1/memory/entries/{id}
GET    /api/v1/memory/entries/{id}/versions
```

#### Schedules (Orchestration → Gateway → `/api/v1/schedules/`)
```
GET    /api/v1/projects/{project_id}/schedules
POST   /api/v1/projects/{project_id}/schedules
PATCH  /api/v1/schedules/{id}
DELETE /api/v1/schedules/{id}
GET    /api/v1/schedules/{id}/history
POST   /api/v1/schedules/{id}/enable
POST   /api/v1/schedules/{id}/disable
```

### 3.4 Scheduler Implementation

- **Background worker** in `orchestration-server` (APScheduler or custom)
- On `next_run_at` due: create `WorkflowRun` (or `AgentInstance` run) via existing engine
- Respect `missed_policy`, `concurrency_policy`, `retry_policy`
- Record `ScheduledJobRun` history (id, job_id, run_id, status, started_at, completed_at, error)

### 3.5 Kanban ↔ Orchestration Integration

- **Auto-update:** When Orchestration `Task` status changes → update linked `KanbanTask.column_id`
- **Transition log:** Every column move = `KanbanComment` (system author) + `KanbanTransition` event
- **Server-owned:** Frontend calls PATCH `/kanban/tasks/{id}`; server validates transition rules (e.g., cannot move to `done` without `WorkflowRun.completed`)

---

## 4. Consequences

**Positive:**
- Models match `domain-architecture.json` spec (23 entities)
- Kanban integrates with existing Orchestration task/run model
- Memory in Agent Management aligns with agent-centric design
- Scheduler triggers runs via existing Orchestration API
- All endpoints behind Gateway (ADR-101) with versioned contract

**Negative:**
- `orchestration-server` grows (Kanban + Scheduler + Teams)
- `agent-management` adds Memory (new domain)
- Background scheduler adds operational complexity (cron-like)
- FTS5 search requires SQLite extension (available in stdlib `sqlite3`)

**Deferred (post-v1 or separate ADR):**
- **Chats (§9):** Requires real-time (WebSocket/SSE), streaming, artifact inline — significant frontend + backend work
- **Teams (§5.1):** Model added above; RBAC/permissions deferred (PRD correctly defers RBAC for v1)

---

## 5. Rejected Alternatives

| Option | Rejection Reason |
|--------|------------------|
| Separate `kanban-service` | Kanban is a view of Orchestration tasks; separate service = sync complexity |
| Memory in separate `memory-service` | Memory is tightly coupled to agents (levels, policies); Agent Management is natural owner |
| External scheduler (cron/systemd) | Needs project/db context; in-process scheduler has transactional access to `ScheduledJob` |
| Redis-backed scheduler | v1 is single-host SQLite; no Redis dependency |
| Full RBAC for Teams | PRD defers RBAC; v1 = trusted admin/local mode |

---

## 6. Verification

- Models: All 23 entities from `domain-architecture.json` have code models
- Kanban: CRUD + move + comments + deps + subtasks + history (tests)
- Memory: Write/search/update/delete/version at all 5 levels (tests + FTS5)
- Schedules: Cron + one-shot + policies + history (tests + time-mocking)
- Integration: Scheduler creates `WorkflowRun` → Kanban auto-updates → Memory accessible
- API: All endpoints under `/api/v1/` with CursorPage pagination (ADR-101)

---

## 7. Implementation Sequence

1. **Models + migrations** in both modules (parallel)
2. **Kanban API** in Orchestration (depends on Task/WorkflowRun models)
3. **Memory API** in Agent Management (independent)
4. **Scheduler** in Orchestration (depends on ScheduledJob model)
5. **Integration wiring**: Orchestration Task status → Kanban column; Scheduler → WorkflowRun
6. **Gateway routes** (ADR-101) for all new endpoints
7. **Frontend Kanban page** (separate frontend task)

---

## 8. Open Questions

1. **Kanban columns:** Fixed per PRD (§8) or configurable per project? PRD says "per-project board" — lean toward configurable with defaults.
2. **Memory FTS5:** Use SQLite FTS5 virtual table or `sqlite-fts5` Python wrapper? Stdlib `sqlite3` supports FTS5.
3. **Schedule timezone:** Store as IANA tz; scheduler runs in server local time → convert.
4. **Team model minimal:** Just name + members for v1; roles/permissions post-v1.

---

*Recorded as part of GAP-ANALYSIS.md response (task t_8cf664ab).*