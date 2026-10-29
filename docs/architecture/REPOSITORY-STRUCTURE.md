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

## GitHub branch protection for `main` (ruleset `main-branch-protection`)

`main` is protected **only** by the repository ruleset (classic branch protection is not configured;
`/branches/main/protection` returns `404`). Verified read-back 2026-10-29 — see
`docs/security/main-branch-protection-verification.md` and
`evidence/rollout-verify-2026-10-29T150511Z-ruleset-26129824.json`.

| Field | Value |
| --- | --- |
| Ruleset id / name | `26129824` / `main-branch-protection` |
| Target / enforcement | `branch` / `active` |
| `conditions.ref_name.include` | `["refs/heads/main"]` (no wildcard) |
| `conditions.ref_name.exclude` | `[]` |
| `bypass_actors` | `[]` → `current_user_can_bypass: "never"` (no admin bypass) |
| Rules | `deletion`, `non_fast_forward`, `pull_request`, `required_status_checks` |
| `pull_request.required_approving_review_count` | `0` (interim — see below) |
| `pull_request.dismiss_stale_reviews_on_push` | `false` |
| `pull_request.require_code_owner_review` | `false` |
| `pull_request.require_last_push_approval` | `false` |
| `pull_request.required_review_thread_resolution` | `false` |
| `pull_request.allowed_merge_methods` | `["merge","squash","rebase"]` |
| `required_status_checks.strict_required_status_checks_policy` | `false` |
| `required_status_checks.do_not_enforce_on_create` | `false` |

Required status-check contexts (14), each mapped to the workflow job that publishes it:

| # | Context | Producer |
| --- | --- | --- |
| 1 | `gitflow policy validation` | `.github/workflows/gitflow-policy.yml` `policy-compliance` |
| 2 | `gitflow worktree isolation` | `.github/workflows/gitflow-policy.yml` `worktree-isolation` |
| 3 | `Reject external QA channel files in product main` | `.github/workflows/coordination-isolation.yml` |
| 4–8 | `backend pytest (agent-management \| orchestration-server \| quality-gates \| runtime-hardening \| tools)` | `.github/workflows/quality-gate.yml` `backend` matrix |
| 9 | `frontend (typecheck + tests + build)` | `.github/workflows/quality-gate.yml` `frontend` |
| 10 | `lint (eslint)` | `.github/workflows/quality-gate.yml` `lint` |
| 11 | `security scan (quality-gates)` | `.github/workflows/quality-gate.yml` `security` |
| 12 | `packaging (clean Python install)` | `.github/workflows/quality-gate.yml` `packaging` |
| 13 | `Native LLM-tool-Contract Gate (offline)` | `.github/workflows/native-agent-e2e.yml` |
| 14 | `quality gate` | `.github/workflows/quality-gate.yml` `quality-gate` (aggregate) |

Notes:

- Use the exact `quality-gate.yml` context strings above. `ci.yml` publishes case-variant near-duplicates
  (`Backend pytest …`, `Frontend (typecheck + vitest)`, `Lint (eslint)`) that must **not** be required.
- Do **not** require `paths`-filtered checks (`docker-qa-smoke`, `frontend npm audit (high/critical)`) or
  the conditional `local Compose build and health` job: on unrelated PRs they never report and would block
  every merge.
- `required_approving_review_count: 0` is an interim owner self-review allowance until the independent
  reviewer identity exists (`SECURITY_AUDIT.md` §5.6, `ROLLOUT_PLAN.md` §9 step F). It is documented here
  for auditability; its expiry is tracked in the rollout plan.
- The in-repo authoritative required-check list is `.github/workflows/gitflow-policy.yml` `REQUIRED_CHECKS`;
  keep it byte-equal to the 14 contexts above (`ROLLOUT_PLAN.md` §4.3, P5).
