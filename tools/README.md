# Shared platform tooling (`tools/`)

Dependency-light, shared libraries used by the platform services and CI. Each
submodule has its own unit tests under `tools/tests/` (run from the repo root
so `import tools` resolves: `python -m pytest tools/tests`).

## Modules

| Module | Purpose | ADR ref | Tasks |
|--------|---------|---------|-------|
| `tools/registry/` | **Tool Registry** — parameter/result validation, ToolPolicy enforcement (deny-by-default), timeout/retry, audit log, filesystem/shell/git/network/spawn tools | ADR-012 | (b) |
| `tools/storage.py` | **SQLite persistence** — thread-safe `SQLiteStore`, `MemoryStore` (levels + versioning + FTS5 keyword search) | ADR-013 §2.2 | (d) |
| `tools/resilience.py` | **Resilience primitives** — `retry`/`retry_async`, `with_timeout*`, `CircuitBreaker` (stdlib-only) | — | (f) |
| `tools/git_storage.py` | **Git storage** — filesystem-scoped `GitStorage` facade (status/diff/commit/log; never `push`) | — | (e) |
| `tools/ci/` | **Unified CI / SDLC pipeline** — `CIPipeline`, SDLC phase engine (`SDLCWorkflow`), pytest suite runner, `QualityGateApiClient` | ADR-014, ADR-016 | (a)+(b) |

## Running the unified CI pipeline

```bash
# Run every backend module's test suite, then drive the SDLC flow to completion.
python -m tools.ci.main --run-id my-run
# With the quality-gates service available, gate enforcement is live:
python -m tools.ci.main --gates-url http://localhost:8003
```

The pipeline performs contract verification on every phase output, enforces the
fix-loop limit (ADR-016 R2), invalidates the candidate on fixer entry
(ADR-016 R3), records every transition to the audit trail (R5) and — when a
`MemoryStore` is attached — persists audit and candidate state (task (d)).