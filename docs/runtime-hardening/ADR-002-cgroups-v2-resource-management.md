# ADR-002: cgroups v2 Resource Management Architecture

## Status
Accepted

## Context
Resource limits must be enforced consistently across all isolation tiers (container, gVisor, Kata). The host runs cgroup v2 unified hierarchy (confirmed: Fedora 43, kernel 7.2.6, `cgroup2fs`). cgroups v2 is the single enforcement layer — a process lives at exactly one node in one tree, and controllers are enabled per subtree via `cgroup.subtree_control`.

Research findings:
- Three-tier strategy per agent: soft ceiling (`memory.high` ≈ 80%), hard ceiling (`memory.max` = 100%), absolute CPU/I/O caps
- `memory.high` throttling causes severe latency/p99 spikes without OOM or CPU increase — must be monitored via PSI and `memory.events{high}`
- `memory.max` without `memory.swap.max=0` on swap-enabled hosts masks leaks via indefinite swapping
- `memory.oom.group=1` kills whole cgroup atomically, avoiding zombie half-broken containers
- Network shaping: cgroup v2 has no bandwidth controller; use `tc` qdiscs on veth or CNI bandwidth annotations
- Hierarchical quotas: parent cgroup (e.g., `agent.slice`) holds aggregate budget; child agent cgroups inherit via `subtree_control`

## Decision
**cgroups v2 unified hierarchy** as the sole resource enforcement layer with a three-tier per-agent limit model and hierarchical budget allocation.

### Resource Classes and Limit Files

| Resource | Soft Limit (Throttle) | Hard Limit (Enforce/Kill) | Protection / Weight | Notes |
|---|---|---|---|---|
| CPU | — | `cpu.max` = `quota period` (µs) | `cpu.weight` (1–10000) | `cpu.max.burst` for temporary over-quota |
| CPU Pinning | — | `cpuset.cpus`, `cpuset.mems`, `cpuset.cpus.exclusive` | — | Latency-critical only |
| Memory | `memory.high` ≈ 80% budget | `memory.max` = 100% budget | `memory.low`/`min` (sparingly) | `memory.swap.max = memory.max` (disable swap) |
| Memory OOM | — | `memory.oom.group = 1` | — | Kill whole cgroup atomically |
| Disk I/O | `io.weight` (relative) | `io.max` `rbps/wbps/riops/wiops` | Per-device only | BFQ scheduler recommended |
| Network | — | `tc` qdisc (TBF/HTB) on veth | — | CNI bandwidth annotations where available |
| PIDs | — | `pids.max` | — | Fork-bomb protection |
| Pressure (PSI) | `cpu/memory/io.pressure` | — | — | Alert on sustained non-zero `full` stall |

### Hierarchical Quota Design
```
agent.slice (parent: aggregate budget)
├── agent-<id-1>.scope (child: per-agent limits)
├── agent-<id-2>.scope
└── ...
```
- Parent `agent.slice` enables `+cpu +memory +io +pids` in `cgroup.subtree_control`
- Each child scope gets individual limits; aggregate cannot exceed parent budget
- Dynamic limit adjustment via `adjust_limits(container_id, delta)` API writes to child scope files

### Critical Implementation Requirements
1. **Explicit `memory.swap.max = memory.max`** on every agent cgroup to disable swap
2. **Enable `memory.oom.group=1`** for atomic cgroup OOM kill
3. **Verify `cgroup.subtree_control`** includes required controllers before writing child limits (common silent failure)
4. **Monitor `memory.events{high}` + PSI** — not just `memory.max` — for early degradation signals
5. **Network limits via `tc` on container veth** at creation time; clean up on teardown

## Consequences
**Benefits:**
- Single consistent enforcement layer across all runtimes
- Soft-then-hard degradation gives observability window before hard kill
- Hierarchical quotas enable "tier budgets" without per-agent caps interacting unpredictably
- PSI provides leading indicators of contention before hard limits hit

**Trade-offs:**
- `memory.high` throttling introduces latency spikes — must be visible in dashboards/alerts
- Network shaping requires `tc`/CNI integration outside cgroups — additional operational surface
- `subtree_control` misconfiguration silently fails — validation required at provisioning

**Risks:**
- R8: `memory.max` without `swap.max=0` masks leaks → High. Mitigate: explicit swap cap in all configs
- R9: `memory.high` throttling causes p99 spikes with no OOM signal → High. Mitigate: PSI + `memory.events{high}` alerting
- R10: Network shaping not in cgroups → Medium. Mitigate: standardize on `tc` qdisc + CNI annotations