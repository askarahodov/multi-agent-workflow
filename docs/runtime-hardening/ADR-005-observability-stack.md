# ADR-005: Observability Stack Architecture

## Status
Accepted

## Context
Full-stack observability is required for the agent runtime: metrics, traces, logs, and runtime security enforcement. Research findings:
- **Metrics**: cgroup v2 `memory.events` + PSI (`cpu.pressure`, `memory.pressure`, `io.pressure`) are the correct leading indicators. Kubernetes v1.36+ graduates PSI to GA (`container_pressure_*_waiting_seconds_total`).
- **Tracing**: OpenTelemetry Collector as DaemonSet (per-node) + Deployment (cluster receivers); `k8sattributes` processor essential for K8s metadata correlation; containerd/CRI-O OTel plugins for runtime spans.
- **Logging**: Structured JSON to stdout/stderr → OTel `filelog` receiver → Loki/Elasticsearch; correlate via trace IDs, not log parsing.
- **Runtime Security**: Cilium Tetragon for eBPF-based security observability and enforcement; observe-first, then author least-privilege policies from observed behavior.
- **Alerting**: `memory.high` rate > 0 sustained, any `oom_kill`, sustained non-zero `memory.full` PSI, rising PSI with flat usage (noisy neighbor).

## Decision
**OpenTelemetry-native stack** with PSI-first metrics, Tetragon runtime security, and PrometheusRule alerting.

### Components

| Layer | Component | Deployment | Purpose |
|---|---|---|---|
| **Collection** | OTel Collector (DaemonSet) | Per-node | OTLP receiver, `k8sattributes`, `kubeletstats`, `filelog` |
| **Collection** | OTel Collector (Deployment) | Single replica | `k8sclusterreceiver`, `k8sobjectsreceiver` (events) |
| **Metrics** | Prometheus | Central | OTLP ingest (`--web.enable-otlp-receiver`), PromQL, Alertmanager |
| **Metrics** | cAdvisor / kubelet | Per-node | `container_pressure_*_waiting_seconds_total`, `cgroup_memory_events_total` |
| **Tracing** | Tempo / Jaeger | Central | OTLP trace ingest, query, retention |
| **Logs** | Loki / Elasticsearch | Central | OTel `filelog` → structured JSON, trace ID correlation |
| **Runtime Security** | Cilium Tetragon | DaemonSet | eBPF process-exec, syscall, I/O events; lineage tracking; enforcement policies |
| **Ad-hoc** | bpftrace | On-demand | Kernel tracing/debugging |

### Key Instrumentation Points

**Agent Runtime API** (`/metrics` endpoint):
- `agent_runtime_agents_total{state="created|running|degraded|failed|terminated"}`
- `agent_runtime_resource_usage{cgroup="...", resource="cpu|memory|disk|network"}`
- `agent_runtime_degradation_mode{agent_id="...", mode="full|throttled|read_only|paused|terminated"}`
- `agent_runtime_circuit_breaker_state{agent_id="...", state="closed|open|half_open"}`
- `agent_runtime_workspace_operations_total{op="create|snapshot|restore|cleanup|promote", status="success|failure"}`

**Resource Manager**:
- `cgroup_memory_events_total{event="high|max|oom_kill", agent_id="..."}`
- `cgroup_pressure_seconds_total{resource="cpu|memory|io", agent_id="..."}`
- `resource_limit_adjustments_total{resource="cpu|memory|disk|network", direction="up|down"}`

**Container Runtime**:
- `container_startup_duration_seconds{runtime="runc|runsc|kata-fc"}`
- `container_oom_kills_total{runtime="...", agent_id="..."}`

### Alerting Rules (PrometheusRule)
```yaml
groups:
- name: agent-runtime-critical
  rules:
  - alert: AgentMemoryHighThrottling
    expr: rate(cgroup_memory_events_total{event="high"}[5m]) > 0
    for: 2m
    labels: {severity: "warning"}
    annotations: {summary: "Agent {{ $labels.agent_id }} memory.high throttling active"}
  - alert: AgentOOMKill
    expr: increase(cgroup_memory_events_total{event="oom_kill"}[1m]) > 0
    labels: {severity: "critical"}
    annotations: {summary: "Agent {{ $labels.agent_id }} OOM killed"}
  - alert: AgentMemoryFullPSI
    expr: rate(container_pressure_memory_waiting_seconds_total[5m]) > 0
    for: 1m
    labels: {severity: "critical"}
    annotations: {summary: "Agent {{ $labels.container }} memory paging in progress"}
  - alert: AgentCircuitBreakerOpen
    expr: agent_runtime_circuit_breaker_state{state="open"} == 1
    for: 30s
    labels: {severity: "warning"}
    annotations: {summary: "Agent {{ $labels.agent_id }} circuit breaker open"}
  - alert: AgentDegradedMode
    expr: agent_runtime_degradation_mode{mode=~"throttled|read_only|paused"} == 1
    for: 1m
    labels: {severity: "warning"}
    annotations: {summary: "Agent {{ $labels.agent_id }} in {{ $labels.mode }} mode"}
  - alert: AgentRetryBudgetExhausted
    expr: agent_runtime_retry_budget_ratio < 0.1
    for: 30s
    labels: {severity: "warning"}
    annotations: {summary: "Agent {{ $labels.agent_id }} retry budget < 10%"}
```

### Tetragon Policy Strategy
1. **Observe phase** (first 2 weeks): `TracingPolicy` with `matchActions: ["TRACE"]` on all agent namespaces
2. **Profile phase**: Analyze observed syscalls, execs, network connections per agent class
3. **Enforce phase**: `TracingPolicy` with `matchActions: ["KILL", "TRACE"]` for deviations from profile
4. **Per-agent-class profiles**: Minimal syscall allowlist, expected exec paths, allowed network egress CIDRs

## Consequences
**Benefits:**
- Vendor-neutral OTel correlates metrics, traces, logs with K8s metadata
- PSI catches contention before OOM; `memory.events` provides hard-limit signals
- Tetragon enforces least privilege at kernel level, tamper-resistant
- PrometheusRule integrates with existing Alertmanager/notification pipelines

**Trade-offs:**
- OTel Collector DaemonSet + Deployment adds resource overhead (~100-200 MB/node)
- Tetragon eBPF programs require kernel headers/BPF CO-RE compatibility
- PSI requires kernel ≥ 4.20, cgroup v2, `CONFIG_PSI=y` (confirmed on target)
- `k8sattributes` requires ClusterRole — RBAC surface

**Risks:**
- R14: Observability gaps miss contention/OOM → Medium. Mitigate: OTel from day one; PSI + `memory.events` alerts; CB-state/retry-budget alerts
- Tetragon enforcement too aggressive breaks agents → Medium. Mitigate: observe-first, profile-per-class, gradual rollout