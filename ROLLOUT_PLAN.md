# ROLLOUT_PLAN.md — Branch Protection on `main` (Issue #44)

**Status:** RE-BASELINED (v3) 2026-10-30 per review `t_e527c2c3` round-1 verdict *changes_requested*.
Binds to the live GitHub state, not to the pre-enforcement premise the earlier draft assumed.
**Owner (decision):** repository owner `askarahodov`. **Enforcement owner:** `askarahodov`. **Operator:** sdlc-security.
**Baseline date:** **2026-10-30 09:10 MSK (06:10 UTC)** — re-verified read-only, evidence hashes in §0.
**Supersedes:** the 44-line draft (`sha256 69b69006…`), the 434-line staged draft (`sha256 119eafb9…`, gates
`t_d5a955b6`/`t_a7116377` — verified against a baseline that is now false), and every copy under
`.worktrees/*/ROLLOUT_PLAN.md`.

> **Single authoritative file.** This root-level `ROLLOUT_PLAN.md` is the only version-controlled rollout plan.
> Copies in other worktrees are snapshots and must not be edited or merged. Any change to the plan is a commit
> to this file on its card branch.

---

> ## ⚠️ READ FIRST — enforcement is already ACTIVE on `main`
>
> On **2026-10-29 17:38 MSK** ruleset **`main-branch-protection` (id 26129824)** was created and applied via
> **PR #188** (`wt/t_de91cac5`, merged by the owner at **2026-10-29 17:42 MSK**). It is **`enforcement=active`**
> on `refs/heads/main` and requires **all 14 status contexts at once** (§3).
>
> This happened **~2 minutes after** the previous handoff and **after** both counted gates
> (`t_d5a955b6` quality / `t_a7116377` security) had verified hash `119eafb9…`. Those gates therefore validated a
> baseline (`main protected=false`, `rulesets []`) that no longer holds, and **neither gate endorses the current
> live state**. The staged plan's warn-only shadow phase and its S1–S14 one-check-at-a-time sequence describe a
> world that no longer exists; they are retained below **only** as the conditional path for option (b) (§1).
>
> **This document changes no enforcement state.** It writes no ruleset and enables/disables no required check.
> All GitHub/CI changes it describes are executed by the named owner after this plan is approved, and any
> ruleset change is a **separate, explicitly authorized act**. Baseline facts were captured read-only.

---

## 0. Live baseline (captured, not assumed)

Captured read-only on **2026-10-30 09:10 MSK**. Evidence files (fresh, this re-baseline):

| Evidence file | sha256 |
|---|---|
| `evidence/rollout-baseline-2026-10-30T0610Z-branch.json` | `9f0c5ed7481a633fbd3f8ea8836f9488755ff3430ce8e94a02ec690b6b8e0516` |
| `evidence/rollout-baseline-2026-10-30T0610Z-rulesets.json` | `259f0716145c7ad56a671e60daac424b2f166d294110cab39c1bc66d919f42b3` |
| `evidence/rollout-baseline-2026-10-30T0610Z-ruleset-26129824.json` | `4620648919f55497709ce0e39e009e5d8b410be227488cb88a1d80be0c9a2c8f` |
| `evidence/rollout-baseline-2026-10-30T0610Z-gitflow-pr-runs.json` | `061fd86638559ec7f50b49d0fa0499eefa5663fb883f36634258275e462578ce` |
| `evidence/rollout-baseline-2026-10-30T0610Z-gitflow-policy-main.yml` | `3334c205b16159d28d7eeae872fd4665e6734f98f82b0c47818046fee38db630` |
| `evidence/rollout-baseline-2026-10-30T0610Z-classic-protection.json` | `0f3b6c9820e47d179fbb559192ca75c0905a360fba228dab7015d092a816319a` |

Commands used:

```bash
gh api repos/askarahodov/multi-agent-workflow/branches/main
gh api repos/askarahodov/multi-agent-workflow/rulesets
gh api repos/askarahodov/multi-agent-workflow/rulesets/26129824
gh api "repos/askarahodov/multi-agent-workflow/actions/workflows/gitflow-policy.yml/runs?per_page=20"
gh api "repos/askarahodov/multi-agent-workflow/contents/.github/workflows/gitflow-policy.yml?ref=main"
gh api repos/askarahodov/multi-agent-workflow/branches/main/protection
```

### 0.1 Baseline facts (live, 2026-10-30 09:10 MSK)

| Fact | Live value | Source |
|---|---|---|
| `main` protected | **`true`** | branch API |
| `main` HEAD | **`c94245ffc8bfc313efc9f7879db6364783583cea`** | branch API |
| Rulesets on the repo | **1** | rulesets API |
| Ruleset | **`main-branch-protection`, id `26129824`**, `target=branch` (`refs/heads/main`), **`enforcement=active`**, created `2026-10-29T17:38:39+03:00` | ruleset API |
| Ruleset rule types | `deletion`, `non_fast_forward`, `pull_request`, `required_status_checks` | ruleset API |
| Required status checks | **14 contexts, all required at once** (§3); `strict_required_status_checks_policy=false`, `do_not_enforce_on_create=false` | ruleset API |
| `pull_request` rule params | `required_approving_review_count`=**0**, `dismiss_stale_reviews_on_push`=false, `require_code_owner_review`=false, `require_last_push_approval`=false, `required_review_thread_resolution`=false, **`require_extra_approval_for_unattributed_changes`=true**, `allowed_merge_methods=[merge,squash,rebase]` | ruleset API |
| Bypass posture | **`bypass_actors=[]`**, **`current_user_can_bypass="never"`** (no standing bypass actor; only an admin ruleset edit can change this) | ruleset API |
| Classic branch protection | **404 — not configured** (all enforcement is via the ruleset above) | branch-protection API |
| `gitflow-policy.yml` runs | **`total_count=4`**: PR run **`40893716138`** (`event=pull_request`, `conclusion=success`, head `4bb881ac…`, = **PR #188**); push runs `40894211568` (`c94245ff`), `40892973884`, `40886671372` (`e01efa18`) | workflow-runs API |
| **In-repo `REQUIRED_CHECKS`** (`.github/workflows/gitflow-policy.yml:175-181` on `main`) | **11 contexts** — omits `Reject external QA channel files in product main`, `packaging (clean Python install)`, `Native LLM-tool-Contract Gate (offline)` | file on `main` (evidence `.yml`) |

### 0.2 Delta from the previous (now false) baseline

| Fact | Previous claim (2026-10-29, hash `119eafb9…`) | Live (2026-10-30 09:10 MSK) |
|---|---|---|
| `main protected` | `false` | **`true`** |
| Rulesets | `[]` | **1 — `main-branch-protection` id `26129824`, active** |
| Required contexts | none marked required | **all 14 at once** |
| `main` HEAD | `e01efa18…` | **`c94245ff…`** |
| `gitflow-policy.yml` PR runs | `0` | **≥1 (`40893716138`, success, PR #188)** |
| Classic protection | 404 | 404 (unchanged) |

**Cause.** PR #188 (`wt/t_de91cac5`, *"docs(security): apply main ruleset control…"*), **merged by the owner at
`2026-10-29T14:42:41Z` (17:42 MSK)** — after both counted gates had been verified against `119eafb9…`.

**Consequence.** The plan's subject is no longer "roll the protection out from an unprotected baseline"; it is
now "a live all-at-once enforcement exists — verify it, keep it or roll it back, and close the gaps".

---

## 1. Owner decision — two options (SURFACED, NOT CHOSEN)

The live change was applied **out-of-band relative to this plan's staged/gated approach** (`§5 P5`: "ruleset and
env var changed in the same PR, or the ruleset change is reverted"). The owner now faces a binary choice which
**this document does not make**. Both are presented; neither is recommended here.

### Option (a) — Accept the live all-at-once enforcement → convert this into a verify/rollback plan

| Aspect | Detail |
|---|---|
| What it means | Keep ruleset `26129824` as-is (14 contexts required at once). Use this document as the **verification + rollback + metrics + notification** plan for the live state. |
| What still holds | Verification of the 14-context set against the negative matrix (§9.4), rollback readiness (§9), metrics (§8), notifications (§6), and the outstanding gaps (§10). |
| Prerequisites to close | **P1** ✔ (gitflow PR evidence now exists), **P2/P4** (secret-scan telemetry + fixture classifier — make FP measurable), **P5** (**sync the in-repo `REQUIRED_CHECKS` 11 → 14**, §3.3), **P6** (independent reviewer identity — live `required_approving_review_count=0`, so there is currently **no** independent-approval check), **P7** (rollback rehearsal). |
| Residual risk | 14 checks switched on simultaneously = a single misnamed/over-strict context blocks **every** PR. No shadow observation window was run, and the live ruleset has **no** bypass actor (`bypass_actors=[]`), so any false block can only be cleared by an admin ruleset edit (§7). |
| Superseded under (a) | §4 (shadow) is moot — enforcement is on. §5 (S1–S14) is moot — the checks are already required. |

### Option (b) — Roll back ruleset `26129824` and resume the staged plan

| Aspect | Detail |
|---|---|
| What it means | Set `26129824` `enforcement=disabled` (or delete it), then execute this document's staged sequence: prerequisites (§10) → warn-only shadow (§4) → one-check-at-a-time with 48 h observation (§5) → step F. |
| What it costs | A ruleset edit by the owner (a **separately authorized** act — not performed by this document); the live protection window is lost for the duration; the shadow + 14-step sequence spans ~2 months (§11). |
| Why one might choose it | It restores the original risk posture: every context is observed with real PR traffic before it can block a merge; the "no producer has completed a verified PR cycle" gap (§10 G1) is closed before enforcement. |
| Cross-refs | §4 (shadow), §5 (gradual enforcement), §6 (notifications), §7 (bypass), §9 (rollback). |

> **Decision owner:** repository owner `askarahodov`. **This document records both options and picks neither.**
> Whichever is chosen, any change to ruleset `26129824` is a separate explicitly-authorized act (§7.4).

---

## 2. Producers (5 PR producers + 1 bypass path)

`admin` is **not** a PR producer. It is the emergency bypass path and is governed by §7, excluded from the
"all producers smoke-tested" criterion. The count is **5** everywhere in this plan.

| # | Producer | Branch pattern | Smoke criterion | External QA exception |
|---|---|---|---|---|
| 1 | Manual product changes | `feat/*`, `fix/*`, `docs/*`, `security/*` | PR → green → independent review → merge | — |
| 2 | Local Kanban / worktree agents | `wt/t_*` | same | — |
| 3 | Native product workers | `feat/issue-*`, `fix/issue-*` (ownership unproven) | same | — |
| 4 | Dependabot | `dependabot/*` | same | — |
| 5 | External QA | `coord/external-qa` | PR **blocked** by `Reject external QA channel files in product main`; never merged | Expected outcome is a red check, not a merge |

---

## 3. Required-check set — the live 14 (verified against ruleset `26129824`)

### 3.1 Exact contexts, LIVE in the ruleset (re-verified 2026-10-30)

The 14 contexts below were read back from ruleset `26129824` and match the plan's target set exactly
(`§0.1`). Context *names* were cross-checked against a real PR head via
`evidence/rollout-checkrun-inventory-pr187.json` (`sha256 e0e7b700…`), PR #187 @ `b3933ed0…`: 32 check runs,
21 unique names.

| # | Context (exact string) | Workflow:line | Live status |
|---|---|---|---|
| 1 | `gitflow policy validation` | `.github/workflows/gitflow-policy.yml:29` | **required (live)**; PR evidence: run `40893716138` |
| 2 | `gitflow worktree isolation` | `.github/workflows/gitflow-policy.yml:128` | **required (live)** |
| 3 | `Reject external QA channel files in product main` | `.github/workflows/coordination-isolation.yml:14` | **required (live)** |
| 4 | `backend pytest (agent-management)` | `.github/workflows/quality-gate.yml:25` + matrix `:31` | **required (live)** |
| 5 | `backend pytest (orchestration-server)` | `.github/workflows/quality-gate.yml:25` + matrix `:32` | **required (live)** |
| 6 | `backend pytest (quality-gates)` | `.github/workflows/quality-gate.yml:25` + matrix `:33` | **required (live)** |
| 7 | `backend pytest (runtime-hardening)` | `.github/workflows/quality-gate.yml:25` + matrix `:34` | **required (live)** |
| 8 | `backend pytest (tools)` | `.github/workflows/quality-gate.yml:25` + matrix `:35` | **required (live)** |
| 9 | `frontend (typecheck + tests + build)` | `.github/workflows/quality-gate.yml:199` | **required (live)** |
| 10 | `lint (eslint)` | `.github/workflows/quality-gate.yml:223` | **required (live)** |
| 11 | `security scan (quality-gates)` | `.github/workflows/quality-gate.yml:241` | **required (live)** |
| 12 | `packaging (clean Python install)` | `.github/workflows/quality-gate.yml:52` | **required (live)** |
| 13 | `Native LLM-tool-Contract Gate (offline)` | `.github/workflows/native-agent-e2e.yml:14` | **required (live)** |
| 14 | `quality gate` | `.github/workflows/quality-gate.yml:258` | **required (live)**; aggregate (`if: always()`) |

Two facts from that inventory still drive naming:

1. Every `quality-gate.yml` check appears **twice** per head SHA because the workflow triggers on both
   `push` and `pull_request` (`.github/workflows/quality-gate.yml:17-18`). Required-check evidence must name the run ID,
   not just the context name.
2. `ci.yml` publishes **case-variant near-duplicates** of the quality-gate contexts —
   `Backend pytest (…)`, `Frontend (typecheck + vitest)`, `Lint (eslint)` — alongside the lower-case
   `backend pytest (…)`, `frontend (typecheck + tests + build)`, `lint (eslint)`. Only the
   `quality-gate.yml` names are used; the `ci.yml` names are a different, overlapping check set.

Rejected names from the original draft: `packaging` and `compose-smoke` are **job ids**, not check names; using
them creates required contexts that no run ever reports, blocking every merge.

Observed but **not** gated (`gitflow required checks`, `Secure QA TLS / RBAC / SQLite Compose (offline live)`):
adding either is an owner decision, not part of this plan.

### 3.2 `local Compose build and health` — excluded, limitation documented

The job runs on every PR, but its build/health steps are conditional on "Detect Compose-related changes"
(`.github/workflows/quality-gate.yml:74`, `:97`, `:105`, `:119`), so on a non-Compose PR it reports green without building
anything. Only the static overlay-policy step (`:99-103`) is unconditional. Making this context required would
give false assurance on the majority of PRs, so it is **excluded** (matching the ruleset, which does not list it).
If the owner later wants Compose coverage enforced, the prerequisite is a dedicated always-running step that
fails on config drift (owner: sdlc-developer, new card, not this rollout).

### 3.3 Live divergence: ruleset (14) vs in-repo `REQUIRED_CHECKS` (11)

`.github/workflows/gitflow-policy.yml:175-181` on `main` lists **11** contexts. The live ruleset requires
**14**. Missing from the env var: `Reject external QA channel files in product main`,
`packaging (clean Python install)`, `Native LLM-tool-Contract Gate (offline)`. The `gitflow policy validation`
job verifies only the 11 it knows about, so **three live-required contexts are not covered by the in-repo
verifier**. This is exactly rollback trigger (c) (§9.1) and is closed by **P5** (§10), which updates the env var
to the 14-context set in one commit:

```yaml
          REQUIRED_CHECKS: >-
            gitflow policy validation,gitflow worktree isolation,
            Reject external QA channel files in product main,quality gate,
            backend pytest (agent-management),backend pytest (orchestration-server),
            backend pytest (quality-gates),backend pytest (runtime-hardening),
            backend pytest (tools),frontend (typecheck + tests + build),
            lint (eslint),security scan (quality-gates),
            packaging (clean Python install),Native LLM-tool-Contract Gate (offline)
```

**Rule (unchanged):** the GitHub ruleset and this env var are changed in the same PR, or the ruleset change is
reverted. A divergence is a rollback trigger (§9.1, trigger c). The divergence exists **now** and is an open gap.

---

## 4. Component 1 — Shadow mode (warn-only, 2 weeks)

> **STATUS: SUPERSEDED under option (a). Revived only under option (b).** Enforcement is already active
> (§0), so there is no unprotected window left to observe. This section defines the warn-only phase that a
> roll-back-and-resume (option b) would run **before** re-applying any required check.

**Planned window (option b):** 14 consecutive days, gated on P1–P4 (§10). During shadow,
`enforcement=disabled` on the ruleset (or no ruleset); no context is marked required. Zero merge blocks.

### 4.1 Violation collection (data sources that exist)

- **Per-context, per-producer violations:** `gh api repos/$R/commits/<head_sha>/check-runs?per_page=100`.
  Attribute a producer from the PR head ref prefix per §2. Deduplicate the `push`/`pull_request` pair by
  keeping the run whose `pull_requests` array is non-empty, and record its run ID.
- **False-positive telemetry:** the P2 artifact `security-gate-findings` → `secret-scan-telemetry.json`, one per run.
- **Storage:** `reports/rollout/<yyyy-mm-dd>/` (P3), plus the artifact retention window.
- **No `quality-gates/audit/` path is used.** That directory does not exist; the data sources above replace it.

### 4.2 Shadow exit gates (all must hold — option b only)

| Gate | Threshold | Measurement |
|---|---|---|
| S-EXIT-1 Producer smoke | Each of the **5** producers has ≥1 verified cycle: PR → all present checks green → independent review → merge (producer 5: verified **blocked** PR) | audit ledger rows with PR/run IDs |
| S-EXIT-2 False positives | FP rate **≤ 5%** over the trailing 14-day window, denominator ≥ 10 secret findings | §8.2 |
| S-EXIT-3 Telemetry | ≥10 PR runs carry the P2 artifact, one per merged PR minimum | artifact listing |
| S-EXIT-4 No accidental block | Zero open PRs blocked by a misnamed/absent context during shadow | `gh pr checks` on every open PR |
| S-EXIT-5 Context presence | All 14 contexts in §3 have been observed at least once on a PR head | check-run inventory |

If S-EXIT-2 has denominator < 10, shadow **extends** by 7 days (repeat until met, or the owner records a
written small-sample acceptance); it never exits on a percentage computed from a handful of hits.

---

## 5. Component 2 — Gradual enforcement (one check per step, 48 h)

> **STATUS: SUPERSEDED under option (a). Revived only under option (b).** The live ruleset already requires all
> 14 contexts at once (§0.1), bypassing this sequence. This section is the staged path a roll-back-and-resume
> would follow.

**Ordering principle:** enable the aggregate `quality gate` **last**. It is `if: always()` and fails if any
`needs` job fails (`.github/workflows/quality-gate.yml:257-278`), so enabling it first would silently enforce all six sub-jobs
at once and destroy per-check attribution. Granular contexts go first, the aggregate closes the phase.

Each step: (1) add exactly one context to the ruleset, (2) read back the config and prove the delta is one
context, (3) verify the context appears and is `pass` on a fresh PR, (4) observe ≥48 h, (5) record the
decision. Any failure → targeted removal of that one context (§9.2), never the whole ruleset.

| Step | Phase | Context enabled | Step acceptance |
|---|---|---|---|
| S1 | A | `gitflow policy validation` | delta = this context only; `gh pr checks` shows it on a fresh PR; 48 h with no unexplained block |
| S2 | A | `gitflow worktree isolation` | as S1 |
| S3 | A | `Reject external QA channel files in product main` | as S1 + a `coord/external-qa`-shaped PR is red and blocked |
| S4 | B | `backend pytest (agent-management)` | as S1 + negative probe shows red for exactly this context |
| S5 | B | `backend pytest (orchestration-server)` | as S1 |
| S6 | B | `backend pytest (quality-gates)` | as S1 |
| S7 | B | `backend pytest (runtime-hardening)` | as S1 |
| S8 | B | `backend pytest (tools)` | as S1 + phase-B negative probe |
| S9 | C | `frontend (typecheck + tests + build)` | as S1 |
| S10 | C | `lint (eslint)` | as S1 |
| S11 | C | `security scan (quality-gates)` | as S1 + phase-C negative probe; FP band ≤5% |
| S12 | D | `packaging (clean Python install)` | as S1 |
| S13 | D | `Native LLM-tool-Contract Gate (offline)` | as S1 + phase-D negative probe |
| S14 | E | `quality gate` (aggregate) | as S1 + aggregate goes red when one sub-check is red |
| F | F | required approval (independent reviewer) | §3.3-independent reviewer; negative matrix §9.4 rows 4 and 7 proven with real IDs |

Per-step config readback:

```bash
R=askarahodov/multi-agent-workflow; ID=26129824
gh api repos/$R/rulesets/$ID --jq '.rules[] | select(.type=="required_status_checks") | .parameters.required_status_checks[].context'
```

The diff between consecutive readbacks must be exactly one added line. Anything else aborts the step.

Per-phase negative probe (6 total, not 14): a throwaway PR on `rollout/negative-probe` carries a commit that
fails the phase's representative check; the run ID and red check are recorded, then the branch is reset.
Between probes, presence + readback + 48 h + zero unexplained blocks is the acceptance.

---

## 6. Component 3 — Agent notification schedule

> **STATUS: HOLDS under both options.** Channels are existing surfaces (no event bus exists — see below).

There is no "agent-management event bus": `runtime-hardening/hardening/README.md:37` documents an AsyncAPI
*contract* only, and `docs/adr/ADR-010-multi-agent-orchestration.md:499` explicitly defers an event bus.

**Channels:** (1) a comment on the issue-44 rollout card, (2) a comment on the active Kanban card of each
affected producer, (3) a comment on GitHub issue #44. Each send is recorded in
`docs/security/rollout-audit-log.md` with date, author, channel and comment ID/permalink; acknowledgement is a
reply on the same thread. Missing acknowledgement holds that producer's phase, not the whole rollout.

**Immediate item (both options):** a single announcement of the **live-state change** (§0) is owed now — the
ruleset became active on 2026-10-29 without a preceding notice. Record it as the ledger row for the live
change, authored by `sdlc-security`, dated 2026-10-30, cross-linking PR #188 and this document.

**Per-phase calendar (T-7 before each phase):**

| Phase | Steps | Send date (T-7) | Sender | Channel | Tracking record |
|---|---|---|---|---|---|
| Live-state notice | — | 2026-10-30 | sdlc-security | rollout card + producer cards + issue #44 | ledger row + permalinks |
| A (gitflow + isolation) | S1–S3 | T-7 before S1 | sdlc-planner | rollout card + producer cards + issue #44 | ledger row + permalinks |
| B (backend matrix) | S4–S8 | T-7 before S4 | sdlc-planner | producer cards (5) + issue #44 | ledger row + permalinks |
| C (frontend/lint/security) | S9–S11 | T-7 before S9 | sdlc-security | producer cards + issue #44 | ledger row + permalinks |
| D (packaging/native) | S12–S13 | T-7 before S12 | sdlc-security | producer cards + issue #44 | ledger row + permalinks |
| E (aggregate) | S14 | T-7 before S14 | sdlc-security | producer cards + issue #44 | ledger row + permalinks |
| F (approval) | F | T-7 before F | sdlc-security | issue #44 + owner | ledger row + owner ack |

Every message states: exact context strings, enable date, rollback triggers (§9.1), and the audit contact.
Dates are anchored to the chosen option: under option (b) the S1 date is set after shadow exit; under option
(a) only the live-state notice applies.

---

## 7. Component 4 — Emergency bypass procedure (documented, audited)

> **STATUS: HOLDS under both options.** Updated for the live ruleset's bypass posture:
> **`bypass_actors=[]` and `current_user_can_bypass="never"`** — there is **no** standing bypass actor, so a
> bypass can only be performed by an admin **ruleset edit**. There are no pre-issued tokens; the "token" is a
> time-boxed context removal.

### 7.1 Who may bypass, and how

Only the repository owner `askarahodov` (admin) can edit ruleset `26129824`. Agents and non-owner humans cannot
bypass a required check. There is no `--no-verify`-style path through the server-side ruleset.

### 7.2 Trigger conditions (bypass is permitted ONLY for these)

| ID | Trigger | Example |
|---|---|---|
| B1 | A required check is **broken at the infrastructure level** (workflow outage, runner failure) and cannot be made green, while a security-critical hotfix is needed | Actions incident; every PR fails one check for non-code reasons |
| B2 | A required check reports a **confirmed false positive** that blocks a legitimate merge and cannot wait for a normal fix cycle | mis-named/absent context blocking all PRs after a rename |
| B3 | A **P0 incident response** requires an immediate merge and the checks cannot complete in time | active exploitation; credential rotation |

**Not permitted:** routine convenience, agent speed, avoiding a slow check, or any reason that is really a
normal fix. Any non-B1/B2/B3 use is itself a post-incident finding.

### 7.3 Approval chain and time box

```
requester (producer owner / incident commander)
  → approver: repository owner askarahodov   (sole approver; admin ruleset edit)
  → executor: sdlc-security                  (applies the ruleset edit)
  → verifier: sdlc-reviewer                  (readback + restore proof)
```

- **Time-limited bypass token:** the bypass IS the temporary removal of **one** named context from ruleset
  `26129824`, never the whole ruleset, with a **hard TTL of 4 h**. The pre-bypass ruleset JSON is saved and
  its `sha256` recorded; restore within 4 h is mandatory.
- If not restored within 4 h, the bypass auto-escalates (owner paged; incident opened).

### 7.4 Audit log format (`docs/security/rollout-audit-log.md`, one row per action)

| Field | Content |
|---|---|
| `timestamp_utc` | ISO-8601 |
| `trigger_class` | `B1` / `B2` / `B3` |
| `incident_id` | issue/card ID |
| `approver` | GitHub login (must be `askarahodov`) |
| `executor` / `verifier` | GitHub login(s) |
| `ruleset_id` | `26129824` |
| `context_removed` | exact string (§3) |
| `pr_or_branch` | PR # / branch |
| `ruleset_sha256_before` / `_after` | saved-JSON hashes |
| `restore_timestamp_utc` / `restore_evidence` | readback hash == pre-bypass |
| `post_review_link` | §7.5 record |

Trail = GitHub audit log + this ledger + a comment on issue #44.

### 7.5 Post-bypass review (mandatory, within 24 h)

`t_reviewer` verifies: the ruleset was restored (readback `sha256` equals the saved pre-bypass hash), the
bypassed PR's context was later run green **or** the change was reverted, and the bypass reason is documented.
If the root cause is a real defect (e.g. a mis-named context), a fix card is opened. A bypass that is not
reviewed within 24 h is an escalation.

---

## 8. Component 5 — Metrics dashboard (grounded data only)

> **STATUS: HOLDS under both options.**

| Metric | Definition | Source (exists?) |
|---|---|---|
| Violation rate | failed runs per required context / PRs carrying that context, per producer | `gh api repos/$R/commits/<sha>/check-runs` — **exists**; dedupe push/PR pair by non-empty `pull_requests` |
| False-positive rate | §8.2 formula, trailing 14 d | P2 artifact `secret-scan-telemetry.json` — **created by P2** |
| Adaptation effort | commits between first red and green per new check (named "effort", not "time") | PR commit list between the two runs; target ≤3 cycles, based on 7 commits / 3 cycles on `fd3cb4e` (`EVIDENCE_BRIEF.md`) |
| Producer smoke pass rate | verified PR → green → review → merge per producer | audit ledger |

Mirror: `reports/rollout/<date>/` (P3); artifact retention is the GitHub default (90 days). Nothing is read
from `quality-gates/audit/` because it does not exist.

### 8.1 Data source reality check (fixes the earlier review item)

`quality-gates/audit/` and a per-run artifact upload in `quality-gate.yml` **do not exist**; the dashboard is
sourced from the check-runs API (violations, adaptation) and the P2 artifact (false positives). P2 creates the
only missing source.

### 8.2 False-positive rate — definition

```
FP rate = fixture_classified_secret_hits / total_secret_hits      (both counted BEFORE allowlisting)
```

- **Numerator:** secret hits in one run that the allowlist classifies as deliberate test fixtures.
- **Denominator:** all secret hits the scanner produced in that run, including the ones later allowlisted.
- **Explicitly excluded from both:** files skipped before scanning, i.e. `SKIP_FILES` basenames
  (`.gitignore`, `.env.example`, `.env.sample`, `.env.template` — `quality-gates/quality_gates/gates/security.py:36`, skipped at
  `quality-gates/quality_gates/gates/security.py:94`). They produce no hit and cannot be measured.
- **Window:** trailing 14 days, per run, aggregated as Σnumerator / Σdenominator.
- **Source:** P2 `secret-scan-telemetry.json` artifacts. No manual estimate.

The original draft's metric was structurally zero (it divided "hits in `SKIP_FILES` paths" by "total hits", but
`SKIP_FILES` files are never scanned). The real 100% FP observation in `EVIDENCE_BRIEF.md` §6 (`t_1200c66e`)
comes from fixture files that are **not** in `SKIP_FILES`.

---

## 9. Component 6 — Rollback triggers and procedures

> **STATUS: HOLDS under both options — and is the CENTRAL component under option (a).** Updated for the live
> ruleset (`id 26129824`, `bypass_actors=[]`, `required_approving_review_count=0`).

### 9.1 Triggers (quantitative where possible)

| ID | Trigger | Action | Authority |
|---|---|---|---|
| a | A producer's PR cannot merge because of a check it previously passed | remove the most recently enabled context | owner authorizes / sdlc-security executes |
| b | FP rate **> 20%** over the trailing 14-day window, or ≥2 consecutive PRs from one producer fail on the same check with fixture-classified hits | remove `security scan (quality-gates)`, hold phase | owner authorizes |
| c | Ruleset and `.github/workflows/gitflow-policy.yml:175-181` diverge | revert the ruleset change; re-sync before continuing | owner authorizes |
| d | Any **open** PR at change time is blocked by a misnamed/absent context | remove that context; correct the name | sdlc-security executes |
| e | Zero independent reviewer identity available at step F | stop before F, not after | owner |
| f | A **critical CI failure** (workflow outage, runner pool down) makes a required check ungreenable for all PRs | apply §7 bypass for the affected context | owner (B1) |

**Precedence between the FP thresholds:** **>20% → rollback; 5% < rate ≤ 20% → hold (no new step, no rollback
unless trigger b's consecutive condition fires); ≤5% → eligible to advance.** Shadow exit uses the same bands
(it cannot exit above 5%). **Trigger c is currently FIRING** (live ruleset 14 vs in-repo env 11, §3.3) and is
resolved by P5.

### 9.2 Rollback steps per option

**Option (a) — live all-at-once:** there are no phases, so rollback is a **targeted context removal**. Remove
exactly the failing context(s) from ruleset `26129824`; keep all others. Never delete the ruleset as the default
rollback.

```bash
R=askarahodov/multi-agent-workflow; ID=26129824; CTX='quality gate'
gh api repos/$R/rulesets/$ID > /tmp/ruleset.json
jq --arg c "$CTX" '(.rules[] | select(.type=="required_status_checks")
  | .parameters.required_status_checks) |= map(select(.context != $c))' \
  /tmp/ruleset.json > /tmp/ruleset.minus.json
gh api --method PUT repos/$R/rulesets/$ID --input /tmp/ruleset.minus.json
```

Restore is the symmetric add (or `PUT` of the saved baseline JSON):

```bash
gh api --method PUT repos/$R/rulesets/$ID --input evidence/rollout-baseline-2026-10-30T0610Z-ruleset-26129824.json
```

There is **no** standing bypass actor (`bypass_actors=[]`, `current_user_can_bypass="never"`), so every removal
requires an admin ruleset edit by the owner — this is why emergency use is governed by §7. Classic
branch-protection calls do **not** apply (classic protection is 404; all enforcement is the ruleset).

**Option (b) — staged:** rollboard = step back one S-step (remove the single most recently added context);
re-observe 48 h; re-advance only after the trigger's fix is verified. Full ruleset deletion is the
last-resort step, owner-authorized only when option (b) is abandoned.

**Rollback owner:** `askarahodov` (authorizes) → `sdlc-security` (executes) → `sdlc-reviewer` (verifies
readback and re-runs the negative/positive rows). **Time budget: 4 h from trigger.**

### 9.3 Rehearsal (P7) — before any further enforcement action

On a throwaway branch and a ruleset scoped **only** to `rollout/rehearsal` (never `main`):

1. require one context on `rollout/rehearsal`;
2. open a correct PR → merge allowed; open a failing PR → merge blocked (record PR + run IDs);
3. run the §9.2 removal for that context → the previously blocked PR becomes mergeable;
4. restore → it blocks again;
5. delete the rehearsal ruleset; verify `main` config is byte-identical to the saved baseline (`sha256`).

Record in `evidence/rollout-rollback-rehearsal-<date>.md`: branch, ruleset ID, PR numbers, run IDs,
before/after config hashes, operator, verifier. **No placeholder is acceptable** — the file ships with real IDs.
The rehearsal is a **separately authorized** ruleset action (it creates a throwaway ruleset on a
non-`main` branch); this document performs none of it.

### 9.4 Post-change verification matrix (same matrix as `main-protection-rollout-issue-44.md` §6)

| Row | Scenario | Expected | Evidence |
|---|---|---|---|
| 1 | PR without a required context | merge blocked | PR #, run ID |
| 2 | PR with failing context | merge blocked | PR #, run ID |
| 3 | PR with pending/cancelled/skipped required context | merge blocked | PR #, run ID |
| 4 | PR without independent approval | merge blocked | PR # |
| 5 | Direct worker write to `main` | rejected (no force) | push attempt ID |
| 6 | Force push / branch deletion | rejected | attempt ID |
| 7 | Green PR + independent approval | merge allowed | PR #, run ID |
| 8 | PR adding `.coordination/external-qa/**` | isolation check red, blocked | PR #, run ID |
| 9 | Push to `coord/external-qa` | still works | branch SHA |

**Live caveat:** rows 4 and 7 depend on an independent-approval check, but `required_approving_review_count=0`
in the live ruleset, so row 4 would **currently not block**. This is gap **G5** (§10), closed by P6.

### 9.5 Communication plan on rollback

On any rollback: (1) comment on issue #44 and the rollout card within 1 h; (2) comment on every affected
producer card; (3) write a ledger row (§7.4); (4) state which context(s) changed and the new required set.

---

## 10. Prerequisites and outstanding gaps

**Prerequisites** close the data/governance gaps; **gaps** are blockers to advancing to full enforcement.
This section replaces the earlier P1–P7 / G1–G4 tables, re-baselined to the live state.

### 10.1 Prerequisites

| ID | Deliverable | Owner | Acceptance | Status (2026-10-30) |
|---|---|---|---|---|
| **P1** | Given **PR evidence now exists**: `gitflow policy validation` ran on PR #188 (run `40893716138`, success). Confirm `gitflow worktree isolation` also publishes on a PR head. | sdlc-security / sdlc-reviewer | both gitflow contexts observed `pass` on a PR head; PR/run IDs in the ledger | **partially satisfied** by PR #188; confirm context #2 |
| **P2** | Secret-scan telemetry artifact (`secret-scan-telemetry.json`: `total_secret_hits`, `fixture_hits`, `real_hits`, per-hit `{file,pattern,reason}`; uploaded `if: always()`) | sdlc-developer / sdlc-security | one real run ID whose artifact downloads and parses | **open** |
| **P3** | Rollout data dir + query harness (`reports/rollout/`) | sdlc-tester / sdlc-planner | dir exists with §8 queries, no secrets | **open** |
| **P4** | Single source of truth for fixture allowlisting (promote `FIXTURE_PATH` from `scripts/security_scan.py:34-44` into `security.py`, with positive/negative test; `pytest quality-gates/tests -q` green) | sdlc-developer / sdlc-security | classifier shared by both call sites; test proves fixture vs. non-fixture classification | **open** |
| **P5** | **Sync in-repo `REQUIRED_CHECKS` 11 → 14** (`.github/workflows/gitflow-policy.yml:175-181` == §3.1) | sdlc-security / sdlc-reviewer | env equals the 14-context set; `gitflow required checks` passes | **open (trigger c firing)** |
| **P6** | Independent reviewer identity (named GitHub user/team, distinct from every producer, documented in `docs/security/rollout-audit-log.md`) — needed to make row 4 enforceable | repository owner `askarahodov` | named identity with write access, recorded | **open (G3/G5)** |
| **P7** | Rollback rehearsal (§9.3) with real IDs | sdlc-security / sdlc-reviewer / owner authorizes | evidence file with real PR/run IDs and config hashes | **open** |

### 10.2 Gaps blocking full enforcement ("READY")

- **G1 —** No producer has a completed verified PR cycle. *(Governance blocker `EVIDENCE_BRIEF.md` §8; the
  earlier "review item #8" citation was wrong — item 8 in §4 is orphaned `src/mvp/**` WIP.)*
  **Status: still open.** **Now more urgent under option (a):** the live ruleset can already block all 5 producers.
- **G2 —** ~~P1 has not yet proven that the two gitflow contexts publish on PRs (0 PR runs).~~
  **RESOLVED:** `gitflow-policy.yml` now has 4 runs including PR run `40893716138` (`pull_request`, success,
  PR #188). Context #1 (`gitflow policy validation`) is proven; context #2 (`gitflow worktree isolation`) still
  needs a PR-head observation.
- **G3 —** P6 independent reviewer identity unassigned. **Open.**
- **G4 —** P2 telemetry not merged, so FP rate (S-EXIT-2 / metric §8.2) cannot be measured. **Open.**
- **G5 (new) —** Live ruleset `required_approving_review_count=0`, so there is currently **no independent-approval
  requirement**; matrix rows 4 and 7 (§9.4) would not block. Closed by P6. **Open.**

**Non-blocking hardening** carried from `EVIDENCE_BRIEF.md` §4 / review `t_a7116377` (fix before final
enforcement, tracked as separate cards, not rollout steps): KEK production guard, WebSocket key transport,
release-approval role elevation, TLS/HSTS tests wired into per-service CI, `src/mvp/**` orphan disposition.
Residual security findings from audit `t_9cf50bae` (`SEC-001/007/008/009`, `--no-verify` and policy-tampering
vectors) are addressed **operationally** by the server-side ruleset (this plan is that mitigation) and remain on
the security card.

---

## 11. Timeline, owners, success criteria

### 11.1 Per option

| Option | Work | Owner | Window | Success criteria |
|---|---|---|---|---|
| **(a)** verify/rollback | Close P2/P4/P5/P6/P7; run matrix §9.4 with real IDs; stand up metrics/notifications | owner + sdlc-security + sdlc-reviewer | from 2026-10-30 | 14-context set verified green-and-red; FP measurable ≤5%; rows 4/7 enforceable (P6); ruleset/env synced; rollback rehearsed |
| **(b)** resume staged | Roll back `26129824` (owner-authorized) → P1–P7 → shadow (14 d) → S1–S14 (+48 h each) → F | owner + sdlc-planner + sdlc-security + sdlc-reviewer | ~2026-11-02 → 2027-01 | S-EXIT-1…5 then per-step acceptance; final ruleset = 14 contexts, each proven green-and-red |

### 11.2 Common success definition

`main` protected; all 14 contexts required and proven green-and-red with real PR/run IDs; rollback rehearsed
and restored; FP rate ≤5% on measured data; **5/5** producers verified; audit trail complete.

**Not success:** merging this plan, or changing ruleset `26129824`, without P1–P7 and an explicit owner
decision between options (a) and (b).

---

## 12. Change log

### v3 — 2026-10-30 re-baseline (this revision)

| Review correction (`t_e527c2c3` round 1, *changes_requested*) | Resolution in this file |
|---|---|
| 1 Re-baseline §0 to the live state with fresh timestamp + evidence | §0, all six evidence files hashed |
| 2 Reframe header + shadow section: enforcement already active; shadow + S1–S14 superseded; state what still holds | "READ FIRST" box; §4/§5 marked superseded (option b only); retained value stated (verification, rollback, metrics, notifications, gaps) |
| 3 Update G2 (no longer "0 PR runs") and P1/P5 wording assuming no enforcement | §10.2 G2 marked RESOLVED; §10.1 P1 partially satisfied; §3.3 + P5 updated for the live 11-vs-14 divergence |
| 4 Surface — do not decide — the owner's two options | §1 presents (a) and (b), picks neither |
| 5 Keep all six components; file at repo root; re-gate the new hash | §4–§9 carry Components 1–6; file at root; re-gating is the reviewer's next step |

### v2 — 2026-10-29 rwork (prior revision, now superseded)

| Review item | Resolution |
|---|---|
| 1 real contexts | §3.1 exact strings + PR #187 evidence; job ids dropped |
| 2 conditional Compose gate | §3.2 excluded; limitation documented |
| 3 one-by-one | §5, 14 single-check steps, aggregate last |
| 4 set consistency | §3.3 P5 sync commit with exact `REQUIRED_CHECKS` |
| 5 tested rollback | §9.2 commands, §9.3 rehearsal, §9.4 matrix, named owner |
| 6 FP metric | §8.2 measurable definition, window, source, exclusions |
| 7 FP mitigation | P4 code change with tests; SEC-007 attribution removed |
| 8 FP gate | §4.2 S-EXIT-2 + §9.1 precedence bands |
| 9 notifications / step F | §6 real channels + table; P6 and correct §8 citation |
| 10 dashboard | §8; `quality-gates/audit/` dropped, P2 artifact + check-runs API |
