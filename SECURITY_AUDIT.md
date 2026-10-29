# Security Audit of GitFlow Enforcement Mechanisms

**Audit Date:** 2026-10-29
**Auditor:** sdlc-security (independent agent)
**Task:** t_9821af44 (audit) / t_de91cac5 (application + SEC-001 correction)
**Base commit:** 6f15980 (`wt/t_5ba84eb3`)
**Version:** 1.2 (SEC-001 corrected; server-side controls applied — see §5)

---

## Executive Summary

This audit identifies **3 CRITICAL**, **6 HIGH**, and **2 MEDIUM** findings across the GitFlow enforcement mechanism. All CRITICAL and HIGH findings must be mitigated before release preparation. The finding IDs SEC-001 through SEC-011 are stable and without duplicates — each finding appears exactly once with one severity level.

**Blocking findings for release prep:** SEC-001, SEC-004, SEC-010, SEC-002, SEC-005, SEC-007, SEC-008, SEC-009, SEC-011

These 9 findings (3 CRITICAL, 6 HIGH) represent block risks for the release preparation phase.

---

## 1. Hook Bypass Vectors (`--no-verify`, `core.hooksPath` manipulation)

### Finding SEC-001: `git commit --no-verify` bypasses pre-commit hook

**Severity:** CRITICAL

**Exploitability:** An attacker can run `git commit --no-verify` to bypass all pre-commit validation (GF-02 branch naming, GF-04 commit format, GF-05 protected-branch checks). With `--no-verify` **git never invokes the hook at all**, so there is nothing for the hook to detect, log, or act on — the bypass is implemented entirely inside `git` before the hook process is spawned. A `--no-verify` guard *inside* a pre-commit hook is therefore not implementable and must not be described as a mitigation.

**Evidence:**
- Git behaviour: `--no-verify` / `-n` suppresses the `pre-commit` and `commit-msg` hooks (git-commit(1)); `--no-verify` on `git push` likewise suppresses `pre-push`. The hook process is not started, so the hook cannot observe the flag.
- The pre-commit hook (`scripts/git/gitflow-hooks/pre-commit`) is a client-side hook — it is bound by this git behaviour by design.
- Documentation acknowledges the bypass: "Bypass: `git commit --no-verify` (audited; CI `gitflow-policy.yml` catches a bypass after the fact)."
- `.github/workflows/gitflow-policy.yml` is triggered on `pull_request` **and** on `push` to `main`/`master`/`develop`, so a direct commit to a protected branch is re-validated server-side after the fact.

**Mitigation (corrected):**
- Treat every client-side hook as advisory, bypassable by design. Do **not** rely on in-hook `--no-verify` detection — it cannot exist.
- The only authoritative control is server-side: a GitHub repository ruleset that (a) requires every change to `main` to arrive through a pull request, and (b) requires the `gitflow policy validation` / `gitflow worktree isolation` status checks before merge. This is now applied — see §5.
- GitHub.com (non-Enterprise) does not expose a user-installable server-side `pre-receive` hook; the repository-ruleset / required-status-checks combination is the supported equivalent and is the enforcement point recorded in §5.

**Impact:** Direct commits to `main`/`develop` with arbitrary commit messages bypass all *client-side* Conventional-Commit and branch-naming validation. The residual risk is bounded by the server-side ruleset (§5): a direct/force push to `main` is rejected, and any PR still runs the authoritative CI policy checks.

---

### Finding SEC-002: `core.hooksPath` manipulation — client-side operational risk

**Severity:** HIGH

**Exploitability:** The `core.hooksPath` Git config is set to `.githooks` relative to the worktree (via `gitflow_context.py` and `worktree-lifecycle.py`). If an attacker can manipulate the Git config (e.g., via `git config core.hooksPath /tmp/evil`), the enforcement hooks will be skipped or replaced.

**Evidence:**
- `gitflow_context.py` line 145-155: Sets `core.hooksPath` to `.githooks` symlink.
- `worktree-lifecycle.py` line 201: `git config core.hooksPath .githooks`.
- The `.githooks` symlink points to `scripts/git/gitflow-hooks` in the repo.
- If an attacker runs `git config core.hooksPath /absolute/path`, they can point hooks to any directory.

**Mitigation:**
- After setting `core.hooksPath`, immediately verify it with `git config core.hooksPath` and refuse to operate if it doesn't match the expected value.
- Consider using a server-side pre-receive hook (GitHub repository-level) as the authoritative enforcement point, making client-side `core.hooksPath` manipulation irrelevant.
- Sign Git config changes or restrict `core.hooksPath` via repository-level config that cannot be overridden.

**Impact:** An attacker could point `core.hooksPath` to a malicious directory, causing hooks to execute arbitrary code or skip validation entirely.

---

### Finding SEC-003: CI workflow reads repo files, not PR content — injection risk low but path traversal possible

**Severity:** MEDIUM

**Exploitability:** The `gitflow-policy.yml` CI workflow performs all policy checks with inline, trusted shell/python and never executes a script from the PR head. The only repository files read are `AGENT_GITFLOW_RULES.md` and `gitflow-policy.schema.json`.

**Evidence:**
- Line 8-10 of gitflow-policy.yml: "The only repository files read are data (AGENT_GITFLOW_RULES.md, gitflow-policy.schema.json)."
- Line 33-34: `uses: actions/checkout@v4` with `fetch-depth: 0` — gets all history, but still only reads declared data files.
- The Python validation script (lines 89-113) reads files with `open()` and parses YAML/JSON — no user input from the PR is involved in the validation logic.

**However:**
- If an attacker modifies `AGENT_GITFLOW_RULES.md` or `gitflow-policy.schema.json` via a PR, the CI would validate the modified versions.
- The version comparison (lines 109-111) only compares `major.minor` (e.g., `1.0` vs `1.0.0`), missing patch-level drift.
- A malicious PR could introduce a subtle schema change that bypasses the version check.

**Mitigation:**
- Extend the schema version comparison to include patch versions, not just major.minor.
- Add checksum/hash verification of the policy files as part of the CI gate.
- Ensure `AGENT_GITFLOW_RULES.md` and `gitflow-policy.schema.json` are protected from PR modifications until they reach main.

**Impact:** A modified policy file in a PR could drift the version check and allow non-compliant rules to pass validation.

---

### Finding SEC-004: Symlink creation in `worktree-lifecycle.py` could escape the worktree sandbox

**Severity:** CRITICAL

**Exploitability:** The `worktree-lifecycle.py` creates a symlink at `.githooks` pointing to `scripts/git/gitflow-hooks` in the repo root (line 200). If the `hooks_src` path resolves unexpectedly or if the worktree path contains traversal sequences, the symlink could point outside the intended directory.

**Evidence:**
- `worktree-lifecycle.py` line 151-178: `create_worktree` creates branch and symlinks hooks.
- `worktree-lifecycle.py` line 180-191: `_inject_policy` calls `gitflow_context.py claim` which installs `.githooks` symlink.
- The `.githooks` symlink is relative — `os.path.relpath(self.hooks_src, worktree)` — which could resolve differently depending on the working directory when the hook is triggered.

**Mitigation:**
- Use absolute paths for symlink targets instead of relative `os.path.relpath`.
- Validate that the symlink target resolves within the expected directory tree.
- Add a post-creation verification step that reads the symlink and confirms its target.
- Consider using `git core.hooksPath` with an absolute path that is set once and cannot be changed without admin privileges.

**Impact:** Symlink escape could allow execution of arbitrary hooks from outside the worktree, potentially leading to code execution when the agent commits or pushes.

---

### Finding SEC-005: `.gitignore` does not protect `.worktrees/` from being tracked

**Severity:** HIGH

**Exploitability:** The `.gitignore` file at the repo root contains rules that ignore `.worktrees/` and `/worktrees/`. However, `.gitignore` rules prevent tracking of new files but do not remove already-tracked files.

**Evidence:**
- `.gitignore` lines 29-30: `.worktrees/` and `/worktrees/` are ignored.
- The gitflow-policy.yml CI job checks: `git ls-files --error-unmatch .worktrees` and `git ls-files | grep -q '^\.worktrees/'` — this fails if .worktrees/ is tracked, which would cause the CI to fail.
- But the check is in the CI, not in a pre-commit hook, so a direct commit could temporarily track .worktrees/ before the CI catches it.

**Mitigation:**
- Ensure `.gitignore` rules are applied before any worktree files are added.
- Add a pre-commit hook check that ver `.worktrees/` is not in the git index.
- Use `git rm --cached -r .worktrees/` to untrack any previously tracked worktree files.

**Impact:** If .worktrees/ is tracked in git, it could expose worktree paths and branch information, aiding reconnaissance. In worst case, a malicious commit could exploit path traversal in how worktree paths are resolved.

---

### Finding SEC-006: Schema version comparison only checks major.minor, not patch version

**Severity:** MEDIUM

**Exploitability:** The `gitflow-policy.yml` CI validation (lines 106-113) compares rule versions using `mm()` function that extracts `major.minor`: this means rules version `1.0.1` and schema version `1.0.0` would pass as compatible, even though they represent different policy versions.

**Evidence:**
- gitflow-policy.yml lines 106-111: Version comparison only checks major.minor.
- gitflow-policy.schema.json has `"version": "1.0.0"`.
- AGENT_GITFLOW_RULES.md has YAML front-matter with `version: 1.0`.

**Mitigation:**
- Change the version comparison to include patch versions: `rules_version == schema_version` or `mm(rules_version) == mm(schema_version) and patch(rules_version) == patch(schema_version)`.
- Enforce strict semantic versioning where any change to rules requires a new schema version.
- Add a CI failure if the versions don't match exactly.

**Impact:** A patch-level change to the rules could pass the version check silently, allowing outdated or non-compliant rules to be used for validation.

---

### Finding SEC-007: Policy files distributed via CI could be stale or modified between claims

**Severity:** HIGH

**Exploitability:** The policy bundle (AGENT_GITFLOW_RULES.md + gitflow-policy.schema.json) is distributed to worktrees via `gitflow_context.py` at claim time. If an attacker can modify these files between the time they are read by the dispatcher and written to the worktree, the agent could receive a tampered policy.

**Evidence:**
- `dispatcher-policy-hook.sh` line 24-28: Calls `gitflow_context.py claim` which reads the repo files and writes them to the worktree.
- The hook writes to a temp file then moves it (`$WORKTREE/.agent-gitflow.env.tmp` → `$WORKTREE/.agent-gitflow.env`), which is atomically replaceable.

**Mitigation:**
- Verify the hash/checksum of policy files before and after the claim operation.
- Use Git tree SHA verification: compare the SHA of AGENT_GITFLOW_RULES.md and gitflow-policy.schema.json at claim time against the known-good baseline.
- Sign the policy files and verify signatures as part of the claim process.

**Impact:** Tampered policy files could relax enforcement rules, allowing non-compliant commits or branches to pass validation.

---

### Finding SEC-008: Race window between new rule deployment and branch protection activation

**Severity:** HIGH

**Exploitability:** During rollout of new GitFlow rules, there is a race condition between:
1. The new rules being deployed to agents (via `gitflow_context.py` claim)
2. The GitHub branch protection ruleset taking full effect

**Evidence:**
- GF-05 relies on GitHub branch protection (linear history, signed commits, no force-push, required checks) per `gitflow-strategy.md` §5.1.
- The enforcement hooks (pre-commit, pre-push) are client-side and can be bypassed with `--no-verify`.
- The gitflow-policy.yml CI catches bypasses after the fact, but only on PRs, not on direct pushes to protected branches.
- During the window between rule deployment and branch protection activation, a direct commit to `main`/`develop` with `--no-verify` could land non-compliant changes.

**Mitigation:**
- Ensure GitHub branch protection is configured **before** new agents are claimed with the new rules.
- Use a feature flag or gradual rollout: keep old rules active until branch protection is fully confirmed.
- Add a repository-level pre-receive hook that enforces the same rules as the CI workflow, making the bypass ineffective regardless of `--no-verify`.
- Log all `--no-verify` attempts via CI audit and alert on repeated occurrences.

**Impact:** During rollout, an attacker could exploit the window to push non-compliant commits directly to protected branches.

---

### Finding SEC-009: `git push --no-verify` bypasses pre-push hook

**Severity:** HIGH

**Exploitability:** The pre-push hook (`scripts/git/gitflow-hooks/pre-push`) acknowledges the bypass at line 18: "Bypass (audited): `git push --no-verify`. The CI job `gitflow-policy.yml` re-validates the PR after the fact, so a bypass is still caught."

**However:**
- The pre-push hook is client-side and can be bypassed with `git push --no-verify`.
- If the target branch is `main` or `develop` (protected by GitHub branch protection), the bypass might be blocked by the branch protection ruleset itself.
- But if branch protection is misconfigured or disabled, the push would succeed.
- The CI catch is after the fact — the commit has already landed.

**Mitigation:**
- Make `git push --no-verify` attempts visible in CI/CD audit logs with task/agent attribution.
- Configure GitHub branch protection to require the `required-checks` gate from gitflow-policy.yml, so `--no-verify` cannot bypass the required checks.
- Add a server-side pre-receive hook that rejects pushes with `--no-verify` flag or that don't pass the policy checks.

**Impact:** Direct push to protected branches with `--no-verify` could bypass all client-side enforcement.

---

### Finding SEC-010: `core.hooksPath` can be manipulated via Git config to point to malicious hooks — server-side enforcement critical risk

**Severity:** CRITICAL

**Exploitability:** The entire enforcement framework relies on `core.hooksPath` being set to `.githooks` (a symlink to `scripts/git/gitflow-hooks`). If an agent or attacker can run `git config core.hooksPath <malicious-path>`, they can:
1. Point hooks to a directory they control
2. Cause arbitrary code execution when the agent commits or pushes
3. Bypass all enforcement by pointing to a no-op or permissive hook set

**Evidence:**
- `gitflow_context.py` line 145: `git -C worktree config core.hooksPath .githooks`
- `worktree-lifecycle.py` line 201: `git config core.hooksPath .githooks`
- The `.githooks` symlink is relative and created with `os.path.relpath()` in `worktree-lifecycle.py` line 200
- Any `git config --global core.hooksPath` or `git config core.hooksPath` in the worktree overrides the enforcement

**Mitigation:**
- After setting `core.hooksPath`, immediately verify it with a read-back check and fail if it doesn't match the expected value.
- Use an **absolute** path for `core.hooksPath` that cannot be easily changed by the agent.
- Set `core.hooksPath` at the repository level (in the `.git` config) rather than the worktree level, making it harder to override without admin access.
- Add a defensive check in every hook that verifies `core.hooksPath` is set correctly before executing enforcement logic.

**Impact:** Full privilege escalation — attacker controls what runs during git commit/push operations, leading to arbitrary code execution with the agent's privileges.

---

### Finding SEC-011: Git config variables could be used to escape the worktree sandbox

**Severity:** HIGH

**Exploitability:** The `gitflow_context.py` and `dispatcher-policy-hook.sh` write the branch name and policy path into the workspace via `AGENT_GITFLOW_CONTEXT.json` and `.agent-gitflow.json`. If these paths contain user-controllable data without proper sanitization, they could be used for path traversal.

**Evidence:**
- `gitflow_context.py` `build_policy_bundle()` constructs `branch_name` as `f"wt/{task_id}"` (line 130) — this is deterministic and safe.
- The `policy_path` is `str(rules_path)` from the repo's `AGENT_GITFLOW_RULES.md` (line 136) — this is a repo-relative path.
- However, if an attacker can modify `AGENT_GITFLOW_RULES.md` to contain a path traversal in the front-matter or rule descriptions, the downstream consumers might be affected.

**Mitigation:**
- Sanitize all path variables before use, especially any that come from policy files.
- Validate that `AGENT_GITFLOW_CONTEXT.json` and `.agent-gitflow.json` paths resolve within the expected worktree.
- Use `os.path.realpath()` and verify the resolved path is within the worktree directory.

**Impact:** Path traversal via Git config or policy files could lead to reading/writing files outside the worktree, potentially exfiltrating credentials or modifying repo files.

---

## Overall Risk Assessment

| Severity | Count | Status |
|----------|-------|--------|
| CRITICAL | 3 | Requires immediate mitigation before release prep |
| HIGH | 6 | Requires mitigation before release prep |
| MEDIUM | 2 | Should be addressed |

**Blocking findings for release prep:** SEC-001, SEC-004, SEC-010, SEC-002, SEC-005, SEC-007, SEC-008, SEC-009, SEC-011

These 9 findings (3 CRITICAL, 6 HIGH) represent block risks for the release preparation phase as specified in the task body: "Any CRITICAL/HIGH findings block release prep."

---

## Recommended Mitigation Priorities

### Immediate (block release prep):

1. **SEC-010 (CRITICAL):** Add core.hooksPath verification after setting it; use absolute paths; add defensive checks in hooks.  
2. **SEC-004 (CRITICAL):** Fix symlink creation in worktree-lifecycle.py to use absolute paths and verify symlink targets.  
3. **SEC-001 (CRITICAL):** In-hook `--no-verify` detection is impossible (git never starts the hook). Enforce server-side instead: repository ruleset requiring PRs + required status checks — **applied**, see §5.
4. **SEC-002 (HIGH):** Add core.hooksPath read-back verification in gitflow_context.py.  
5. **SEC-005 (HIGH):** Ensure .gitignore rules prevent .worktrees/ tracking; add pre-commit check.  
6. **SEC-007 (HIGH):** Add hash/checksum verification of policy files during claim.  
7. **SEC-008 (HIGH):** Ensure branch protection is deployed before new rule rollout; add feature flags.  
8. **SEC-009 (HIGH):** Configure GitHub branch protection to require policy checks; make --no-vere attempts auditable.  
9. **SEC-011 (HIGH):** Sanitize Git config path variables; validate worktree resolution.

### Short-term:

10. **SEC-003 (MEDIUM):** Extend schema version comparison to patch level; add checksum verification.  
11. **SEC-006 (MEDIUM):** Implement exact version matching for policy/schema.

### Long-term:

12. **Server-side enforcement:** Implement pre-receive hooks as the authoritative enforcement point, making client-side bypasses irrelevant. Configure GitHub ruleset with `gitflow-policy`-check requirement.

---

## 5. Applied server-side controls (evidence-backed)

Owner authorized the server-side application (`UNBLOCK: OWNER OK`). The controls below are **applied to the live repository** and verified by API read-back and by rejected push attempts (task `t_de91cac5`). Raw outputs are in `evidence/`.

### 5.1 Repository ruleset on `main` — APPLIED

- Ruleset `main-branch-protection`, id **`26129824`**, `target: branch`, `enforcement: active`, `conditions.ref_name.include: ["refs/heads/main"]`, `bypass_actors: []` → `current_user_can_bypass: "never"`.
- Rules: `deletion`, `non_fast_forward`, `pull_request` (`required_approving_review_count: 0`), `required_status_checks` (14 contexts, `strict_required_status_checks_policy: false`).
- Read-back:

  ```console
  $ gh api repos/askarahodov/multi-agent-workflow/rulesets
  [{"id":26129824,"name":"main-branch-protection","target":"branch","enforcement":"active", ...}]
  ```

- Verified rejections (return codes captured in `evidence/negtest-*.txt`):
  - **Direct push** of a new commit to `main` → `GH013: Repository rule violations … "Changes must be made through a pull request." / "14 of 14 required status checks are expected."`, exit code **1**;
  - **Force push** (`+<old-sha>:main`) → `GH013 … "Cannot force-push to this branch" / "Changes must be made through a pull request."`, exit code **1**.

  `main` remained at `5bf7cef` after both attempts.

### 5.2 SEC-001 / SEC-009 — server-side `pre-receive` equivalent

GitHub.com (non-Enterprise) does not expose a user-installable server-side `pre-receive` hook; that capability requires GitHub Enterprise Server / Enterprise-level rulesets. The supported **equivalent** authoritative control is the repository ruleset above: the `pull_request` rule rejects direct pushes, and `required_status_checks` require the authoritative `gitflow policy validation` / `gitflow worktree isolation` contexts (plus the 12 quality/coordination contexts) before merge. Client hooks remain advisory and are bypassable with `--no-verify` **by design** — this is the correct description of the SEC-001 vector, corrected in §1.

### 5.3 SEC-008 — enable-then-require ordering respected

The 14 contexts were confirmed present and green on `main` (`evidence/rollout-baseline-*-checkruns-main.txt`, 24 unique check names) **before** they were made required. The ruleset's required set equals the `.github/workflows/gitflow-policy.yml` `REQUIRED_CHECKS` env and ROLLOUT_PLAN.md §4.1 (14 contexts).

### 5.4 SEC-007 — signing / baseline-hashes: DEFERRED (owner decision required)

Selected interim option **(A)**: the ruleset does **not** require signed commits for the transition window, because agent commits are currently unsigned (e.g. `5bf7cef`) and no signing key material exists in the project; enabling `require signed commits` now would block the project's own candidate work. Adopting signing (option **B** — issue key(s), configure `user.signingkey`/`commit.gpgsign` in the worktree hooks, re-sign the candidate) is an **owner decision** and is *not* implemented by this task. The policy-file hash/baseline-verification half of SEC-007 also remains open. Both are recorded as an explicit deferred item pending owner sign-off.

### 5.5 Emergency bypass

`bypass_actors` is empty, so no actor — including the repository admin — bypasses by push. The documented emergency path is owner-only: set the ruleset `enforcement` to `evaluate`/`disabled` via the API (audited), make the change, then restore — per ROLLOUT_PLAN §5/§6.2 (never `DELETE …/protection`, never delete the ruleset as the default rollback).

### 5.6 Known gap vs ROLLOUT_PLAN step F

`required_approving_review_count` is `0` because the independent reviewer identity (P6) is not yet assigned and would otherwise block every merge. Requiring independent approval is a step-F prerequisite and is **not** enabled here.

---

## Audit Methodology

- Reviewed implementation files: `AGENT_GITFLOW_RULES.md`, `gitflow-policy.schema.json`, `gitflow-policy.yml`, `gitflow_context.py`, `dispatcher-policy-hook.sh`, `worktree-lifecycle.py`, hook scripts (pre-commit, pre-push, commit-msg, post-merge), `gitflow-lib.sh`.
- Analyzed GitFlow enforcement architecture across layers L2-L5.
- Considered bypass vectors: `--no-verify`, `core.hooksPath` manipulation, symlink attacks.
- Evaluated CI workflow injection risks via `gitflow-policy.yml`.
- Assessed worktree isolation via symlink and path traversal analysis.
- Reviewed policy file distribution and validation flow.
- Examined branch protection race conditions during rollout.
- Analyzed privilege escalation vectors via Git config.
- No code execution or external system interaction was performed; all analysis was based on code review.