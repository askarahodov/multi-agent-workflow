# ADR-001: Isolation Tier Selection for Agent Runtime

## Status
Accepted

## Context
The agent runtime must execute untrusted/arbitrary code (LLM-authored tooling, external submissions) with strong isolation guarantees while maintaining acceptable density and startup latency. The research (t_8aaf9df7) identified an isolation spectrum from plain containers (Tier 0) through process sandboxes (Tier 1), userspace kernels/gVisor (Tier 2), microVMs/Kata (Tier 3), to full VMs (Tier 4). Each tier trades security boundary strength against performance, memory overhead, and operational complexity.

Key constraints from research:
- Plain containers share the host kernel; a kernel escape defeats all namespace-based isolation
- gVisor provides userspace syscall interception without KVM but has ~240/400 syscall compatibility
- Kata Containers on Firecracker provides hardware (KVM) isolation with near-native I/O but requires `/dev/kvm`
- Process sandboxes (bubblewrap/nsjail) share the host kernel and should be layered inside a container/VM as a second barrier
- 2026 unprivileged user-namespace restrictions (Ubuntu 24.04 AppArmor, sysctls) break non-setuid bubblewrap/nsjail on some distros

## Decision
Adopt a **tiered, defense-in-depth isolation model** with three runtime classes selected per workload:

| Workload Class | KVM Available? | Isolation Tier | RuntimeClass |
|---|---|---|---|
| Trusted internal tooling | Either | Baseline container + cgroup v2 + restricted securityContext + inner bubblewrap/nsjail | `runc` (default) |
| Untrusted/LLM-authored code | No | **gVisor (runsc)** | `runsc` |
| Untrusted/adversarial, multi-tenant | Yes | **Kata-on-Firecracker** | `kata-fc` |
| Untrusted/adversarial, multi-tenant | No | gVisor + inner nsjail + strict cgroups + network egress allowlist | `runsc` (with fallback) |

All tiers **must** apply the baseline hardening:
- cgroup v2 unified hierarchy enforcement
- Rootless containers (user namespace mapping)
- Restricted `securityContext`: `runAsNonRoot`, `drop: ["ALL"]`, `RuntimeDefault` seccomp (or custom allowlist), `readOnlyRootFilesystem`, `allowPrivilegeEscalation: false`
- Inner process sandbox (bubblewrap/nsjail) as a second barrier inside the container

## Consequences
**Benefits:**
- Matches isolation strength to threat model and infrastructure capability
- gVisor tier works in nested-virtualization/CI environments without KVM
- Kata tier provides strongest boundary for multi-tenant adversarial workloads
- Baseline hardening applies everywhere, reducing blast radius even if tier selection is misconfigured
- RuntimeClass abstraction allows pod-level selection without application changes

**Trade-offs:**
- gVisor syscall gaps may break agent toolchains using io_uring, eBPF, exotic ioctls → requires compatibility testing and Kata fallback
- Kata requires KVM; unavailable in some cloud/nested environments → must detect `/dev/kvm` at provisioning
- MicroVM overhead (20–180 MB/VM) reduces density for short-lived sandboxes → mitigate with Firecracker snapshot warm-pools
- Operational complexity of managing multiple RuntimeClasses and seccomp profiles

**Risks:**
- R1: Misconfigured tier selection (e.g., running untrusted code on `runc`) → Critical. Mitigate: admission webhook validating workload labels against allowed RuntimeClasses
- R2: gVisor compatibility breaks agent workloads → High. Mitigate: pre-deployment compat matrix test; automated fallback to Kata where KVM exists
- R3: KVM unavailable when expected → Medium. Mitigate: detect at node level; label nodes; scheduler prefers KVM nodes for `kata-fc` pods