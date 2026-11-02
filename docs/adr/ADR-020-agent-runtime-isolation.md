# ADR-020: Agent Runtime Isolation Model (No Hermes Runtime Dependency)

- **Status:** Proposed (architect) — pending review (`sdlc-reviewer`) and security gate (`sdlc-security`).
- **Date:** 2026-10-29
- **Author:** `sdlc-architect` (task `t_e72b7d4f`)
- **Deciders:** project owner (human release gate), `sdlc-architect`, `sdlc-security`, `sdlc-release`
- **Supersedes:** ADR-001 §4.3 (workspace isolation convention), ADR-010 §7 (workspace isolation), ADR-011 §3.4 (runtime boundaries)
- **Related:** ADR-001 (CAL replaces Hermes), ADR-011 (agent runtime loop), ADR-012 (tool registry), ADR-014 (cross-subsystem integration), ADR-111 (single orchestrator)

---

## 1. Context and Problem

The platform must execute autonomous agents with **zero implementation dependency on Hermes**. Current state:

- **Agent Runtime** (`services/agent-management/agent_loop.py`) is a bounded filesystem-only proof-of-concept; no durable journal, no container sandbox, no Git/shell/HTTP tools.
- **Runtime Hardening** provides container lifecycle, workspace manager, resource manager, but **no integration** with Orchestration or Agent Management (ADR-014 G6).
- **Hermes Kanban** coordinates development tasks but is **not** the product's agent runtime. ADR-001 extracts coordination into CAL; product runtime must be independent.
- **ADR-111** establishes: single orchestrator (`orchestration-server`), native worker via HTTP polling, task dependencies via `depends_on`, Contract Gate mandatory on every stage.

**Critical gaps blocking autonomy (from AUDIT_REPORT.md):**
- G1: No module implements the agent runtime loop (PRD §5.4).
- G2: Tool Registry missing — only `ToolPolicy` metadata exists.
- G6: Orchestration↔Quality-Gates↔Runtime not integrated — three independent FastAPI apps.
- G7: No auth layer on management APIs; no SSRF guard; secret storage not deeply audited.

---

## 2. Requirements

| Req | Description |
|-----|-------------|
| R1 | **No Hermes runtime dependency** — product agent execution must not call Hermes CLI, gateway, or dispatcher. |
| R2 | **Per-task isolation** — each agent run gets a dedicated, ephemeral workspace with filesystem, network, and process boundaries. |
| R3 | **Container-based sandbox** — Linux namespaces (user, pid, net, mnt, ipc), cgroups v2, seccomp, OverlayFS. |
| R4 | **Tool execution within sandbox** — all tool calls (fs, shell, git, network, memory, task, artifact, spawn) execute inside the container. |
| R5 | **Orchestrator-driven provisioning** — Orchestration Server provisions workspace + container via Runtime Hardening API before agent run starts (ADR-014 §3.2.2). |
| R6 | **Policy enforcement at two layers** — Agent Management (LLM tool calls) + Runtime Hardening (OS-level) per ADR-103. |
| R7 | **Deterministic cleanup** — workspace and container torn down on completion, failure, or timeout; artifacts extracted before teardown. |
| R8 | **Budget enforcement** — step count, token usage, cost (USD), wall-clock time limits per agent settings (ADR-011 §3.5). |

---

## 3. Architectural Decision

### 3.1 High-Level Structure

```
┌─────────────────────────────────────────────────────────────────────┐
│                    ORCHESTRATION SERVER (composition root)          │
│  ┌─────────────────────────────────────────────────────────────┐    │
│  │  SDLCWorkflowEngine / OrchestratorEngine                     │    │
│  │  • claim_task → provisions runtime → starts agent run        │    │
│  │  • submit → runs Quality Gates → finalizes                    │    │
│  └──────────────────────────┬────────────────────────────────────┘    │
│                             │ HTTP (internal)                          │
│        ┌────────────────────┼────────────────────┐                     │
│        ▼                    ▼                    ▼                     │
│ ┌─────────────┐      ┌─────────────┐      ┌─────────────┐            │
│ │Agent Mgmt   │      │ Runtime     │      │ Quality     │            │
│ │(config)     │      │ Hardening   │      │ Gates       │            │
│ │             │      │ (infra)     │      │             │            │
│ └──────┬──────┘      └──────┬──────┘      └──────┬──────┘            │
│        │                    │                    │                     │
│        │  AgentSpec:        │  Workspace +       │  Gate eval:        │
│        │  - model_profile   │  Container per     │  - tester          │
│        │  - tool_policy     │  agent run         │  - reviewer        │
│        │  - budget          │  Tool execution    │  - security        │
│        │                    │  inside container  │  - release_prep    │
└────────┴────────────────────┴────────────────────┴────────────────────┘
```

### 3.2 Component: `agent-runtime` Module (New)

Create a new first-class module `agent-runtime/` (sibling to `orchestration-server`, `agent-management`, `quality-gates`, `runtime-hardening`) that owns the **agent execution loop** — per ADR-011.

```
agent-runtime/
├── api.py                    # FastAPI endpoints: /runs, /runs/{id}/stream
├── loop.py                   # Core turn-taking loop (async generator)
├── message_builder.py        # Build message history from task + context
├── tool_executor.py          # Tool Registry + execution sandbox
├── contract_verifier.py      # JSON Schema verification (reuse orchestration logic)
├── budget_enforcer.py        # Step/time/token/cost limits
├── provider_adapter.py       # Streaming wrapper over agent-management providers
├── models.py                 # Run, Turn, ToolCall, ToolResult, BudgetState
├── schemas.py                # Request/response DTOs
├── db.py                     # SQLite persistence for run state
└── tests/
```

**Loop Algorithm (Single Turn):**

```python
async def run_turn(run_id: UUID, task: Task, agent_spec: AgentSpec) -> TurnResult:
    # 1. Build message history (system + user + prior turns + tool results)
    messages = build_messages(task, agent_spec, run_id)

    # 2. Stream from provider (with tool-call parsing)
    async for chunk in provider_adapter.stream(messages, agent_spec.model_profile):
        if chunk.is_tool_call:
            # 3. Parse tool call → enforce policy → execute
            tool_call = parse_tool_call(chunk)
            policy_check = tool_policy_engine.enforce(agent_spec.tool_policy, tool_call)
            if not policy_check.allowed:
                return TurnResult(blocked=True, reason="tool_policy_denied")
            result = await tool_executor.execute(tool_call, run_id, agent_spec)
            messages.append(ToolResultMessage(tool_call.id, result))
        elif chunk.is_text:
            messages.append(AssistantMessage(chunk.text))
        # Check budgets after each chunk
        budget_enforcer.check(agent_spec.budget)

    # 4. Contract verification (if task expects structured output)
    if task.contract_schema:
        verify_contract(messages[-1].content, task.contract_schema)

    # 5. Persist turn + check completion
    persist_turn(run_id, messages)
    return TurnResult(complete=is_done(messages), messages=messages)
```

### 3.3 Isolation Boundaries

| Boundary | Mechanism | Owner |
|----------|-----------|-------|
| **Process** | Fresh container per `AgentRun` (ephemeral) | Runtime Hardening |
| **Filesystem** | OverlayFS: read-only base + read-write upper dir scoped to workspace | Runtime Hardening |
| **Network** | nftables egress rules per container cgroup (allow-list from ToolPolicy) | Runtime Hardening |
| **Shell/Commands** | Restricted shell / command allow-list in container entrypoint | Runtime Hardening |
| **Git** | Git wrapper with subcommand allow-list; commits via gateway (ADR-111) | Runtime Hardening + Gateway |
| **Secrets** | Never injected into container; provider keys via `trusted_https` worker (agent-management) | Agent Management |

### 3.4 Integration Contracts

| Boundary | Mechanism |
|----------|-----------|
| Orchestrator → Agent Runtime | `POST /api/v1/agent-runs` with `Task`, `AgentSpec`; receives `run_id`; polls/status websocket for completion |
| Agent Runtime → Orchestrator | On completion: `POST /tasks/{id}/submit` with contract-verified result |
| Agent Runtime → Agent Management | Resolve `AgentInstance` → `AgentDefinition` + `ModelProfile` + `ToolPolicy` at run start |
| Agent Runtime → Runtime Hardening | Create container/workspace via Runtime API; execute tools inside container |
| Agent Runtime → Quality Gates | Contract verification uses same JSON Schema validator as Orchestrator |

### 3.5 Data Model (New Entities)

| Entity | Fields | Owner |
|--------|--------|-------|
| `AgentRun` | id, task_id, agent_instance_id, status, current_turn, budget_state, created_at, updated_at | Agent Runtime |
| `Turn` | id, run_id, turn_number, messages_json, tool_calls_json, result, started_at, completed_at | Agent Runtime |
| `ToolCall` | id, turn_id, name, params, result, status, started_at, completed_at | Agent Runtime |
| `BudgetState` | run_id, steps_used, tokens_used, cost_usd, time_elapsed_ms | Agent Runtime |

---

## 4. Consequences

**Positive:**
- Single component owns the complete execution loop (no split across services).
- Streaming-native design from day one (not retrofitted).
- Tool Registry is a first-class, testable component (ADR-012).
- Clear integration contracts with existing subsystems.
- Budget enforcement built into the loop (not an afterthought).
- **Zero Hermes runtime dependency** — product agent execution is fully owned.

**Negative:**
- New module adds operational surface (5th FastAPI service).
- Requires provider streaming support (OpenRouter supports; mock provider needs update).
- Container-per-run or container-per-agent-instance decision affects resource usage.
- Tool implementations are net-new code (8+ tool backends).

**Migration:**
1. Implement `agent-runtime` module with loop + tool executor (Phase 1).
2. Add streaming to `agent-management` provider adapters (Phase 2).
3. Implement Tool Registry with filesystem/shell/git tools (Phase 3).
4. Wire Orchestrator `claim_task` → `agent-runtime` create run (Phase 4).
5. Add contract verification + handoff (Phase 5).

---

## 5. Rejected Alternatives

| Option | Rejection Reason |
|--------|------------------|
| Embed loop in `agent-management` | Conflates configuration domain with execution domain; violates ADR-102 ownership. |
| Embed loop in `runtime-hardening` | Runtime Hardening is infrastructure (isolation, resources); shouldn't own LLM/tool semantics. |
| Embed loop in `orchestration-server` | Orchestrator = scheduling + workflow execution; agent turn-taking is a distinct concern. |
| Use existing `/completions` + polling | Non-streaming, no tool execution, no contract verification; fundamentally insufficient. |
| LangGraph / custom workflow engine | Over-engineered; the loop is a linear turn-taking algorithm, not a DAG. |

---

## 6. Verification

- Unit: `loop.py` turn logic with mocked provider + tool executor.
- Integration: `agent-runtime` + `agent-management` (provider) + `runtime-hardening` (container) → full turn.
- Contract: `run_completion` returns `CursorPage<AgentRunDTO>` per ADR-101.
- Budget: step/token/cost limits enforced and logged per turn.
- Policy: tool call denied by `ToolPolicyEngine` → run blocked with `tool_policy_denied`.
- **No Hermes calls** in any integration test path.

---

## 7. Open Questions

1. **Container granularity:** One container per `AgentRun` (ephemeral) vs. one per `AgentInstance` (persistent across tasks)? PRD §5.3 suggests per-instance context/dir/permissions → lean toward per-instance container with run-scoped workspace overlay.
2. **Provider streaming normalization:** OpenRouter streams SSE; other providers may differ. `provider_adapter` must normalize to a common `Chunk` type.
3. **Human-in-the-loop:** Where does approval gate live? In `tool_executor` (blocks on designated tools) or Orchestrator (separate gate)? PRD §6.2 `HumanApproval` node type suggests workflow-level; tool-level approval is a policy flag.

---

*Recorded as part of AUDIT_REPORT.md response (task t_e72b7d4f).*