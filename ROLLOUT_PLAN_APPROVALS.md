# ROLLOUT_PLAN.md — Approval Ledger and Gate Status (v3)

**Document under review:** `ROLLOUT_PLAN.md` (repository root, this worktree) — **v3, re-baselined 2026-10-30**.
**Overall gate status: RE-GATING IN PROGRESS — NOT yet approved for the human gate.**
This ledger does not approve the plan and does not authorize execution.

> **v3 supersedes every earlier revision.** The previous frozen revision (`sha256 119eafb9…`, 434 lines) was
> approved by gates `t_d5a955b6` (quality) and `t_a7116377` (security), but against a baseline
> (`main protected=false`, `rulesets []`) that became false when **PR #188** activated ruleset `26129824`
> on 2026-10-29 17:42 MSK. Those gate verdicts are **not transferable** to v3 and are recorded below only as
> history. Fresh v3 gates are required.

---

## 1. Artifact manifest (v3)

| Artifact | Path | Produced by |
|---|---|---|
| Rollout plan (v3, authoritative) | `ROLLOUT_PLAN.md` | this card `t_e527c2c3` (re-baseline) |
| Executive summary (v3) | `ROLLOUT_EXECUTIVE_SUMMARY.md` | this card `t_e527c2c3` |
| This ledger (v3) | `ROLLOUT_PLAN_APPROVALS.md` | this card `t_e527c2c3` |
| Live baseline evidence (6 files) | `evidence/rollout-baseline-2026-10-30T0610Z*` | this card `t_e527c2c3` |
| Check-run inventory, PR #187 | `evidence/rollout-checkrun-inventory-pr187.json` | `t_d5a955b6` |

Artifact hashes for v3 are pinned by the first commit of the re-baseline on branch `wt/t_e527c2c3`; verify with
`git show <commit>:ROLLOUT_PLAN.md | sha256sum`.

Copies in other worktrees (`.worktrees/*/ROLLOUT_PLAN.md`) are snapshots, not authoritative. Only the root-level
`ROLLOUT_PLAN.md` on this card's branch is authoritative (plan header).

---

## 2. Gate ledger

| # | Gate | Card | Verdict | Artifact actually reviewed | Covers v3? |
|---|---|---|---|---|---|
| G1 | Quality review (1st) | `t_cf1bc31e` | changes_requested — 9 blocking defects | 44-line draft `69b69006…` | No — superseded |
| G2 | Quality re-review | `t_d5a955b6` | approved | revision `119eafb9…` | **No — superseded revision** |
| G3 | Security review (1st) | `t_ccd446d9` | passed | draft `69b69006…` | No — stale |
| G4 | Security re-review | `t_a7116377` | passed | revision `119eafb9…` | **No — superseded revision** |
| G5 | **v3 Quality re-review** | *(created by `t_e527c2c3`)* | pending | `ROLLOUT_PLAN.md` v3 | **Yes — required** |
| G6 | **v3 Security re-review** | *(created by `t_e527c2c3`)* | pending | `ROLLOUT_PLAN.md` v3 | **Yes — required** |

**No mandatory gate yet covers v3.** The human gate must not proceed until G5 and G6 both pass on the v3 hash.

### Why G2/G4 do not carry over

They were verified against `119eafb9…`, whose §0 asserted `main protected=false` and `rulesets []`. That
assertion is now false (§3 here; plan §0.2). A gate verdict is bound to the revision and the facts it validated;
a later live-state change invalidates it. This is the precise cause of the `changes_requested` verdict on this
card and the reason for the v3 re-baseline.

---

## 3. Live re-verification (this card, read-only, 2026-10-30 09:10 MSK)

```bash
gh api repos/askarahodov/multi-agent-workflow/branches/main --jq '{protected,sha:.commit.sha}'
# {"protected":true,"sha":"c94245ffc8bfc313efc9f7879db6364783583cea"}

gh api repos/askarahodov/multi-agent-workflow/rulesets --jq '.[]|{id,name,enforcement,target}'
# {"id":26129824,"name":"main-branch-protection","enforcement":"active","target":"branch"}

gh api repos/askarahodov/multi-agent-workflow/rulesets/26129824 \
  --jq '.rules[]|select(.type=="required_status_checks")|.parameters.required_status_checks[].context'
# 14 contexts — gitflow policy validation … quality gate  (plan §3.1)
```

Matches the v3 plan §0 table and the hashed evidence files. **No enforcement state was changed by this card**,
and no push, PR, merge, tag, publish, deploy or ruleset/required-check change was performed.

---

## 4. Open items

- **G5/G6 (blocking the human gate):** v3 quality and security re-reviews — cards created by `t_e527c2c3`.
- **Blocking the rollout itself (not this document):** plan §10 P1–P7 and G1–G5. Notably the live ruleset
  requires **14** contexts while in-repo `REQUIRED_CHECKS` (`.github/workflows/gitflow-policy.yml:175-181`) lists
  **11** — rollback trigger (c) is currently firing; closed by P5.
- **Non-blocking hardening** (before final enforcement, separate cards): KEK production guard, WebSocket key
  transport, release-approval role elevation, TLS/HSTS tests in per-service CI, `src/mvp/**` orphan disposition.
  Residual audit findings `SEC-001/007/008/009` are mitigated operationally by the server-side ruleset (this plan).

---

## 5. Version-control record

| Fact | Value |
|---|---|
| Branch | `wt/t_e527c2c3` |
| Base HEAD before re-baseline | `085a78b` (staged `119eafb9…` revision) |
| Files changed by v3 | `ROLLOUT_PLAN.md`, `ROLLOUT_EXECUTIVE_SUMMARY.md`, `ROLLOUT_PLAN_APPROVALS.md`, `evidence/rollout-baseline-2026-10-30T0610Z*` |
| Pushed / merged | **No.** No push, PR, merge to `main`/`develop`. |

**No publication, deployment, tag, ruleset change or required-check enablement was performed. Human approval —
after the v3 gates pass — is required before any execution step in the plan.**
