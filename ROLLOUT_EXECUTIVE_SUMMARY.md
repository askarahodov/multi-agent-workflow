# Executive Summary — Branch Protection Rollout (Issue #44)

**Artifact:** `ROLLOUT_PLAN.md` · `sha256 119eafb9…f511` · 434 lines · frozen
**Prepared for:** repository owner `askarahodov` (human gate) · **Date:** 2026-10-29
**Status: READY_FOR_HUMAN_APPROVAL — both mandatory gates (quality, security) passed on this exact revision.**
Approval of the plan is **not** authorization to execute it; execution is a separate decision.

---

## The problem

`main` has **no server-side protection**: `protected=false`, `rulesets=[]`, classic protection 404
(re-verified read-only 2026-10-29; HEAD `e01efa18`). Local hooks can be bypassed (`--no-verify`,
`core.hooksPath`), so a careless or compromised agent can write to `main` directly. Issue #44 asks for real
enforcement without freezing delivery.

## What the plan does

A staged, reversible enforcement of **14 required status checks** on `main`, over ~9 weeks:

| Phase | Dates | What happens |
|---|---|---|
| Prereqs P1–P7 | 10-30 → 11-06 | Prove the 2 gitflow contexts can report on PRs; ship secret-scan telemetry; create rollout data dir; one fixture-classifier source of truth; sync the authoritative 14-context list; name an independent reviewer; rehearse rollback |
| Shadow (warn-only) | 11-09 → 11-23 | `main` stays unprotected, nothing is required, zero merge blocks; collect per-context/per-producer violations and the false-positive rate |
| Enforcement S1–S14 | 11-25 → 12-28 | One context at a time, each with config readback proving a one-context delta, a fresh-PR pass, and **48 h** observation; 6 negative probes; aggregate `quality gate` enabled **last** |
| Step F | 12-30 | Independent approval required; final ruleset |

**Safety properties:** any failure → targeted removal of *that one* context (never delete the ruleset); named
owner chain (owner authorizes → `sdlc-security` executes → `sdlc-reviewer` verifies) with a 4 h budget; a
rehearsal on a throwaway branch before S1; 5 producers each need one verified PR → green → review → merge
before shadow can exit.

## Gate status

| Gate | Card | Verdict | Applies to this revision? |
|---|---|---|---|
| Quality review (first pass) | `t_cf1bc31e` | `changes_requested` — 9 blocking defects | No — draft, superseded |
| Quality re-review | `t_d5a955b6` | **approved** — all 10 blocking items closed, every citation re-verified | **Yes** (`119eafb9…`) |
| Security first pass | `t_ccd446d9` | `passed` 4/4 areas | No — reviewed the superseded draft (`§1 shadow / §4 bypass / §5 metrics` numbering) |
| Security re-review of final | `t_a7116377` | **passed** — 5/5 scope areas on the final numbering; no secrets; read-only honored | **Yes** (`119eafb9…`) |

Both gates that count were run against the frozen artifact's hash; neither predates the rework. No gate is
outstanding for `ROLLOUT_PLAN.md` itself.

## Still required — and explicitly not done here

- **Not done:** no ruleset or branch-protection change, no required check enabled, no push, tag, PR, merge or
  deployment. Enforcement state is exactly as found: `main` unprotected, `rulesets []`.
- **Blocking the rollout itself (not this document):** G1 no producer has a verified PR cycle yet; G2 the
  gitflow contexts have 0 PR runs and must be proven by P1; G3 no independent reviewer identity is named yet;
  G4 secret-scan telemetry (P2) is not merged, so the false-positive gate cannot be measured. These are
  prerequisites P1–P7 inside the plan, not gaps in the plan.
- **Non-blocking hardening before final enforcement:** KEK production guard, WebSocket key transport,
  release-approval role elevation, TLS/HSTS tests in per-service CI, `src/mvp/**` orphan disposition.
- **Provenance caveat (non-blocking):** §3.4 cites `SECURITY_AUDIT.md` (untracked) for SEC-007 while a
  tracked doc reuses the id for fixture false positives; fix identifier collision when that file is
  committed (card `t_de91cac5`). No enforcement impact.

## Decision requested

1. **Approve `ROLLOUT_PLAN.md` @ `sha256 119eafb9…`** as the rollout procedure (this is the human gate).
2. **Authorize execution as a separate act**, starting with prerequisites P1–P7; enforcement begins only
   after shadow exit S-EXIT-1…5 is met on measured data.
3. Acknowledge that publication, merge to `main` and any branch-protection/ruleset change remain separate
   human-authorized actions that this agent did not perform and cannot perform on your behalf.
