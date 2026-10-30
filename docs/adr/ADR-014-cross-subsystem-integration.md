# ADR-014: Cross-Subsystem Integration Architecture

**Status:** Proposed
**Date:** 2026-10-12
**Author:** sdlc-architect (task t_8cf664ab)
**Related:** GAP-ANALYSIS.md (G6), ADR-101 (API contract), ADR-102 (ownership), ADR-103 (tool policy), ADR-011 (agent runtime), ADR-012 (tool registry), ADR-013 (core subsystems), EPIC-INT E2–E9

---

## 1. Context and Problem

GAP-ANALYSIS.md identifies **G6: Orchestration↔quality-gates↔runtime not integrated** — three independent FastAPI apps with no cross-wiring:

| Subsystem | Port | Current Integration |
|-----------|------|---------------------|
| Orchestration Server | 8000 | Standalone; owns tasks/runs/contracts |
| Agent Management | 8001 | Standalone; owns agents/providers/policies |
| Runtime Hardening | 8002 | Standalone; owns containers/resources |
| Quality Gates | 8003 | Standalone; owns gate pipeline |

**Observed gaps:**
- Orchestrator `engine.py` does **not** invoke Quality Gates on task completion
- Orchestrator does **not** provision Runtime workspaces/containers for agent runs
- Agent Management does **not** register agents with Orchestrator (ADR-102 sync protocol)
- Runtime Hardening has no concept of Orchestration tasks or Quality Gates
- Frontend uses MockAdapter (no backend wiring)

EPIC-INT E2–E9 already scopes this integration. This ADR codifies the architectural decisions.

---

## 2. Requirements

| Req | Description |
|-----|-------------|
| R1 | Orchestrator invokes Quality Gates before task completion (gate enforcement) |
| R2 | Orchestrator provisions Runtime workspace/container for each agent run |
| R3 | Agent Management registers agents with Orchestrator on creation |
| R4 | Runtime reports health/metrics to Orchestrator for scheduling decisions |
| R5 | Single API Gateway at `/api/v1` routes to all backends (ADR-101) |
| R6 | Shared authentication context across all services (ADR-015) |
| R7 | Distributed tracing / correlation IDs across service calls |

---

## 3. Architectural Decision

### 3.1 Integration Pattern: Orchestrator as Composition Root

The **Orchestration Server** is the **composition root** — it orchestrates the other subsystems via **direct HTTP calls** (not message bus). This matches PRD §2.1 "Platform-owned orchestration" and ADR-102 ownership.

```
┌─────────────────────────────────────────────────────────────┐
│                      API Gateway (nginx/Traefik)            │
│                        /api/v1/*                              │
└──────────────┬────────────────────┬──────────────────────────┘
               │                    │
       ┌───────▼───────┐    ┌───────▼───────┐
       │ Orchestration │    │ Agent Mgmt    │
       │   Server      │    │               │
       │  (composition │    │  (config)     │
       │   root)       │    │               │
       └───────┬───────┘    └───────┬───────┘
               │                    │
       ┌───────▼───────┐    ┌───────▼───────┐
       │  Quality      │    │  Runtime      │
       │  Gates        │    │  Hardening    │
       │  (gates)      │    │  (infra)      │
       └───────────────┘    └───────────────┘
```

### 3.2 Service-to-Service Contracts

#### 3.2.1 Orchestrator → Quality Gates (Gate Enforcement)

**Trigger:** `Task.submit()` or `WorkflowRun.finalize()`

```python
# orchestration_server/engine.py
async def _run_gates(self, task: Task, attempt: TaskAttempt) -> GateResult:
    async with httpx.AsyncClient() as client:
        resp = await client.post(
            f"{settings.quality_gates_url}/api/v1/gates/evaluate",
            json={
                "candidate_version": attempt.id,
                "task_id": task.id,
                "project_id": task.project_id,
                "artifacts": attempt.artifacts,
                "required_gates": ["tester", "reviewer", "security", "release_prep"]
            },
            timeout=300.0
        )
    return GateResult.from_response(resp)
```

**Quality Gates API:**
```
POST /api/v1/gates/evaluate
  → runs pipeline for candidate → returns { passed: bool, gate_results: [...], evidence_ref: str }
GET  /api/v1/gates/status/{candidate_version}
```

#### 3.2.2 Orchestrator → Runtime Hardening (Workspace + Container)

**Trigger:** `claim_task` → before agent run starts

```python
# orchestration_server/engine.py
async def _provision_runtime(self, task: Task, agent_spec: AgentSpec) -> RuntimeHandle:
    async with httpx.AsyncClient() as client:
        # 1. Create workspace (scratch + overlay)
        ws_resp = await client.post(
            f"{settings.runtime_url}/api/v1/workspaces",
            json={"project_id": task.project_id, "task_id": task.id, "policy": agent_spec.tool_policy}
        )
        workspace = WorkspaceHandle.from_response(ws_resp)

        # 2. Create container for agent run
        container_resp = await client.post(
            f"{settings.runtime_url}/api/v1/agents",
            json={
                "workspace_id": workspace.id,
                "agent_spec": agent_spec.to_runtime_spec(),
                "resource_limits": agent_spec.resource_limits
            }
        )
        container = ContainerHandle.from_response(container_resp)

    return RuntimeHandle(workspace=workspace, container=container)
```

**Runtime Hardening API:**
```
POST /api/v1/workspaces          → create scoped workspace
POST /api/v1/agents              → create container (returns agent_id)
GET  /api/v1/agents/{id}/health  → health probe
POST /api/v1/agents/{id}/stop    → stop container
GET  /api/v1/agents/{id}/metrics → resource usage
```

#### 3.2.3 Agent Management → Orchestrator (Agent Registration)

**Trigger:** `AgentInstance` created

```python
# agent_management/services.py
async def _register_with_orchestrator(self, instance: AgentInstance) -> None:
    async with httpx.AsyncClient() as client:
        await client.post(
            f"{settings.orchestration_url}/api/v1/agents/register",
            json={
                "id": str(instance.id),
                "definition_id": str(instance.definition_id),
                "status": "idle"
            }
        )
```

**Orchestration API:**
```
POST /api/v1/agents/register     → create Agent row (idle)
PATCH /api/v1/agents/{id}/status → Orchestrator-owned (idle/busy/terminated)
GET  /api/v1/agents/{id}         → scheduling status
```

#### 3.2.4 Runtime → Orchestrator (Health/Metrics Callback)

**Trigger:** Periodic (every 30s) or on state change

```python
# services/runtime-hardening/runtime/api.py
async def _report_health(self, agent_id: UUID) -> None:
    async with httpx.AsyncClient() as client:
        await client.post(
            f"{settings.orchestration_url}/api/v1/agents/{agent_id}/health",
            json={"state": "running", "metrics": {...}}
        )
```

---

### 3.3 Shared Infrastructure

| Concern | Solution |
|---------|----------|
| **Service Discovery** | Static config via `settings.py` (env vars: `ORCHESTRATION_URL`, `AGENT_MGMT_URL`, `RUNTIME_URL`, `QUALITY_GATES_URL`) |
| **Auth Context** | Shared JWT secret (ADR-015); each service validates + forwards `X-Request-ID` |
| **Correlation IDs** | `X-Request-ID` header propagated on all inter-service calls |
| **Timeouts** | Per-call: 30s (register), 300s (gates), 60s (runtime provision) |
| **Retries** | Exponential backoff (max 3) for transient failures; circuit breaker per upstream |
| **Error Format** | RFC 9457 Problem Details (all services) |

---

### 3.4 Gateway Routing (ADR-101 Implementation)

```
Gateway (nginx) at /api/v1/
├── /workflows/*           → Orchestration Server (8000)
├── /tasks/*               → Orchestration Server
├── /agents/*              → Orchestration Server (scheduling)
├── /kanban/*              → Orchestration Server
├── /schedules/*           → Orchestration Server
├── /agents/definitions*   → Agent Management (8001)
├── /agents/instances*     → Agent Management
├── /model-profiles*       → Agent Management
├── /tool-policies*        → Agent Management
├── /providers*            → Agent Management
├── /usage*                → Agent Management
├── /memory*               → Agent Management
├── /runtime/agents*       → Runtime Hardening (8002)
├── /runtime/workspaces*   → Runtime Hardening
├── /runtime/metrics*      → Runtime Hardening
└── /gates/*               → Quality Gates (8003)
```

---

### 3.5 Quality Gates Integration Detail (PRD §14, §7.3)

**Current:** Quality Gates `pipeline.py` evaluates a candidate version independently.

**Required:** Orchestrator **blocks** task completion until required gates pass.

```python
# orchestration_server/engine.py - in submit()
async def submit(self, task_id: UUID, attempt_id: UUID, result: TaskResult, identity: Identity) -> None:
    # 1. Verify contract (JSON Schema)
    self._verify_contract(task, result)

    # 2. Run quality gates (BLOCKING)
    gate_result = await self._run_gates(task, attempt)
    if not gate_result.passed:
        raise GateFailedError(gate_result)

    # 3. Only then: write saga_event, mark completed, release agent
    await self._finalize_task(task, attempt, result, identity)
```

**Gate Configuration:** Per-project `QualityGateConfig` (Quality Gates module) defines required gates per task type.

---

## 4. Consequences

**Positive:**
- Clear composition root (Orchestrator) — no circular dependencies
- Synchronous gate enforcement = strong consistency (PRD §7.3)
- Runtime provisioning per-task = isolation (PRD §4.3, §5.3)
- Gateway isolates frontend from backend topology (ADR-101)
- All inter-service calls observable via correlation IDs

**Negative:**
- Orchestrator becomes a **fan-out hub** — latency adds up (gates 300s + runtime 60s)
- Temporal coupling: Orchestrator must wait for gates; async would weaken guarantees
- Quality Gates must be highly available (blocker for all completions)
- Service mesh not used — direct HTTP adds operational burden (mitigated: single host)

**Mitigations:**
- Gate evaluation async with webhook/callback (future): Orchestrator submits → polls status
- Circuit breakers on all upstream calls (prevent cascade)
- Health checks on all services before dispatching work

---

## 5. Rejected Alternatives

| Option | Rejection Reason |
|--------|------------------|
| Message bus (Redis/RabbitMQ) for all integration | Adds infrastructure; synchronous gate enforcement needs request/response anyway |
| Quality Gates as library (embedded in Orchestrator) | Violates independence (PRD §2.3); gates must be independently verifiable |
| Runtime Hardening as library | Runtime is infrastructure (containers, cgroups); separate process boundary is security |
| Orchestrator calls Agent Management for tool execution | Tool execution is Runtime concern (ADR-011, ADR-012); Agent Mgmt = config only |
| gRPC for inter-service | REST+JSON sufficient; Gateway already normalizes; gRPC for high-perf later |

---

## 6. Verification

- Integration test: `claim_task` → Runtime provisions → Agent Runtime runs → Gates evaluate → Orchestrator finalizes
- Contract test: Each inter-service endpoint returns RFC 9457 on error
- Chaos test: Kill Quality Gates mid-evaluation → Orchestrator handles timeout/retry correctly
- Observability: Correlation ID appears in logs of all 4 services for one task
- Gateway: Routes all `/api/v1/*` correctly (integration test matrix)

---

## 7. Implementation Sequence (aligns with EPIC-INT E2–E9)

1. **Service discovery config** — env vars + health endpoints on all services
2. **Orchestrator → Quality Gates** — blocking gate evaluation in `submit()`
3. **Orchestrator → Runtime** — workspace + container provisioning in `claim_task`
4. **Agent Mgmt → Orchestrator** — agent registration on `AgentInstance` create
5. **Runtime → Orchestrator** — health/metrics callback
6. **Gateway deployment** — nginx config + routing rules
7. **Frontend wiring** — `HttpAdapter` → Gateway, `mock:false` default
8. **E2E test** — full SDLC run through all subsystems

---

## 8. Open Questions

1. **Gate evaluation async?** Current sync blocks Orchestrator for minutes. Webhook-based async would need Orchestrator to persist "waiting for gates" state and handle callback.
2. **Shared database vs HTTP?** ADR-102 says logical FKs only (no cross-DB constraints). HTTP is correct for v1.
3. **Gateway auth termination?** Gateway validates JWT → forwards claims as headers? Or each service validates? ADR-015 will decide.

---

*Recorded as part of GAP-ANALYSIS.md response (task t_8cf664ab).*