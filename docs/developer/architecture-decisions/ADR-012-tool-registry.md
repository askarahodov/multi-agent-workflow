# ADR-012: Tool Registry and Execution Framework

**Status:** Proposed
**Date:** 2026-10-12
**Author:** sdlc-architect (task t_8cf664ab)
**Related:** ADR-011 (agent runtime loop), ADR-103 (tool policy enforcement), PRD §13, GAP-ANALYSIS.md (G2)

---

## 1. Context and Problem

PRD §13 specifies a **Tool Registry** with 9 tool categories, each with params/policy/limits/timeout/log/structured result/error rules. Current state (GAP-ANALYSIS.md G2):

- Only `ToolPolicy` metadata exists (`agent-management/agent_management/tool_policy.py`)
- `ToolPolicyEngine.allow/enforce` implemented but **never called** (ADR-103)
- **No tool implementations, no Tool Registry, no execution, no call log**
- No SSRF/path-canonicalization guards (tools don't exist to guard)

ADR-103 mandates enforcement at two layers: (1) Agent Management `run_completion` for LLM tool calls, (2) Runtime Hardening for OS-level (FS, network, shell). This ADR defines the **Tool Registry** that sits between them.

---

## 2. Requirements (from PRD §13)

| Tool Category | Tools | Key Requirements |
|---------------|-------|------------------|
| Filesystem | `fs_read`, `fs_write`, `fs_search`, `fs_list` | Path canonicalization, symlink guard, allow-list scoping |
| Shell | `shell_exec` | Command allow-list, timeout, resource limits, no shell injection |
| Git | `git_read` (status, diff, log), `git_write` (commit, push, branch) | Subcommand allow-list, repo scoping, signed commits |
| Network | `http_request` (GET, POST, limited methods) | SSRF guard (no localhost/private), allow-list domains, timeout |
| Memory | `memory_search`, `memory_write` | Level scoping (agent/task/project/workflow/global), versioning |
| Task | `task_read`, `task_update` (status, result) | Cannot change status to completed/verify; read-only mostly |
| Artifact | `artifact_read`, `artifact_write` | Size limits, type validation, checksum |
| Agent Spawn | `spawn_agent` | Child cannot expand parent rights; pinned config version |

**Cross-cutting:** Each tool has `params` schema, `policy` ref, `limits` (timeout, retries, size), `log` (structured), `result` schema, `error` rules.

---

## 3. Architectural Decision

### 3.1 Tool Registry as a Library (not a service)

The Tool Registry is a **shared library** (`tools/registry/`) used by `agent-runtime` (ADR-011). It is **not** a separate network service — tool execution happens in the agent's container context.

```
tools/
├── registry/
│   ├── __init__.py
│   ├── base.py              # ToolSpec, ToolResult, ExecutionContext
│   ├── registry.py          # ToolRegistry (singleton per process)
│   ├── filesystem.py        # FsReadTool, FsWriteTool, FsSearchTool, FsListTool
│   ├── shell.py             # ShellExecTool
│   ├── git.py               # GitReadTool, GitWriteTool
│   ├── network.py           # HttpRequestTool
│   ├── memory.py            # MemorySearchTool, MemoryWriteTool
│   ├── task.py              # TaskReadTool, TaskUpdateTool
│   ├── artifact.py          # ArtifactReadTool, ArtifactWriteTool
│   ├── spawn.py             # SpawnAgentTool
│   └── policies.py          # ToolPolicy integration
├── tests/
```

### 3.2 Tool Specification

```python
@dataclass
class ToolSpec:
    name: str                    # e.g., "fs_read"
    category: str                # "filesystem" | "shell" | "git" | ...
    description: str
    params_schema: dict          # JSON Schema for parameters
    result_schema: dict          # JSON Schema for result
    required_policy: list[str]   # e.g., ["fs_read"] for fs_read
    default_timeout_ms: int
    max_retries: int
    is_destructive: bool         # write/exec/spawn = true

@dataclass
class ExecutionContext:
    run_id: UUID
    agent_instance_id: UUID
    workspace_root: Path         # Container workspace path
    allowed_paths: list[Path]    # From ToolPolicy + workspace scoping
    allowed_domains: list[str]   # From ToolPolicy network allow-list
    allowed_commands: list[str]  # From ToolPolicy shell allow-list
    memory_level: str            # agent|task|project|workflow|global
    parent_run_id: UUID | None   # For spawn_agent child restriction
```

### 3.3 Tool Execution Flow

```python
async def execute_tool(tool_name: str, params: dict, context: ExecutionContext) -> ToolResult:
    # 1. Resolve tool
    spec = registry.get_tool(tool_name)
    if not spec:
        return ToolResult(error=f"Unknown tool: {tool_name}", status="error")

    # 2. Validate params against schema
    validate(params, spec.params_schema)

    # 3. Policy check (application layer - ADR-103)
    for policy_action in spec.required_policy:
        if not tool_policy_engine.enforce(context.agent_policy, policy_action, params):
            return ToolResult(error=f"Policy denied: {policy_action}", status="denied")

    # 4. Execute with timeout + retries
    try:
        result = await asyncio.wait_for(
            _execute_with_retries(spec, params, context),
            timeout=spec.default_timeout_ms / 1000
        )
    except asyncio.TimeoutError:
        return ToolResult(error="Tool timeout", status="timeout")

    # 5. Validate result schema
    validate(result, spec.result_schema)

    # 6. Structured logging
    log_tool_call(tool_name, params, result, context)

    return ToolResult(data=result, status="success")
```

### 3.4 Security Controls Per Tool

| Tool | Path Canonicalization | SSRF Guard | Resource Limits |
|------|----------------------|------------|-----------------|
| `fs_read`/`fs_write` | `os.path.realpath` + `allowed_paths` prefix check | N/A | Max file size (config) |
| `fs_search`/`fs_list` | Same as above | N/A | Max results, max depth |
| `shell_exec` | N/A | N/A | cgroup memory/CPU, timeout, allow-list |
| `git_read`/`git_write` | Repo root scoping | N/A | Timeout, allow-list subcommands |
| `http_request` | N/A | **Block**: localhost, 10.x, 172.16-31.x, 192.168.x, link-local; allow-list domains only | Timeout, max response size, no redirects |
| `memory_*` | Level scoping enforcement | N/A | Max entries, TTL |
| `task_update` | Status transition validation | N/A | Read-only for most fields |
| `spawn_agent` | Child policy ⊆ parent policy check | N/A | Max depth, pinned config |

### 3.5 Policy Integration (ADR-103)

```python
# ToolPolicy.permissions format (JSON)
{
  "fs_read": ["workspace/**", "project/**"],
  "fs_write": ["workspace/**"],
  "shell": ["python", "pytest", "git"],
  "git": ["read", "write"],
  "network": ["https://api.github.com/**", "https://openrouter.ai/**"],
  "memory": ["agent", "task"],
  "task": ["read"],
  "artifact": ["read", "write"],
  "spawn": ["allowed_definitions": ["uuid1", "uuid2"]]
}
```

The `ToolPolicyEngine` (existing) validates each tool call against this. The Tool Registry **requires** a valid `ExecutionContext` with resolved permissions — no default permissive policy.

---

## 4. Consequences

**Positive:**
- Single registry, testable in isolation (unit tests per tool)
- Policy enforcement at library level + OS level (defense in depth)
- Structured logging enables audit trail per tool call
- Extensible: new tools register via `ToolRegistry.register()`

**Negative:**
- 8 tool implementations = significant code surface
- Each tool needs container integration (FS overlay, nftables, seccomp)
- `http_request` SSRF guard must be robust (test against bypasses)
- `spawn_agent` requires Orchestrator integration (circular dep risk)

**Implementation Priority:**
1. Core: `base.py`, `registry.py`, `policies.py` + `fs_read`/`fs_write`/`fs_list`
2. Shell + Git (high value for SDLC agents)
3. Network (with SSRF guard)
4. Memory/Task/Artifact (depend on those subsystems existing)
5. Spawn Agent (depends on Orchestrator integration)

---

## 5. Rejected Alternatives

| Option | Rejection Reason |
|--------|------------------|
| External tool service (gRPC/REST) | Latency per tool call; container context (FS, env) harder to share; over-engineered |
| LLM provider native tool calling only | Provider tools are opaque; no policy enforcement, no audit log, no custom tools (git, memory) |
| Shell-only tools (everything via `shell_exec`) | No policy granularity; shell injection risk; no structured results |
| Skip Memory/Task/Artifact tools for v1 | PRD §13 lists them as v1; agents can't interact with platform without them |

---

## 6. Verification

- Unit: Each tool has tests for params/result validation, policy denial, timeout, error paths
- Integration: Tool Registry + `agent-runtime` loop + `runtime-hardening` container → real tool execution
- Security: `http_request` SSRF test suite (localhost, private IP, DNS rebinding, redirect chains)
- Policy: `ToolPolicyEngine` + registry integration tests (allow/deny per action/resource)
- Observability: Structured JSON log per call (tool, params_hash, result_status, duration_ms)

---

## 7. Open Questions

1. **Tool versioning:** PRD mentions tool versioning. Registry should support multiple versions of same tool name?
2. **Async vs sync tools:** All tools async? Some (fs_read) could be sync; keep uniform async for simplicity.
3. **Tool result caching:** For idempotent tools (fs_read, http GET), cache within a run?
4. **Memory subsystem dependency:** `memory_*` tools need the Memory subsystem (ADR-013). Stub for now?

---

*Recorded as part of GAP-ANALYSIS.md response (task t_8cf664ab).*