# Repository layout and concurrent-agent migration contract (#182)

## Current layout and ownership

| Scope | Purpose | Migration risk |
| --- | --- | --- |
| `orchestration-server/` | Durable workflow orchestration; public Python package `orchestration_server` | Dockerfile COPY, import paths, SQLite and CI tests |
| `agent-management/` | Agents, OpenRouter adapter, trusted gateway; `agent_management` | Provider credentials, gateway image and E2E |
| `runtime-hardening/` | Local Docker runtime and security policies | Privileged dev Compose mounts; do not silently widen privileges |
| `quality-gates/` | QA service, controller, evidence and release checks | Signed receipt / TLS secrets / isolated test execution |
| `frontend/` | React UI, Vite, Playwright | Node paths, bind mounts, browser acceptance |
| `shared/` | First-party Python package | Install order and import compatibility |
| `tools/` | Development-only agent tooling | Historical Hermes scripts must stay outside runtime images |
| `tests/`, `scripts/` | Cross-service integration tests and local tooling | CI workflows, cwd assumptions, subprocess paths |
| `docs/` | Design decisions, runbooks and acceptance | Historical evidence links must remain discoverable |
| root `compose.*.yml` | Protected overlays, separate from unsafe local dev Compose | `-f` order, relative bind paths and `build.context` |
| root `*-REPORT-*.md` and standalone probes | Historical reports and inspection utilities | External links and historical evidence |

## Proposed end state (not yet migrated)

```text
apps/frontend/
services/{orchestration-server,agent-management,runtime-hardening,quality-gates}/
packages/shared/
deploy/compose/{dev,secure}/
scripts/
tests/
docs/
reports/archive/
tools/dev-only/
```

Preserve Python *import names*, public REST endpoints, state file formats and secrets behavior.
Keep one discoverable root `Makefile` and `README.md`. Consolidate Compose via explicit
entrypoints; avoid relying on Docker's implicit overlay discovery. Docker Compose relative
paths ordinarily resolve against the first `-f` file; relocating files without fixing
`--project-directory` / `build.context` / bind mounts will break deploys.

## Concurrent agents: mandatory work ownership

1. Before each move, list current GitHub PRs and `wt/t_*` branches, and compare
   branch files against paths to be moved. **Treat active branches and worktrees as owned
   by their local agents**; never delete, rebase, force-push or commit into them.
2. Do not bulk-move live service directories while another agent edits them.
   Coordinate an exclusive migration window; stop at a conflict rather than
   overwrite someone else's work.
3. Use a dedicated `refactor/issue-182-*` PR, based on the latest `main`, and
   stage atomic path updates for all Dockerfile, Compose, CI, tests, pyproject,
   scripts and runbooks in the **same** migration.
4. Archive historical reports instead of deleting evidence. Five legacy `*-REPORT-*.md` files are now under `reports/archive/` with their original blob content and an index. Preserve `coord/external-qa`
   as its own channel; never merge it into product `main`.
5. Gate every migration with local + GitHub CI, clean Compose dev and secure
   merged configuration, offline E2E and frontend build/browser acceptance.
6. **Do not close #182** until actual files are relocated, all references work and
   the full acceptance matrix has evidence. This file is only the prerequisite
   contract for the coordinated full migration.

## Current operational entrypoints (until migration)

- Local trusted host development: `docker compose -f docker-compose.yml config --quiet`.
- Protected native + QA composition: `python3 scripts/check_native_qa_compose.py --live-sdlc`
  with explicit QA test command; do **not** combine with `docker-compose.yml`.
- Local CI analogue: `make check`.
- UI: `http://127.0.0.1:5173` when local dev Compose is started.

The default dev Compose has `AUTH_ENABLED=false` and Docker daemon access in
`runtime-hardening`; it is not production sandboxing. Offline native E2E does not
prove a live OpenRouter call or the completion criteria of #11.
