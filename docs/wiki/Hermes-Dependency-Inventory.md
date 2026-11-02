# Hermes Dependency Inventory

- **Status:** Completed (research) — pending `sdlc-architect` review.
- **Author:** `sdlc-researcher` (task `t_ceb4fb15`).
- **Scope:** Every place the product relies on Hermes-specific libraries, CLIs, APIs, file-system layouts, or implementation details.
- **Grounding:** live inspection of commit `eba4685` (`wt/t_ceb4fb15`). Every path below was observed; the `grep` evidence for each file is shown.
- **Purpose:** input to ADR `docs/adr/001-hermes-independence.md` (removal of direct Hermes ties) and the self-sufficiency requirement: the product must have no implementation relationship to Hermes.

## 1. Headline finding

The **product subsystems are already Hermes-independent.** Content search for `[Hh]ermes` across the repo matched **no** implementation files in `services/orchestration-server/`, `services/agent-management/`, `services/runtime-hardening/`, `services/quality-gates/`, or `apps/frontend/`. (The only `runtime-hardening` hit is `reports/coverage.xml`, a generated coverage report whose XML `source` path happens to contain `~/.hermes/kanban/.../workspaces/<task>` — an incidental prior-run artifact, not a code dependency.)

All Hermes dependence lives in (a) the **development/coordination tooling** under `tools/agent-orchestration/` and (b) **planning/architecture documentation** that mandates Hermes as the coordination backbone (ADR-010, research report). Removing implementation ties therefore means neutralizing `tools/agent-orchestration/` and reworking the docs that hard-code Hermes behavior.

## 2. Inventory table

| # | File | Hermes dependency | Kind | Evidence (grep) |
|---|------|-------------------|------|-----------------|
| 1 | `tools/agent-orchestration/agent_orchestration/kanban_tools.py` | Shells out to `hermes kanban create/attach/show/list/promote ...` via `subprocess.run`; hard-codes board `me`, db path `~/.hermes/kanban/boards/me/`, project/tenant `multi-agent-workflow`; parses Hermes CLI JSON/text output incl. `t_<id>` regex | CLI/DB layout + output contract | `hermes`, `KANBAN_BOARD_PATH`, `KANBAN_DB_PATH`, `["hermes","kanban",...]` |
| 2 | `tools/agent-orchestration/agent_orchestration/agent_workspace.py` | Reads `~/.hermes/kanban/boards/me/kanban.db`; hard-codes `PROJECT_ROOT=/mnt/data/multi-agent-workflow` and per-task worktree/branch convention `multi-agent-workflow/<task_id>`; task ids assume Hermes `t_<id>` | DB path + project/worktree convention | `KANBAN_DB_PATH`, `Path.home()/".hermes"/"kanban"`, `PROJECT_ROOT` |
| 3 | `tools/agent-orchestration/scripts/spawn-agent.sh` | Directly invokes `hermes -p <profile> --cli --accept-hooks chat -q "work kanban task <task-id>"`; uses Hermes CLI flags; hard-codes Multi-Agent Workflow Platform paths `/mnt/data/multi-agent-workflow` | Hermes CLI spawn contract | `hermes -p`, `work kanban task`, `PROJECT_ROOT` |
| 4 | `tools/agent-orchestration/scripts/detect-hotspots.py` | Reads Hermes board DB + `attachments/*/metadata.json` under `~/.hermes/kanban/boards/me/`; depends on Hermes `metadata.hotspot`/`changed_files`/`timestamp` schema | DB + attachment/metadata schema | `KANBAN_DB_PATH`, `attachments`, `metadata`, `hotspot` |
| 5 | `tools/agent-orchestration/demo_orchestration.py` | Validates/imports the Hermes-dependent modules (1–4) | (transitive) | `from ... import agent_workspace, kanban_tools`, `spawn-agent.sh` |
| 6 | `tools/agent-orchestration/test_orchestration.py` | `import s: agent_workspace, kanban_tools; test_orchestration` — imports and exercises Hermes-coupled functions | (transitive) | `from agent_workspace import ...`, `from kanban_tools import ...` |
| 7 | `tools/agent-orchestration/README.md` | Documents the Hermes Kanban workflow as the orchestration approach; de-facto design doc for the coupling | Documentation | `Hermes Kanban CLI`, `hermes kanban`, board `me` |
| 8 | `docs/adr/ADR-010-multi-agent-orchestration.md` | **Architectural dependency.** AD-1 <q>Kanban-as-backbone</q> mandates `kanban.db` (SQLite, WAL) as the *single durable store*; prescribes `kanban_*` tool calls, the gateway-hosted dispatcher, `~/.hermes/config.yaml` `kanban:` block, `<repo>/.worktrees/<task-id>` with branch `<project-slug>/<task-id>`, `HERMES_KANBAN_*` env semantics, 19-profile fleet oriented on `~/.hermes/profiles/`, MCP servers (`mcp-hermes`, `mcp-tmux`) | Architecture / configuration contract | `AD-1`, `kanban.db`, `hermes kanban`, `~/.hermes/`, `hermes project` |
| 9 | `docs/research/01-autonomous-dev-patterns-report.md` | Research design is anchored on Hermes Kanban; reproduces Hermes CLI recipes (`hermes kanban init/create/watch`, `hermes profile create`, `hermes gateway start`, `hermes dashboard`); cites Hermes docs/skill as the reference | Documentation (prescriptive recipes) | `hermes kanban`, `hermes profile create`, `hermes gateway start`, `hermes-agent.skill` |
| 10 | `docs/reviews/p8.3-runtime-hardening-verification.md`, `docs/reviews/p8.3-runtime-hardening-review.md`, `services/runtime-hardening/reports/coverage.xml` | Reference prior run workspace paths `~/.hermes/kanban/boards/me/workspaces/<task>` | Incidental path artifacts (NOT implementation deps) | `~/.hermes/kanban/boards/me/workspaces/` |

## 3. Hermes-specific libraries / APIs / configuration items

No third-party Hermes **Python/library** import exists anywhere (no `import hermes...`). The coupling is entirely to the **Hermes CLI** (`hermes kanban ...`, `hermes -p <profile> chat ...`, `hermes project ...`) and to the **on-disk board layout/schema**. Concretely:

- CLI surface consumed: `hermes kanban {create, attach, show, list, promote}` (tooling) and `{init, swarm, watch, diag, stats, reclaim, reassign, set-model, unblock, notify-subscribe, project …}` (docs/runbooks).
- On-disk contract: board db `~/.hermes/kanban/boards/me/kanban.db` (SQLite: `tasks`, `deps`, `events`, `runs`, `comments`, `attachments`); attachments `attachments/<task>/metadata.json` with `hotspot`/`changed_files`/`timestamp` fields.
- Task/DAG contract: id format `t_[a-z0-9]+`; parent–child promotion; states `triage/todo/ready/running/review/done/blocked/scheduled`.
- Workspace contract: `<repo>/.worktrees/<task-id>`; branch `<project-slug>/<task-id>`; `workspace_kind=worktree|scratch|dir`.
- Runtime contract: worker spawn command `hermes -p <profile> --cli --accept-hooks chat -q "work kanban task <id>"`; env `HERMES_KANBAN_TASK` / `HERMES_KANBAN_WORKSPACE` / `HERMES_KANBAN_BRANCH`; mandatory terminal call (`complete`/`request_review`/`block`).
- Profile/config: `~/.hermes/profiles/<name>/{config.yaml,profile.yaml,SOUL.md}`; `~/.hermes/config.yaml` `kanban:` block; board `me`, project `multi-agent-workflow`.
- MCP servers implied: `filesystem`, `github`, `mcp-hermes`, `mcp-tmux`.

## 4. Functions constituting Hermes dependencies

- `kanban_tools.py`: `create_child_tasks`, `attach_artifacts`, `get_task_graph`, `promote_to_ready`, `create_task_with_parents`, `get_kanaban_task_info`.
- `agent_workspace.py`: `create_worktree`, `cleanup_worktree`, `get_agent_status`, `scan_overlapping_modifications`, `get_all_worktrees`, `cleanup_all_worktrees` (task-id/branch naming tied to Hermes; `KANBAN_DB_PATH`).
- `scripts/spawn-agent.sh`: the `hermes -p … chat -q "work kanban task …"` spawn line (line 77).
- `scripts/detect-hotspots.py`: kanban db / attachments / metadata readers.

## 5. Configuration items constituting Hermes dependencies

| Item | Value observed | Where mandated |
|------|----------------|----------------|
| Board | `me` | `kanban_tools.py`, `detect-hotspots.py`, ADR-010 |
| Project / tenant | `multi-agent-workflow` | `kanban_tools.py`, ADR-010 |
| Board DB path | `~/.hermes/kanban/boards/me/kanban.db` | `kanban_tools.py`, `detect-hotspots.py`, `agent_workspace.py` |
| Workspace dir | `<repo>/.worktrees/<task-id>` | ADR-010 §7 |
| Branch scheme | `<project-slug>/<task-id>` | ADR-010 §7 |
| Worker spawn | `hermes -p <profile> chat -q "work kanban task <id>"` | `spawn-agent.sh`, ADR-010 §5.1 |
| Kanban config | `~/.hermes/config.yaml` `kanban:` | ADR-010 §2 |

## 6. Dependency severity classification

| Severity | Meaning | Files |
|----------|---------|-------|
| **Hard (implemented coupling)** | code shells out to / reads Hermes CLI+DB | `kanban_tools.py`, `agent_workspace.py`, `spawn-agent.sh`, `detect-hotspots.py` (+ `demo_`, `test_`) |
| **Structural (architecture mandate)** | design prescribes Hermes as backbone | `docs/adr/ADR-010-multi-agent-orchestration.md` |
| **Prescriptive (docs/recipes)** | docs/runbooks reproduce Hermes commands | `docs/research/01-autonomous-dev-patterns-report.md`, `tools/agent-orchestration/README.md` |
| **Incidental** (no implementation tie) | prior-run workspace path strings | `docs/reviews/*.md`, `services/runtime-hardening/reports/coverage.xml` |

## 7. Evidence commands

- `search_files(pattern='[Hh]ermes', target='content', output_mode='files_only')` on repo root → 12 files (all listed above; product subsystems absent).
- `search_files(pattern='hermes', target='files')` on repo root → 0 files with `hermes` in the name.
- `grep -rn hermes docs/reviews/*.md services/runtime-hardening/reports/coverage.xml` → only `~/.hermes/kanban/boards/me/workspaces/<task>` path strings (incidental).
- `find tools -type f` + `read_file` of each `tools/agent-orchestration` member → confirmed CLI/DB coupling details above.

## 8. Notes for the architect (inputs to ADR-001)

- Removal surface is bounded and small: 4 tooling files + 2 supporting scripts/tests + 3 doc files.
- Backfill needed where docs hard-code Hermes: board-as-source-of-truth (ADR-010 AD-1) must be replaced by a generic coordination-abstraction or a self-owned store; DO NOT just delete — the behavior (task DAG, lifecycle, review, observability) is a requirement we re-host.
- Product code requires no change.
- `tools/agent-orchestration/` is paired with ADR-010's orchestration tooling deliverable (`t_25e65cca`); removing it may make that ADR partially obsolete — architect should reconcile.