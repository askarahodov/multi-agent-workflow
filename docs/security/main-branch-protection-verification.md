# Branch protection verification — ruleset `main-branch-protection` (task `t_1fd6385e`)

**Auditor:** `sdlc-security` (independent gate) · **Date:** 2026-10-29 (UTC) ·
**Repository:** `askarahodov/multi-agent-workflow` · **Ruleset id:** `26129824`
**Method:** live GitHub API read-back + one real negative push attempt + YAML/job-name
inventory. No code, workflow, or ruleset was modified by this task.

Machine-readable result: `reports/branch-protection-audit-t_1fd6385e.json`
(contract: `status`, `findings`, `checks_run`, `residual_risk`).

---

## 1. Verified live state (read-back, not assumed)

Source: `evidence/rollout-verify-2026-10-29T150511Z-ruleset-26129824.json`
(`sha256 4620648919f55497709ce0e39e009e5d8b410be227488cb88a1d80be0c9a2c8f`).

```json
{
  "id": 26129824, "name": "main-branch-protection", "target": "branch",
  "enforcement": "active",
  "conditions": { "ref_name": { "include": ["refs/heads/main"], "exclude": [] } },
  "bypass_actors": [],
  "current_user_can_bypass": "never"
}
```

Rules present: `deletion`, `non_fast_forward`, `pull_request`, `required_status_checks`.

| Rule | Parameters |
| --- | --- |
| `deletion` | branch deletion blocked |
| `non_fast_forward` | force-push blocked |
| `pull_request` | `required_approving_review_count: 0`, `dismiss_stale_reviews_on_push: false`, `require_code_owner_review: false`, `require_last_push_approval: false`, `required_review_thread_resolution: false`, `require_extra_approval_for_unattributed_changes: true`, `allowed_merge_methods: [merge, squash, rebase]` |
| `required_status_checks` | `strict_required_status_checks_policy: false`, `do_not_enforce_on_create: false`, 14 contexts (below) |

Required contexts (14), each mapped to the workflow job that publishes it:

| # | Context (exact) | Producer |
| --- | --- | --- |
| 1 | `gitflow policy validation` | `.github/workflows/gitflow-policy.yml` job `policy-compliance` |
| 2 | `gitflow worktree isolation` | `.github/workflows/gitflow-policy.yml` job `worktree-isolation` |
| 3 | `Reject external QA channel files in product main` | `.github/workflows/coordination-isolation.yml` job `isolate-coordination` |
| 4 | `backend pytest (agent-management)` | `.github/workflows/quality-gate.yml` job `backend` (matrix `agent-management`) |
| 5 | `backend pytest (orchestration-server)` | same matrix |
| 6 | `backend pytest (quality-gates)` | same matrix |
| 7 | `backend pytest (runtime-hardening)` | same matrix |
| 8 | `backend pytest (tools)` | same matrix |
| 9 | `frontend (typecheck + tests + build)` | `.github/workflows/quality-gate.yml` job `frontend` |
| 10 | `lint (eslint)` | `.github/workflows/quality-gate.yml` job `lint` |
| 11 | `security scan (quality-gates)` | `.github/workflows/quality-gate.yml` job `security` |
| 12 | `packaging (clean Python install)` | `.github/workflows/quality-gate.yml` job `packaging` |
| 13 | `Native LLM-tool-Contract Gate (offline)` | `.github/workflows/native-agent-e2e.yml` job `native-agent-e2e` |
| 14 | `quality gate` | `.github/workflows/quality-gate.yml` job `quality-gate` (aggregate, `needs` 6 jobs) |

`ci.yml` publishes case-variant near-duplicates (`Backend pytest …`, `Frontend (typecheck + vitest)`,
`Lint (eslint)`) that are **not** in the required set; the required set uses the `quality-gate.yml`
names only. `Main` is **not** covered by classic branch protection (`/branches/main/protection` → `404`):
the ruleset is the single authoritative control.

---

## 2. Requirement-by-requirement verdict

| # | Requirement | Verdict | Evidence |
| --- | --- | --- | --- |
| 1 | Required PR for all main changes | **PASS** | `pull_request` rule active; direct push rejected (below) |
| 2 | No deletion or force-push of main | **PASS** | `deletion` + `non_fast_forward` rules active; bypass empty |
| 3 | Required CI and security checks (list jobs) | **PASS** | 14 contexts, mapped in §1 |
| 4 | Owner self-review allowance documented **and time-boxed** | **PARTIAL** | documented in `SECURITY_AUDIT.md` §5.6 / `ROLLOUT_PLAN.md` §9, but no explicit expiry → `F-BP-01` |
| 5 | No bypass paths (admin bypass, wildcards) | **PASS** | `bypass_actors: []`, `current_user_can_bypass: "never"`, `ref_name.include: ["refs/heads/main"]` (no wildcard), `exclude: []`. Only one ruleset exists. |
| 6 | Add any missing required status checks | **GAP** | `Secure QA TLS / RBAC / SQLite Compose (offline live)` runs on every PR to main but is not required → `F-BP-03` |
| 7 | Document exact ruleset config in `REPOSITORY-STRUCTURE.md` | **DONE (this task)** | `docs/architecture/REPOSITORY-STRUCTURE.md` §"GitHub branch protection for `main`" |
| 8 | Test by attempting a violating push (expect rejection) | **PASS** | fresh direct-push attempt rejected, `main` unchanged (below) |

### Requirement 8 — negative test executed

Fresh attempt against the live repository (2026-10-29):

- Pre-test `origin/main` = `c94245ffc8bfc313efc9f7879db6364783583cea`.
- Pushed a throwaway commit `22c671404255d0c8270f6348c7ffa19a19bd5a18` (temp branch, since deleted)
  straight to `main`:

```
remote: error: GH013: Repository rule violations found for refs/heads/main.
remote: - Changes must be made through a pull request.
remote: - 14 of 14 required status checks are expected.
 ! [remote rejected] tmp-negprobe-t_1fd6385e -> main (push declined due to repository rule violations)
exit code 1
```

Raw output: `evidence/negtest-directpush-t_1fd6385e.txt`
(`sha256 4cd9fec369df5916c56b7a32a29a3fdc6907c376f4b8b9f4bffb8a658932bcc7`).
Post-test `main` (API + `origin/main`) = `c94245ffc8bfc313efc9f7879db6364783583cea` — **unchanged**.

Force-push and `--delete main` were **not** re-executed: the session's destructive-command guard
blocks rewinding/removing remote history, and `docs/security/main-protection-rollout-issue-44.md` §6
explicitly forbids a real force-push to a production branch for testing. The `non_fast_forward` and
`deletion` rules are confirmed present and active by read-back, and rejection was independently
captured in the prior application run (`evidence/negtest-forcepush-main.txt`, task `t_de91cac5`).

---

## 3. Findings

### F-BP-01 — Self-review allowance is documented but not time-boxed (MEDIUM)

`required_approving_review_count: 0` means **any** identity with write access can open and merge a PR to
`main` with **zero independent approvals** — the `pull_request` rule forces a PR but not a review.
This is a deliberate interim allowance (`SECURITY_AUDIT.md` §5.6: reviewer identity P6 unassigned;
`ROLLOUT_PLAN.md` §9 step F, planned 2026-12-30). Requirement 4 permits the allowance only if it is
**documented and time-boxed**; it is documented but carries no enforced expiry or review-by date in the
authoritative config, and nothing automatically fails closed when the date passes.

*Impact:* a compromised or misbehaving writer identity can self-merge unreviewed changes to `main`.
*Remediation:* record an explicit expiry (e.g. `reviewed-by: 2026-12-30`, owner `askarahodov`) in the
governance doc and add a scheduled reminder; at expiry set
`required_approving_review_count: 1` (requires P6). Owner decision.

### F-BP-02 — Branch not required to be up to date before merge (MEDIUM)

`strict_required_status_checks_policy: false` lets a PR merge while its head is behind `main`
(merge queue not enabled). Required checks then validated a base that is not the final merge result.

*Impact:* semantic merge conflicts / regressions can land even with all checks green.
*Remediation:* enable `strict_required_status_checks_policy` once the producer flow tolerates rebases
(`ROLLOUT_PLAN.md` §5 deferred it). Owner decision.

### F-BP-03 — Missing required check: live QA integration job (MEDIUM)

`Secure QA TLS / RBAC / SQLite Compose (offline live)`
(`.github/workflows/native-agent-e2e.yml` job `protected-qa-live-compose`) triggers on **every** PR to
`main` (no `paths` filter) and was green on the last `main` run
(`evidence/rollout-baseline-2026-10-29T143832Z-checkruns-main.txt`), but it is **not** in the required
set. It is the only always-running integration/security-relevant check that is omitted.

Requirement 6 asks to add missing checks. **Do not** add `docker-qa-smoke`
(`isolated-qa-docker-smoke.yml`) or `frontend npm audit (high/critical)`
(`frontend-dependency-audit.yml`): both are `paths`-filtered, so on unrelated PRs they never report and
GitHub would hold the merge at "Expected — waiting", blocking **all** merges. `local Compose build and
health` is conditional on Compose-related changes (`ROLLOUT_PLAN.md` §4.2) and is already covered
transitively via the required aggregate `quality gate`; it must not be required directly.

*Remediation:* owner adds `Secure QA TLS / RBAC / SQLite Compose (offline live)` to the ruleset —
it is additive and safe (unconditional trigger). Per `ROLLOUT_PLAN.md` §4.1 this is an owner decision,
which is why this audit did not apply it.

### F-BP-04 — In-repo required-check list drifted from the ruleset (MEDIUM)

`.github/workflows/gitflow-policy.yml` `REQUIRED_CHECKS` lists **11** contexts; the ruleset requires
**14**. Missing from the CI gate: `packaging (clean Python install)`,
`Native LLM-tool-Contract Gate (offline)`, `Reject external QA channel files in product main`.
The gate only `core.warning`s for absent contexts (it fails on present-and-red only), so this is a
detection inconsistency, not a bypass of the ruleset — but `ROLLOUT_PLAN.md` §6.1 trigger (c) makes
any drift a rollback trigger.

*Remediation:* P5 in `ROLLOUT_PLAN.md` (§4.3) — update `REQUIRED_CHECKS` to the exact 14 contexts in
the same change as any ruleset edit.

### F-BP-05 — Applied enforcement pre-empts the authoritative staged rollout (MEDIUM, process)

`ROLLOUT_PLAN.md` (reviewed, authoritative) prescribes warn-only **shadow mode 2026-11-09→11-23**, then
**one required check per step** from 2026-11-25, and states: *"Not success: creating a ruleset without
P1–P7 and shadow exit."* The live ruleset instead has `enforcement: active` with all **14** contexts
required as of **2026-10-29 17:38 MSK**, without the P1–P7 prerequisites or shadow exit. This is not a
protection weakness (it is stricter), but it is a governed-process deviation that removes the safety net
the plan built for blocking producers.

*Remediation:* owner/reviewer acknowledge the deviation and reconcile `ROLLOUT_PLAN.md` with the applied
state, or roll back to staged enablement. Owner decision.

### F-BP-06 — Absent required checks are only warned, never failed (LOW)

`gitflow required checks` (`gitflow-policy.yml` job `required-checks-gate`) calls `core.warning` when a
required context is missing or pending; only `failing` contexts fail the job. A required check that
silently stops reporting would not be caught by this gate (the ruleset still blocks the merge, but the
failure mode is less legible). *Remediation:* escalate `missing` to failure once the 14-context sync
(F-BP-04) lands.

### F-BP-07 — Protected-branch config was undocumented in `REPOSITORY-STRUCTURE.md` (LOW — fixed)

Requirement 7. Added a dedicated section to `docs/architecture/REPOSITORY-STRUCTURE.md` in this task.

### Informational (not findings)

- `dismiss_stale_reviews_on_push: false`, `require_last_push_approval: false`,
  `required_review_thread_resolution: false` — moot while `required_approving_review_count: 0`;
  revisit together with F-BP-01.
- `allowed_merge_methods` includes `rebase`; `AGENT_GITFLOW_RULES.md` references "linear history" but the
  ruleset does not enforce a linear-history rule. Cosmetic until a history policy is decided.
- `require_extra_approval_for_unattributed_changes: true` adds an extra approval only for PRs whose
  commits are not attributed to a GitHub user; it does not substitute for a required approval count.
- GitHub reports **22 open Dependabot vulnerabilities on the default branch** (2 critical, 5 high,
  12 moderate, 3 low) in the push banner for this branch (2026-10-29). Branch protection gates *merges*,
  not the pre-existing dependency backlog; it is called out here so the owner triages Dependabot alerts
  separately. The dependency scanner (`frontend npm audit (high/critical)`) cannot be made a required
  check because it is `paths`-filtered (F-BP-03).

---

## 4. Residual risk

1. **Single control, no fallback.** Classic branch protection is not configured (`404`); every guarantee
   rests on ruleset `26129824`. The documented emergency path flips `enforcement` to
   `evaluate`/`disabled`, which would leave `main` completely unprotected while the change is live. No
   second layer (e.g. an org-level ruleset) is confirmed — `GET /orgs/askarahodov/rulesets` returns
   `404` (no org or no permission), so org-level bypass cannot be *fully* excluded from this session.
2. **No independent review** while F-BP-01 stands.
3. **Stale-base merges** while F-BP-02 stands.
4. **No signed-commit requirement** (SEC-007 interim option A, `SECURITY_AUDIT.md` §5.4).
5. Client-side `--no-verify` hooks remain advisory — by design; server-side ruleset is the enforcement
   point (`SECURITY_AUDIT.md` §5.2).

---

## 5. Method / checks run

- `gh auth status`; `git fetch origin`.
- `gh api repos/.../rulesets`, `.../rulesets/26129824`, `.../git/ref/heads/main`,
  `.../branches/main/protection` (404), `.../orgs/askarahodov/rulesets` (404).
- Inventory of `.github/workflows/*.yml`: job display names, triggers, `paths` filters, aggregate `needs`.
- Real negative push: direct push of a throwaway commit to `main` → `GH013`, exit 1; `main` SHA
  confirmed unchanged afterwards by API and by `origin/main`.
- Cross-checked `SECURITY_AUDIT.md` §5, `ROLLOUT_PLAN.md` (git `085a78b`),
  `docs/security/main-protection-rollout-issue-44.md`, `AGENT_GITFLOW_RULES.md`, `evidence/*`.

**No changes were made to the ruleset, workflows, or any security policy.** Requirements 6 (owner
decision) and 4 (owner-decision expiry) are reported as findings rather than applied, per repository
governance (`ROLLOUT_PLAN.md`: every GitHub settings change is executed by the owner).
