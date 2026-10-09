# ADR-004: Workspace Lifecycle Management

## Status
Accepted

## Context
Agent workspaces require atomic creation, guaranteed cleanup, and crash recovery. Research findings emphasize:
- Immutable/ephemeral-by-default workspaces: base image read-only, agent writes only to mounted scratch overlay
- Atomic creation with rollback: allocate all resources in staging, commit atomically, tear down on failure
- Snapshot/fork (Firecracker snapshot-restore; overlayfs) for fast deterministic starts
- Idempotent provisioning with convergence checks
- Guaranteed cleanup via reaper/finalizer pattern tied to parent lifecycle
- Crash recovery via checkpoint/restore (CRIU, Firecracker snapshots) or recreate-from-base with idempotent setup
- Ephemeral vs persistent: ephemeral scratch (tmpfs/emptyDir with sizeLimit) for working state; durable volumes only for promoted outputs

## Decision
**Immutable base + ephemeral scratch + atomic lifecycle + reaper cleanup** model.

### Workspace Structure
```
/workspace (mount point)
├── /workspace/base          # Read-only base image (overlayfs lower)
├── /workspace/scratch       # Ephemeral tmpfs/emptyDir (overlayfs upper + work)
│   ├── .agent-state/        # Agent runtime state (checkpoints, temp files)
│   ├── .artifacts/          # Output artifacts (promoted to durable on success)
│   └── .logs/               # Structured JSON logs
└── /workspace/durable       # Optional: named volume for promoted outputs only
```

### Lifecycle Operations

| Operation | Semantics | Failure Handling |
|---|---|---|
| `create(agent_id, spec)` | Allocate cgroup, user-ns, network, volumes atomically; mount overlayfs; write spec | On any failure: `cleanup(partial)` → rollback all allocations |
| `snapshot(agent_id)` | Firecracker snapshot OR overlayfs diff + state checkpoint | Best-effort; log failure, continue |
| `restore(agent_id, snapshot_id)` | Mount snapshot base + replay state | Validate checksum; on failure: `create` fresh |
| `cleanup(agent_id, grace=30s, force=false)` | `SIGTERM` → wait grace → `SIGKILL` → unmount → release cgroup/user-ns/network/volumes | `force=true`: immediate `SIGKILL` + force-unmount |
| `promote(agent_id, artifact_paths)` | Copy from scratch to durable volume with checksum | Atomic rename; on failure: retry, alert |

### Atomic Creation Protocol
1. **Pre-flight**: Validate spec, check resource availability (cgroup budget, user-ns range, network pool)
2. **Staging**: 
   - Create child cgroup under `agent.slice` with limits
   - Allocate user-ns mapping (subuid/subgid range)
   - Create network namespace + veth pair + `tc` qdisc
   - Provision overlayfs mount (lower=base, upper=scratch, work=scratch/.work)
3. **Validation**: Verify all mounts, limits, network connectivity
4. **Commit**: Write agent spec to `/workspace/scratch/.agent-state/spec.json`, mark `created` event
5. **Rollback on failure**: Reverse staging in reverse order; `cleanup` with `force=true`

### Cleanup Guarantees
- **Parent-tied**: `--die-with-parent` (bubblewrap), systemd scope, or Kubernetes ownerReference/finalizer
- **Reaper daemon**: Periodic scan for orphaned cgroups/mounts/volumes/networks → force-cleanup
- **Force-cleanup timeout**: 30s default after `SIGTERM`; configurable per workspace class
- **Idempotent**: `cleanup` safe to call multiple times; converges to "nothing allocated"

### Crash Recovery
- **Primary**: Recreate-from-base with idempotent setup script (simplest, most reliable)
- **Optional (low-latency)**: Firecracker snapshot restore for warm-pool agents
- **State checkpoint**: Periodic CRIU dump or application-level checkpoint to `/workspace/scratch/.agent-state/`
- **Never assume graceful teardown happened** — always validate on restart

## Consequences
**Benefits:**
- Ephemeral-by-default eliminates state drift and reduces blast radius
- Atomic creation prevents partial allocations that leak resources
- Reaper/finalizer guarantees cleanup even if launcher crashes
- Snapshot/restore enables warm pools for low-latency starts
- Clear separation: scratch (ephemeral, swept on teardown) vs durable (explicit promotion only)

**Trade-offs:**
- Overlayfs adds complexity vs bind mounts; requires kernel support (standard on modern Linux)
- Snapshot/restore only for Firecracker/Kata tier; gVisor/runc tiers use recreate-from-base
- Idempotent setup scripts require discipline — all provisioning must be convergent

**Risks:**
- R13: Orphaned workspaces leak containers/volumes/networks → High. Mitigate: reaper + finalizer + force-cleanup timeout
- Overlayfs mount failures on exotic kernels → Medium. Mitigate: validate at node provisioning; fallback to bind-mount + tmpfs