# Runtime Hardening Implementation (P8.3)

Implementation of the hardened runtime components for the Harbor-Transfer-Portal
agent sandbox, produced by the sdlc-developer chain task `t_a0f09cd1` against
the architect's ADR-011 / `runtime-hardening-spec.md`.

## 1. Overview

This package delivers the five P8.3 runtime-mode hardening components:

1. Isolation layer — sandbox wrapper, admission control and seccomp profiles.
2. Resource controller — cgroups v2 integration with quota enforcement.
3. Resilience framework — circuit breaking, bulkhead, timeout, retry and budget.
4. Workspace manager — atomic transactional workspaces with a reaper.
5. Observability — health probes, JSON logs, metrics and OTel instrumentation.

Four isolation tiers are selected per workload class (spec §3.1):

- `baseline-runc`   — trusted internal tooling
- `gvisor-runsc`    — untrusted when no /dev/kvm
- `kata-fc`         — adversarial / untrusted when /dev/kvm is present
- `gvisor-nsjail`   — adversarial fallback when no /dev/kvm

Every sandbox receives baseline hardening flags regardless of tier (spec §3.2,
AC-2): read-only root filesystem, privilege-escalation disabled, all caps
dropped, a non-root UID and a seccomp profile. The admission controller (AC-1)
rejects `untrusted`/`adversarial` workloads that request `runtimeClassName: runc`.

## 2. Module map

Package root: `src/runtime/hardening/` (imports: `runtime.hardening.*`).

| Module            | Component / key classes                                  | Spec section |
|-------------------|----------------------------------------------------------|--------------|
| `__init__.py`     | Package marker                                           | —            |
| `models.py`       | pydantic contracts: tiers, limits, agents, health, PSI   | §8           |
| `config.py`       | `RuntimeSettings`, quota configuration loader            | §8           |
| `isolation.py`    | `AdmissionController`, `SeccompProfile`, `RuntimeSelector`,`DockerRuntime`, `SandboxSpec`, `runtime_class_for`, `detect_kvm` | §3           |
| `resource_manager.py` | `ResourceManager` (cgroups v2), `parse_memory_events`, `parse_pressure`, errors | §4 |
| `resilience.py`   | `CircuitBreaker`, `Bulkhead`, `TimeLimiter`, `RateLimiter`, `RetryPolicy`, `RetryBudget`, `ResilientCaller`, `DegradationLadder`, `RecoveryCoordinator`, `ResilienceRegistry` | §5 |
| `degradation.py`  | `DegradationController`, `DefaultPressurePolicy`, `DegradationTrigger`, `degraded_execution_guard` | §5.1, §5.3 |
| `workspace_manager.py` | `WorkspaceManager`, `WorkspaceReaper`, `sha256_of_file`, errors | §6 |
| `observability.py` | `HealthRegistry`, `MetricsRegistry`, `OTelHooks`, `StructuredLogger`, `build_observability` | §7 |
| `api.py`          | `RuntimeApp` (FastAPI control plane)                     | §2.1, §8    |

## 3. Component notes

### 3.1 Isolation layer
A tier selector maps workload class to runtime class; admission rejects
untrusted/adversarial workloads on `runc`. A default-deny seccomp BPF allowlist
(`BASELINE_SYSCALLS`) is applied to every sandbox. `DockerRuntime` wraps the
`docker` CLI with baseline hardening flags (`--read-only`, `--cap-drop ALL`,
`--security-opt no-new-privileges`, `--user 65532`) and enforces
read-only-root + default-deny profiles. Container start is idempotent
(best-effort cleanup of stale names), and `pause`/`resume`/`stop`/`status`
implement the lifecycle used by the control plane.

### 3.2 Resource controller
`ResourceManager` drives a unified cgroups v2 tree (`agent.slice/<agent>`). It
enforces CPU quota/period/burst, cpuset, memory max/high/low/min, swap
(`swap.max == max` disables swap), pids, and io weight. `adjust_limits`
applies deltas and keeps the swap-follows-max invariant. Network (egress
rate/class) and disk-I/O limits are stored in the applied-cache where no cgroup
controller maps directly. OOM group + PSI pressure files are parsed for
telemetry (`parse_pressure`, `parse_memory_events`). Removal is idempotent and
agent ids are validated against path traversal.

### 3.3 Resilience framework
The full stack composes circuit breaker -> bulkhead -> rate limiter -> time
limiter with retry over an exponential backoff (base 100 ms, max 10 s, jitter).
`RetryBudget` (token bucket, ~10% of request volume) caps retry attempts (AC-6);
4xx client errors are never retried. The degradation ladder
FULL -> THROTTLED -> READ_ONLY -> PAUSED -> TERMINATED is driven by PSI
pressure and circuit-open events; recovery only promotes back up when the
health gate reports healthy for the backoff window.

### 3.4 Workspace manager
Workspace creation is transactional: dirs are staged under a temp sibling and
atomically promoted, with rollback on partial failure (AC-7) so no orphans are
left. `promote` moves scratch artifacts into the durable volume and is
idempotent via per-file sha256 checksums. `validate` reports a checklist of
provisioning checks; the reaper sweeps abandoned/failed workspaces for
crash-recovery (AC-8). All operations reject path-escape.

### 3.5 Observability
`HealthRegistry` exposes liveness/readiness/startup probes. `StructuredLogger`
emits JSON records with W3C trace correlation. `MetricsRegistry` exposes
prometheus metrics (running agents, resource usage, retries, OOM kills,
sandbox/workspace latencies, cgroup PSI). `OTelHooks` is a
no-op-compatible exporter hook (no `opentelemetry` runtime dependency).

## 4. Control-plane API

`RuntimeApp` wires all components behind FastAPI. Endpoints (see
`api/agent-runtime-openapi.yaml`):

- Health: `GET /healthz/live|ready|startup`
- Agents: `POST /agents`, `GET /agents/{id}`, `GET /agents/{id}/status`,
  `POST /agents/{id}/pause|resume|stop`, `DELETE /agents/{id}`,
  `GET/PUT/PATCH /agents/{id}/limits`, `GET /agents/{id}/health`
- Workspaces: `POST /workspaces`, `GET /workspaces/{id}`,
  `DELETE /workspaces/{id}`
- Metrics: `GET /metrics` (prometheus text exposition)

Errors are modelled as RFC 9457 Problem Details; 4xx/503 map to the OpenAPI
documented responses.

## 5. Configuration reference

`RuntimeSettings` (from `config.py` / `config/settings.example.yaml`) selects
the isolation backend defaults, non-root uid, seccomp policy, workspace root,
pressure thresholds and enabling flags (`enable_real_mounts`,
`enable_tc_qdisc`). `ResourceQuotaConfig` loads
`config/resource-quotas.example.yaml` per the `config/resource-quota.schema.json`
JSON Schema (draft 2020-12); every resource class enforces the
`swapMax == max` invariant.

## 6. Testing

- `uv run pytest -q` — full suite (unit + chaos; integration auto-skips
  without docker).
- Markers: `integration` (real container runtime), `chaos`
  (resilience/degradation).
- Coverage target via `--cov=src/runtime`. Current suite: 130 tests green,
  ruff clean, mypy clean (11 source files).

## 7. Known limitations / documented deviations

- Real overlayfs mounts and `tc` network shaping are modelled but not wired to a
  real veth/host; gated by `isolation.enable_real_mounts` / `enable_tc_qdisc`.
- gVisor/Kata backends require `runsc`/`kata` runtime binaries not present on
  this host; the reference backend is Docker (`runc`). Selectors and admission
  are fully unit-tested.
- The OTel exporter is a no-op-compatible hook (no `opentelemetry`
  dependency); W3C trace correlation is emitted on structured logs.
- mTLS/bearer auth is declared in the OpenAPI security block but not enforced by
  the reference app (deployment responsibility).

## 8. Relationship to the sibling implementation

This chain implementation (`t_a0f09cd1`) uses a `src/runtime/hardening/`
package layout with a `hardening` subpackage. It is a distinct implementation
from the earlier flat-module `runtime/` P8.3 implementation that was previously
synced into the canonical repo (`runtime-hardening/runtime/`, commit
`fa1da65`). Both target the same ADR-011 spec; this package adds the explicit
isolation, degradation and observability modules and is packaged as
`agent-runtime-hardening`. See the operator consolidation note for how the two
coexist in the canonical repository.