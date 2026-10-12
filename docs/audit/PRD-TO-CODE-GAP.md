# GAP-ANALYSIS.md — PRD → Code, MVP v1

**Task:** `t_f560c67d` — Perform PRD-to-Code Gap Analysis for MVP v1
**Author profile:** sdlc-researcher
**Date:** 2026-10-12
**Repository:** `askarahodov/multi-agent-workflow` @ commit `eba4685` (worktree `wt/t_f560c67d`)
**Source of truth for requirements:** PRD (Draft 1.0), stored in root kanban card `t_06d22d87`, extracted to this analysis. Product doc directory: `/mnt/data/multi-agent-workflow/`.

> **Note on "sections 3.1–3.12".** The task brief references PRD "sections 3.1–3.12". The actual PRD (Draft 1.0 in card `t_06d22d87`) does not use a `3.1–3.12` numbering: chapter `3` is *"Основные сущности платформы"* (an entity table), and the concrete requirement chapters are §4–§15 (subsystems), §2 (principles), §17–§19 (reliability/security/v1-scope), §21 (acceptance criteria). This report therefore maps against the **actual** PRD structure, which is the only defensible, evidence-based reading. Every requirement below carries its real PRD reference and an implementation status of **IMPLEMENTED / PARTIAL / MISSING**.

---

## 0. Method and verification

Evidence was gathered by direct inspection of source files and by **actually running** each backend test suite against the shared canonical venv (`.venv`, Python 3.12). No source files were modified.

### Test execution (real runs, this session)

| Module | Command | Result |
|---|---|---|
| orchestration-server | `pytest tests -q` | **28 passed** |
| agent-management | `pytest tests -q` | **48 passed** |
| quality-gates | `pytest tests -q` | **45 passed** |
| runtime-hardening | `pytest tests -q` | **117 passed** (0 skipped) |
| **Backend total** | | **238 passed** |
| frontend | `make check` (typecheck/lint/vitest/schema/build) | **documented red** — `vitest run` gathers Playwright `e2e/*.spec.ts` and exits 2; 49 unit tests pass, schema validation PASS. Not re-executed here (Node toolchain not mounted in worktree); status from `docs/PROJECT-SYNTHESIS.md` (verified at this same commit) with a dedicated fixer card `t_c7475906` already assigned. |

Statements below are labelled with confidence (`verified` = directly observed code/test run; `inferred` = derived from structure; `unknown` = not determinable).

---

## 1. Module → subsystem map (structure)

| Module (repo dir) | PRD subsystem(s) | Verified component surface |
|---|---|---|
| `orchestration-server/` | §7 Orchestrator, §4.1 projects, §4.2 workspace (data), §2.1/§2.2 | `engine.py`, `api.py`, `models.py`, `schemas.py`, `db.py`, `queries.py` |
| `agent-management/` | §5.1–5.3 agents, §12 providers/model profiles, §13 policies | `api.py`, `services.py`, `models.py`, `tool_policy.py`, `providers/*` |
| `quality-gates/` | §7.3 gates, §2.3 verification, §2.6 release, §8 (partial), §14 (partial) | `pipeline.py`, `evidence.py`, `gates/{tester,reviewer,security,release_prep,walk,base}.py` |
| `runtime-hardening/` | §5.4 runtime control-plane, §4.3 environment, §17, §18 | `container_runtime.py`, `resource_manager.py`, `workspace_manager.py`, `circuit_breaker.py`, `health.py`, `metrics.py`, `api.py`, `models.py` |
| `frontend/` | §6 visual workflow builder, §15 (only one section) | React Flow editor: `editor/*`, `workflow/workflow.schema.json`, `api/{client,httpAdapter,mockAdapter}.ts` |
| `docs/` | §3 entity spec, ADRs, research | `domain-architecture.json`, `runtime-hardening/ADR-001..005`, `adr/ADR-010` |
| `tools/` | (§23 dev tooling / Hermes SDLC, **not** product features) | `agent-orchestration/*` (spawn-agent.sh, worktree mgr, detect-hotspots, kanban_tools.py) |

---

## 2. PRD → implementation mapping

Status legend: **IMPLEMENTED** = feature present and covered by tests; **PARTIAL** = present but materially incomplete vs. the PRD; **MISSING** = absent from the codebase.

### 2.1 Principles (§2)

| PRD | Status | Evidence |
|---|---|---|
| §2.1 Platform-owned orchestration (agents cannot self-mark completed) | **IMPLEMENTED** | `orchestration_server/engine.py` — single authority; `submit()` completes only after contract verification; no agent-status-write API. `tests/test_api.py`, `test_engine_lifecycle.py`. confidence verified |
| §2.2 Durable execution (state survives restart) | **IMPLEMENTED** | append-only `saga_events` journal written in the same transaction as state change; startup `recover()` re-queues incomplete work; `tests/test_durability.py::test_restart_*`, `test_api.py::test_restart_via_api_preserves_completed_run`. verified |
| §2.3 Independent quality verification (TESTER/REVIEWER/SECURITY verify a version; DEVELOPER report ≠ proof) | **IMPLEMENTED** (gate presence) / PARTIAL (depth) | `quality_gates/gates/{tester,reviewer,security}.py`, checksummed `EvidenceStore` in `quality_gates/evidence.py`, `pipeline.py::transition` blocks without passing gates. Limitation: gates are heuristic file/dep/secret scans, not deep independent execution against a pinned candidate; cross-module wiring to a specific candidate version is not fully present. verified |
| §2.4 Provider independence (business logic independent of any provider) | **IMPLEMENTED** | `agent_management/providers/base.py` `BaseProvider` ABC; adapters `openrouter/huggingface/custom/mock` in `providers/adapters.py`; `tests/test_providers.py`. verified |
| §2.5 Controlled autonomy (agents confined by policies/budgets/workspaces) | **PARTIAL** | `tool_policy.py` (deny-by-default) + container isolation exist, but policies are metadata; budget/step/time/token/cost limits are not enforced by any executing runtime (see §5.2). verified |
| §2.6 Human-controlled release (publish/release/deploy require approval; v1 RELEASE only prepares) | **IMPLEMENTED** | `quality_gates/gates/release_prep.py` — candidate created in `awaiting_approval`; `approve_release_candidate` requires human identity; release agent cannot self-approve (`reject_release_candidate`/`approve_release_candidate`, tests `test_release_prep.py`). verified |

### 2.2 Entity model (§3)

| PRD | Status | Evidence |
|---|---|---|
| §3 All 23 platform entities (Project, Workspace, Environment, AgentDef/Instance, Team, Workflow Def/Version/Run, Task, TaskAttempt, KanbanBoard, Gate, Contract, Conversation, Memory, ScheduledJob, Artifact, Provider, ModelProfile, ToolPolicy, AuditEvent) | **PARTIAL** — spec complete, code partial | Spec: `docs/domain-architecture.json` covers all 23 entities ("23 сущности" per synthesis). Code models: orchestration (`Project,Workspace,Contract,Agent,WorkflowRun,Task,TaskAttempt,SagaEvent` = audit), agent-management (`Provider,ModelProfile,ToolPolicy,AgentDefinition,AgentInstance,TokenUsage`), quality-gates (`Task,GateRun,EvidenceItem,ReleaseCandidate`), runtime-hardening (in-memory `Agent,AgentSpec,Workspace,Snapshot`). **Not modelled in code:** `Team`, `WorkflowDefinition/Version`, `Conversation`, `Memory`, `ScheduledJob`, `Artifact`, `Environment`, `KanbanBoard`. verified |

### 2.3 Projects / workspaces / environments (§4)

| PRD | Status | Evidence |
|---|---|---|
| §4.1 Project creation (name, desc, working dir, git link, branch, team template, workflow, environment, budgets, kanban) | **PARTIAL** | `create_project(name, description, settings)` — free-form `settings` JSON absorbs everything else; no dedicated typed fields, no git-link/branch/team-template/env/budget/kanban creation logic; no project UI. verified |
| §4.2 Workspace (read/write areas, shell policy, git/worktrees, temp dir, cleanup, concurrency control) | **PARTIAL** | Orchestration `Workspace(path, settings)`; runtime `workspace_manager.py` adds create/snapshot/restore/promote/validate, scratch dirs, checksummed snapshots, cleanup (`tests/test_workspace_manager.py`). File-access enforcement depends on the container isolation layer, not on path checks alone. verified |
| §4.3 Environment (Local / Isolated Container now; Remote Worker later; real sandbox not path-checking) | **PARTIAL** | §4.3 isolated-container requirement is well advanced: `container_runtime.py` isolation tiers (runc, gVisor runsc, Kata-on-Firecracker, nsjail), default-deny seccomp generator, rootless/user-ns config (ADR-001). Remote Worker: MISSING. Local Workspace shell control partial. verified |

### 2.4 Agents (§5)

| PRD | Status | Evidence |
|---|---|---|
| §5.1 Agent Manager (create/edit/template/copy/teams/multi-instance) | **PARTIAL** | `AgentDefinition` (template) + `AgentInstance` CRUD + lifecycle endpoints in `agent_management/api.py`. **Teams: MISSING** (no `Team` model). verified |
| §5.2 Agent settings (core/LLM/tools/policies/memory/result) | **PARTIAL** | Present: system_prompt, description, `config_schema`/capabilities, model_profile (params/context_window/cost in `ModelProfile`), tool_policy, ToolPolicy permissions (fs/git/shell/network, deny-by-default). **Absent/mostly absent:** retry policy + fallback model fields, step/time/token/cost limits, stop conditions, human-approval requirement, memory/knowledge-source settings, output JSON-Schema success/error rules. verified |
| §5.3 Agent Spawn (dynamic instances, parent-run id, pinned config, per-instance context/dir/permissions/limits/log; child cannot expand parent rights) | **PARTIAL** | Multiple instances from a definition exist (`AgentInstance`; `create_agent_instance`). **Missing:** parent-run linkage, pinned config-version guarantee, per-instance resource limits in agent-management (that lives in runtime-hardening with its own model), per-instance permissions, and no enforcement that a child cannot expand parent rights. verified |
| §5.4 Agent Runtime loop (task→messages→LLM→stream→tools→save→lo≥→verify contract→hand to orchestrator; model cannot bypass gates) | **MISSING** | No module implements the turn-taking runtime loop. Closest pieces, isolated from each other: `agent_management` `/completions` (single provider call via `run_completion`, non-streaming, messages+params only), `runtime-hardening` control-plane lifecycle (create/pause/resume/stop/limits/status — **no model/tool loop**). No tool-execution loop, no streaming-to-tools handling, no contract-handoff path to the orchestrator. This is the single largest platform gap and blocks a functioning autonomous SDLC run. verified |

### 2.5 Visual workflow builder (§6) — frontend

| PRD | Status | Evidence |
|---|---|---|
| §6.1 Editor (nodes, edges, property config, drag, zoom, group, deps, save, version, validate-before-run) | **IMPLEMENTED** (editor) / PARTIAL (versioning/save-live) | `frontend/src/editor/*` — `WorkflowCanvas`, `NodePalette`, `PropertyPanel`, `EdgePanel`, Zustand `store`, `importExport.ts` (JSON export/import), graph validation `workflow/validateGraph.ts` (+tests). Save/versioning is file/JSON export only; no server persistence API wired live (mock adapter). verified |
| §6.2 Node types (Start, Agent, Condition, Gate, Parallel, Join, HumanApproval, Tool, Memory, Delay, End) | **IMPLEMENTED** | `frontend/src/workflow/workflow.schema.json` enumerates all 11 (Draft 2020-12, `schema_version` "1.0"); schema validation PASS in test suite. verified |
| §6.3 Edges (source, target, result type, condition, error rule, retries; no free-text instead of contract) | **IMPLEMENTED** | `EdgePanel`, `referenceSelectors.tsx`, `validateGraph.ts` edge typing; import/export carries edge metadata. verified |
| §6.4 Execution control (run/pause/resume/cancel/retry-step/history/new-version/loop-limit/timeouts; run pinned to version) | **PARTIAL** | Runtime control-plane has pause/resume/stop + health/metrics (`runtime-hardening/api.py`); editor has **no** wired run/pause/cancel controls and no version pinning; run launching is not connected to the editor. verified |

### 2.6 Orchestrator (§7)

| PRD | Status | Evidence |
|---|---|---|
| §7.1 Orchestrator responsibilities (accept requests, create tasks, select workflow, launch agents, deps, contracts, retries, FIXER routing, stop on critical, update Kanban, persist, check gates, prep results) | **IMPLEMENTED** (core) / PARTIAL (workflow selection, gate checks, Kanban update, FIXER routing) | `engine.py` covers create/launch/claim/submit/fail/block/tick, retries, run finalization, persistence. **Not wired:** workflow-definition selection, automated FIXER re-routing, gate-check integration with quality-gates, Kanban update, human result packaging. verified |
| §7.2 Task state machine (backlog/ready/running/verification/blocked/failed/completed/cancelled) | **PARTIAL** | Code task statuses: `pending, in_progress, completed, failed, blocked` (models.py `ck_task_status`); run: `pending, running, completed, failed, cancelled`; attempt: `running, completed, failed, verification_failed, interrupted`. Missing explicit `verification` and `cancelled` **task** states; `verification` exists only as an attempt status. All transitions are engine-owned. verified |
| §7.3 Gate enforcement (transactional completion: status, identity, JSON schema, confirmations, candidate version, QG, audit, status change; atomic on error; no tool bypass; restrict direct DB) | **IMPLEMENTED** | `engine.submit()` performs status+identity+owner checks, JSON-Schema (`Draft202012Validator`) verification, writes `saga_events` in the same transaction, applies retry/fail on failure → nothing changes on error; no alternate completion API. Cross-layer gate enforcement: `quality_gates/pipeline.py::transition` blocks unless required gates passed. verified |
| §7.4 Recovery / idempotency (detect interrupted runs; no double completion; idempotency of non-atomic external ops) | **IMPLEMENTED** (core) / PARTIAL (external-op intent journal) | `engine.recover()` (attempts→interrupted, in_progress tasks→pending, busy agents freed) + `saga_events`; `_finalize_run` guarded by `UPDATE ... WHERE status='running'` for idempotent finalization. **PARTIAL:** PRD §7.4's explicit action-id/intent-recording + recovery rules for uncertain external results (command execution ≠ atomic with SQLite write) is not implemented; `tests/test_durability.py`, `test_concurrency.py`. verified |

### 2.7 Kanban (§8)

| PRD | Status | Evidence |
|---|---|---|
| §8 Automatic Kanban board (per-project board, user/PLANNER task creation, Workflow Run link, assignee, dependencies, priorities, subtasks, attempt history, comments/artifacts, errors/blockers, check status, transition log, auto-update; manual move cannot bypass server) | **MISSING** (product) | No Kanban-board entity/UI in the product code. Closest: quality-gates `pipeline.transition()` models an abstract transition gate; orchestration `Task.priority`; `tools/agent-orchestration/agent_orchestration/kanban_tools.py` is the *Hermes development* board tooling (dev meta-process per PRD §23), not the product's Kanban. No dependencies/subtasks/comments/transition-log board model. verified |

### 2.8 Chats / Memory / Schedules (§9–§11)

| PRD | Status | Evidence |
|---|---|---|
| §9 Chats (dialogs, streaming, history, artifacts, tool-call view, continuity after restart, create-task-from-message; chat cannot bypass process) | **MISSING** | No `Conversation` model, no chat endpoints, no frontend chat. verified |
| §10 Memory (agent/task/project/workflow/global levels; write/search/update/delete/version/keyword; SQLite text search for v1; memory must not be higher-priority instructions) | **MISSING** | No `Memory` model or service anywhere in the product code. (Hermes's own memory is agent infrastructure, not a product Memory subsystem.) verified |
| §11 Schedules / cron (create schedule, one-shot, run workflow/agent, project, on/off, history, timezone, missed/skip/concurrency/retry policy) | **MISSING** | No `ScheduledJob` model, no scheduler background executor. Cron exists only as Hermes platform machinery, not product features. verified |

### 2.9 Providers & tools (§12–§13)

| PRD | Status | Evidence |
|---|---|---|
| §12.1 Provider abstraction (messages, streaming, tool calling, params, cancellation, timeouts, provider errors, token usage, cost, capabilities + compatibility checks) | **PARTIAL** | `BaseProvider` supports messages, generation params, `Usage`, model `capabilities`/`supports()`, cost fields on `ModelProfile`. **Missing from the interface:** streaming, tool-calling, cancellation, timeout, provider-error taxonomy, capability-compatibility enforcement. verified |
| §12.2 Initial providers (v1 OpenRouter; others later) | **IMPLEMENTED** | Providers: `openrouter` (v1), plus `huggingface`, `custom`, `mock` adapters (`providers/adapters.py`); registry `providers/registry.py`. verified |
| §12.3 Model profiles (user-created, assigned to agents; secrets stored separately from exported configs) | **IMPLEMENTED** | `ModelProfile` CRUD + assignment to `AgentDefinition`; `Provider.auth_config` holds secrets and models expose them via `_require` (not in exported model rows). Secret-separation is by design; not deeply audited here. verified/inferred |
| §13 Tool registry (File Read/Write/Search, Shell, Git Read/Ops, HTTP-limited, Memory Search/Write, Task Read, Artifact Read, Agent Spawn; each with params/policy/limits/timeout/log/structured result/error rules; task tools cannot change status or bypass gates; dangerous ops technically blocked) | **MISSING** (execution) / PARTIAL (policy only) | Only *policy metadata* exists (`ToolPolicy` + `tool_policy.py` checker: fs_read/fs_write/git/shell/network, deny-by-default). **No tool implementations, no Tool Registry, no execution, no call log, no SSRF/path-canonicalization guards** (tools don't exist to guard). No memory/task/artifact/spawn tool backends. verified |

### 2.10 SDLC template (§14)

| PRD | Status | Evidence |
|---|---|---|
| §14 Standard SDLC workflow (RESEARCHER→ARCHITECT→PLANNER→DEVELOPER→TESTER+REVIEWER+SECURITY→FIXER→re-verify→RELEASE→HUMAN; versioned contracts, JSON Schema, independent checks, transition rules, fix-loop limit, auto task creation, decision audit; TESTER fail→FIXER; FIXER change invalidates prior candidate checks; RELEASE forms package only) | **PARTIAL** | The four gates + release-prep + transition enforcement + approval gate are implemented (`quality-gates/`, 45 tests). **Missing as an integrated template:** the automated role DAG (RESEARCHER→…→HUMAN), fix-loop limit, candidate invalidation when FIXER touches source, auto task creation, and wiring TESTS results to orchestration routing. `docs/adr/ADR-010-multi-agent-orchestration.md` specifies the model but it is not built out. verified |

### 2.11 Web interface (§15)

| PRD | Status | Evidence |
|---|---|---|
| §15 Single web app with 14 sections (Dashboard, Projects, Workspaces, Agents, Teams, Workflow Builder, Kanban, Runs, Live Execution, Chats, Memory, Schedules, Providers, Settings), typed HTTP API, SSE/WebSocket with reconnect replay, paginated run history | **PARTIAL** | Only **Workflow Builder** exists (`frontend/src/App.tsx` renders NodePalette + WorkflowCanvas + PropertyPanel only). The other 13 sections are absent. API client has `httpAdapter`/`mockAdapter`; live backend not wired (mock in use). No SSE/WebSocket reconnect replay; no other pages. verified |

### 2.12 Reliability & security (§17–§18), v1 scope (§19), stages (§20), acceptance (§21)

| PRD | Status | Evidence |
|---|---|---|
| §17 Reliability (provider errors/401/429/5xx, network loss, timeout, bad JSON, tool error, agent crash, worker death, restart, concurrent file edit, workflow loop, budget exceed, web disconnect → definite persisted state; no unsafe auto-retry) | **PARTIAL** | Implemented/tested: retry with backoff, run/task/attempt recovery, concurrent-claim guarding (orchestration); circuit breaker + bulkhead + degradation ladder + health probes (runtime-hardening, unit/chaos tests). **Not implemented:** budget-exceed handling end-to-end, workflow-loop limit, provider-failure fault-injection beyond unit mocks, worker-process death handling across modules. verified |
| §18 Security (no keys in source, no secrets in logs, protect management API incl. network, no direct DB from UI, restrict paths, prevent symlink bypass, limit shell/network, validate tool inputs, control git, SSRF check, isolate dangerous exec, audit privileged ops) | **PARTIAL** | Strong isolation substrate: container isolation tiers + default-deny seccomp + rootless user-ns (runtime-hardening); secret/dependency scan gate (quality-gates/security.py); RFC-9457 errors; no secrets in model rows. **Gaps:** the FastAPI apps expose **no authentication/authorization layer** (management APIs are open), no SSRF guard layer, no symlink-canonicalization enforcement in tool layer (no tool layer), no RBAC (correctly deferred for v1), UI→API access is the only intended DB path. verified/inferred |
| §19 v1 core (server, admin/local mode, multi-project+board+env, OpenRouter, custom agents/model profiles, own agent runtime, visual workflow, sequential+conditional transitions, contracts+gates, Kanban, workspaces+git, run+observe agents, chat, basic project memory, cron, SQLite, history+audit+recovery, SDLC template) | **PARTIAL** | Present: server (3 FastAPI apps), projects+workspaces+contracts, provider abstraction+OpenRouter+mock, agent defs/model-profiles/tool-policies, visual workflow builder (editor+11 node types+schema), contract+gates+gate enforcement+recovery (238 backend tests green). **Missing for v1 core:** own agent run-time loop, Kanban board, chats, project memory, cron/schedules, integrated SDLC template. verified |
| §20 Stages 1–4 (foundation/agent-engine/orchestration/visual-workflow+kanban) & 5–6 (chats-memory-schedules; hardening) | **PARTIAL** | Stage 1–2: largely implemented. Stage 3 (orchestration): implemented. Stage 4 Kanban half: **not** built. Stage 5 (chats/memory/schedules): **MISSING**. Stage 6 (acceptance/hardening): partial (E2–E9 integration EPIC-INT in progress; see `docs/PROJECT-SYNTHESIS.md`). verified |
| §21 AC-01..AC-15 | **PARTIAL** | Covered by tests/suites: AC-01 projects, AC-02 agents, AC-03 workflow (schema/editor), AC-04 mandatory gate, AC-06 tools (policy), AC-10 provider failures (partial), AC-11 recovery, AC-14 `make check` (red—see §0), AC-15 release prep. **Not demonstrably covered:** AC-05 Kanban, AC-07 chats, AC-08 memory, AC-09 cron, AC-12 full SDLC run, AC-13 end-to-end security. inferred |

---

## 3. Platform-wide gaps (highest priority for ARCHITECT/PLANNER)

| # | Gap | PRD ref | Evidence | Impact |
|---|---|---|---|---|
| G1 | **No agent runtime loop** (task→messages→LLM stream→tools→verify contract→handoff). Tool execution, streaming, contract verification, orchestrator handoff are absent. | §5.4, §13 | `agent-management` only `/completions`; `runtime-hardening` is a control-plane with no loop | Blocks any real autonomous agent execution |
| G2 | **No Tool Registry / tool implementations** (File/Shell/Git/HTTP/Memory/Task/Artifact/Spawn). Only ToolPolicy metadata. | §13 | `tool_policy.py` + `ToolPolicy` model only | No agent can act on a workspace |
| G3 | **Feature subsystems missing:** Kanban board, Chats, Memory, Schedules/cron, Teams. | §8, §9, §10, §11, §5.1 | No models/endpoints; `docs/domain-architecture.json` spec only | Part of PRD §19 v1 core unbuilt |
| G4 | **Web UI is editor-only**; 13 of 14 PRD sections absent; backend not wired (mock adapter). | §15 | `frontend/src/App.tsx`, `api/mockAdapter.ts` | No product UX beyond editor |
| G5 | **No integrated SDLC template** automation (role DAG, fix-loop limit, candidate invalidation, auto task creation). | §14 | gates exist; no orchestrating template | No turnkey autonomous development |
| G6 | **Orchestration↔quality-gates↔runtime not integrated** (gate checks not invoked by engine; env/workspace not shared). | §7.1, §14 | separate FastAPI apps, no cross-wiring; EPIC-INT E2–E9 in progress | Subsystems are islands |
| G7 | **No auth layer** on management APIs; no SSRF guard; secret-storage not deeply audited. | §18 | all 3 FastAPI apps expose open routes | Management API exposure risk (mitigated only by "trusted admin / local mode" v1 assumption) |
| G8 | **Known green-gate defects:** frontend `make check` red (vitest collects e2e specs) — fixer card `t_c7475906`; runtime-hardening quality gate flagged (perf/lint) — fixer `t_360267d8`. | §6, AC-14 | `docs/PROJECT-SYNTHESIS.md` §3 | CI signal red for frontend |

---

## 4. Mapping to acceptance criteria (AC) — coverage

| AC | Subsystem | Status |
|---|---|---|
| AC-01 Projects | orchestration | covered (tests) |
| AC-02 Agents | agent-management | covered |
| AC-03 Workflow | frontend | covered (schema/editor) |
| AC-04 Mandatory gate | orchestration + quality-gates | covered |
| AC-05 Kanban | — | **not covered** |
| AC-06 Tools | agent-management (policy only) | **partial** (no execution) |
| AC-07 Chats | — | **not covered** |
| AC-08 Memory | — | **not covered** |
| AC-09 Cron | — | **not covered** |
| AC-10 Provider failures | agent-management/providers | partial |
| AC-11 Recovery | orchestration | covered |
| AC-12 SDLC | — | **not covered** (G1/G5) |
| AC-13 Security | runtime-hardening + quality-gates | partial |
| AC-14 `make check` | frontend | **red** (documented) |
| AC-15 Release | quality-gates | covered |

---

## 5. Risk summary

1. **§5.4/§13 absence** is the dominant risk: the product cannot yet run a real agent against a workspace or verify a delivered contract autonomously. High impact; blocks AC-06/AC-12 and demo SDLC.
2. **Subsystem isolation (G6):** three independent FastAPI apps with no shared wiring → "implemented" features are not reachable end-to-end. Medium-high impact.
3. **Open management APIs (G7):** acceptable only under the PRD v1 "trusted admin / local mode" assumption; must not be exposed publicly without auth.
4. **Frontend/nuance gates red (G8):** CI is not fully green; fixer cards already assigned.
5. **PRD "3.1–3.12" vs actual §1–§23 numbering:** confirmation needed from the task author that mapping to the real PRD chapters is acceptable (this report assumes so).

---

## 6. Recommend focus for ARCHITECT/PLANNER

1. **Design the missing agent runtime loop (§5.4) + Tool Registry (§13)** — the highest-value, currently-blocking gap. Reuse the existing provider abstraction (messages/tools/capabilities) and the runtime control-plane for execution context.
2. **Integrate the three backends** (orchestration engine invoking gates; runtime workspace shared with orchestration) — EPIC-INT E2–E9 already scopes this.
3. **Add the §19 v1-core subsystems** the PRD marks mandatory: Kanban (§8), basic project memory (§10), cron (§11), and optionally chats (§9) — at minimum persist their models, since the entity spec already exists (`docs/domain-architecture.json`).
4. **Add an auth boundary** on the management APIs (session/token) before any public exposure; keep secret storage isolated and verify via the security gate.
5. **Close the `make check` red gate** (T7-fix `t_c7475906`) so AC-14 is green and CI is trustworthy.
6. Surface an explicit decision on the "3.1–3.12" vs actual-section mapping so downstream tasks use consistent requirement IDs.

---

## 7. Evidence index (files inspected / tests run)

- Orchestration: `orchestration-server/orchestration_server/{engine,api,models,schemas,db,config,queries}.py`, `tests/*` → **28 passed**
- Agent management: `agent-management/agent_management/{api,models,tool_policy,services}.py`, `providers/{base,adapters,registry}.py`, `tests/*` → **48 passed**
- Quality gates: `quality-gates/quality_gates/{pipeline,config,evidence}.py`, `gates/*`, `tests/*` → **45 passed**
- Runtime hardening: `runtime-hardening/runtime/{container_runtime,resource_manager,workspace_manager,circuit_breaker,health,metrics,api,models}.py`, `tests/{unit,integration,chaos}/*` → **117 passed**
- Frontend: `frontend/src/{App,api,editor,workflow}/**`, `workflow.schema.json`, `package.json` (tests documented, see §0)
- Docs/spec: `docs/domain-architecture.json`, `docs/PROJECT-SYNTHESIS.md`, `README.md`, `workspace-map.md`
- PRD source: root kanban card `t_06d22d87` (extracted during this task)