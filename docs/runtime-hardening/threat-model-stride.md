# Threat Model: Agent Runtime (STRIDE Analysis)

## System Overview
The agent runtime executes untrusted/arbitrary code in sandboxed workspaces. The system comprises:
- **Agent Runtime API** (control plane)
- **Container Runtime** (Docker/Podman/containerd with gVisor/Kata backends)
- **Resource Manager** (cgroups v2 enforcement)
- **Workspace Manager** (overlayfs/tmpfs lifecycle)
- **Observability Stack** (OTel, Prometheus, Tetragon)

**Trust Boundaries:**
1. **Host OS ↔ Container Runtime** (kernel attack surface)
2. **Container Runtime ↔ Agent Process** (syscall boundary)
3. **Agent Process ↔ Workspace** (filesystem boundary)
4. **Agent Process ↔ Network** (egress control)
5. **Control Plane ↔ Data Plane** (API authentication/authorization)

---

## STRIDE Analysis

### S - Spoofing Identity
| # | Threat | Asset | Impact | Likelihood | Mitigation |
|---|---|---|---|---|---|
| S1 | Attacker spoofs agent identity to Runtime API | Agent identity, API auth | Unauthorized agent control, resource theft | Medium | mTLS between control plane components; JWT/OIDC for API; SPIFFE workload identity |
| S2 | Compromised agent spoofs another agent's cgroup | cgroup hierarchy | Resource limit bypass, noisy neighbor | Low | cgroup v2 hierarchy immutable after creation; kernel enforces membership |
| S3 | Attacker spoofs Tetragon/OTel collector identity | Observability data integrity | False metrics, hidden attacks | Low | mTLS for collector↔backend; signed telemetry payloads |

### T - Tampering
| # | Threat | Asset | Impact | Likelihood | Mitigation |
|---|---|---|---|---|---|
| T1 | Agent escapes container, tampers host kernel | Host integrity | Full host compromise | Critical (Tier 0) / High (Tier 1) / Low (Tier 2/3) | Tiered isolation (ADR-001); gVisor/Kata for untrusted; seccomp allowlist; Tetragon enforcement |
| T2 | Agent modifies workspace base image | Base image integrity | Persistent compromise, supply chain | Medium | Read-only base (overlayfs lower); verified image signatures; sbom |
| T3 | Agent tampers resource limit configs (cgroup files) | Resource enforcement | Limit bypass, DoS | Low | cgroup fs mounted read-only in container; only Resource Manager (host) writes |
| T4 | Agent modifies OTel/Tetragon config | Observability integrity | Blind spots, alert suppression | Low | Config via ConfigMap/Secret; RBAC; immutable container rootfs |
| T5 | Man-in-the-middle on agent↔API communication | API integrity | Command injection, data exfil | Medium | mTLS everywhere; certificate pinning for critical paths |

### R - Repudiation
| # | Threat | Asset | Impact | Likelihood | Mitigation |
|---|---|---|---|---|---|
| R1 | Agent denies malicious action; no audit trail | Accountability | Inability to attribute attacks | Medium | Immutable audit logs (Tetragon + OTel); signed events; WORM storage for critical logs |
| R2 | Control plane operator denies config change | Operational accountability | Compliance failure | Low | GitOps for all config; signed commits; admission webhook audit |

### I - Information Disclosure
| # | Threat | Asset | Impact | Likelihood | Mitigation |
|---|---|---|---|---|---|
| I1 | Agent reads host filesystem via /proc, /sys, mounts | Host secrets, other containers | Credential theft, lateral movement | Critical (Tier 0) / High (Tier 1) / Low (Tier 2/3) | `readOnlyRootFilesystem`; no hostPath mounts; `hidepid=2` on /proc; user-ns mapping |
| I2 | Agent accesses other agents' workspace data | Cross-agent data | Data exfiltration, IP theft | Medium | Per-agent cgroup + user-ns + network ns; overlayfs per-agent; no shared volumes |
| I3 | Agent exfiltrates data via network egress | Data confidentiality | Data breach | High | Default-deny egress; explicit allowlist per agent class; Tetragon network enforcement |
| I4 | Side-channel attacks (cache, timing, PSI) | Cross-VM/container secrets | Crypto key extraction | Medium (Kata) / Low (gVisor) | CPU pinning (`cpuset.cpus.exclusive`); disable SMT; noise injection; dedicated nodes for high-value |
| I5 | Observability stack leaks sensitive data in logs/metrics | Logs, metrics, traces | Accidental secret exposure | Medium | Structured logging with PII redaction; metric label sanitization; trace sampling |

### D - Denial of Service
| # | Threat | Asset | Impact | Likelihood | Mitigation |
|---|---|---|---|---|---|
| D1 | Agent exhausts CPU (busy loop, crypto mining) | Host CPU, other agents | Service degradation | High | `cpu.max` hard quota; `cpu.weight` shares; PSI alerting; bulkhead pool |
| D2 | Agent exhausts memory (leak, allocation) | Host memory, other agents | OOM kills, system instability | High | `memory.high` (throttle), `memory.max` (kill), `memory.swap.max=0`, `memory.oom.group=1` |
| D3 | Agent exhausts disk I/O (heavy reads/writes) | Host disk, other agents | Latency spikes, timeouts | Medium | `io.max` per-device; `io.weight`; separate volumes per agent class |
| D4 | Agent exhausts network bandwidth | Host NIC, other agents | Network saturation | Medium | `tc` qdisc (TBF/HTB) on veth; CNI bandwidth annotations |
| D5 | Agent forks unbounded (fork bomb) | Host PID table, cgroup | Process table exhaustion | High | `pids.max` per agent; `memory.oom.group=1` |
| D6 | Agent holds resources during degradation (zombie) | Resource availability | Capacity leak | Medium | Degradation ladder (ADR-003) with forced cleanup; reaper daemon |
| D7 | Control plane overwhelmed by agent events | API availability | Operational blindness | Low | Event bus backpressure; batching; rate limiting on ingestion |

### E - Elevation of Privilege
| # | Threat | Asset | Impact | Likelihood | Mitigation |
|---|---|---|---|---|---|
| E1 | Agent exploits kernel CVE via syscall | Host kernel | Root on host | Critical (Tier 0) / High (Tier 1) / Low (Tier 2/3) | Seccomp allowlist (minimal); gVisor/Kata for untrusted; kernel live-patching; Tetragon syscall blocking |
| E2 | Agent exploits setuid binary in container | Container root | Container escape | Medium | `allowPrivilegeEscalation: false`; `drop: ["ALL"]`; no setuid binaries in base image |
| E3 | Agent exploits user-ns mapping to reach host root | Host root | Full host compromise | Medium | Rootless containers; subuid/subgid ranges non-overlapping; `kernel.unprivileged_userns_clone=0` on high-security nodes |
| E4 | Agent compromises Resource Manager API | Resource control | Limit modification, DoS | Low | mTLS + RBAC; Resource Manager runs on separate control plane network |
| E5 | Agent compromises Workspace Manager | Workspace control | Persistent backdoor, data access | Low | Workspace Manager runs outside agent namespace; API auth; idempotent operations only |

---

## Risk Summary by Isolation Tier

| Threat | Tier 0 (runc) | Tier 1 (bwrap/nsjail) | Tier 2 (gVisor) | Tier 3 (Kata) |
|---|---|---|---|---|
| T1 Kernel escape | Critical | High | Low | Very Low |
| I1 Host FS access | Critical | High | Low | Very Low |
| E1 Kernel CVE | Critical | High | Low | Very Low |
| E3 User-ns escape | Medium | Medium | Low | Very Low |
| I4 Side-channels | Medium | Medium | Low | Medium* |
| D1-D6 Resource DoS | High | High | High | High (mitigated by cgroups) |

*Kata: dedicated guest kernel reduces but doesn't eliminate side-channels; CPU pinning recommended for high-value.

---

## Recommended Controls Priority

| Priority | Control | Threats Mitigated |
|---|---|---|
| P0 | Tiered isolation (ADR-001) + baseline hardening | T1, I1, E1, E3 |
| P0 | cgroups v2 three-tier limits (ADR-002) | D1-D6 |
| P0 | Default-deny network egress + Tetragon enforcement | I3, D4 |
| P0 | Seccomp allowlist per agent class | T1, E1 |
| P1 | PSI + memory.events alerting (ADR-005) | D2, D6 |
| P1 | Degradation ladder + reaper (ADR-003, ADR-004) | D6, R1 |
| P1 | mTLS + SPIFFE identity | S1, T5, E4, E5 |
| P2 | Immutable audit logs + WORM | R1, R2 |
| P2 | CPU pinning for high-value agents | I4 |
| P3 | Signed images + sbom verification | T2 |

---

## Residual Risks (Accepted with Monitoring)
1. **Hardware side-channels (Spectre/Meltdown class)**: Mitigated by microcode updates, kernel mitigations, dedicated nodes for highest-value workloads. Cannot be fully eliminated in shared hardware.
2. **gVisor syscall compatibility gaps**: Accepted for Tier 2; fallback to Tier 3 where KVM available.
3. **Tetragon false positives during observe phase**: Accepted; tuning period required before enforcement.
4. **PSI alert noise under burst**: Accepted; tune `for:` duration and `memory.high` threshold (80%).