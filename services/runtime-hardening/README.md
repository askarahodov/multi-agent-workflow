# Agent Runtime — Hardened Runtime Components (P8.3)

Implementation of the hardened runtime for executing untrusted / LLM-authored
agent code, built to the architecture package produced by task `t_72478f3c`.

## Components

| Module | Responsibility | Architecture |
|---|---|---|
| `runtime/container_runtime.py` | Container engine abstraction (Docker/Podman), isolation backends (runc/gVisor/Kata), seccomp profile generator, rootless userns mapping | ADR-001 |
| `runtime/resource_manager.py` | cgroup v2 unified-hierarchy management, three-tier limits, hierarchical quotas, usage/PSI reads | ADR-002 |
| `runtime/workspace_manager.py` | Atomic workspace create, snapshot/restore with checksums, grace/force cleanup, idempotent recovery | ADR-004 |
| `runtime/health.py` | Liveness / readiness / startup probes | ADR-005 |
| `runtime/metrics.py` | Prometheus exposition, OpenTelemetry hooks, structured JSON logging with correlation IDs | ADR-005 |
| `runtime/circuit_breaker.py` | Circuit breaker state machine, semaphore bulkheads, degradation ladder, recovery coordinator | ADR-003 |
| `runtime/api.py` | FastAPI control plane (agents, workspaces, resources, health, WebSocket events) | OpenAPI / AsyncAPI |
| `runtime/models.py` | Pydantic contracts mirroring the OpenAPI + quota JSON Schema | — |
| `runtime/config.py` | Pydantic Settings (env + YAML) and quota-config loader | — |

## Development

```bash
# From the repository root (Windows CMD or Linux):
python -m pip install -e ./shared -e "./runtime-hardening[dev]"
cd runtime-hardening
python -m ruff check .
python -m ruff format --check .
python -m mypy
python -m pytest -q --cov=runtime --cov-report=term-missing
```

Integration tests that talk to a real container engine are marked
`integration`; run with `python -m pytest -m integration` (skipped when no engine
binary is available).
