# Architecture Overview

High-level system architecture of the Multi-Agent Workflow System.

## System Context

```
┌─────────────────────────────────────────────────────────────────┐
│                      Multi-Agent Workflow System                  │
├─────────────────────────────────────────────────────────────────┤
│                                                                 │
│  ┌──────────────┐    ┌──────────────┐    ┌──────────────┐      │
│  │   Client     │    │   Client     │    │   Client     │      │
│  │  (CLI/Web)   │    │  (Webhook)   │    │  (API)       │      │
│  └──────┬───────┘    └──────┬───────┘    └──────┬───────┘      │
│         │                   │                   │               │
│         └───────────────────┼───────────────────┘               │
│                             ▼                                   │
│                    ┌──────────────────┐                          │
│                    │   API Gateway    │                          │
│                    │   (FastAPI)      │                          │
│                    └────────┬─────────┘                          │
│                             │                                   │
│         ┌───────────────────┼───────────────────┐               │
│         ▼                   ▼                   ▼               │
│  ┌──────────────┐   ┌──────────────┐   ┌──────────────┐        │
│  │   Kanban     │   │  Dispatcher  │   │  Webhooks    │        │
│  │   Service    │   │   Service    │   │  Handler     │        │
│  └──────┬───────┘   └──────┬───────┘   └──────────────┘        │
│         │                  │                                     │
│         │         ┌────────┴────────┐                            │
│         │         ▼                 ▼                            │
│         │  ┌─────────┐         ┌─────────┐                       │
│         │  │ Worker  │  ...    │ Worker  │                       │
│         │  │ Pool    │         │ Pool    │                       │
│         │  └────┬────┘         └────┬────┘                       │
│         │       │                   │                            │
│         ▼       ▼                   ▼                            │
│  ┌──────────────────────────────────────────────┐               │
│  │           Shared Infrastructure              │               │
│  │  ┌──────────┐ ┌──────────┐ ┌──────────────┐ │               │
│  │  │ SQLite   │ │  File    │ │  Git         │ │               │
│  │  │ Kanban DB│ │  Storage │ │  Repositories│ │               │
│  │  └──────────┘ └──────────┘ └──────────────┘ │               │
│  └──────────────────────────────────────────────┘               │
│                                                                 │
└─────────────────────────────────────────────────────────────────┘
```

## Core Components

### 1. API Gateway (`services/api/`)
**Technology:** FastAPI + Uvicorn
**Responsibilities:**
- REST API for task/board management
- Authentication & authorization (JWT, API keys)
- Request validation (Pydantic)
- OpenAPI schema generation
- WebSocket for real-time updates

**Key Endpoints:**
```
GET    /health                    # Health check
GET    /boards                    # List boards
POST   /boards                    # Create board
GET    /boards/{slug}/tasks       # List tasks
POST   /boards/{slug}/tasks       # Create task
GET    /tasks/{id}                # Get task details
PATCH  /tasks/{id}                # Update task
POST   /tasks/{id}/complete       # Complete task
POST   /tasks/{id}/review         # Request review
POST   /tasks/{id}/block          # Block task
GET    /tasks/{id}/attachments    # List attachments
POST   /tasks/{id}/attachments    # Upload attachment
```

### 2. Kanban Service (`services/kanban/`)
**Technology:** Python + SQLite (aiosqlite)
**Responsibilities:**
- Task CRUD operations
- State machine enforcement
- Dependency graph management
- Event sourcing (audit log)
- Attachment storage
- Board/tenant isolation

**State Machine:**
```
triage → todo → ready → running → review → done
                ↓         ↓
             blocked   (retry)
                ↓
             (unblock) → ready
```

### 3. Dispatcher Service (`services/dispatcher/`)
**Technology:** Python asyncio
**Responsibilities:**
- Poll Kanban for `ready` tasks
- Spawn worker processes
- Manage worker lifecycle
- Enforce concurrency limits
- Handle heartbeats/timeouts
- Retry failed tasks

**Worker Spawn Flow:**
```
1. Query Kanban for ready tasks (assignee matches worker profile)
2. Create isolated workspace (scratch/dir/worktree)
3. Inject task context + profile config + skills
4. Spawn worker process (subprocess)
5. Monitor stdout/stderr, heartbeats
6. On completion: collect results, update Kanban
7. On failure: retry per policy or block
```

### 4. Worker Runtime (`agent-management/`)
**Technology:** Python + LLM SDKs
**Responsibilities:**
- Execute agent loop (plan → act → observe)
- Load profile, skills, tools
- Manage conversation context
- Execute tool calls
- Stream results to Kanban
- Handle checkpoints/recovery

**Agent Loop:**
```
┌─────────────────────────────────────┐
│        Initialize Context           │
│  (task, profile, skills, tools)     │
└──────────────┬──────────────────────┘
               ▼
┌─────────────────────────────────────┐
│         LLM Inference               │
│  (prompt + conversation history)    │
└──────────────┬──────────────────────┘
               ▼
    ┌────────┴────────┐
    ▼                 ▼
Tool Call         Final Answer
    │                 │
    ▼                 ▼
Execute Tool    ┌─────────────┐
    │           │ Update      │
    ▼           │ Kanban      │
┌─────────┐     │ (heartbeat, │
│ Observe │     │  progress)  │
└────┬────┘     └──────┬──────┘
     │                 │
     └────────┬────────┘
              ▼
       (loop or exit)
```

### 5. Frontend (`frontend/`)
**Technology:** React 18 + TypeScript + Vite + Tailwind CSS
**Responsibilities:**
- Kanban board visualization (drag-drop)
- Task detail views
- Real-time updates (Server-Sent Events)
- Agent log streaming
- Configuration management

**Key Pages:**
- `/` — Dashboard (board list, stats)
- `/board/:slug` — Kanban board
- `/task/:id` — Task detail + logs
- `/settings` — Profiles, skills, config

### 6. Quality Gates (`quality-gates/`)
**Technology:** Python + Ruff, MyPy, Bandit, PyTest, Trivy
**Responsibilities:**
- Security scanning (dependencies, secrets, SAST)
- Code review (linting, formatting, complexity)
- Test execution (unit, integration, coverage)
- Policy enforcement (thresholds, gates)

**Gate Pipeline:**
```
Security Gate → Review Gate → Quality Gate → Release Gate
     │              │             │              │
  bandit         ruff          pytest         git tag
  safety         mypy          coverage       docker push
  trivy          eslint        integration    github release
```

## Data Flow

### Task Creation → Execution
```
User/API          Dispatcher          Worker              Kanban
  │                 │                  │                   │
  ├─POST /tasks────►│                  │                   │
  │                 │                  │                   │
  │                 ├─Poll ready ─────►│                   │
  │                 │                  │                   │
  │                 ├─Spawn worker────►│                   │
  │                 │                  │                   │
  │                 │                  ├─Heartbeat────────►│
  │                 │                  │                   │
  │                 │                  ├─Tool calls───────►│
  │                 │                  │  (via API)        │
  │                 │                  │                   │
  │                 │                  ├─Complete─────────►│
  │                 │                  │                   │
  │◄──201 Created───┤                  │                   │
```

### Inter-Agent Communication
Agents communicate **only via Kanban**:
- Parent tasks pass context via `metadata` on completion
- Child tasks read parent `metadata` at startup
- No direct agent-to-agent messaging

## Security Architecture

### Defense in Depth
```
┌────────────────────────────────────────┐
│           Network Layer                │
│  TLS termination, mTLS between svcs   │
├────────────────────────────────────────┤
│           Application Layer            │
│  JWT auth, RBAC, rate limiting        │
├────────────────────────────────────────┤
│           Workspace Layer              │
│  Scoped filesystem, no host access    │
├────────────────────────────────────────┤
│           Runtime Layer                │
│  Seccomp, capability drop, user ns    │
├────────────────────────────────────────┤
│           Data Layer                   │
│  Encryption at rest, signed artifacts │
└────────────────────────────────────────┘
```

### Worker Isolation
- **Filesystem:** Scoped to workspace via `ScopedFilesystem` (ADR-017)
- **Network:** Egress allowlist per profile
- **Process:** No `ptrace`, limited `rlimit`
- **Secrets:** Injected at runtime, never in workspace

## Scalability

### Horizontal Scaling
- **Dispatcher:** Single leader (SQLite lock), add read replicas for API
- **Workers:** Stateless, scale horizontally via `docker compose up --scale worker=5`
- **Kanban DB:** SQLite for single-node; PostgreSQL for multi-node (planned)

### Performance Targets
| Metric | Target |
|--------|--------|
| Task dispatch latency | < 5s |
| API p99 latency | < 200ms |
| Worker startup | < 10s |
| Concurrent tasks | 100+ |
| Board size | 10,000 tasks |

## Deployment Topology

### Development
```
docker compose up
# All services on single host
```

### Production (Recommended)
```
                    ┌─────────────┐
                    │  Load       │
                    │  Balancer   │
                    └──────┬──────┘
                           │
         ┌─────────────────┼─────────────────┐
         ▼                 ▼                 ▼
    ┌─────────┐       ┌─────────┐       ┌─────────┐
    │ API #1  │       │ API #2  │       │ API #3  │
    └────┬────┘       └────┬────┘       └────┬────┘
         │                 │                 │
         └─────────────────┼─────────────────┘
                           ▼
                    ┌─────────────┐
                    │  PostgreSQL │
                    │  (Kanban)   │
                    └─────────────┘
                           │
         ┌─────────────────┼─────────────────┐
         ▼                 ▼                 ▼
    ┌─────────┐       ┌─────────┐       ┌─────────┐
    │ Worker  │       │ Worker  │       │ Worker  │
    │ Pool A  │       │ Pool B  │       │ Pool C  │
    └─────────┘       └─────────┘       └─────────┘
```

## Key Design Decisions (ADRs)

| ADR | Title | Status |
|-----|-------|--------|
| 001 | Hermes Independence | Accepted |
| 010 | Multi-Agent Orchestration | Accepted |
| 011 | Agent Runtime Loop | Accepted |
| 012 | Tool Registry | Accepted |
| 013 | MVP Core Subsystems | Accepted |
| 014 | Cross-Subsystem Integration | Accepted |
| 015 | Management API Auth | Accepted |
| 016 | SDLC Template Automation | Accepted |
| 017 | Scoped Filesystem Profiles | Accepted |

See [Architecture Decisions](../developer/architecture-decisions/adr-index.md) for details.

---

*See also: [Developer Guide](../developer/agent-development.md) | [Quality Gates](../developer/quality-gates.md) | [Deployment Guide](../operations/deployment-guide.md)*