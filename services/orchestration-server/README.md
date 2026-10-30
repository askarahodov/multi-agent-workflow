# Orchestration Server

Server-side orchestration engine for the AI Multi-Agent Workflow platform. It owns
task transitions, agent launches and durable state persistence, and exposes a
REST API for creating projects and workspaces, launching workflow runs, managing
tasks and retrieving results.

The guiding principle is **platform-owned orchestration**: agents are clients of
this server, never authorities. An agent cannot mark a task `completed`; it can
only *submit* an attempt, and the engine moves the task to `completed` **only
after contract verification passes**.

## Architecture at a glance

| Layer | Module | Responsibility |
|-------|--------|----------------|
| API | `orchestration_server/api.py` | FastAPI app, RFC 9457 error handling, endpoint wiring |
| Schemas | `orchestration_server/schemas.py` | Pydantic request/response DTOs and the generated OpenAPI model |
| Engine | `orchestration_server/engine.py` | State machine, contract verification, retry policy, recovery |
| Queries | `orchestration_server/queries.py` | Read-only access helpers |
| Models | `orchestration_server/models.py` | SQLAlchemy async models (projects, workspaces, contracts, agents, runs, tasks, attempts, saga journal) |
| Storage | `orchestration_server/db.py` | Async engine/session factory; SQLite (default) or PostgreSQL (`postgresql+asyncpg://`) |

## Running

```bash
# From the repository root, on Linux or Windows CMD:
python -m pip install -e ./shared -e "./orchestration-server[dev]"
cd orchestration-server
# SQLite by default (zero infrastructure):
uvicorn orchestration_server.main:app --port 8000

# Production PostgreSQL:
export ORCH_DATABASE_URL="postgresql+asyncpg://user:pass@host:5432/orchestration"
uvicorn orchestration_server.main:app --port 8000
```

Interactive API docs: `http://localhost:8000/docs`. The generated OpenAPI
document is checked in at `docs/openapi.json` and validated by the test suite.

## Durability model

Every state change is written to the append-only **saga journal**
(`saga_events`) inside the *same transaction* as the state change, so a confirmed
result and its journal entry can never diverge.

On startup the server runs `OrchestrationEngine.recover()` (and exposes
`POST /admin/recover`):

- `running` attempts are marked `interrupted`;
- tasks left `in_progress` are returned to `pending`;
- agents left `busy` are freed.

Confirmed terminal results (completed runs/tasks/attempts) are never touched, so
they survive a restart while incomplete work is re-queued rather than lost. This
behaviour is verified by `tests/test_durability.py` (a restart is modelled by
opening a fresh engine over the same database file) and
`tests/test_api.py::test_restart_via_api_preserves_completed_run`.

## Orchestration rules enforced

- **No self-declaration of success.** Completion is a platform transition that
  runs JSON Schema contract verification (`engine.submit`).
- **Contract binding is validated at launch.** `launch_run` rejects tasks that
  reference a missing contract; `submit` rejects output that fails verification
  (`422`, `verification_failed`).
- **Platform-owned retry policy.** Failed / unverified attempts are re-queued
  with exponential backoff (`attempt_count`, `max_attempts`, `retry_at`); the
  task fails only when attempts are exhausted. `POST /workflows/tick` opens due
  retry windows.
- **Attempt ownership.** Only the agent that claimed an attempt may submit or
  fail it (`409` otherwise).
- **Concurrency control.** `claim_task` uses an atomic
  `UPDATE ... WHERE status='pending'` guard plus agent exclusivity, so racing
  workers yields exactly one winner; the loser receives `409`.
- **Optimistic locking.** Every mutable entity carries a `version` column.

## API surface

```
POST /projects                     GET /projects
POST /workspaces                   GET /workspaces
POST /contracts                    GET /contracts
POST /agents/register              GET /agents
POST /workflows/runs               GET /workflows/runs      GET /workflows/runs/{id}
GET  /workflows/runs/{id}/tasks
GET  /tasks/{id}                   GET /tasks/{id}/attempts
POST /tasks/{id}/claim
POST /tasks/{id}/attempts/{attempt_id}/submit
POST /tasks/{id}/attempts/{attempt_id}/fail
POST /tasks/{id}/block
POST /workflows/tick               POST /admin/recover      GET /health
```

Errors are returned as RFC 9457 Problem Details
(`type`, `title`, `status`, `detail`, optional `errors`).

## Tests

```bash
python -m pytest          # 28 tests: lifecycle, durability, concurrency, API, OpenAPI
```

Coverage includes the full REST lifecycle, contract-verification enforcement,
retry/fail transitions, restart durability, concurrent-claim racing, and OpenAPI
schema validation (`openapi-spec-validator`).
