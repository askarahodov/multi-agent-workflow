# Implementation Sequence Plan — P8.3 Runtime Hardening

**Project:** Harbor-Transfer-Portal
**Task:** t_c39cb99e (architect) → t_a0f09cd1 (implement, sdlc-developer)
**Executor of this plan:** sdlc-developer (child task t_a0f09cd1)
**Status:** Ready
**Version:** 1.0.0

This plan sequences implementation so that (a) every phase is independently
testable, (b) hard dependencies are built before dependents, and (c) the runtime
is usable (for trusted traffic) as early as possible, with hardening layered on.
Each phase lists its **exit criterion** — the implementer must prove it before
moving to the next phase.

Dependencies: resource enforcement must exist before workspace atomic-creation
can be proven (workspaces allocate cgroups); resilience must exist before
degradation can be exercised; observability is instrumentation-on-everything and
should start early but only be "done" at the end.

---

## Phase 0 — Foundation & schema (1–2 days)

**Goal:** repo layout, config schema, test harness, CI skeleton.

- Establish module/repo structure for the control plane (API, Resource Manager,
  Workspace Manager, Runtime Selector, Circuit Breaker Coordinator, Degradation
  Controller), the runtime wrapper, and shared types.
- Commit `schemas/resource-quota.schema.json` and
  `config/resource-quotas.example.yaml` as the contract for all resource config.
- Validate the example config against the JSON Schema (add a unit test that
  loads and validates it).
- Scaffold the OpenAPI (Agent Runtime Control Plane API) and AsyncAPI (lifecycle
  events) contracts as versioned assets; generate server/client stubs where a
  generator is used.
- Set up CI: lint, unit tests (pytest for control plane, go test where the
  cgroup/netns layer is Go), container build.

**Exit:** `resource-quotas.example.yaml` validates against the schema; stub API
boots; health probes `/healthz/{live,ready,startup}` implemented and return 200.

---

## Phase 1 — cgroups v2 Resource Manager (2–3 days)

**Goal:** kernel-enforced resource limits and accounting.

- Resource Manager that: creates `agent.slice` parent with
  `subtree_control = +cpu +memory +io +pids`; creates per-agent child scopes;
  applies `cpu.max/weight/burst`, `memory.high/max/swap.max/oom.group`,
  `io.max/weight`, `pids.max`; reads usage and PSI pressure.
- Enforce invariants: `swapMax==max`, `high<=max`, aggregate `<= parentBudget`.
- OOM handling maps `memory.events{oom_kill}` → metric + event.
- Expose `GET/PUT/PATCH /agents/{id}/limits`, `GET /agents/{id}/usage`,
  `GET /agents/{id}/pressure` (Resource tags in OpenAPI).
- **If target is bare-metal systemd** (research open item #4 unresolved): map
  cgroup scopes to systemd transient scopes instead of K8s RuntimeClass.

**Exit:** a test agent exceeding `memory.max` is OOM-killed atomically
(`oom.group`), swap is disabled, PSI `memory.events{high}` fires, and a
budget-exceeding child returns 409. **= AC-3, AC-4.**

---

## Phase 2 — Runtime Wrapper + Tier 1 (baseline-runc) (2–3 days)

**Goal:** first runnable sandbox.

- Abstract `ContainerRuntime` interface: `start/stop/pause/resume/status/logs`,
  seccomp-profile generation, rootless execution.
- Implement `runc` backend with full baseline hardening per §3.2
  (`readOnlyRootFilesystem`, `drop:["ALL"]`, `allowPrivilegeEscalation:false`,
  non-root UID, `RuntimeDefault`/custom seccomp, inner bwrap/nsjail, `hidepid`).
- Runtime Selector returns `baseline-runc` for `trusted`.
- `POST /agents` creates + starts a Tier-1 agent end to end; lifecycle events
  published.

**Exit:** a trusted agent creates, runs, pauses, resumes, and stops cleanly with
all baseline hardening flags proven by inspection. **= AC-1 (partial: not yet
admission), AC-2.**

---

## Phase 3 — Isolation hardening: admission + Tier 2/3 selectors (3–4 days)

**Goal:** untrusted/adversarial traffic cannot land on `runc`.

- Admission controller that rejects `untrusted`/`adversarial` workloads
  requesting `runtimeClassName: runc` (AC-1).
- Runtime Selector completes: `/dev/kvm` detection → choose `runsc` (no KVM) vs
  `kata-fc` (KVM) vs `gvisor-nsjail` (adversarial, no KVM).
- Implement `runsc` (gVisor) and `kata-fc` (Kata-on-Firecracker) backends behind
  the same wrapper interface.
- gVisor compatibility test for the actual agent syscall profile (research open
  item #1); where a toolchain syscall is missing, provision the Kata fallback.

**Exit:** untrusted workload on the correct tier; admission test proves
rejection of untrusted-on-runc; gVisor compatibility matrix recorded.
**= AC-1, AC-2 (all tiers).**

---

## Phase 4 — Workspace Manager: atomic lifecycle + reaper (2–3 days)

**Goal:** guaranteed workspace create/cleanup/recovery.

- Workspace Manager over overlayfs (lower=base r/o, upper=scratch tmpfs, work)
  + optional durable volume for promotion.
- Atomic creation protocol with rollback (pre-flight → staging → validation →
  commit); deterministic cleanup on success/failure; idempotency keyed by
  workspace-id.
- Reaper daemon + `--die-with-parent`/finalizer to reclaim orphans after
  controller crash.
- Snapshot/restore (overlayfs diff for runc/runsc; Firecracker for Kata) and
  `promote()`.
- Lifecycle events `workspace.created|snapshot_taken|restored|cleaned`.

**Exit:** induced partial-create failure leaves zero orphaned resources;
simulated controller crash is reclaimed by the reaper within force-cleanup
timeout; promote moves checksummed artifacts to durable. **= AC-7, AC-8.**

---

## Phase 5 — Resilience: circuit breaker, bulkhead, timeouts, retry budget (2–3 days)

**Goal:** graceful degradation of agent work under stress.

- Layer-1 resilience stack in the right decorator order
  (Bulkhead→TimeLimiter→RateLimiter→CircuitBreaker→Retry) for outbound deps.
- Layer-2: per-agent circuit breaker + per-resource bulkhead pools.
- Cross-layer global retry budget (token bucket, 10%).
- Degradation Controller: FULL→THROTTLED→READ_ONLY→PAUSED→TERMINATED with a
  recovery coordinator (exp backoff + health gate).
- Bi-directional wiring: Resource Manager pressure → Degradation Controller;
  circuit breaker OPEN short-circuits app-layer calls.

**Exit:** a flaky dependency trips CB OPEN, fast-fails while OPEN, half-opens,
and closes after 3 successes; retry budget caps amplification; a memory-pressure
agent degrades THROTTLED→READ_ONLY and recovers. **= AC-5, AC-6.**

---

## Phase 6 — Observability integration (2 days)

**Goal:** metrics, logs, traces, health, events all flow.

- Wire every component to emit: OTel metrics (the `harbor_*`/`cgroup_*` set),
  JSON-line structured logs with W3C trace correlation, spans for the key
  operations, lifecycle events.
- OTel Collector DaemonSet + Deployment; export OTLP to Prometheus/Tempo/Loki
  (or the selected backend); if bare-metal, local agents instead.
- PSI + `memory.events` data exported; `memory.high` throttling visible.
- Deploy PrometheusRule alert set.

**Exit:** create→run→stop of an agent yields a trace-correlated log+trace+metric
+event set; probes correct; alert expressions return results.
**= AC-9.**

---

## Phase 7 — Tetragon security policy (observe → enforce) (starts here, overlapping)

**Goal:** kernel-level least-privilege enforcement.

- Deploy Tetragon in **observe** mode across agent namespaces (~2 weeks unless
  accelerated).
- Profile per-agent-class syscall/exec/network behavior.
- Author and enable enforcement `TracingPolicy` (`KILL` + `TRACE`) with a
  gradual rollout, then re-run threat-model verification (**AC-10**).

**Exit:** enforcement policies in place; no `Critical` residual risk from the
threat model remains unmitigated.

---

## Phase 8 — Chaos & integration test hardening (2–3 days)

**Goal:** prove the acceptance criteria under adversarial conditions.

- Chaos tests: isolation escape attempts, resource exhaustion, dependency
  outage, controller crash during create/cleanup, retry-storm.
- Full regression over AC-1..AC-10.
- Security review gate before Phase-3 Kata rollout to production and before
  Phase-10 cutover.

**Exit:** all acceptance criteria pass; security review sign-off recorded.

---

## Phase 9 — Docs, runbooks, handoff (1–2 days)

**Goal:** operational completeness.

- Runbooks: degradation ladder ops, OOM triage, workspace reclaim, collector
  backpressure, Tetragon alert triage.
- Update `architecture-decision-record.md`/spec with implementation-learned
  deltas (via amendment, not unlogged edits).
- Hand off to the test task (sdlc-tester) and review task (sdlc-reviewer) with
  the acceptance-criteria evidence.

**Exit:** runbooks committed; handoff package complete.

---

## Critical path & dependencies

```
Phase 0 ─▶ Phase 1 ─▶ Phase 2 ─▶ Phase 3 ─▶ Phase 4 ─▶ Phase 5 ─▶ Phase 6 ─▶ Phase 8 ─▶ Phase 9
              ▲          │          │                      │          ▲
              │          └──────────┼──────────────────────┘          │
              │                     └───── Phase 7 (observe→enforce, overlaps) ──┘
              └── config/schema contract feeds all phases ────────────┘
```

- **Phase 1 before 4** (workspaces allocate cgroups). **Phase 2 before 3**
  (wrapper before hardening selectors). **Phase 5 before 6** (degradation events
  are observability inputs). **Phase 3 and 7 both feed the security gate.**

---

## Open items to resolve before/during implementation
_(carried from research; none block starting but must be closed per phase)_

| # | Open item | Owner | Blocking phase |
|---|---|---|---|
| 1 | Actual agent syscall profile / gVisor compatibility | implementer | Phase 3 |
| 2 | `/dev/kvm` availability in target deployment | implementer + ops | Phase 3 |
| 3 | Expected sandbox density/lifetime (warm-pool sizing, quota right-size) | implementer + ops | Phase 1, 4 |
| 4 | Deployment target: Kubernetes/containerd RuntimeClass vs bare-metal systemd | implementer + ops | Phase 1 onward |
| 5 | SLO budgets (startup latency, per-sandbox overhead) quantification | implementer | Phase 8 |
| 6 | Untrusted vs semi-trusted default isolation assumption | product | Phase 3 |
| 7 | Existing observability stack to extend vs greenfield | implementer + ops | Phase 6 |