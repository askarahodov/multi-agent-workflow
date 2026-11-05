# Repository layout and concurrent-agent migration contract (#182)

## Current layout and ownership

| Scope | Purpose | Migration risk |
| --- | --- | --- |
| `services/orchestration-server/` | Durable workflow orchestration; public Python package `orchestration_server` | Dockerfile COPY, import paths, SQLite and CI tests |
| `services/agent-management/` | Agents, OpenRouter adapter, trusted gateway; `agent_management` | Provider credentials, gateway image and E2E |
| `services/runtime-hardening/` | Local Docker runtime and security policies | Privileged dev Compose mounts; do not silently widen privileges |
| `services/quality-gates/` | QA service, controller, evidence and release checks | Signed receipt / TLS secrets / isolated test execution |
| `apps/frontend/` | React UI, Vite, Playwright | Node paths, bind mounts, browser acceptance |
| `packages/shared/` | First-party Python package | Install order and import compatibility |
| `tools/` | Development-only agent tooling | Historical Hermes scripts must stay outside runtime images |
| `tests/`, `scripts/` | Cross-service integration tests and local tooling | CI workflows, cwd assumptions, subprocess paths |
| `docs/` | Design decisions, runbooks and acceptance | Historical evidence links must remain discoverable |
| `reports/archive/` | Historical reports and inspection utilities | External links and historical evidence |
| root `Makefile` | Primary entrypoint for local CI and dev operations | Must stay discoverable at root |
| root `README.md` | Main entry point | Must stay at root |
| root `compose.override.yml` | Local dev Compose override (git-ignored) | Local override, not for CI |

## Current operational entrypoints

- Local trusted host development: `docker compose --project-directory . -f deploy/compose/dev/docker-compose.yml config --quiet`.
- Protected native + QA composition: `python3 scripts/check_native_qa_compose.py --live-sdlc`
  with explicit QA test command; do **not** combine with `deploy/compose/dev/docker-compose.yml`.
- Local CI analogue: `make check`.
- UI: `http://127.0.0.1:5173` when local dev Compose is started.

The default dev Compose has `AUTH_ENABLED=false` and Docker daemon access in
`runtime-hardening`; it is not production sandboxing. Offline native E2E does not
prove a live OpenRouter call or the completion criteria of #11.

## Completed migration (issue #257 — partial)

| File | Old location | New location | Status |
|------|--------------|--------------|--------|
| `SECURITY_AUDIT.md` | root | `docs/SECURITY_AUDIT.md` | ✅ Done |
| `SYSTEM_INFO_RU.md` | root | `docs/SYSTEM_INFO_RU.md` | ✅ Done |
| `ROLLOUT_PLAN.md` | root | `reports/archive/ROLLOUT_PLAN.md` | ✅ Done |
| `ROLLOUT_PLAN_APPROVALS.md` | root | `reports/archive/ROLLOUT_PLAN_APPROVALS.md` | ✅ Done |
| `ROLLOUT_EXECUTIVE_SUMMARY.md` | root | `reports/archive/ROLLOUT_EXECUTIVE_SUMMARY.md` | ✅ Done |
| `security-gate-output.json` | root | `reports/archive/security-gate-output.json` | ✅ Done |
| `workspace-map.md` | root | `reports/archive/workspace-map.md` | ✅ Done |
| `scan_secrets.py` | root | `scripts/scan_secrets.py` | ✅ Done |
| `verify_final.py` | root | `scripts/verify_final.py` | ✅ Done |
| `test_hsts_middleware.py` | root | `tests/test_hsts_middleware.py` | ✅ Done |
| `test_tls_config.py` | root | `tests/test_tls_config.py` | ✅ Done |

## Remaining work for issue #257 (not yet migrated)

| Area | Scope |
|------|-------|
| `docs/architecture/REPOSITORY-STRUCTURE.md` | Update this document to reflect actual state; remove "not yet migrated" |
| `docs/SYSTEM_INFO_RU.md` | Fix structure references and stale links |
| `reports/archive/README.md` | Add index entries for newly archived files |
| Frontend consolidation | De-duplicate `apps/frontend/src/pages/` vs `apps/frontend/src/mvp/sections/` |
| API/state unification | Unify API client and state management |
| Test consolidation | Wire `tests/test_hsts_middleware.py` and `test_tls_config.py` into CI |
| Root consolidation | Decide fate of `PLAN.md`, `package.json`, `package-lock.json` at root |
| Ownership boundaries | Explicit ownership map + automated layout checks |
| Root cruft cleanup | Remove untracked `agent-management/`, `frontend/`, `orchestration-server/`, `quality-gates/`, `runtime-hardening/`, `shared/` build artifacts |

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
3. Use a dedicated `refactor/issue-257-*` PR, based on the latest `main`, and
   stage atomic path updates for all Dockerfile, Compose, CI, tests, pyproject,
   scripts and runbooks in the **same** migration.
4. Archive historical reports instead of deleting evidence. Five legacy `*-REPORT-*.md` files are now under `reports/archive/` with their original blob content and an index. Preserve `coord/external-qa`
   as its own channel; never merge it into product `main`.
5. Gate every migration with local + GitHub CI, clean Compose dev and secure
   merged configuration, offline E2E and frontend build/browser acceptance.
6. **Do not close #257** until actual files are relocated, all references work and
   the full acceptance matrix has evidence. This file is only the prerequisite
   contract for the coordinated full migration.

## Current operational entrypoints

- Local trusted host development: `docker compose --project-directory . -f deploy/compose/dev/docker-compose.yml config --quiet`.
- Protected native + QA composition: `python3 scripts/check_native_qa_compose.py --live-sdlc`
  with explicit QA test command; do **not** combine with `deploy/compose/dev/docker-compose.yml`.
- Local CI analogue: `make check`.
- UI: `http://127.0.0.1:5173` when local dev Compose is started.

The default dev Compose has `AUTH_ENABLED=false` and Docker daemon access in
`runtime-hardening`; it is not production sandboxing. Offline native E2E does not
prove a live OpenRouter call or the completion criteria of #11.

## Concurrent agents: mandatory work ownership

1. Before each move, list current GitHub PRs and `wt/t_*` branches, and compare
   branch files against paths to be moved. **Treat active branches and worktrees as owned
   by their local agents**; never delete, rebase, force-push or commit into them.
2. Do not bulk-move live service directories while another agent edits them.
   Coordinate an exclusive migration window; stop at a conflict rather than
   overwrite someone else's work.
3. Use a dedicated `refactor/issue-257-*` PR, based on the latest `main`, and
   stage atomic path updates for all Dockerfile, Compose, CI, tests, pyproject,
   scripts and runbooks in the **same** migration.
4. Archive historical reports instead of deleting evidence. Five legacy `*-REPORT-*.md` files are now under `reports/archive/` with their original blob content and an index. Preserve `coord/external-qa`
   as its own channel; never merge it into product `main`.
5. Gate every migration with local + GitHub CI, clean Compose dev and secure
   merged configuration, offline E2E and frontend build/browser acceptance.
6. **Do not close #257** until actual files are relocated, all references work and
   the full acceptance matrix has evidence. This file is only the prerequisite
   contract for the coordinated full migration.
