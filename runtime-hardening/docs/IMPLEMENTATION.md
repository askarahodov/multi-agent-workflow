# P8.3 Implementation Summary — Hardened Runtime Components

Task: `t_cea09e5d` (P8.3 Implement) · Architecture input: `t_72478f3c` (P8.3 Architect)
Package: `runtime/` · Language: Python ≥3.11 (verified on 3.14.7) · License: MIT

## What was built

A complete, tested implementation of the hardened agent runtime described by the
architecture package (ADRs 001–005, OpenAPI/AsyncAPI contracts, quota schema).

| Component | Module | Architecture | Status |
|---|---|---|---|
| Isolation tiers + engine abstraction + seccomp + rootless userns | `runtime/container_runtime.py` | ADR-001 | ✅ |
| cgroup v2 limits, hierarchical quotas, usage/PSI reads | `runtime/resource_manager.py` | ADR-002 | ✅ |
| Atomic workspace lifecycle, snapshot/restore, cleanup, reaper | `runtime/workspace_manager.py` | ADR-004 | ✅ |
| Liveness/readiness/startup probes | `runtime/health.py` | ADR-005 | ✅ |
| Prometheus metrics, OTel hooks, JSON logs w/ correlation IDs | `runtime/metrics.py` | ADR-005 | ✅ |
| Circuit breaker, bulkheads, degradation ladder, recovery coordinator, retry budget | `runtime/circuit_breaker.py` | ADR-003 | ✅ |
| FastAPI control plane (agents, workspaces, resources, health, WS events) | `runtime/api.py` | OpenAPI / AsyncAPI | ✅ |
| Pydantic contracts | `runtime/models.py` | OpenAPI / quota schema | ✅ |
| Pydantic Settings (env + YAML) and quota loader | `runtime/config.py` | — | ✅ |

## Acceptance criteria — evidence

| Criterion | Result |
|---|---|
| Components implement the architecture interfaces | `runtime/api.py` exposes every path in `agent-runtime-openapi.yaml` (`test_openapi_exposes_contract`); event contract modelled by the WS route |
| Unit tests (>80% coverage) | **91%** total branch coverage; per-module ≥86% (`reports/coverage.xml`, `reports/coverage_html/`) |
| Integration tests with a real container runtime | **2 passed** against real Docker (`tests/integration/runtime/`) — hardening flags verified via `docker inspect`, full create→health→stop→cleanup lifecycle |
| Configuration via Pydantic Settings (env + YAML) | `runtime/config.py`; tested in `tests/unit/runtime/test_config.py` |
| Type hints throughout, mypy clean | `mypy` → *Success: no issues found in 10 source files* |
| Ruff / lint clean | `ruff check` + `ruff format --check` clean for `runtime/` and `tests/` |

Full suite: **117 passed** (`reports/junit.xml`).

## Test layout

```
tests/unit/runtime/         # models, config, container runtime, resource manager,
                            # workspace manager, health+metrics, circuit breaker, API
tests/integration/runtime/  # real docker hardening + lifecycle (marker: integration)
tests/chaos/runtime/        # OOM, CPU/memory pressure, bulkhead saturation, network
                            # partition, runtime crash rollback, partial-corruption recovery
```

Run:

```bash
uv sync --extra dev
uv run pytest -q --cov=runtime --cov-report=term-missing          # unit + chaos + integration
uv run pytest -m integration                                       # real container engine only
uv run ruff check . && uv run ruff format --check . && uv run mypy
```

## Resilience semantics (ADR-003)

* Circuit breaker: sliding window ≥ minimum calls, trips at the failure-rate threshold,
  `OPEN → HALF_OPEN` after the wait duration, closes after N half-open successes; a
  half-open failure re-opens.
* Bulkheads: `threading.BoundedSemaphore` pools per `ResourceClass`, context-managed
  `slot()` raising `BulkheadFull` when exhausted.
* Degradation ladder: `FULL → THROTTLED → READ_ONLY → PAUSED → TERMINATED`, terminal at
  `TERMINATED`, stepping recovery back toward `FULL`.
* Recovery coordinator: exponential backoff (base 2 s, cap 60 s, optional full jitter).
* Retry budget: token bucket capped at ≈10 % of request volume.

Chaos tests document the failure→recovery path for OOM kills, `memory.high`/PSI pressure,
bulkhead exhaustion, network partition, runtime crash rollback and corrupted workspace
metadata.

## Security notes (STRIDE mitigations implemented)

* Baseline hardening is emitted on **every** tier: `--read-only`, `--cap-drop=ALL`,
  `--security-opt=no-new-privileges:true`, `--init` (`test_create_args_includes_hardening`).
* Custom seccomp profiles are default-deny (`SCMP_ACT_ERRNO`) with an explicit allowlist.
* Kata-on-Firecracker requests are downgraded to gVisor+nsjail when `/dev/kvm` is absent.
* `memory.swap.max == memory.max` and `memory.oom.group=1` are enforced for every agent
  cgroup; the soft/hard and swap invariants are validated at the model layer.
* Hierarchical quotas reject any single agent or aggregate that exceeds the parent slice.

## Known limitations / deviations (carry forward)

1. **Rootless userns.** `--userns=keep-id` is Podman-specific and is only emitted for
   Podman; Docker expects the *daemon* to be rootless. User-namespace *mapping* data
   (`subuid`/`subgid`) is modelled (`UsernsMapping`) but not written to `/proc/<pid>/*_map`.
2. **Overlayfs mount.** Workspace creation stages and atomically commits an immutable
   `base/` + ephemeral `scratch/` layout on the host filesystem; the actual
   `mount -t overlay` is not performed (requires root and is host-specific). Layout,
   snapshot/restore, promote and reaper semantics are implemented and tested.
3. **Network shaping.** `NetworkLimits` is modelled and returned, but `tc` qdisc
   application on the veth is not wired (needs CNI/veth integration); the cgroup v2
   implementation cannot enforce it.
4. **Authentication.** The OpenAPI security schemes (mTLS + bearer JWT) are declared in
   the spec but not enforced by the reference app; deploy behind the service mesh.
5. **cgroup writes** target the real `/sys/fs/cgroup` in production; unit tests drive a
   synthetic tree, so kernel-side `EACCES/EBUSY` paths are best-effort wrapped.

## Architecture open items still open (from the design package)

gVisor syscall-compatibility profiling, `/dev/kvm` availability, sandbox density/lifetime,
deployment target (Kubernetes RuntimeClass vs systemd), startup-latency SLOs, untrusted
default assumption, and existing observability stack — none block this implementation.