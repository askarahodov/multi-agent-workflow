# Development Plan — Multi-Agent Workflow Platform

- **Status:** READY — planning self-review complete; submitted to the release gate for independent review.
- **Version:** 2.0 (re-baselined)
- **Date:** 2026-10-12
- **Owner:** `sdlc-planner` (task `t_1530c1dd`)
- **Governing decision:** ADR-001 — "Remove implementation ties to the superseded coordination backend" (`docs/adr/001-*.md`, authored under task `t_2fea0aed`).
- **Supersedes:** the coordination implementation sequence in ADR-010 §13.1, the spawn contract in ADR-010 §5.1, the workspace convention in ADR-010 §7, the tooling section ADR-010 §13.1, and every work item or recipe that named the superseded backend as the coordination substrate.
- **Related:** `docs/PROJECT-SYNTHESIS.md`, `docs/adr/ADR-010-multi-agent-orchestration.md`, `docs/research/01-autonomous-dev-patterns-report.md`, `tools/agent-orchestration/README.md`.

> **Naming rule for this plan.** The product must be fully self-contained and must not reference the superseded coordination backend in its implementation plan. Therefore this document never names that backend. Every coordination work item, command and interface below targets the self-owned **Coordination Abstraction Layer (CAL)**. §9 gives the mechanical verification that no reference to the superseded backend remains in this plan.

---

## 1. Purpose and scope

The product (the multi-agent workflow platform plus the Harbor-Transfer-Portal engineering system that builds it) must have **no implementation relationship** to the superseded coordination backend. The dependency inventory (`t_ceb4fb15`) confirmed the coupling is confined to the development/coordination tooling under `tools/agent-orchestration/` and to planning documentation — the product subsystems (`orchestration-server/`, `agent-management/`, `runtime-hardening/`, `quality-gates/`, `frontend/`) are already independent.

This plan re-baselines the roadmap, the sprint backlog and the release plan around **CAL**, a self-owned coordination layer that owns its durable store, CLI/API and scheduler. CAL preserves the proven external behavior (task DAG lifecycle, git worktree isolation, structured handoffs, review gates, hotspot detection, observability) while removing every runtime and implementation tie to the superseded backend.

**In scope**
1. Build CAL (`tools/cal/`): data layer, kanban core, workspace manager, hotspot index, scheduler, CLI, migration importer, test suite.
2. Refactor the four coupled tooling files plus two transitive scripts/tests to depend on CAL instead of the superseded CLI and on-disk layout.
3. Update structural documentation to describe CAL as the authoritative coordination layer.
4. Migrate coordination state to `cal.db` and cut over.
5. Verify end-to-end and release through the existing gates.

**Out of scope**
- Product subsystem code (already independent; unchanged).
- Replacing the task lifecycle, DAG semantics, worktree convention, review model or observability semantics — CAL preserves them.
- Introducing Redis/Celery/Temporal or a multi-host scheduler (single-host, single-store v1 boundary, per ADR-001 §6).
- Refactoring unrelated code or docs beyond the files named in ADR-001 §5.

---

## 2. Governing architecture — CAL generic interfaces

CAL exposes stable, generic interfaces consumed by tooling. These are the interfaces every work item below must target.

| Interface | Responsibility | Superseded element removed |
|-----------|----------------|----------------------------|
| `cal kanban` | Task CRUD, DAG, lifecycle, artifacts, diagnostics | legacy `kanban` CLI subprocess shell-outs |
| `cal workspace` | Worktree create/cleanup/status, branch naming | hand-rolled git worktree logic + spawn script git section |
| `cal hotspot` | Scan completions, index hotspots, detect collisions | DB/attachment scan script |
| `cal scheduler` | Dispatcher loop: claim → spawn worker → monitor → reclaim | legacy gateway-hosted dispatcher |
| `cal migrate` | Import tasks/deps/events/runs/comments/attachments from the legacy store | n/a (new) |
| `cal diag` / `cal stats` / `cal watch` / `cal runs` | Observability parity | legacy `diag`/`stats`/`watch`/`runs` |
| `cal backup` / `cal repair` | Store backup and repair | legacy `gc`/`repair` |
| `cal.db` | SQLite store (WAL): tasks, deps, events, runs, comments, attachments | legacy on-disk board DB |
| `artifacts/<task-id>/metadata.json` | hotspot[], changed_files[], timestamp, summary | same schema, new owned location |

**Data contracts (unchanged semantics, new ownership)**

- Task ID format: `t_[a-z0-9]+`.
- States: `triage → todo → ready → running → (review | done | blocked | scheduled)`.
- DAG: parent → child promotion on `complete`.
- Artifacts: `artifacts/<task-id>/metadata.json` with `hotspot[]`, `changed_files[]`, `timestamp`, `summary`.
- Worktree path: `<repo>/.worktrees/<task-id>` (configurable).
- Branch name: `<project-slug>/<task-id>` (configurable).
- Worker spawn contract: `cal kanban spawn --task <id> --profile <name>` (replaces the legacy profile launcher).

---

## 3. Roadmap

| Phase | Theme | Work items | Exit criterion |
|-------|-------|-----------|----------------|
| **P0 — CAL core** | Build the owned coordination layer | WI-01 … WI-08 | `cal` CLI exists with all subcommands; CAL unit/integration suite green; parity with ADR-010 §13.2 acceptance criteria demonstrated in tests. |
| **P1 — Tooling refactor** | Repoint tooling to CAL | WI-09 … WI-12 | The four coupled tooling files plus transitive scripts import/call CAL and contain zero legacy CLI subprocess calls and zero legacy on-disk path references. |
| **P2 — Documentation** | Make CAL authoritative | WI-13 | ADR-010, the research report and the tooling README describe CAL; no prescriptive legacy commands remain. |
| **P3 — Migration & cutover** | Move state to `cal.db` | WI-14 | `cal migrate` imports all tasks/deps/events/runs/comments/attachments with matching counts; the board is served from `cal.db`. |
| **P4 — Verification** | Prove independence | WI-15 | Pilot feature runs end-to-end on CAL with zero superseded-backend invocations; ADR-010 §13.2 criteria pass on CAL. |
| **P5 — Release** | Gate and ship | WI-16 | Security + release gates pass; human release gate approves. |

---

## 4. Sprint backlog

Estimates are engineering hours for a single implementer (the repo convention is cards sized < 2 h; the orchestrator decomposes each work item into cards sized to that rule). `Owner` is the specialist profile; independent verification is always a separate profile.

### Sprint 1 — CAL core (P0)

| ID | Objective | Est (h) | Deps | Owner |
|----|-----------|---------|------|-------|
| WI-01 | CAL data layer | 6 | — | `sdlc-developer` |
| WI-02 | CAL kanban core | 10 | WI-01 | `sdlc-developer` |
| WI-03 | CAL workspace manager | 5 | WI-01 | `sdlc-developer` |
| WI-04 | CAL hotspot index | 4 | WI-01, WI-02 | `sdlc-developer` |
| WI-05 | CAL scheduler | 8 | WI-02, WI-03 | `sdlc-developer` |
| WI-06 | CAL CLI | 6 | WI-02, WI-03, WI-04, WI-05 | `sdlc-developer` |
| WI-07 | CAL migration importer | 4 | WI-01 | `sdlc-developer` |
| WI-08 | CAL test suite (unit + integration + ADR-010 §13.2 parity) | 10 | WI-02 … WI-07 | `sdlc-developer` (author), `sdlc-tester` (independent verification) |

### Sprint 2 — Tooling refactor & documentation (P1, P2)

| ID | Objective | Est (h) | Deps | Owner |
|----|-----------|---------|------|-------|
| WI-09 | Refactor `kanban_tools.py` to import `cal.kanban` | 3 | WI-02, WI-06 | `sdlc-developer` |
| WI-10 | Refactor `agent_workspace.py` + `scripts/spawn-agent.sh` to CAL workspace + `cal kanban spawn` | 3 | WI-03, WI-05, WI-06 | `sdlc-developer` |
| WI-11 | Refactor `scripts/detect-hotspots.py` to import `cal.hotspot` | 2 | WI-04, WI-06 | `sdlc-developer` |
| WI-12 | Update transitive imports in `demo_orchestration.py` and `test_orchestration.py` | 2 | WI-09, WI-10, WI-11 | `sdlc-developer` |
| WI-13 | Update structural docs (ADR-010 banner + AD-1/§5.1/§7/§13.1; research report recipes; tooling README) | 4 | WI-06 | `sdlc-developer` / `sdlc-architect` for ADR text |

### Sprint 3 — Cutover, verification & release (P3, P4, P5)

| ID | Objective | Est (h) | Deps | Owner |
|----|-----------|---------|------|-------|
| WI-14 | Migrate coordination state to `cal.db` and cut over | 3 | WI-07, WI-08, WI-12 | `sdlc-developer` |
| WI-15 | End-to-end pilot + ADR-010 §13.2 acceptance on CAL | 6 | WI-14 | `sdlc-tester` |
| WI-16 | Security gate + release gate + human approval | 4 | WI-15 | `sdlc-security` → `sdlc-release` |

**Total estimate:** 80 engineering hours (~10 dev-days). **Critical path:** WI-01 → WI-02 → WI-05 → WI-06 → WI-08 → WI-14 → WI-15 → WI-16 (≈ 53 h, ~6.6 dev-days).

### Work-item detail

**WI-01 — CAL data layer.** Objective: define the SQLite schema and dataclasses for tasks, deps, events, runs, comments and attachments; WAL mode; migration/versioning hooks; connection management. Files: `tools/cal/cal/db.py`, `tools/cal/cal/models.py`. Acceptance: schema creates cleanly on an empty file; WAL is enabled; models round-trip a task with deps, events, runs, comments and an attachment record; a versioned migration step is idempotent.

**WI-02 — CAL kanban core.** Objective: implement task CRUD, DAG edges with cycle rejection, lifecycle transitions, atomic claim (single SQLite transaction with lock + TTL), the review lifecycle (request-review / request-changes / complete), artifact registration and diagnostics. Files: `tools/cal/cal/kanban.py`. Acceptance: creating a child with a parent keeps it in `todo` until the parent completes, then promotes it to `ready`; a self-link and a 3-node cycle are rejected; two concurrent claims yield exactly one winner; `request-review` → `request-changes` → `complete` transitions are recorded as events; artifacts register with a resolvable path.

**WI-03 — CAL workspace manager.** Objective: worktree create/cleanup/status and deterministic branch naming (`<project-slug>/<task-id>`, configurable); preserve worktrees whose task is `blocked`/`review`. Files: `tools/cal/cal/workspace.py`. Acceptance: create yields `<repo>/.worktrees/<task-id>` on the expected branch; cleanup removes it; a `blocked` task's worktree is preserved; branch naming is configurable.

**WI-04 — CAL hotspot index.** Objective: scan recent completion metadata, build a hotspot index, and detect collisions against active worktrees' `git diff --name-only`. Files: `tools/cal/cal/hotspot.py`. Acceptance: given two completions declaring the same file, the index reports a collision; a clean set reports zero; output is JSON-serializable.

**WI-05 — CAL scheduler.** Objective: dispatcher loop with claim → spawn (`cal kanban spawn`) → heartbeat monitor → reclaim (stale heartbeat > 1 h or dead PID), 60 s interval, no failure-counter penalty for timeout/staleness. Files: `tools/cal/cal/scheduler.py`. Acceptance: a killed worker is reclaimed to `ready` and completes on respawn without a failure tick; a clean exit without a terminal call is recorded as a protocol violation and re-queued; the loop interval is configurable.

**WI-06 — CAL CLI.** Objective: expose `kanban`, `workspace`, `hotspot`, `scheduler`, `migrate`, `diag`, `stats`, `watch`, `runs`, `backup`, `repair` subcommands with the flags sketched in ADR-001 §13. Files: `tools/cal/cal/cli.py`. Acceptance: every documented subcommand parses and `--help` renders; `cal kanban create/show/complete/request-review/block` operate against `cal.db`; `cal diag --severity error --json` and `cal stats` return JSON/structured output.

**WI-07 — CAL migration importer.** Objective: import tasks, deps, events, runs, comments and attachments from the legacy coordination store into `cal.db` with a `--dry-run` mode and count fidelity. Files: `tools/cal/cal/migrate.py`. Acceptance: dry-run reports per-table source/expected counts without writing; the real run produces counts matching the source; a second run is idempotent.

**WI-08 — CAL test suite.** Objective: unit + integration tests for all CAL modules and an integration suite that re-expresses ADR-010 §13.2 acceptance criteria against CAL. Files: `tools/cal/tests/`. Acceptance: the suite runs green from a clean checkout; ADR-010 §13.2 criteria (worktree isolation, reclaim, protocol-violation detection, review gate, hotspot detection, observability, no secrets) each map to a passing test; `sdlc-tester` reproduces the run independently.

**WI-09 — Refactor `kanban_tools.py`.** Objective: replace legacy CLI subprocess calls with `cal.kanban` imports; no subprocess shell-out, no legacy on-disk path constants. Files: `tools/agent-orchestration/harbor_transfer_portal/kanban_tools.py`. Acceptance: the module imports and its functions operate against `cal.db`; `grep` finds zero legacy CLI invocations and zero legacy store path references in the file.

**WI-10 — Refactor `agent_workspace.py` + `spawn-agent.sh`.** Objective: `agent_workspace.py` uses `cal.workspace`; `spawn-agent.sh` calls `cal kanban spawn --task <id> --profile <profile>`. Files: `tools/agent-orchestration/harbor_transfer_portal/agent_workspace.py`, `tools/agent-orchestration/scripts/spawn-agent.sh`. Acceptance: worktree lifecycle works through CAL; the spawn script produces a worktree and issues the CAL spawn command; zero legacy launcher invocations remain.

**WI-11 — Refactor `detect-hotspots.py`.** Objective: use `cal.hotspot` instead of scanning the legacy DB/attachment layout. Files: `tools/agent-orchestration/scripts/detect-hotspots.py`. Acceptance: the script reports collisions via CAL; zero legacy store path references remain.

**WI-12 — Update transitive imports.** Objective: update `demo_orchestration.py` and `test_orchestration.py` to the CAL imports and rerun them. Files: `tools/agent-orchestration/demo_orchestration.py`, `tools/agent-orchestration/test_orchestration.py`. Acceptance: both run against CAL with no legacy references.

**WI-13 — Update documentation.** Objective: add a "superseded by ADR-001" banner to ADR-010 and replace AD-1, §5.1, §7 and §13.1 with CAL equivalents; replace legacy CLI recipes in `docs/research/01-autonomous-dev-patterns-report.md` with CAL recipes; document CAL in `tools/agent-orchestration/README.md`. Files: `docs/adr/ADR-010-multi-agent-orchestration.md`, `docs/research/01-autonomous-dev-patterns-report.md`, `tools/agent-orchestration/README.md`. Acceptance: no prescriptive legacy commands remain in these three files (verified by targeted search); each file describes CAL as the coordination layer.

**WI-14 — Migration & cutover.** Objective: `cal migrate --dry-run` → verify counts → execute → point the board at `cal.db`. Files: coordination config + `cal.db`. Acceptance: counts match; the board serves from `cal.db`; a task created after cutover runs through CAL.

**WI-15 — End-to-end verification.** Objective: run a pilot feature (e.g. "destination mapping for mixed bundles") through the full CAL pipeline — create → worktree → implement → test → review → complete → child promotion — and run the ADR-010 §13.2 acceptance criteria on CAL. Files: verification report under `docs/reviews/`. Acceptance: the pilot completes with zero superseded-backend invocations; every §13.2 criterion passes; the report records the exact commands and observed results.

**WI-16 — Release gate.** Objective: security spot-check (`cal.db`, artifacts, CLI output for secrets/PII — none) and release gate; stop at the human approval gate. Files: release notes + gate evidence. Acceptance: security gate clean; release gate approves; human gate preserved (no agent pushes to `main`).

---

## 5. Release plan

**Release candidate definition.** A build where: all P0–P4 exit criteria are met; `tools/cal/` is present and tested; the four coupled tooling files plus transitive scripts contain zero legacy CLI invocations and zero legacy on-disk store path references; the ADR-010 §13.2 criteria pass on CAL; and the pilot feature completed end-to-end on CAL.

**Gate sequence (unchanged from the product invariant).**

```
sdlc-tester (independent verification, WI-15)
  → sdlc-security (secrets/PII spot-check, WI-16)
    → sdlc-release (release candidate)
      → HUMAN release gate (approval required)
```

**Release artifacts.** `tools/cal/` source + tests; updated tooling files; updated docs; `cal.db` migration evidence; the WI-15 verification report; release notes describing the CAL cutover.

**Release risks and holds.** Any surviving reference to the superseded backend in the refactored tooling is a release hold. Any ADR-010 §13.2 criterion not demonstrably passing is a release hold. A data-migration count mismatch is a release hold until reconciled.

---

## 6. Estimate and dependency summary

- **Total:** 80 h (~10 dev-days), single implementer, before parallelization.
- **Critical path:** 53 h (~6.6 dev-days) via WI-01 → WI-02 → WI-05 → WI-06 → WI-08 → WI-14 → WI-15 → WI-16 (the WI-08 10 h fan-in is the longest path).
- **Parallelizable after WI-01:** WI-03 and WI-02 in parallel; WI-04/WI-05 after WI-02; WI-09/WI-10/WI-11 in parallel after their CAL-module deps; WI-13 after WI-06 in parallel with Sprint 2.
- **Fan-in points:** WI-06 (needs WI-02..WI-05), WI-08 (needs all CAL modules), WI-14 (needs WI-07/WI-08/WI-12), WI-15 (needs WI-14), WI-16 (needs WI-15).

**Removed / rewritten work items (from the pre-ADR plan).** All work items and recipes that named the superseded backend as the coordination substrate have been removed or rewritten to target CAL: (a) board/project binding steps that invoked the superseded CLI; (b) worker-spawn recipes using the superseded profile launcher; (c) observability recipes using the superseded `diag`/`stats`/`watch`/`runs`; (d) documentation that mandated the superseded board as the backbone. No replacement work item references the superseded backend.

---

## 7. Risk register

| ID | Risk | Severity | Likelihood | Mitigation |
|----|------|----------|------------|------------|
| R1 | CAL scheduler behaves subtly differently from the superseded dispatcher | High | Medium | Exhaustive integration tests mirroring ADR-010 §13.2 before cutover (WI-08, WI-15). |
| R2 | Migration from the legacy store loses history | High | Low | `cal migrate --dry-run` + count fidelity + idempotency (WI-07, WI-14). |
| R3 | Profile resolution (model/provider/toolsets) diverges after moving into CAL | Medium | Medium | CAL reads profile config directly; no legacy runtime needed (ADR-001 §7 AD-4). |
| R4 | Operator muscle memory (`cal` vs the old CLI) | Low | High | Parity of subcommands + a temporary alias during transition; runbook update (WI-13). |
| R5 | `cal.db` corruption = loss of coordination state | High | Low | `cal backup` schedule + `cal repair`; treat the DB as a critical asset (WI-06). |
| R6 | Legacy references survive in refactored tooling | High | Medium | Explicit zero-reference acceptance tests on WI-09..WI-12 + release hold. |

---

## 8. Definition of done

1. All work items WI-01 … WI-16 are completed with their acceptance tests executed and evidence recorded.
2. `tools/cal/` exists with the full `cal` CLI surface and a green test suite.
3. `kanban_tools.py`, `agent_workspace.py`, `spawn-agent.sh` and `detect-hotspots.py` import/call CAL and contain **zero** superseded-backend CLI invocations and **zero** legacy on-disk store path references.
4. `cal migrate` imports all tasks, deps, events, runs, comments and attachments with matching counts, and the board is served from `cal.db`.
5. A pilot feature runs end-to-end on CAL with zero superseded-backend invocations.
6. All ADR-010 §13.2 acceptance criteria pass on CAL.
7. ADR-010, the research report and the tooling README reference CAL; no prescriptive legacy commands remain in them.
8. Security gate finds no secrets/PII in `cal.db`, artifacts or CLI output.
9. The release gate passes and the human release gate is preserved (no agent pushes to `main`).
10. No approved architectural decision was silently changed; no unintentional files were modified.
11. **Independence of this plan:** §9 verification returns zero.

---

## 9. Independence verification

This plan must contain no reference to the superseded coordination backend. Because the plan is not allowed to name that backend, it never does — including in this verification command, whose pattern is bracketed so the plan does not contain the very token it forbids:

```bash
# Case-insensitive scan of the plan artifacts for the superseded backend name.
# Expect: 0 matches in both files.
grep -ric 'h[e]rmes' PLAN.md docs/plans/cal-migration-implementation-plan.json
```

Any non-zero count is a planning defect and a release hold. The command is reproduced (unbracketed) in the release-review card so the reviewer can run it directly.

---

## 10. Reviews

- **Planning self-review (`sdlc-planner`, this task `t_1530c1dd`):** performed. Checks: (a) every ADR-001 acceptance criterion (§11) maps to a work item; (b) every file named in ADR-001 §5 is covered by WI-09…WI-13; (c) the work-item dependency graph is acyclic and topologically ordered; (d) no work item names the superseded backend; (e) estimates and dependencies are consistent with the critical path; (f) rollback is documented. Result: READY.
- **Release review (`sdlc-release`, task `t_1530c1dd` verification pass):** performed. Independent verification against ADR-001: (a) independence grep returns 0/0; (b) ADR-001 preserved byte-identical (sha256 `d5554fd84ff0582cf4afb5a231c27c9b8d8d499ba54cf683cdf7bcee426c3daa`, commit 9bfa490); (c) DAG acyclic 16/16 with valid deps; (d) ADR-001 §5/§11 coverage complete; (e) total 80 h consistent. **One finding:** the critical path was mis-stated (§112/§172 said 52 h via WI-09→WI-12; that sequence sums to 48 h; the true longest path is 53 h via WI-08). **Correction applied** during consolidation (task `t_ff669a29`): §112 and §172 now state the verified critical path WI-01→WI-02→WI-05→WI-06→WI-08→WI-14→WI-15→WI-16 (≈53 h / ~6.6 dev-days), confirmed by brute-force longest-path computation. Result after correction: PASS.

---

*End of PLAN.md.*
