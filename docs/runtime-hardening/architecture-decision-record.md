# Architecture Decision Record: P8.3 Hardened Runtime Architecture

**ADR ID**: ADR-011
**Date**: 2026-10-09
**Status**: Accepted
**Authors**: sdlc-architect
**Reviewers**: sdlc-developer, sdlc-reviewer

## Context

Harbor-Transfer-Portal requires a hardened runtime architecture for multi-agent execution with strong isolation, resource enforcement, resilience, and observability. Research task t_98743fa0 evaluated isolation technologies (gVisor, Kata Containers, Firecracker, nsjail, bubblewrap), resource management (cgroups v2), resilience patterns (circuit breakers, bulkheads, timeouts), workspace lifecycle, and observability stacks.

### Key Requirements

- **REQ-1**: Container/sandbox isolation for agent workspaces with strong security boundary
- **REQ-2**: CPU, memory, disk, network quotas via cgroups v2 with OOM handling
- **REQ-3**: Circuit breakers, timeout budgets, retry with backoff, bulkhead isolation
- **REQ-4**: Atomic workspace creation, guaranteed cleanup, crash recovery, idempotent operations
- **REQ-5**: Health checks, structured logging, OpenTelemetry distributed tracing, Prometheus metrics, alerting

### Constraints

- Deployment targets: Ubuntu 24.04+, Debian 12+, RHEL 9+ (cgroups v2 unified hierarchy)
- Orchestration: Kubernetes/containerd with RuntimeClass support
- Agent workloads: Primarily Python/Node/Go with standard syscalls
- KVM availability: Required for strongest isolation tier (Kata/Firecracker)
- Network egress: Internal networks + allowlist proxy required

## Decision

We adopt a **three-tier isolation architecture** with progressive hardening, enforced by cgroups v2 unified hierarchy, implementing defense-in-depth resilience patterns, atomic workspace lifecycle with snapshot-based rollback, and full OpenTelemetry/Prometheus observability.

### 1. Isolation Architecture (Three-Tier)

| Tier | Technology | Use Case | Security Boundary | KVM Required |
|------|------------|----------|-------------------|--------------|
| **Tier 1 (Lightweight)** | bubblewrap + seccomp | Trusted agents, CI tasks, build steps | Process + syscall filtering | No |
| **Tier 2 (Moderate)** | gVisor (runsc) | Untrusted agent code, external contributions | User-space kernel (Sentry) | No |
| **Tier 3 (Maximum)** | Kata Containers (Firecracker) | Highly untrusted, multi-tenant, sensitive data | Hardware VM (microVM) | Yes |

**Selection Rationale**:
- Tier 1: bubblewrap is in kernel, minimal overhead (~1-2%), sufficient for trusted workloads
- Tier 2: gVisor provides strong syscall isolation without KVM; compatible with standard Linux syscalls used by Python/Node/Go agents; integrates with containerd via runsc
- Tier 3: Kata/Firecracker for when hardware virtualization is available and maximum isolation is required

**Security Boundaries**:
- Each agent runs in dedicated sandbox with dedicated UID/GID mapping
- Filesystem namespaces: read-only rootfs, tmpfs for workspace, no host mounts
- Network namespaces: isolated, egress via allowlist proxy (Tier 2/3), no egress (Tier 1 default)
- Syscall filtering: seccomp-bpf profiles per tier (Tier 1: restrictive; Tier 2: gVisor internal; Tier 3: VM boundary)

### 2. Resource Management (cgroups v2 Unified Hierarchy)

```
cgroup hierarchy:
/harbor-transfer-portal/
├── agents/
│   ├── agent-{uuid}/          # Per-agent cgroup
│   │   ├── memory.max         # Hard limit (OOM kill)
│   │   ├── memory.high        # Soft limit (throttle)
│   │   ├── memory.swap.max    # Swap limit
│   │   ├── cpu.max            # Quota/period (e.g., 50000 100000 = 50%)
│   │   ├── io.max             # Bandwidth/IOPS per device
│   │   ├── pids.max           # Fork bomb protection
│   │   └── oom_score_adj      # OOM killer preference
├── system/                    # System services
└── burst/                     # Shared burst pool (optional)
```

**Quota Assignment** (per agent profile):
- CPU: Configurable shares + max quota (default: 1 core equivalent)
- Memory: memory.high = 80% of max, memory.max = hard limit, swap = 50% of memory.max
- Disk: io.max on workspace device (default: 100 MB/s read, 50 MB/s write)
- Network: tc qdisc on sandbox veth (default: 100 Mbps)
- PIDs: pids.max = 256 (adjustable)

**OOM Handling**:
- memory.high triggers reclaim/throttle before OOM
- memory.max triggers OOM kill within cgroup
- oom_score_adj = 500 (agents preferred over system)
- PSI (Pressure Stall Information) monitoring for proactive alerts

### 3. Resilience Patterns

**Pattern Composition Order** (applied per dependency call):
```
1. Deadline Propagation    → Context with timeout budget
2. Bulkhead Isolation      → Per-dependency semaphore/thread pool
3. Circuit Breaker         → Fail-fast on repeated failures
4. Retry with Backoff      → Exponential + full jitter, idempotent only
5. Fallback/Degradation    → Stale cache, degraded response, error
```

**Circuit Breaker Configuration**:
- States: CLOSED → OPEN → HALF_OPEN
- Failure threshold: 5 failures in 10 seconds
- Success threshold (HALF_OPEN): 3 successes
- Timeout in OPEN: 30 seconds
- Per-dependency instance (not global)

**Timeout Budgets**:
- Total operation deadline: Configurable per agent task (default: 5 min)
- Per-hop budget: Total / (hops + 1) with 20% reserve
- Minimum per-call timeout: 500ms

**Bulkhead Isolation**:
- Per-external-dependency: dedicated semaphore (default: 10 concurrent)
- Per-agent: dedicated thread pool (default: 4 workers)
- No shared connection pools across agents

**Retry Policy**:
- Exponential backoff: base=100ms, max=10s, full jitter
- Max attempts: 3 (idempotent), 0 (non-idempotent)
- Retry budget: token bucket, 10% of request rate
- Retryable errors: 5xx, timeout, network errors

### 4. Workspace Lifecycle

**Atomic Creation**:
1. Allocate cgroup + reserve quotas
2. Create filesystem snapshot (overlayfs/btrfs/ZFS) or prepare tmpfs
3. Mount read-only base image + writable upper layer
4. Initialize sandbox (Tier 1/2/3)
5. Write workspace manifest (JSON) with metadata
6. Mark workspace ACTIVE only after all steps succeed

**Deterministic Cleanup** (guaranteed via finalizers):
- On SUCCESS: Commit overlay → release cgroup → archive logs → delete workspace
- On FAILURE: Rollback overlay → release cgroup → preserve failure artifacts → delete workspace
- On CRASH/INTERRUPT: Reaper daemon detects orphaned workspaces → forced cleanup

**Recovery Procedures**:
- Checkpoint: Periodic CRIU checkpoint of agent process (Tier 1/2)
- Snapshot: Filesystem snapshot before each major step
- Restore: New sandbox from snapshot + CRIU restore (Tier 1/2) or VM restore (Tier 3)
- Max recovery time: 30 seconds

**Idempotency**:
- All workspace operations keyed by workspace-id (UUIDv7)
- Setup scripts convergent (ansible-like): apply desired state
- Manifest tracks completed steps for resume

### 5. Observability Stack

**Structured Logging**:
- Format: JSON Lines with fields: timestamp (RFC3339), level, trace_id, span_id, agent_id, workspace_id, component, message, attributes
- Levels: DEBUG, INFO, WARN, ERROR, CRITICAL
- Output: stdout (container) → Fluent Bit → Loki/Elasticsearch

**OpenTelemetry Traces**:
- Propagation: W3C TraceContext (traceparent, tracestate)
- Sampler: Parent-based + TraceIDRatio (10% default)
- Exporters: OTLP/gRPC to collector
- Key spans: workspace.create, sandbox.start, agent.execute, sandbox.stop, workspace.cleanup

**Prometheus Metrics** (key metrics):
- `harbor_agent_running_total` (gauge)
- `harbor_workspace_duration_seconds` (histogram)
- `harbor_resource_usage_bytes` (gauge: memory, cpu, disk, network)
- `harbor_circuit_breaker_state` (gauge: 0=closed, 1=open, 2=half-open)
- `harbor_retry_total` (counter)
- `harbor_oom_kills_total` (counter)
- `harbor_sandbox_start_duration_seconds` (histogram)

**Health Checks**:
- Liveness: `/health/live` → sandbox process alive, cgroup accessible
- Readiness: `/health/ready` → workspace mounted, network proxy reachable, dependencies healthy
- Startup: `/health/startup` → initialization complete

**Alerting Rules** (PrometheusRule):
- Agent OOM kill rate > 0.01/min
- Workspace creation latency p99 > 30s
- Circuit breaker OPEN > 5min
- Resource saturation (memory > 90% high, CPU throttle > 50%)
- Sandbox start failure rate > 5%

## Consequences

### Positive
- Defense-in-depth: Three isolation tiers match threat model to overhead
- cgroups v2 provides kernel-enforced, hierarchical resource control
- Resilience patterns compose cleanly, prevent cascade failures
- Atomic workspace with rollback eliminates partial-state corruption
- Full OTel/Prometheus integration enables debugging at scale

### Negative
- Three-tier complexity requires runtime selection logic
- gVisor adds ~15-20% CPU overhead for syscall interception
- Kata/Firecracker requires KVM, increases cold-start to ~1-2s
- cgroups v2 unified hierarchy requires modern kernel (5.15+)
- Observability stack adds infrastructure (collector, Loki, Prometheus, Grafana)

### Risks & Mitigations
| Risk | Likelihood | Impact | Mitigation |
|------|------------|--------|------------|
| gVisor syscall incompatibility | Medium | High | Tier 1 fallback; compatibility testing in CI |
| KVM unavailable in CI | High | Medium | Tier 2 default for CI; Tier 3 only in prod |
| cgroup v2 hierarchy conflicts | Low | High | Dedicated cgroup subtree; systemd delegation |
| Observability pipeline backpressure | Medium | Medium | Buffering in Fluent Bit; sampling at source |

## Alternatives Considered

### Single-tier: gVisor Only
- **Rejected**: No lightweight option for trusted agents; no maximum isolation for sensitive workloads; gVisor doesn't protect against kernel exploits

### Single-tier: Kata/Firecracker Only
- **Rejected**: KVM required everywhere; 1-2s cold start unacceptable for short-lived agents; high memory overhead (~50MB base per VM)

### systemd-nspawn Instead of bubblewrap
- **Rejected**: Heavier; requires systemd; less granular syscall control; not designed for short-lived sandboxes

### Custom seccomp Profiles Per Agent
- **Rejected**: Maintenance burden; Tier 1 uses standardized restrictive profile; Tier 2/3 delegate to sandbox runtime

## Implementation Sequence

1. **Phase 1**: cgroups v2 hierarchy + resource quota API
2. **Phase 2**: Tier 1 (bubblewrap) sandbox runtime
3. **Phase 3**: Tier 2 (gVisor/runsc) integration with containerd
4. **Phase 4**: Tier 3 (Kata/Firecracker) integration
5. **Phase 5**: Runtime selector + tier assignment policy
6. **Phase 6**: Resilience library (circuit breaker, bulkhead, retry, timeout)
7. **Phase 7**: Workspace lifecycle manager (atomic create, rollback, cleanup, recovery)
8. **Phase 8**: Observability stack (logging, tracing, metrics, alerting)
9. **Phase 9**: Integration testing + chaos engineering
10. **Phase 10**: Documentation + runbooks

## Verification

- Each phase has acceptance criteria in runtime-hardening-spec.md
- Integration tests cover: isolation escape attempts, resource exhaustion, cascade failure, crash recovery
- Security review required before Phase 4 (Kata) and production deployment

---

*This ADR is immutable once accepted. Amendments require new ADR.*