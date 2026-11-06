# Repository ownership map (#257)

Every path belongs to exactly one scope. A change that spans scopes needs the
owning reviewers listed here. Ownership is about *review*, not permission: the
branch-protection ruleset still applies to `main`.

| Path | Scope | Owns (what may be changed there) | Consumers |
| --- | --- | --- | --- |
| `services/orchestration-server/` | Workflow engine | API surface, state machine, migrations, OpenAPI contract (`docs/openapi.json`) | frontend, quality-gates, native worker |
| `services/agent-management/` | Agents & providers | Provider adapters, credentials handling, trusted gateway, tool dispatch | orchestration-server |
| `services/quality-gates/` | QA & release | Gates, isolated tester, attestations, evidence/artifact schema | orchestration-server, CI |
| `services/runtime-hardening/` | Local runtime | Sandbox policy, Compose hardening, privilege boundaries | dev Compose only |
| `apps/frontend/` | UI | React app, design system (`src/components`, `src/patterns`), `src/mvp/sections` layouts | end users |
| `packages/shared/` | Python shared kernel | Auth middleware, attempt fences, QA attestation primitives | all Python services |
| `packages/agent-runtime/` | Agent runtime | Message loop, event journal | orchestration-server, agent-management |
| `tools/` | Developer tooling | GitHub kanban sync, gitflow scripts, repo helpers | maintainers, CI |
| `scripts/` | Repository automation | Security gate wrapper, Compose validators, docs checks | CI |
| `tests/` | Cross-service tests | Only tests that need more than one service (TLS/HSTS, layout guard) | CI |
| `deploy/compose/` | Deployment | Dev and protected Compose entry points | CI, operators |
| `docs/` | Documentation | Architecture, ADRs, runbooks, user guide | everyone |
| `reports/archive/` | Historical evidence | Frozen reports; append-only | auditors |
| root `README.md`, `Makefile`, `AGENT_GITFLOW_RULES.md` | Entry surface | Must stay at the root | everyone |
| root `package.json`, `package-lock.json` | Docs toolchain (VitePress only) | Not the frontend toolchain — that is `apps/frontend/package.json` | `docs-dependency-check` workflow |

## Boundary rules

1. Frontend layouts live only in `apps/frontend/src/mvp/sections/`. There is no
   second `pages/` tree — `tests/test_repository_layout.py` fails if one appears.
2. Root-level Python modules are not allowed. Helpers belong to `scripts/` or a
   service package.
3. Root `package.json` exists solely for the VitePress documentation build and
   the repository-level `docker:*` convenience scripts. Any change to frontend
   dependencies belongs in `apps/frontend/package.json`.
4. Cross-service tests belong in `tests/`; everything else belongs to the
   service that owns the behaviour (`services/<name>/tests/`).
5. Historical reports are read-only. New evidence goes to `docs/` (active) or a
   dedicated audit file, never by editing an archived report.

The guard test enforces rules 1–3 mechanically; rules 4–5 are review rules.
