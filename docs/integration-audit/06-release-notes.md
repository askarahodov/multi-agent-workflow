# Release Notes — EPIC-INT Integration Audit (E9.1–E9.5)

**Branch:** `epic-int/e9-release`
**Commit:** `f6ef1f1` (HEAD)
**Date:** 2026-10-12
**Contract:** `local-only` — no push, tag, publish, or deploy. Publication requires a separate authorized release process.

---

## Summary

This release completes the EPIC-INT integration audit and delivers a reproducible local development environment with a unified quality gate. The platform can now be started, validated, and tested with a single Makefile entry point (`make up`, `make check`), matching the CI pipeline exactly.

---

## What Changed

| Epic Step | Task | Scope | Key Artifacts |
|-----------|------|-------|---------------|
| **E9.1** | `t_178f8579` | Reproducible local launch | `Makefile` (up/down/logs/ps), `deploy/compose/dev/docker-compose.yml` (6 services, healthchecks), 5 service Dockerfiles, `/health` endpoints |
| **E9.2** | `t_daef9edf` | Unified CI quality gate | `.github/workflows/quality-gate.yml` (backend matrix, frontend, lint, security, aggregating gate), `Makefile check` target, `scripts/security_scan.py` |
| **E9.3** | `t_82b08777` | Documentation alignment | `README.md`, `SYSTEM_INFO_RU.md`, `workspace-map.md` updated to reflect real commands & structure; foreign-project terminology purged from docs |
| **E9.4** | `t_6fb8b723` | Repo hygiene | `.gitignore` extended (benchmarks, throwaway OpenAPI scripts); untracked generated artifacts removed from status |
| **E9.5** | `t_989c495b` | Release notes (this file) | `docs/integration-audit/06-release-notes.md` |
| **E9.6** | `t_3048e4d8` | Tools neutralization | `tools/agent-orchestration`: package renamed `harbor_transfer_portal` → `orchestration_tools`, paths/env-driven (`ORCHESTRATION_PROJECT_ROOT`, `ORCHESTRATION_PROJECT`, `ORCHESTRATION_TENANT`), Harbor branding stripped |

**Total commits on branch:** 5 (9dc0889 → bd06d89 → 3e1e894 → f96295c → f6ef1f1)

---

## How to Launch (Local Development)

Requires Docker with the `compose` plugin.

```bash
# Start the full stack (6 services + postgres)
make up

# Verify all services are healthy
make ps

# Tail live logs
make logs

# Stop and remove everything
make down
```

**Services started by `make up`:**

| Service | Port | Healthcheck |
|---------|------|-------------|
| `orchestration-server` | 8000 | `GET /health` |
| `agent-management` | 8001 | `GET /health` |
| `runtime-hardening` | 8002 | `GET /health` |
| `quality-gates` | 8003 | `GET /health` |
| `frontend` | 5173 | `GET /` |
| `postgres` | 5432 | `pg_isready` |

All images are built locally (`docker compose up -d --build`). The Python services install dependencies into `/app/.venv` (seeded by compose's anonymous volume); the `shared` package is copied in at build time.

---

## Quality Gate (Local & CI)

### Local (`make check`)

Runs the **exact same checks** as CI. Every step is a prerequisite — the gate fails on the first error.

```bash
make check
# lint → typecheck → backend-test → frontend-check → security
```

**Individual targets:**

```bash
make lint          # eslint (frontend)
make typecheck     # tsc --noEmit (frontend)
make backend-test  # pytest across 5 Python subsystems
make frontend-test # vitest (frontend)
make frontend-check # vitest + schema:validate + production build
make test          # backend-test + frontend-test
make security      # static security scan (quality-gates SecurityGate)
```

The local gate uses the repo's `.venv` (uv-managed, git-ignored) when present; falls back to system `python3`. CI creates the same path.

### CI (`.github/workflows/quality-gate.yml`)

Triggered on push and pull request. Jobs:

| Job | Maps to local target |
|-----|---------------------|
| `backend` (matrix: 5 subsystems) | `make backend-test` |
| `frontend` (typecheck, vitest, schema, build) | `make typecheck` + `make frontend-check` |
| `lint` (eslint) | `make lint` |
| `security` (quality-gates SecurityGate) | `make security` |
| `quality-gate` (aggregator) | **fails if any required job ≠ success** |

The `quality-gate` job is the single required status check — it fails if any of `backend`, `frontend`, `lint`, or `security` does not report `success`.

---

## Branch / Commit Reference

- **Branch:** `epic-int/e9-release`
- **HEAD commit:** `f6ef1f1b8f55fd02bc1f4a75e9ddd28e02b72c90`
- **Parent commits on branch:**
  - `9dc0889` — E9.1: reproducible local launch
  - `bd06d89` — E9.2: unified CI quality gate
  - `3e1e894` — E9.3: docs alignment & terminology purge
  - `f96295c` — E9.4: repo hygiene (gitignore)
  - `f6ef1f1` — E9.6: tools/agent-orchestration neutralization

**No tags created. No push performed.** (per `local-only` contract)

---

## Important Limitations & Known Constraints

1. **Shared working tree is transiently RED for frontend lint/typecheck**  
   Peer task `t_16d5878b` has uncommitted WIP in `apps/frontend/src/mvp/**` (eslint `prefer-const`, TS2322). This is **not** part of EPIC-INT and was not touched per the scope guard.  
   - `make backend-test security` passes in the shared tree (exit 0).  
   - A clean worktree verification (`git worktree add --detach`) shows `make check` → `quality gate: ALL CHECKS PASSED` (exit 0).

2. **Foreign WIP untouched**  
   Tasks `t_524fef64` (SEC-002 TLS) and `t_16d5878b` (frontend MVP) have uncommitted changes in the shared workspace. Their files are listed in `git status` but were **not** staged or committed by EPIC-INT.

3. **Code-side Harbor purge pending (out of E9.3 scope)**  
   Per E9.3 caveats: `tools/agent-orchestration/` (now `orchestration_tools/`), `services/runtime-hardening/runtime/__init__.py`, `services/runtime-hardening/pyproject.toml`, `PLAN.md` still contain "harbor" references in code/comments. Docs now reference `agent_orchestration/` / `orchestration_tools/`. A follow-up dev card should rename the package for docs to be literally true.

4. **`docs/integration-audit/` is untracked**  
   This directory (E1/E2 work) is not committed. Harbor purged in working tree but not committed per scope guard.

5. **No version tag / release artifact**  
   This is a local-only integration snapshot. Version selection and publication require human release-management authorization.

---

## Rollback Considerations

- **Previous known-good state:** commit `c8e9e4f` (pre-E9 integration snapshot) on the same branch history.
- **Artifacts:** All changes are source-level (Makefile, docker-compose, workflows, docs, package rename). No external registry images or published packages.
- **Configuration:** No database migrations. Docker compose stacks are ephemeral (`make down` removes everything).
- **Irreversible changes:** Package rename (`harbor_transfer_portal` → `orchestration_tools`) is a git rename; reversible via `git revert` or branch reset.

---

## Verification Evidence

| Check | Evidence |
|-------|----------|
| `make up` → all 6 services healthy | E9.1 acceptance log (`make_up.log`, `e9_acceptance_evidence.txt`) |
| `make check` (clean worktree) → ALL CHECKS PASSED | E9.2 clean worktree log (`make_check_clean.log`) |
| `make backend-test security` (shared tree) → exit 0 | E9.2 shared tree log (`make_check_shared.log`) |
| Harbor grep in `tools/` → 0 matches | E9.6 acceptance (`grep -rni harbor tools/ → exit 1`) |
| Harbor grep in docs → 0 matches | E9.3 acceptance (`grep -ri harbor docs/ README.md ... → exit 1`) |
| Generated artifacts absent from `git ls-files` | E9.4 acceptance (`git ls-files | grep -E 'benchmarks|.worktrees' → exit 1`) |

---

## Next Steps (Out of Scope)

- Human approval for version tagging and publication.
- Clean worktree CI run on the exact commit (`f6ef1f1`) via PR or push (separate authorized process).
- Code-side Harbor reference purge (follow-up task).
- Frontend WIP resolution (peer task `t_16d5878b`).