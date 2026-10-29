# ROLLOUT_PLAN.md — Staged Enforcement of Branch Protection on `main` (Issue #44)

**Status:** REWORKED per quality review `t_cf1bc31e` (verdict: changes_requested, 9 blocking items).
**Owner:** sdlc-planner. **Enforcement owner:** repository owner `askarahodov`. **Operator:** sdlc-security.
**Baseline date:** 2026-10-29. **Supersedes:** the 44-line draft (`sha256 69b69006…`) and every copy under
`.worktrees/*/ROLLOUT_PLAN.md` (notably the divergent 197-line `.worktrees/t_e527c2c3/ROLLOUT_PLAN.md`).

> **Single authoritative file.** This root-level `ROLLOUT_PLAN.md` is the only version-controlled rollout plan.
> Copies in other worktrees are snapshots and must not be edited or merged. Any change to the plan is a commit
> to this file on its card branch.

> **This document changes no enforcement state.** It writes no ruleset, edits no CI workflow, and enables no
> required check. All GitHub/CI changes it schedules are executed by the named owner after this plan is approved.
> Baseline facts below were captured read-only.

---

## 0. Verified baseline (captured, not assumed)

Evidence: `evidence/rollout-baseline-2026-10-29.json`
(`sha256 f81a93869d1312623a8fb369feb9cda44b7210073f9778101402254c1fd3aa9c`), produced with:

```bash
gh api repos/askarahodov/multi-agent-workflow/branches/main
gh api repos/askarahodov/multi-agent-workflow/rulesets
gh api repos/askarahodov/multi-agent-workflow/branches/main/protection/required_status_checks
```

| Fact | Value | Source |
|---|---|---|
| `main` protected | `false` | branch API, 2026-10-29 |
| Rulesets | `[]` | rulesets API, 2026-10-29 |
| Classic required status checks | 404 (not configured) | branch protection API |
| `main` HEAD at capture | `e01efa18ae837c61c4f6dcdf3864fcfd926717c8` | branch API |
| Open PRs #1/#79/#87/#88 | **all `CLOSED`** (stale trigger from the 16.10 doc) | `gh pr view <n>` |

Required-check names below were verified against a real PR head, not inferred from YAML:
`evidence/rollout-checkrun-inventory-pr187.json`
(`sha256 e0e7b7006b643af372660517cf8eea92d01a01bcdf558f4b9c004c8e256f0a8d`), PR #187 @ `b3933ed0…`:
32 check runs, 21 unique names.

Two facts from that inventory drive the whole plan:

1. Every `quality-gate.yml` check appears **twice** per head SHA because the workflow triggers on both
   `push` and `pull_request` (`.github/workflows/quality-gate.yml:17-18`). Required-check evidence must name the run ID,
   not just the context name.
2. `ci.yml` publishes **case-variant near-duplicates** of the quality-gate contexts —
   `Backend pytest (…)`, `Frontend (typecheck + vitest)`, `Lint (eslint)` — alongside the lower-case
   `backend pytest (…)`, `frontend (typecheck + tests + build)`, `lint (eslint)`. Only the
   `quality-gate.yml` names may be used; the `ci.yml` names are a different, overlapping check set.

A third fact is a hard preflight gate: `.github/workflows/gitflow-policy.yml` landed on `main` in
`2a5c6bd` at **2026-10-29 15:10 MSK**, after every recent PR merged. As of capture it has **zero
`pull_request` runs** (`gh api .../actions/workflows/gitflow-policy.yml/runs` → one `push` run,
`40886671372`). Its contexts `gitflow policy validation` / `gitflow worktree isolation` therefore have
**no PR check-run evidence** and must be proven by a smoke PR before being made required.

---

## 1. Prerequisites (must close before shadow starts)

Shadow collection is worthless if its data source does not exist. These six items are scheduled work,
not assumptions. **Shadow start is gated on P1–P4; enforcement start is gated on P1–P6.**

| ID | Deliverable | Files | Owner / reviewer | Due | Acceptance (objective) |
|---|---|---|---|---|---|
| **P1** | Proving PR for the two gitflow contexts | none (throwaway PR from `rollout/check-probe`) | sdlc-security / sdlc-reviewer | 2026-11-02 | `gh pr checks <PR>` lists `gitflow policy validation` and `gitflow worktree isolation` as `pass`; the PR number, head SHA and run IDs are recorded in the audit ledger. If absent, fix `gitflow-policy.yml` triggers **before** any enablement. |
| **P2** | Secret-scan telemetry artifact | `scripts/security_scan.py`, `.github/workflows/quality-gate.yml` | sdlc-developer / sdlc-security | 2026-11-03 | `security_scan.py` writes `secret-scan-telemetry.json` with `total_secret_hits`, `fixture_hits`, `real_hits`, and per-hit `{file, pattern, reason}`; `security` job uploads it via `actions/upload-artifact@v4` (`name: security-gate-findings`, `if: always()`). Verified by one real run ID whose artifact downloads and parses. |
| **P3** | Rollout data directory + query harness | `reports/rollout/README.md`, `reports/rollout/queries.md` | sdlc-tester / sdlc-planner | 2026-11-03 | `reports/rollout/` exists with the two documented `gh api` queries from §7 and no secrets. |
| **P4** | Single source of truth for fixture allowlisting | `quality-gates/quality_gates/gates/security.py`, `scripts/security_scan.py`, `quality-gates/tests/` | sdlc-developer / sdlc-security | 2026-11-04 | Fixture classification is one exported constant/function in `security.py`; `security_scan.py` imports it instead of duplicating `FIXTURE_PATH` (`scripts/security_scan.py:34-44`). Unit test proves (a) a fixture-shaped token under `quality-gates/tests/` is classified fixture, (b) the same token outside a fixture path still fails the gate. `python -m pytest quality-gates/tests -q` green. |
| **P5** | Sync the in-repo authoritative required-check list | `.github/workflows/gitflow-policy.yml:175-181` | sdlc-security / sdlc-reviewer | 2026-11-05 | The `REQUIRED_CHECKS` env equals the 14-context set in §4 exactly (diff shown in §4.3), and `gitflow required checks` passes on the sync PR. |
| **P6** | Independent reviewer identity | governance record; no code | repository owner `askarahodov` | 2026-11-06 | A named GitHub user/team, distinct from every producer identity, with write access and documented in `docs/security/rollout-audit-log.md`. Required for step F; blocks enforcement if absent. |
| **P7** | Rollback rehearsal | `evidence/rollout-rollback-rehearsal-<date>.md` | sdlc-security executes / sdlc-reviewer verifies / owner authorizes | 2026-11-05 | §6.3 rehearsal executed end-to-end on a throwaway branch with real PR and run IDs recorded; restore verified. |

---

## 2. Producers (5 PR producers + 1 bypass path)

`admin` is **not** a PR producer. It is the emergency bypass path and is governed by §5, excluded from the
"all producers smoke-tested" criterion. The count is **5** everywhere in this plan.

| # | Producer | Branch pattern | Smoke criterion | External QA exception |
|---|---|---|---|---|
| 1 | Manual product changes | `feat/*`, `fix/*`, `docs/*`, `security/*` | PR → green → independent review → merge | — |
| 2 | Local Kanban / worktree agents | `wt/t_*` | same | — |
| 3 | Native product workers | `feat/issue-*`, `fix/issue-*` (ownership unproven) | same | — |
| 4 | Dependabot | `dependabot/*` | same | — |
| 5 | External QA | `coord/external-qa` | PR **blocked** by `Reject external QA channel files in product main`; never merged | Expected outcome is a red check, not a merge |

---

## 3. Shadow mode — 2 weeks, warn-only

**Planned window:** 2026-11-09 00:00 MSK → 2026-11-23 00:00 MSK (14 days), gated on P1–P4.
`main` stays `protected=false`; no context is marked required. Zero merge blocks.

### 3.1 Violation collection (data sources that exist)

- **Per-context, per-producer violations:** `gh api repos/$R/commits/<head_sha>/check-runs?per_page=100`.
  Attribute a producer from the PR head ref prefix per §2. Deduplicate the `push`/`pull_request` pair by
  keeping the run whose `pull_requests` array is non-empty, and record its run ID.
- **False-positive telemetry:** the P2 artifact `security-gate-findings` →
  `secret-scan-telemetry.json`, one per run.
- **Storage:** `reports/rollout/<yyyy-mm-dd>/` (P3), plus the artifact retention window.
- **No `quality-gates/audit/` path is used.** That directory does not exist and `quality-gate.yml` had no
  artifact-upload step; both are replaced by the data sources above. (Creating it is not required.)

### 3.2 Shadow exit gates (all must hold)

| Gate | Threshold | Measurement |
|---|---|---|
| S-EXIT-1 Producer smoke | Each of the **5** producers has ≥1 verified cycle: PR → all present checks green → independent review → merge (producer 5: verified **blocked** PR) | audit ledger rows with PR/run IDs |
| S-EXIT-2 False positives | FP rate **≤ 5%** over the trailing 14-day window, denominator ≥ 10 secret findings | §3.3 |
| S-EXIT-3 Telemetry | ≥10 PR runs carry the P2 artifact, one per merged PR minimum | artifact listing |
| S-EXIT-4 No accidental block | Zero open PRs blocked by a misnamed/absent context during shadow | `gh pr checks` on every open PR |
| S-EXIT-5 Context presence | All 14 contexts in §4 have been observed at least once on a PR head | check-run inventory |

If S-EXIT-2 has denominator < 10, shadow **extends** by 7 days (repeat until met or the owner records a
written small-sample acceptance); it never exits on a percentage computed from a handful of hits.

### 3.3 False-positive rate — definition (fixes review item 6)

```
FP rate = fixture_classified_secret_hits / total_secret_hits      (both counted BEFORE allowlisting)
```

- **Numerator:** secret hits in one run that the allowlist classifies as deliberate test fixtures.
- **Denominator:** all secret hits the scanner produced in that run, including the ones later allowlisted.
- **Explicitly excluded from both:** files skipped before scanning, i.e. `SKIP_FILES` basenames
  (`.gitignore`, `.env.example`, `.env.sample`, `.env.template` — `quality-gates/quality_gates/gates/security.py:36`, skipped at
  `quality-gates/quality_gates/gates/security.py:94`). They produce no hit and cannot be measured; they are not part of the metric.
- **Window:** trailing 14 days, per run, aggregated as Σnumerator / Σdenominator.
- **Source:** P2 `secret-scan-telemetry.json` artifacts. No manual estimate.

Why the draft's metric was structurally zero: it divided "hits in `SKIP_FILES` paths" by "total hits", but
`SKIP_FILES` files are never scanned, so the numerator is always 0. The real 100% FP observation in
`EVIDENCE_BRIEF.md` §6 comes from fixture files that are **not** in `SKIP_FILES`.

### 3.4 False-positive mitigation (fixes review item 7, implementable)

The draft's "`SKIP_FILES` updated for test fixtures" cannot work: `SKIP_FILES` is an exact-basename set,
so it cannot express `quality-gates/tests/…`. The repo already solves this one layer up:
`scripts/security_scan.py:34-44` defines `FIXTURE_PATH` and allowlists
`tests?|e2e|fixtures?|__fixtures__` plus `test_*.py` / `*.spec.ts(x)`. That allowlist is CI-only; the
`SecurityGate` itself still reports the 5 fixture hits.

**P4** is therefore the mitigation: promote the wrapper's classification into `security.py` as the single
exported classifier used by both call sites, with the positive/negative unit test above. It is scheduled
before shadow starts so the metric and the gate agree from day one. There is **no** SEC-007 attribution:
SEC-007 is stale/tampered policy bundles between distribution and validation (finding SEC-007 in
`SECURITY_AUDIT.md`), unrelated to fixture false positives.

---

## 4. Required-check set (fixes review items 1 and 4)

### 4.1 Exact contexts, verified on PR #187

| # | Context (exact string) | Workflow:line | Required-set status |
|---|---|---|---|
| 1 | `gitflow policy validation` | `.github/workflows/gitflow-policy.yml:29` | in authoritative set; **0 PR evidence** → P1 |
| 2 | `gitflow worktree isolation` | `.github/workflows/gitflow-policy.yml:128` | in authoritative set; **0 PR evidence** → P1 |
| 3 | `Reject external QA channel files in product main` | `.github/workflows/coordination-isolation.yml:14` | new to authoritative set |
| 4 | `backend pytest (agent-management)` | `.github/workflows/quality-gate.yml:25` + matrix `:31` | authoritative |
| 5 | `backend pytest (orchestration-server)` | `.github/workflows/quality-gate.yml:25` + matrix `:32` | authoritative |
| 6 | `backend pytest (quality-gates)` | `.github/workflows/quality-gate.yml:25` + matrix `:33` | authoritative |
| 7 | `backend pytest (runtime-hardening)` | `.github/workflows/quality-gate.yml:25` + matrix `:34` | authoritative |
| 8 | `backend pytest (tools)` | `.github/workflows/quality-gate.yml:25` + matrix `:35` | authoritative |
| 9 | `frontend (typecheck + tests + build)` | `.github/workflows/quality-gate.yml:199` | authoritative |
| 10 | `lint (eslint)` | `.github/workflows/quality-gate.yml:223` | authoritative |
| 11 | `security scan (quality-gates)` | `.github/workflows/quality-gate.yml:241` | authoritative |
| 12 | `packaging (clean Python install)` | `.github/workflows/quality-gate.yml:52` | new to authoritative set |
| 13 | `Native LLM-tool-Contract Gate (offline)` | `.github/workflows/native-agent-e2e.yml:14` | new to authoritative set |
| 14 | `quality gate` | `.github/workflows/quality-gate.yml:258` | authoritative; **enabled last** |

Rejected names from the draft: `packaging` and `compose-smoke` are **job ids**, not check names; using them
creates required contexts that no run ever reports, blocking every merge.

Observed but **not** gated in this rollout (outside the issue-44 §5 candidate set): `gitflow required checks`,
`Secure QA TLS / RBAC / SQLite Compose (offline live)`. Adding either is an owner decision, not part of this plan.

### 4.2 `local Compose build and health` — excluded, with the limitation documented (item 2)

The job runs on every PR, but its build/health steps are conditional on "Detect Compose-related changes"
(`.github/workflows/quality-gate.yml:74`, `:97`, `:105`, `:119`), so on a non-Compose PR it reports green without building
anything. Only the static overlay-policy step (`:99-103`) is unconditional. Making this context required
would therefore give false assurance on the majority of PRs.

**Decision:** excluded from the required set (matching `.github/workflows/gitflow-policy.yml:175-181`). If the owner later wants
Compose coverage enforced, the prerequisite is a dedicated always-running step that fails on config drift
(owner: sdlc-developer, new card, not this rollout). Until then, Compose validation is advisory.

### 4.3 Keeping the two lists in sync (item 4)

`.github/workflows/gitflow-policy.yml:175-181` is the in-repo authoritative set. P5 updates it in one commit to exactly the
14 contexts §4.1 lists:

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

Rule: the GitHub ruleset and this env var are changed in the same PR, or the ruleset change is reverted.
A divergence is a rollback trigger (§6.1, trigger c).

---

## 5. Gradual enforcement — one check per step, 48 h observation (fixes review item 3)

**Ordering principle:** enable the aggregate `quality gate` **last**. It is `if: always()` and fails if any
`needs` job fails (`.github/workflows/quality-gate.yml:257-278`), so enabling it first would silently enforce all six sub-jobs
at once and destroy per-check attribution. Granular contexts go first, the aggregate closes the phase.

Each step: (1) add exactly one context to the ruleset, (2) read back the config and prove the delta is one
context, (3) verify the context appears and is `pass` on a fresh PR, (4) observe ≥48 h, (5) record the
decision. Any failure → targeted removal of that one context (§6.2), never the whole ruleset.

| Step | Phase | Context enabled | Planned date (10:00 MSK) | Step acceptance |
|---|---|---|---|---|
| S1 | A | `gitflow policy validation` | 2026-11-25 | delta = this context only; `gh pr checks` shows it on a fresh PR; 48 h with no unexplained block |
| S2 | A | `gitflow worktree isolation` | 2026-11-27 | as S1 |
| S3 | A | `Reject external QA channel files in product main` | 2026-11-30 | as S1 + a `coord/external-qa`-shaped PR is red and blocked |
| S4 | B | `backend pytest (agent-management)` | 2026-12-02 | as S1 + negative probe shows red for exactly this context |
| S5 | B | `backend pytest (orchestration-server)` | 2026-12-04 | as S1 |
| S6 | B | `backend pytest (quality-gates)` | 2026-12-07 | as S1 |
| S7 | B | `backend pytest (runtime-hardening)` | 2026-12-09 | as S1 |
| S8 | B | `backend pytest (tools)` | 2026-12-11 | as S1 + phase-B negative probe |
| S9 | C | `frontend (typecheck + tests + build)` | 2026-12-14 | as S1 |
| S10 | C | `lint (eslint)` | 2026-12-16 | as S1 |
| S11 | C | `security scan (quality-gates)` | 2026-12-18 | as S1 + phase-C negative probe; FP band ≤5% |
| S12 | D | `packaging (clean Python install)` | 2026-12-21 | as S1 |
| S13 | D | `Native LLM-tool-Contract Gate (offline)` | 2026-12-23 | as S1 + phase-D negative probe |
| S14 | E | `quality gate` (aggregate) | 2026-12-28 | as S1 + aggregate goes red when one sub-check is red |
| F | F | required approval (independent reviewer) | 2026-12-30 | §8; negative matrix §6.4 rows 4 and 7 proven with real IDs |

Per-step config readback (ruleset path; `<ID>` from the baseline snapshot):

```bash
R=askarahodov/multi-agent-workflow
gh api repos/$R/rulesets/<ID> --jq '.rules[] | select(.type=="required_status_checks") | .parameters.required_status_checks[].context'
```

The diff between consecutive readbacks must be exactly one added line. Anything else aborts the step.

Per-phase negative probe (6 total, not 14): a throwaway PR on `rollout/negative-probe` carries a commit that
fails the phase's representative check; the run ID and red check are recorded, then the branch is reset.
Between probes, presence + readback + 48 h + zero unexplained blocks is the acceptance.

---

## 6. Rollback — tested, owned, reversible (fixes review item 5)

### 6.1 Triggers

| ID | Trigger | Action |
|---|---|---|
| a | A producer's PR cannot merge because of a check it previously passed | remove the most recently enabled context |
| b | FP rate > 20% over the trailing 14-day window, or ≥2 consecutive PRs from one producer fail on the same check with fixture-classified hits | remove `security scan (quality-gates)`, hold phase |
| c | Ruleset and `.github/workflows/gitflow-policy.yml:175-181` diverge | revert the ruleset change; re-sync before continuing |
| d | Any **open** PR at change time is blocked by a misnamed/absent context | remove that context; correct the name |
| e | Zero independent reviewer identity available at step F | stop before F, not after |

Precedence between the FP thresholds (item 8): **>20% → rollback; 5% < rate ≤ 20% → hold (no new step, no
rollback unless trigger b's consecutive condition fires); ≤5% → eligible to advance.** Shadow exit uses the
same bands: it cannot exit above 5%.

### 6.2 Baseline snapshot and targeted removal/restore (exact commands)

Baseline already captured (§0). Refresh before the first change:

```bash
R=askarahodov/multi-agent-workflow; TS=$(date -u +%Y-%m-%dT%H%M%SZ)
mkdir -p evidence
gh api repos/$R/branches/main > evidence/rollout-baseline-$TS-branch.json
gh api repos/$R/rulesets     > evidence/rollout-baseline-$TS-rulesets.json
# for each ruleset id in the list:
gh api repos/$R/rulesets/<ID> > evidence/rollout-baseline-$TS-ruleset-<ID>.json
sha256sum evidence/rollout-baseline-$TS-*.json
```

Targeted removal of **one** context from the active ruleset (read–modify–PUT keeps every other field):

```bash
R=askarahodov/multi-agent-workflow; ID=<ruleset-id>; CTX='quality gate'
gh api repos/$R/rulesets/$ID > /tmp/ruleset.json
jq --arg c "$CTX" '(.rules[] | select(.type=="required_status_checks")
  | .parameters.required_status_checks) |= map(select(.context != $c))' \
  /tmp/ruleset.json > /tmp/ruleset.minus.json
gh api --method PUT repos/$R/rulesets/$ID --input /tmp/ruleset.minus.json
```

Restore is the symmetric add (or `PUT` of the saved baseline file). If classic branch protection is used
instead of a ruleset, the equivalent single-context calls are:

```bash
gh api --method DELETE repos/$R/branches/main/protection/required_status_checks/contexts \
  --input - <<< '{"contexts":["quality gate"]}'
gh api --method POST   repos/$R/branches/main/protection/required_status_checks/contexts \
  --input - <<< '{"contexts":["quality gate"]}'
```

Both forms touch one context. Never `DELETE …/protection` and never delete the ruleset as the default rollback.

**Rollback owner:** `askarahodov` (authorizes) → `sdlc-security` (executes) → `sdlc-reviewer` (verifies
readback and re-runs the negative/positive rows). Time budget: 4 h from trigger.

### 6.3 Rehearsal (P7) — must happen before S1

On a throwaway branch and a ruleset scoped **only** to `rollout/rehearsal` (never `main`):

1. require one context on `rollout/rehearsal`;
2. open a correct PR → merge allowed; open a failing PR → merge blocked (record PR + run IDs);
3. run the §6.2 removal for that context → the previously blocked PR becomes mergeable;
4. restore → it blocks again;
5. delete the rehearsal ruleset; verify `main` config is byte-identical to the saved baseline (`sha256`).

Record in `evidence/rollout-rollback-rehearsal-<date>.md`: branch, ruleset ID, PR numbers, run IDs,
before/after config hashes, operator, verifier. **No placeholder is acceptable** — the file ships with real IDs.

**Why the record is not attached to this plan:** the rework scope is document-only ("do not change
enforcement state, rulesets, or CI configuration"). Creating even a throwaway ruleset would violate that, and
inventing IDs would defeat the requirement. P7 is the execution card that produces the real record before S1.

### 6.4 Post-rollback verification (same matrix as `main-protection-rollout-issue-44.md` §6)

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

---

## 7. Metrics dashboard — grounded data only (fixes review item 10)

| Metric | Definition | Source (exists?) |
|---|---|---|
| Violation rate | failed runs per required context / PRs carrying that context, per producer | `gh api repos/$R/commits/<sha>/check-runs` — **exists**; dedupe push/PR pair by non-empty `pull_requests` |
| False-positive rate | §3.3 formula, trailing 14 d | P2 artifact `secret-scan-telemetry.json` — **created by P2** |
| Adaptation effort | commits between first red and green per new check (named "effort", not "time") | PR commit list between the two runs; target ≤3 cycles, based on 7 commits / 3 cycles on `fd3cb4e` |
| Producer smoke pass rate | verified PR → green → review → merge per producer | audit ledger |

Mirror: `reports/rollout/<date>/` (P3); artifact retention is the GitHub default (90 days). Nothing is read
from `quality-gates/audit/` because it does not exist.

---

## 8. Notifications — one row per phase, channels that exist (fixes review item 9)

There is no "agent-management event bus": `runtime-hardening/hardening/README.md:37` documents an AsyncAPI
*contract* only, and `docs/adr/ADR-010-multi-agent-orchestration.md:499` explicitly defers an event bus.

**Channels:** (1) a comment on the issue-44 rollout card, (2) a comment on the active Kanban card of each
affected producer, (3) a comment on GitHub issue #44. Each send is recorded in
`docs/security/rollout-audit-log.md` with date, author, channel and comment ID/permalink, and acknowledgement
is a reply on the same thread. Missing acknowledgement holds that producer's phase, not the whole rollout.

| Phase | Steps | Send date (T-7) | Sender | Channel | Tracking record |
|---|---|---|---|---|---|
| A (gitflow + isolation) | S1–S3 | 2026-11-18 | sdlc-planner | rollout card + producer cards + issue #44 | ledger row + permalinks |
| B (backend matrix) | S4–S8 | 2026-11-25 | sdlc-planner | producer cards (5) + issue #44 | ledger row + permalinks |
| C (frontend/lint/security) | S9–S11 | 2026-12-07 | sdlc-security | producer cards + issue #44 | ledger row + permalinks |
| D (packaging/native) | S12–S13 | 2026-12-14 | sdlc-security | producer cards + issue #44 | ledger row + permalinks |
| E (aggregate) | S14 | 2026-12-21 | sdlc-security | producer cards + issue #44 | ledger row + permalinks |
| F (approval) | F | 2026-12-23 | sdlc-security | issue #44 + owner | ledger row + owner ack |

Every message states: exact context strings, enable date, rollback triggers (§6.1), and the audit contact.

---

## 9. Phase F — step prerequisites and gaps blocking enforcement

**Step F prerequisites** (both, not either):
1. Independent reviewer identity exists and is mapped to GitHub (P6; `EVIDENCE_BRIEF.md` §8 governance blocker).
2. Negative matrix row 4 and row 7 pass with real PR IDs while all 14 contexts are required.

**Gaps blocking READY** (enforcement, not this document):

- **G1** — No producer has a completed verified cycle. Shadow cannot exit until all **5** producers satisfy
  S-EXIT-1. *(Previously mis-cited as "review item #8"; item 8 in `EVIDENCE_BRIEF.md` §4 is orphaned
  `src/mvp/**` WIP and is unrelated. The correct governance blocker is §8.)*
- **G2** — P1 has not yet proven that the two gitflow contexts publish on PRs (0 PR runs as of 2026-10-29).
- **G3** — P6 independent reviewer identity is unassigned until the owner names it.
- **G4** — P2 telemetry is not yet merged, so S-EXIT-2/3 cannot be measured.

Non-blocking hardening carried from `EVIDENCE_BRIEF.md` §4 (must be fixed before final enforcement, tracked
as separate cards, not as rollout steps): KEK production guard, WebSocket key transport, release-approval
role elevation, TLS/HSTS tests wired into per-service CI, `src/mvp/**` orphan disposition.

---

## 10. Timeline, owners, success criteria

| Window | Work | Owner | Criteria |
|---|---|---|---|
| 2026-10-30 → 11-06 | P1–P7 | per §1 | each prerequisite's acceptance met and evidenced |
| 2026-11-09 → 11-23 | Shadow (warn-only) | sdlc-planner + sdlc-security | S-EXIT-1…5 |
| 2026-11-25 → 12-28 | 14 single-check steps | sdlc-security (execute) / sdlc-reviewer (verify) | per-step acceptance + FP band |
| 2026-12-30 | Step F + final ruleset | repository owner | §9 prerequisites + negative matrix |

**Success:** `main` protected; all 14 contexts required and proven green-and-red with real PR/run IDs;
rollback rehearsed and restored; FP rate ≤5% on measured data; audit trail complete; 5/5 producers verified.

**Not success:** merging this plan, or creating a ruleset, without P1–P7 and shadow exit.

---

## 11. Change log for this rework

| Review item | Resolution in this file |
|---|---|
| 1 real contexts | §4.1 exact strings + PR #187 evidence; job ids dropped |
| 2 conditional Compose gate | §4.2 excluded; limitation documented with line refs |
| 3 one-by-one | §5, 14 single-check steps, aggregate last, per-step dates/acceptance |
| 4 set consistency | §4.3 P5 sync commit with exact new `REQUIRED_CHECKS` |
| 5 tested rollback | §6.2 commands, §6.3 rehearsal, §6.4 matrix, named owner, saved baseline (§0) |
| 6 FP metric | §3.3 measurable definition, window, source, exclusions |
| 7 FP mitigation | §3.4 P4 code change with tests; SEC-007 attribution removed |
| 8 FP gate | §3.2 S-EXIT-2 + §6.1 precedence bands |
| 9 notifications / step F | §8 real channels + table; §9 P6 and correct §8 citation |
| 10 dashboard | §7; `quality-gates/audit/` dropped, P2 artifact + check-runs API |
| cleanups | 5 producers (§2), "adaptation effort" (§7), single target file (header) |
