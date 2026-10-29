# ADR-011: Agent Runtime Loop Architecture

**Status:** Proposed
**Date:** 2026-10-12
**Author:** sdlc-architect (task t_8cf664ab)
**Related:** GAP-ANALYSIS.md (G1, G2), PRD §5.4, §13, ADR-102 (ownership), ADR-103 (tool policy)

---

## 1. Context and Problem

The GAP-ANALYSIS.md identifies the **single largest platform gap (G1)**: no module implements the agent runtime loop specified in PRD §5.4:

> *Agent Runtime loop (task→messages→LLM→stream→tools→save→loop→verify contract→hand to orchestrator; model cannot bypass gates)*

Current state:
- `agent-management` exposes only `/completions` — a single non-streaming provider call (`run_completion`), messages+params only
- `runtime-hardening` provides a control-plane (create/pause/resume/stop/limits/status) but **no model/tool loop**
- No tool execution, no streaming handling, no contract verification handoff to orchestrator
- Tool Registry (§13) is entirely missing — only `ToolPolicy` metadata exists (ADR-103)

This gap blocks AC-06 (Tools) and AC-12 (full SDLC run) — the product cannot run a real autonomous agent against a workspace.

---

## 2. Requirements (from PRD §5.4, §13, §7.3)

| Req | Description |
|-----|-------------|
| R1 | Turn-taking loop: task → build messages → LLM (streaming) → parse tool calls → execute tools → save results → repeat until done |
| R2 | Streaming LLM responses with tool-call parsing (OpenRouter + future providers) |
| R3 | Tool execution sandboxed per `ToolPolicy` (deny-by-default, ADR-103) |
| R4 | Contract verification (JSON Schema) before handoff to Orchestrator |
| R5 | Handoff to Orchestrator via `submit` (status + identity + schema + confirmations) |
| R6 | Budget enforcement: step/time/token/cost limits per agent settings (§5.2) |
| R7 | Retry/fallback model policy per agent settings |
| R8 | Human-approval requirement for designated tool calls |
| R9 | Output JSON Schema success/error rules per agent settings |

---

## 3. Architectural Decision

### 3.1 New Component: `agent-runtime` Module

Create a new first-class module `agent-runtime/` (sibling to `orchestration-server`, `agent-management`, `quality-gates`, `runtime-hardening`) that owns the **agent execution loop**.

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

### 3.2 Loop Algorithm (Single Turn)

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

### 3.3 Tool Registry (PRD §13)

| Tool Category | Tools | Execution Model |
|---------------|-------|-----------------|
| Filesystem | `fs_read`, `fs_write`, `fs_search`, `fs_list` | OverlayFS-scoped paths (Runtime Hardening) |
| Shell | `shell_exec` | Restricted shell in container (allow-list) |
| Git | `git_read`, `git_write` (status, diff, commit, push) | Git wrapper with subcommand allow-list |
| Network | `http_request` | nftables-egress-limited (Runtime Hardening) |
| Memory | `memory_search`, `memory_write` | Agent Management Memory service (new) |
| Task | `task_read`, `task_update` | Orchestration Server API (internal) |
| Artifact | `artifact_read`, `artifact_write` | Orchestration Server API (internal) |
| Agent Spawn | `spawn_agent` | Orchestration Server → new AgentInstance |

**Registry Interface:**
```python
class ToolRegistry:
    def get_tool(self, name: str) -> ToolSpec
    def execute(self, name: str, params: dict, context: ExecutionContext) -> ToolResult
    def list_available(self, policy: ToolPolicy) -> list[str]
```

### 3.4 Integration Boundaries

| Boundary | Mechanism |
|----------|-----------|
| Orchestrator → Agent Runtime | Orchestrator calls `POST /api/v1/agent-runs` with `Task`, `AgentSpec`; receives `run_id`; polls/status websocket for completion |
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
- Single component owns the complete execution loop (no split across services)
- Streaming-native design from day one (not retrofitted)
- Tool Registry is a first-class, testable component
- Clear integration contracts with existing subsystems
- Budget enforcement built into the loop (not an afterthought)

**Negative:**
- New module adds operational surface (5th FastAPI service)
- Requires provider streaming support (OpenRouter supports; mock provider needs update)
- Container-per-run or container-per-agent-instance decision affects resource usage
- Tool implementations are net-new code (8+ tool backends)

**Migration:**
1. Implement `agent-runtime` module with loop + tool executor (Phase 1)
2. Add streaming to `agent-management` provider adapters (Phase 2)
3. Implement Tool Registry with filesystem/shell/git tools (Phase 3)
4. Wire Orchestrator `claim_task` → `agent-runtime` create run (Phase 4)
5. Add contract verification + handoff (Phase 5)

---

## 5. Rejected Alternatives

| Option | Rejection Reason |
|--------|------------------|
| Embed loop in `agent-management` | Conflates configuration domain with execution domain; violates ADR-102 ownership |
| Embed loop in `runtime-hardening` | Runtime Hardening is infrastructure (isolation, resources); shouldn't own LLM/tool semantics |
| Embed loop in `orchestration-server` | Orchestrator = scheduling + workflow execution; agent turn-taking is a distinct concern |
| Use existing `/completions` + polling | Non-streaming, no tool execution, no contract verification; fundamentally insufficient |
| LangGraph / custom workflow engine | Over-engineered; the loop is a linear turn-taking algorithm, not a DAG |

---

## 6. Verification

- Unit: `loop.py` turn logic with mocked provider + tool executor
- Integration: `agent-runtime` + `agent-management` (provider) + `runtime-hardening` (container) → full turn
- Contract: `run_completion` returns `CursorPage<AgentRunDTO>` per ADR-101
- Budget: step/token/cost limits enforced and logged per turn
- Policy: tool call denied by `ToolPolicyEngine` → run blocked with `tool_policy_denied`

---

## 7. Open Questions

1. **Container granularity:** One container per `AgentRun` (ephemeral) vs. one per `AgentInstance` (persistent across tasks)? PRD §5.3 suggests per-instance context/dir/permissions → lean toward per-instance container with run-scoped workspace overlay.
2. **Provider streaming normalization:** OpenRouter streams SSE; other providers may differ. `provider_adapter` must normalize to a common `Chunk` type.
3. **Human-in-the-loop:** Where does approval gate live? In `tool_executor` (blocks on designated tools) or Orchestrator (separate gate)? PRD §6.2 `HumanApproval` node type suggests workflow-level; tool-level approval is a policy flag.

---

*Recorded as part of GAP-ANALYSIS.md response (task t_8cf664ab).*