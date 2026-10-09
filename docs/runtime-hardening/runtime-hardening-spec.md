# Runtime Hardening — Technical Specification

**Project:** Harbor-Transfer-Portal — multi-agent autonomous development runtime
**Task:** t_c39cb99e (P8.3 Runtime Mode Hardening, architect/spec stage)
**Status:** Ready for implementation (child task t_a0f09cd1, assignee sdlc-developer)
**Author:** sdlc-architect
**Version:** 1.0.0

This document is the authoritative, implementable specification. It MUST be read
together with the immutable decision record (`architecture-decision-record.md`,
ADR-011) and the API contracts under `api/`, `schemas/`, and `config/`. Any
conflict is resolved in this priority order:

1. OpenAPI/AsyncAPI/schema contracts (machine-checkable interfaces)
2. This specification (behavioral and operational requirements)
3. ADR-011 (rationale and constraints)

---

## 1. Scope and Design Principles

### 1.1 What is being built

A hardened runtime that executes agent code (LLM-authored tooling, external
submissions, internal build tasks) inside strongly isolated sandboxes with
kernel-enforced resource limits, graceful degradation, guaranteed workspace
lifecycle management, and full-stack observability.

### 1.2 Design principles

1. **Isolation matched to threat**: no single sandbox for all work; a runtime
   selector assigns one of four isolation tiers per workload class.
2. **Defense in depth**: every tier also applies the baseline hardening (user
   namespaces, dropped capabilities, `RuntimeDefault` seccomp, read-only
   rootfs, `allowPrivilegeEscalation: false`, inner bwrap/nsjail).
3. **cgroups v2 is the single enforcement layer**: all resource guarantees map
   to one unified hierarchy; no parallel ad-hoc limiters.
4. **Degrade, don't die**: soft→hard limit gradations plus a per-agent
   degradation ladder give operators a window to act before hard kills.
5. **Ephemeral by default**: workspaces are immutable-base + ephemeral scratch;
   nothing precious lives in a sandbox until explicitly promoted.
6. **Observe everything**: OpenTelemetry for metrics/traces/logs + PSI for
   pressure + Tetragon for kernel-level security visibility, from day one.

### 1.3 Non-goals (explicitly out of scope)

- Writing the agent application code itself (that is the implementer's job after
  this runtime exists).
- Replacing the existing orchestration layer; this runtime is invoked by it.
- Multi-region or multi-cluster federation — a single deployment is assumed.
- Building a custom hypervisor; Kata-on-Firecracker is adopted as-is where KVM
  is available.

---

## 2. Component Decomposition

The runtime is structured as the control plane and the data plane.

### 2.1 Control plane components

| Component | Responsibility | Consumes | Serves |
|---|---|---|---|
| **Agent Runtime API** | HTTP/WebSocket control plane for agent lifecycle (create/stop/pause/resume/status/metrics/logs/health) and the event stream | Client/orchestrator | REST (`api/agent-runtime-openapi.yaml`), WS events (`api/lifecycle-events-asyncapi.yaml`) |
| **Resource Manager** | cgroups v2 hierarchy management: create/apply/adjust limits, read usage + PSI pressure, enforce aggregate parent budget | API, Degradation Controller | `GET/PUT/PATCH /agents/{id}/limits`, `/usage`, `/pressure` |
| **Workspace Manager** | Atomic create/snapshot/restore/cleanup/promote of workspaces over overlayfs + tmpfs; idempotent; reaper for orphans | API | `POST /workspaces…` |
| **Runtime Selector** | Chooses isolation tier/runtime class per workload + KVM availability; admission validation that untrusted work can't land on `runc` | API | Selects `runc`/`runsc`/`kata-fc` |
| **Circuit Breaker Coordinator** | Per-agent CB state machine + per-resource bulkhead pools | API, Resource Manager | `record_success/failure`, `get_state`, bulkhead acquire/release |
| **Degradation Controller** | Owns FULL→THROTTLED→READ_ONLY→PAUSED→TERMINATED transitions and recovery | Resource Manager, Circuit Breaker | `get_mode`, `transition`, recovery coordination |

### 2.2 Data plane components

| Component | Responsibility |
|---|---|
| **Container Runtime Wrapper** | Abstract interface over `runc`/`runsc`(gVisor)/`kata-fc`; uniform `start/stop/pause/resume/status/logs`; seccomp profile generation; rootless execution |
| **runtime → runc** | Trusted tier (baseline container + inner sandbox) |
| **runtime → runsc** | gVisor user-space kernel; untrusted tier without KVM |
| **runtime → kata-fc** | Kata-on-Firecracker microVM; adversarial multi-tenant tier with KVM |
| **Agent Sandbox** | One per agent: dedicated cgroup scope, user-ns mapping, network-ns, overlayfs workspace |
| **Inner sandbox** | bubblewrap/nsjail second barrier inside every container |

### 2.3 Observability stack components

OTel Collector (per-node DaemonSet + cluster Deployment) → Prometheus (OTLP),
Tempo/Jaeger (traces), Loki/Elasticsearch (logs), Alertmanager (rules);
Cilium Tetragon (eBPF security observability + enforcement).

---

## 3. Isolation Architecture (Tier Selection)

### 3.1 The four tiers

| Tier | RuntimeClass | KVM | Use | Baseline hardening |
|---|---|---|---|---|
| **baseline-runc** | `runc` | Either | Trusted internal tooling | All (below) |
| **gvisor-runsc** | `runsc` | No | Untrusted / LLM-authored code | All + gVisor |
| **kata-fc** | `kata-fc` | Yes | Adversarial, multi-tenant | All + microVM |
| **gvisor-nsjail** | `runsc` | No | Adversarial fallback when no KVM | All + gVisor + inner nsjail + strict cgroups + egress allowlist |

### 3.2 Baseline hardening (applied to EVERY tier)

- Rootless containers: user namespace mapping, distinct non-overlapping
  subuid/subgid ranges per agent.
- `securityContext`: `runAsNonRoot: true`, `runAsUser: 65532`,
  `drop: ["ALL"]`, `allowPrivilegeEscalation: false`,
  `readOnlyRootFilesystem: true`, seccomp `RuntimeDefault` (or custom allowlist
  per tier).
- Inner `bubblewrap` (or `nsjail` where user-ns restrictions apply) as a second
  barrier inside the container.
- Default-deny network egress; explicit allowlist per agent class enforced via
  `tc` qdisc + Tetragon. Tier 1 default: no egress.
- `/proc` mounted `hidepid=2`; no `hostPath` mounts; no shared volumes.

### 3.3 Runtime selector rules

1. Workload labeled `harbor.hardening/isolation` ∈ {trusted, untrusted, adversarial}.
2. `untrusted` → `gvisor-runsc` if no `/dev/kvm`, else `kata-fc`.
3. `adversarial` → `kata-fc` if `/dev/kvm` present; **must not** run on `runc`;
   fallback `gvisor-nsjail` when KVM absent.
4. `trusted` → `baseline-runc`.
5. Admission controller rejects a pod labeled `untrusted`/`adversarial` that
   requests `runtimeClassName: runc`.

### 3.4 Seccomp strategy

- Tier 1 (runc): restrictive custom BPF allowlist tuned from Tetragon observe
  data; fall back to `RuntimeDefault`.
- Tier 2 (runsc): default gVisor platform filter + gVisor's own sentry syscall
  policy.
- Tier 3 (kata-fc): microVM guest kernel boundary; host-side `RuntimeDefault`.
- Inner sandbox applies its own bwrap/nsjail seccomp profile on top.

---

## 4. Resource Management (cgroups v2)

### 4.1 Hierarchy

```
agent.slice                       <- parent: aggregate budget, subtree_control "+cpu +memory +io +pids"
└── agent-<uuid>.scope            <- per-agent limits
    (run each agent process in its own child scope)
```

- Parent `agent.slice` holds the aggregate budget (`parentBudget` in
  `config/resource-quotas.example.yaml`); child scopes cannot collectively
  exceed it.
- `cgroup.subtree_control` MUST enable `+cpu +memory +io +pids` on the parent
  before writing any child limits.

### 4.2 Per-agent limit files (three-tier model)

| Resource | Soft (throttle) | Hard (enforce/kill) | Protection |
|---|---|---|---|
| CPU | — | `cpu.max` = `quota period` | `cpu.weight`; `cpu.max.burst` for temporary over-quota |
| CPU pin | — | `cpuset.cpus`, `cpuset.mems`, `cpuset.cpus.exclusive` | latency-critical only |
| Memory | `memory.high` ≈ 80% `max` | `memory.max` | `memory.low`/`min` sparingly |
| Swap | — | `memory.swap.max` **== `memory.max`** (disable swap) | — |
| Memory OOM | — | `memory.oom.group = 1` | atomic whole-cgroup kill |
| Disk I/O | `io.weight` | `io.max` (`rbps/wbps/riops/wiops`) per device | BFQ scheduler |
| Network | — | `tc` qdisc (htb/tbf) on veth | CNI bandwidth annotations |
| PIDs | — | `pids.max` | fork-bomb protection |
| Pressure | PSI `cpu/memory/io` | — | alert on sustained `full` stall |

### 4.3 Mandatory invariants (checked at admission/config validation)

1. `memory.swapMaxBytes == memory.maxBytes` (disables swap; otherwise leaks are
   masked by indefinite swapping). Enforced in the JSON Schema AND at apply time.
2. `memory.highBytes <= memory.maxBytes` (soft ≤ hard).
3. Sum of child `memory.maxBytes` + `cpu.quotaMicros` across the slice ≤ parent
   `parentBudget`.
4. `cgroup.subtree_control` includes the controllers before writing children
   (silent failure otherwise).
5. `memory.oom.group = 1` set on every agent cgroup.

### 4.4 OOM handling & pressure

- `memory.high` throttling triggers reclaim BEFORE OOM — monitor
  `memory.events{high}` and PSI, not just `memory.max`.
- `memory.max` triggers in-cgroup OOM kill.
- `oom_score_adj`: agents preferred over system services (configurable, e.g. 500).
- PSI (`cpu.pressure`, `memory.pressure`, `io.pressure`) read from the agent
  cgroup and exposed via `/agents/{id}/pressure`; used as leading indicator for
  the degradation ladder and pre-OOM alerting.

### 4.5 Resource classes

Named classes (`trusted`, `untrusted`, `high-isolation`) carry concrete quotas;
per-agent `overrides` merge over the class. Defaults in
`config/resource-quotas.example.yaml` are illustrative starting points and MUST
be re-sized against the real workload before production (research open item #3).

---

## 5. Resilience Patterns

### 5.1 Two layers

**Layer 1 — Application (outbound dependencies: LLM APIs, tools, DB):** decorator
order (mandatory) **Bulkhead → TimeLimiter → RateLimiter → CircuitBreaker →
Retry**.

- **TimeLimiter**: per-endpoint SLA timeout, `cancelRunningFuture: true`.
- **CircuitBreaker**: sliding window ≥ 100, `minimumNumberOfCalls` ≥ 20,
  `failureRateThreshold` 50%, `waitDurationInOpenState` ≥ 30s,
  `permittedNumberOfCallsInHalfOpenState` ≥ 3.
- **Bulkhead**: semaphore `maxConcurrentCalls` per dependency (e.g. 25), small
  `maxWaitDuration`.
- **RateLimiter**: token bucket per downstream quota.
- **Retry**: ≤ 3 attempts, exp backoff (base 100ms, max 10s) ×2 + full jitter,
  **idempotent operations only**, ignore 4xx.
- **Fallback**: stale cache / degraded response.

**Layer 2 — Runtime (agent sandbox), keyed on health/latency/resource pressure:**

- Per-agent circuit breaker: `CLOSED → OPEN → HALF_OPEN → CLOSED`;
  sliding window ≥ 100, min calls ≥ 20, 50% failure threshold, ≥ 30s open,
  ≥ 3 half-open successes.
- Bulkhead pools per resource class (cpu, memory, disk_io, network) —
  semaphore-based, no shared pools across agents.
- **Degradation modes** (owned by Degradation Controller):

  1. **FULL** — normal operation, resources within soft limits.
  2. **THROTTLED** — `memory.high`/`cpu.max` pressure detected → reduce
     `cpu.max`, apply `memory.high` throttle, reject new work.
  3. **READ_ONLY** — persistent pressure → enforce `readOnlyRootFilesystem`, no
     new executions, serve cached results only.
  4. **PAUSED** — critical pressure → `SIGSTOP` agent processes, retain state,
     stop scheduling.
  5. **TERMINATED** — unrecoverable → `SIGKILL` + cleanup, emit `terminated`.

- **Recovery:** exponential backoff (base 2s, max 60s, jitter); promote back up
  the ladder only when the health gate passes (pressure cleared for 2× backoff
  window).

### 5.2 Retry budget (cross-layer)

- Global token-bucket retry budget = **10% of request volume**; refill 1 token
  per 10 requests; consumed on every retry attempt in both layers; when
  exhausted → fail fast, no retries. Guards against retry-storm amplification
  (3 retries × layers).

### 5.3 State transitions (Degradation Controller)

```
FULL → (sustained PSI high / memory.events{high}>0) → THROTTLED
THROTTLED → (pressure clears 2×window) → FULL
THROTTLED → (pressure persists, memory.max approaching) → READ_ONLY
READ_ONLY → (pressure clears, resources freed) → THROTTLED → FULL
READ_ONLY → (OOM / unrecoverable) → PAUSED
PAUSED → (manual or auto policy) → TERMINATED | THROTTLED
```

---

## 6. Workspace Lifecycle

### 6.1 Structure

```
/workspace
├── base          # read-only overlay lower (immutable base image)
├── scratch       # ephemeral tmpfs/overlay upper + work
│   ├── .agent-state/   # runtime state: spec.json, checkpoints, temp
│   ├── .artifacts/     # outputs (promoted to durable on success)
│   └── .logs/          # structured JSON logs
└── durable       # named volume, promoted outputs only
```

### 6.2 Atomic creation protocol

1. **Pre-flight**: validate spec; check resource availability (cgroup budget,
   user-ns range, network pool).
2. **Staging**: create child cgroup under `agent.slice` with limits → allocate
   user-ns mapping → create netns + veth + `tc` qdisc → provision overlayfs
   (lower=base, upper=scratch, work=scratch/.work).
3. **Validation**: verify mounts, limits, egress connectivity.
4. **Commit**: write `spec.json` under `.agent-state/`, mark workspace/agent
   ACTIVE; publish `agent.created`.
5. **Rollback on any failure**: reverse staging in reverse order; `cleanup`
   with `force=true`.

### 6.3 Deterministic cleanup (guaranteed)

- **Success**: promote `score_adj` declared artifacts → commit overlay → release
  cgroup/netns/userns/volumes → archive logs → delete workspace.
- **Failure**: rollback overlay → release resources → preserve failure
  artifacts for diagnosis → delete workspace.
- **Crash/interrupt**: reaper daemon periodic scan of orphaned cgroups/mounts/
  volumes/netns → force cleanup (default 30s after SIGTERM; `--die-with-parent`/
  systemd scope/K8s ownerReference + finalizer tie lifecycles).
- Cleanup is **idempotent**: safe to call repeatedly; converges to "nothing
  allocated".

### 6.4 Recovery

- **Primary**: recreate-from-base with idempotent (convergent) setup — simplest,
  most reliable.
- **Optional low-latency**: Firecracker snapshot-restore for warm pools
  (Kata tier); overlayfs diff for runc/runsc.
- **State checkpoint**: periodic CRIU dump or app-level checkpoint to
  `.agent-state/`.
- **Never assume graceful teardown**: validate on every restart.
- Max recovery time target: 30s.

### 6.5 Promotion

`promote()` copies checksummed scratch artifacts to durable volume via atomic
rename; idempotent; retries with alert on failure.

---

## 7. Observability Stack

### 7.1 Architecture

OTel Collector **DaemonSet** (per-node: OTLP receiver, `k8sattributes`,
`kubeletstats`, `filelog`) + **Deployment** (cluster: `k8sclusterreceiver`,
`k8sobjectsreceiver`) → Prometheus (OTLP ingest + PromQL + Alertmanager) ,
Tempo/Jaeger (traces), Loki/Elasticsearch (logs). Cilium Tetragon DaemonSet for
eBPF runtime security.

### 7.2 Structured logging (JSON Lines)

Fields (mandatory): `timestamp` (RFC3339Nano), `level`
(DEBUG|INFO|WARN|ERROR|CRITICAL), `trace_id` (W3C), `span_id`, `agent_id`,
`workspace_id`, `component`, `message`, `attributes{}`. PII redaction at source.
Output: stdout → OTel `filelog` → Loki/ES, correlated by trace id.

### 7.3 Distributed tracing

- W3C TraceContext (`traceparent`, `tracestate`) propagation end-to-end.
- Sampler: parent-based + TraceIDRatio (10% default).
- Export: OTLP/gRPC to the collector.
- Key spans: `workspace.create`, `sandbox.start`, `agent.execute`,
  `sandbox.stop`, `workspace.cleanup`, `dependency.call` (with per-hop bytes).

### 7.4 Metrics (Prometheus)

Control plane `/metrics` (`_total`/histogram naming):
- `harbor_agent_running_total{state=...}`
- `harbor_workspace_duration_seconds` (histogram)
- `harbor_resource_usage_bytes{cgroup,resource}`
- `harbor_circuit_breaker_state{agent_id,state}` (0=closed,1=open,2=half_open)
- `harbor_degradation_mode{agent_id,mode}` (0/1)
- `harbor_retry_total`, `harbor_retry_budget_ratio`
- `harbor_oom_kills_total`, `harbor_sandbox_start_duration_seconds`
- `harbor_workspace_operations_total{op,status}`

Resource Manager / runtime:
- `cgroup_memory_events_total{event=high|max|oom_kill,agent_id}`
- `cgroup_pressure_seconds_total{resource=cpu|memory|io,agent_id}`
- `container_startup_duration_seconds{runtime=runc|runsc|kata-fc}`

### 7.5 Health-check protocol

- Liveness `/healthz/live` (200 alive / 503 dead) — process up, cgroup reachable.
- Readiness `/healthz/ready` — workspace mounted, proxy reachable, deps healthy.
- Startup `/healthz/startup` — initialization complete.
- Per-agent `/agents/{id}/health` returning liveness/readiness/startup snapshot.

### 7.6 Alerting rules (PrometheusRule)

| Alert | Expression | Severity |
|---|---|---|
| AgentMemoryHighThrottling | `rate(cgroup_memory_events_total{event="high"}[5m]) > 0` for 2m | warning |
| AgentOOMKill | `increase(cgroup_memory_events_total{event="oom_kill"}[1m]) > 0` | critical |
| AgentMemoryFullPSI | `rate(container_pressure_memory_waiting_seconds_total[5m]) > 0` for 1m | critical |
| AgentCircuitBreakerOpen | `harbor_circuit_breaker_state{state="open"} == 1` for 30s | warning |
| AgentDegradedMode | `harbor_degradation_mode{mode=~"throttled|read_only|paused"} == 1` for 1m | warning |
| AgentRetryBudgetExhausted | `harbor_retry_budget_ratio < 0.1` for 30s | warning |
| AgentSandboxStartFailure | Sandbox start failure rate > 5% | warning |
| WorkspaceCreateLatencyP99 | Workspace creation p99 > 30s | warning |

### 7.7 Tetragon policy strategy

1. **Observe** (first ~2 weeks): `TracingPolicy` with `matchActions: ["TRACE"]`
   on all agent namespaces — capture syscalls, execs, network per agent class.
2. **Profile**: derive minimal per-class allowlists.
3. **Enforce**: `TracingPolicy` with `matchActions: ["KILL","TRACE"]` for
   deviations.
4. Gradual rollout; `observe-first` avoids breaking legitimate agents.

---

## 8. Interface Definitions (index)

Machine-readable contracts ship with this task:

| Contract | Path | Implements |
|---|---|---|
| Agent Runtime Control Plane API (OpenAPI 3.1) | `api/agent-runtime-openapi.yaml` | §2.1 API, §5 degradation verbs, §7.5 health |
| Lifecycle Event Bus (AsyncAPI 2.6) | `api/lifecycle-events-asyncapi.yaml` | §5.3 events, STRIDE R1 audit trail |
| Resource Quota JSON Schema (draft 2020-12) | `schemas/resource-quota.schema.json` | §4 cgroups quotas + invariants |
| Example resource classes | `config/resource-quotas.example.yaml` | §4.5 classes/parent budget |

### 8.1 Key error semantics (all endpoints)

Errors return RFC 9457 `ProblemDetails`
(`type/title/status/detail/instance/retryable`). Standard responses:
`400 BadRequest`, `404 NotFound`, `409 Conflict` (invalid state transition or
budget-exceeds-parent), `422` (snapshot checksum violation),
`503 CircuitOpen` (breaker open — **do not retry**), `507 InsufficientCapacity`
(workspace create). All endpoints require **mTLS + bearer JWT/OIDC**
(security: `mtls`, `bearerAuth`); health probes are unauthenticated by design.

### 8.2 Lifecycle verb → API map

| Verb | Endpoint |
|---|---|
| Create+start agent | `POST /agents` |
| Pause (SIGSTOP) | `POST /agents/{id}/pause` |
| Resume | `POST /agents/{id}/resume` |
| Stop (SIGTERM→SIGKILL) | `POST /agents/{id}/stop?graceSeconds=` |
| Delete+cleanup | `DELETE /agents/{id}?graceSeconds=&force=` |
| Workspace create/snapshot/restore/promote/validate | `POST /workspaces{/...}` |
| Read/apply/adjust limits | `GET/PUT/PATCH /agents/{id}/limits` |
| Usage/pressure | `GET /agents/{id}/usage`, `/pressure` |
| Events stream | WS `agents/{id}/events`, `agents/events`, `workspaces/{id}/events` |

---

## 9. Interface definitions were verified consistent

The OpenAPI and AsyncAPI ship as-is from the validated reference package and
mutually agree on: enums (`IsolationTier`, `DegradationMode`,
`CircuitBreakerState`, resource classes), event `EventType`
(`agent.created|running|degraded|recovered|failed|terminated`,
`workspace.created|snapshot_taken|restored|cleaned`), the degradation trigger
set `[psi_memory, psi_cpu, psi_io, memory_high, memory_max, cpu_throttle,
io_max, circuit_open, health_fail]`, and the problem-detail error contract. The
JSON Schema enforces the two cgroup invariants (§4.3.1, §4.3.2) that otherwise
silently break hardening.

---

## 10. Configuration Surface

Concrete classes and the parent budget live in `config/resource-quotas.example.yaml`,
validated against `schemas/resource-quota.schema.json`. Runtime defaults
(circuit-breaker thresholds, timeouts, retry budget, degradation backoff) are
expressed in the Resilience section (§5) and are configurable via environment or
config file; no secrets are stored in any config file shipped with this task.

---

## 11. Acceptance Criteria (implementation entry gate)

The implementation (t_a0f09cd1) is considered acceptable for the test phase only
when every criterion below holds:

1. **AC-1 Isolation**: a workload labeled `untrusted` cannot be scheduled on
   `runtimeClassName: runc` (admission rejection proven by test).
2. **AC-2 Isolation**: baseline hardening flags present on every created
   sandbox regardless of tier (`readOnlyRootFilesystem:true`,
   `allowPrivilegeEscalation:false`, `drop:["ALL"]`, non-root UID, seccomp).
3. **AC-3 Resources**: an agent that exceeds `memory.maxBytes` is OOM-killed
   atomically (`memory.oom.group=1`); swap effectively disabled
   (`swapMax==max`); PSI `memory.events{high}` fires.
4. **AC-4 Resources**: child limits cannot collectively exceed `parentBudget`
   (409 on violation).
5. **AC-5 Resilience**: dependency outage trips the circuit breaker to OPEN
   within config, fast-fails without retry while OPEN, recovers to HALF_OPEN
   after wait, and closes after 3 successes.
6. **AC-6 Resilience**: retry budget caps attempts at ~10% of volume; exhaustion
   fails fast.
7. **AC-7 Workspace**: workspace create is atomic and rollback leaves zero
   orphaned cgroups/mounts/netns/volumes after induced partial failure.
8. **AC-8 Workspace**: after a simulated controller crash mid-create, the reaper
   reclaims the orphaned workspace within the force-cleanup timeout.
9. **AC-9 Observability**: creating+running+stopping an agent produces a
   trace-correlated set of log line, trace, metrics, and a lifecycle event for
   every transition; health probes return correct 200/503.
10. **AC-10 Threat model**: the STRIDE findings in
    `architecture/threat-model-stride.md` are satisfied by the deployed controls
    (see mitigation column), with no open `Critical` residual risk.

---

*Technical companion to ADR-011. This specification is versioned with the code
and may be amended only by an ADR amendment.*