# Executive Summary — Branch Protection on `main` (Issue #44) — v3

**Companion to:** `ROLLOUT_PLAN.md` (repository root, **authoritative**, **v3 re-baselined 2026-10-30**).
**Prepared for:** repository owner `askarahodov` (human gate).
**Status: RE-GATING IN PROGRESS — v3 is NOT yet gate-approved for the human gate.** The gates below
(`t_d5a955b6` quality / `t_a7116377` security) cover the **superseded** 434-line revision `119eafb9…`,
not this v3 file; fresh gates for v3 are required (§5).

---

## The situation changed after the earlier approval

The prior revision was approved against a baseline that has since become false. On **2026-10-29 17:38–17:42 MSK**,
**after** both counted gates ran, the owner merged **PR #188** (`wt/t_de91cac5`), which created and activated
ruleset **`main-branch-protection` (id 26129824)** on `refs/heads/main`, requiring **all 14 status contexts at
once**. `main` is now `protected=true` and the pre-enforcement premise (`protected=false`, `rulesets []`) no
longer holds.

Consequence: this is no longer a "*roll protection out from an unprotected baseline*" plan. It is now a
"*a live all-at-once enforcement exists — verify it, keep it or roll it back, and close the gaps*" plan.

## What v3 delivers

The plan keeps all six required components and adds a live baseline and an explicit owner choice:

| § | Component | Status in live state |
|---|---|---|
| §4 | Shadow mode (warn-only, 2 weeks) | **Superseded** — enforcement already on; revived only if the owner rolls back (option b) |
| §5 | Gradual enforcement (one check at a time, 48 h) | **Superseded** — all 14 checks are already required at once; revived only under option (b) |
| §6 | Agent notification schedule | **Holds** both options; a live-state notice is owed now |
| §7 | Emergency bypass (audited, owner-only, 4 h token) | **Holds**; live ruleset has `bypass_actors=[]`, so bypass = one-context ruleset edit |
| §8 | Metrics dashboard (violation / FP / adaptation) | **Holds**; FP source is the P2 telemetry artifact (not yet merged) |
| §9 | Rollback triggers & procedures | **Central** under option (a); quantitative triggers + tested procedure |

## The decision the owner now faces (§1 — surfaced, not chosen)

- **(a) Accept the live all-at-once enforcement** → use the plan as a verify/rollback plan. Residual risk:
  14 checks on at once with `bypass_actors=[]` means one misnamed context blocks every PR with no standing bypass.
- **(b) Roll back ruleset `26129824` and resume the staged plan** → warn-only shadow, then one-check-at-a-time.

**This document records both and picks neither.** Any ruleset change is a separate, explicitly authorized act.

## Verified live baseline (§0, captured read-only 2026-10-30 09:10 MSK)

| Fact | Live value |
|---|---|
| `main` protected | `true` |
| `main` HEAD | `c94245ffc8bfc313efc9f7879db6364783583cea` |
| Ruleset | `main-branch-protection` id `26129824`, `enforcement=active`, target `refs/heads/main` |
| Required contexts | **14, all required at once** (plan §3.1) |
| Ruleset vs in-repo `REQUIRED_CHECKS` | **14 vs 11 — DIVERGENT** (rollback trigger `c` currently firing) |
| Bypass actors | `[]` (`current_user_can_bypass=never`) |
| Independent approval | `required_approving_review_count=0` (no independent-approval check yet) |

Evidence files (fresh, hashed in `evidence/rollout-baseline-2026-10-30T0610Z*`).

## Gate status

| Gate | Card | Verdict | Applies to v3? |
|---|---|---|---|
| Quality review (1st) | `t_cf1bc31e` | changes_requested | No — draft |
| Quality re-review | `t_d5a955b6` | approved | **No — superseded revision `119eafb9…`** |
| Security (1st) | `t_ccd446d9` | passed | No — superseded draft |
| Security re-review | `t_a7116377` | passed | **No — superseded revision `119eafb9…`** |
| v3 quality + security re-gates | *(being created)* | — | **Yes — required before the human gate** |

## Still required — and explicitly not done here

- **Not done:** no ruleset or branch-protection change, no required check enabled, no push, PR, merge, tag,
  publish or deploy. Enforcement state is exactly as found.
- **Blocking the rollout itself (not this document):** P1–P7 and gaps G1–G5 (plan §10) — e.g. no producer has a
  verified PR cycle, secret-scan telemetry not merged (FP not measurable), no independent reviewer identity,
  in-repo `REQUIRED_CHECKS` still 11 vs live 14.
- **Non-blocking hardening** before final enforcement: KEK guard, WebSocket key transport, release-approval
  role elevation, TLS/HSTS CI wiring, `src/mvp/**` orphan disposition; residual audit findings
  `SEC-001/007/008/009` are mitigated **operationally** by the server-side ruleset (this plan is that mitigation).

## Decision requested

1. **Choose option (a) or (b)** (§1) — this document does not choose.
2. **Approve `ROLLOUT_PLAN.md` v3** once the fresh v3 gates pass (this is the human gate).
3. **Authorize execution as a separate act.** Publication, merge to `main` and any ruleset/branch-protection
   change remain separate human-authorized actions that this agent did not and cannot perform.
