# P8.3 Hardened Runtime Architecture — Design Package

**Task:** t_72478f3c (P8.3 Architect: Hardened runtime architecture design)
**Project:** Multi-Agent Workflow Platform — multi-agent autonomous development runtime
**Inputs:** research report + technology comparison matrix from t_8aaf9df7
**Status:** READY for implementation (child task t_cea09e5d, assignee sdlc-developer)

This package specifies the hardened runtime architecture for executing
untrusted/LLM-authored agent code. It is organized so the implementer (P8.3
Implement) and reviewers/security can consume each artifact independently.

## Artifact index

| Artifact | Path | Purpose |
|---|---|---|
| ADR-001 Isolation tiers | `ADR-001-isolation-tiers.md` | Tiered runc/gVisor/Kata isolation selection rule |
| ADR-002 cgroups v2 resources | `ADR-002-cgroups-v2-resource-management.md` | Three-tier limits, hierarchical quotas, controller setup |
| ADR-003 Resilience | `ADR-003-resilience-circuit-breaker.md` | Circuit breaker + bulkheads + degradation ladder |
| ADR-004 Workspace lifecycle | `ADR-004-workspace-lifecycle.md` | Atomic create/snapshot/restore/cleanup, reaper |
| ADR-005 Observability | `ADR-005-observability-stack.md` | OTel + PSI + Tetragon + PrometheusRule |
| Threat model (STRIDE) | `threat-model-stride.md` | Assets, trust boundaries, threats, controls |
| Component diagram | `component-diagram.md` | Components, security boundaries, data flows |
| OpenAPI spec | `api/agent-runtime-openapi.yaml` | REST control plane + Workspace/Resource APIs + health |
| AsyncAPI spec | `api/lifecycle-events-asyncapi.yaml` | Event bus (created/running/degraded/failed/terminated) |
| Quota schema | `schemas/resource-quota.schema.json` | JSON Schema for resource-class + per-agent quota config |
| Quota example | `config/resource-quotas.example.yaml` | Concrete resource classes (trusted/untrusted/high-isolation) |

## Architecture at a glance

- **Isolation (ADR-001):** three tiers selected per workload by `RuntimeClass` —
  `runc` (trusted), `runsc`/gVisor (untrusted, no KVM), `kata-fc`/Kata-on-Firecracker
  (adversarial multi-tenant, KVM). Every tier also applies baseline hardening:
  rootless user-ns, `drop: [ALL]`, `RuntimeDefault`/custom seccomp,
  `readOnlyRootFilesystem`, `allowPrivilegeEscalation: false`, inner bwrap/nsjail.
- **Resources (ADR-002):** cgroup v2 unified hierarchy; parent `agent.slice`
  aggregate budget; three-tier per agent (`memory.high` ≈80% soft → `memory.max`
  hard), `cpu.max`/`io.max`/`pids.max`, `memory.swap.max == memory.max`,
  `memory.oom.group=1`; network via `tc` qdisc on the veth.
- **Resilience (ADR-003):** two layers — application (Resilience4j-style
  Bulkhead→TimeLimiter→RateLimiter→CircuitBreaker→Retry with a 10% retry budget)
  and runtime (per-agent CB + bulkhead pools + FULL→THROTTLED→READ_ONLY→PAUSED→TERMINATED).
- **Workspace (ADR-004):** immutable read-only base + ephemeral scratch overlay;
  atomic create with rollback; reaper/finalizer cleanup; recreate-from-base recovery.
- **Observability (ADR-005):** OTel collector (DaemonSet + Deployment) → Prometheus
  (OTLP) / Tempo / Loki; PSI + `memory.events` alerting; Cilium Tetragon
  observe-then-enforce.

## Contract map (component → interface)

| Component | Interface surface | Spec artifact |
|---|---|---|
| Agent Runtime API | `POST/GET /agents`, lifecycle verbs, `/metrics`, `/logs`, `/health` | OpenAPI `tags: Agents, Health` |
| Workspace Manager | `POST /workspaces`, snapshot/restore/promote/validate, DELETE | OpenAPI `tags: Workspaces` |
| Resource Manager | `GET/PUT/PATCH /agents/{id}/limits`, `/usage`, `/pressure` | OpenAPI `tags: Resources`, quota schema |
| Event bus | agent/workspace lifecycle events | AsyncAPI |

## Known open items (non-blocking; carry into implementation)

From the research report §8 — these do not block the design but must be resolved
before/while implementing:
1. Actual syscall profiles of Multi-Agent Workflow Platform agent workloads (gVisor viability test).
2. Availability of `/dev/kvm` in the target deployment (Kata tier).
3. Expected sandbox density/lifetime distribution (warm-pool sizing).
4. Deployment target confirmation (Kubernetes/containerd RuntimeClass vs systemd).
5. Startup-latency and per-sandbox overhead SLO budgets — not yet quantified.
6. Untrusted vs semi-trusted default assumption for isolation tier.
7. Existing observability stack to extend vs greenfield.

**Inference:** the environment inspected by research is a single Fedora 43 host
(kernel 7.2.6, cgroup2fs, PSI present). The K8s-flavored artifacts in ADR-005 and
the OpenAPI/AsyncAPI specs assume a Kubernetes/containerd deployment; if the real
target is bare-metal systemd, the RuntimeClass references map to `systemd-run`
scopes and the collector DaemonSet/Deployment split collapses to local agents.
Confirm open item #4 before implementation.
