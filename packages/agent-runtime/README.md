# agent-runtime

The **native agent execution engine and autonomy framework** for the
Multi-Agent Workflow platform. It implements the P0 runtime capabilities from
the target ADR set and is intentionally dependency-free (stdlib only) so the
product runtime runs self-contained, with no external agent engine present
(ADR-107 R1).

## Capabilities → modules

| Capability | Module | ADR |
|------------|--------|-----|
| Isolated workspace provisioning per task (git worktree / scratch, 1:1 workspace↔task, fail-closed) | `agent_runtime.workspace` | ADR-107, ADR-109 §3.4 |
| Role/tool/model/context/permission enforcement (`AgentSpec`, intersection, deny-by-default) | `agent_runtime.spec`, `agent_runtime.permissions` | ADR-108, ADR-103 |
| Task DAG execution with parallelism and contract-gated result passing | `agent_runtime.graph`, `agent_runtime.runner` | ADR-109 |
| Retry, timeout, circuit breaker, checkpoint/restore & run resume | `agent_runtime.retry` | ADR-104 |
| Cost budgets, resource quotas and mandatory quality gates (fail-closed) | `agent_runtime.limits` | ADR-105 |
| Structured JSON logging, event hooks and metrics | `agent_runtime.observability` | ADR-106 |
| Error taxonomy | `agent_runtime.errors` | ADR-104 |

## Design invariants

- **Fail-closed everywhere**: missing policy ⇒ deny all; missing budget ⇒ zero;
  missing resource tier ⇒ minimal limits; a gate that is unavailable or raises
  blocks the task (never passes).
- **Intersection, never union**: an action is allowed only when the role grants
  the capability *and* the tool policy allows the resource.
- **No authority in the prompt**: the model context never contains lease / key /
  workspace-root / tool-policy fields (`build_model_context` rejects them).
- **One workspace per task**: no two concurrent runs share a `workspace_id`, and
  a task cannot hold two active workspaces.
- **Server-owned ordering**: a `pending` task is claimable only when every
  prerequisite is `completed`; the model can never grant itself claimability.
- **Checkpoints survive crashes**: run/turn state is persisted per turn and
  `resume_node` continues from `last_completed_turn + 1`.

## Usage

```python
from agent_runtime import AgentRuntime, TaskGraph, ProfileManager, WorkspaceManager

runtime = AgentRuntime(
    profiles=ProfileManager(store),          # config plane (Agent Management)
    workspaces=WorkspaceManager(ws_root, repo=repo),
    tool_executor=tool_executor,             # injects tool side effects
    gate_config=GateConfig(required_gates=("tester", "security")),
)
graph = TaskGraph.from_spec([...])           # validated, acyclic DAG
result = await runtime.run_graph(graph, agent_executor, max_parallelism=4)
```

The engine is transport-agnostic: the model turn loop (`agent_executor`) and the
real tool side effects (`tool_executor`) are injected, so the framework is fully
unit-testable without network, Docker or a provider.

## Tests

```bash
python -m pytest tests -q      # run from packages/agent-runtime
```

Unit tests exist for **every** module plus an end-to-end engine suite covering
chain execution, genuine parallelism, prerequisite gating, permission denial,
budget exhaustion, gate blocking, transient-error retry, workspace isolation and
crash-recovery resume.
