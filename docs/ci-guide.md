# CI & GitHub Guide for Agents

**Version:** 1.0
**Status:** Reference guide — read alongside the mandatory `AGENT_GITFLOW_RULES.md`
**Repository:** `github.com/askarahodov/multi-agent-workflow` (remote `origin`, default branch `main`)
**Canonical working copy:** `/mnt/data/multi-agent-workflow/`
**Applies to:** every agent profile (`orchestrator`, `sdlc-*`) and humans working on this repo.

This guide is the actionable companion to `AGENT_GITFLOW_RULES.md` (branch/commit/merge policy).
It covers only the GitHub surface: authenticating, triggering workflows, reading their output,
configuring secrets, and diagnosing failures. When the two disagree about *policy*, the rules win.

> **Portable skill:** the `github` skill (`gh` CLI: auth, issues, PRs, review, CI) is installed on the
> agent profiles. Load it (`skill_view(name="github")`) and read `references/auth.md`,
> `references/ci-troubleshooting.md`, `references/pr-workflow.md` before improvising — this document is
> the repo-specific delta on top of it.

---

## 0. Quick reference

```bash
gh auth status                                   # am I authenticated, with which scopes?
gh workflow list                                 # workflows known to GitHub
gh run list --limit 20                           # recent runs (all workflows)
gh run list --workflow=quality-gate.yml          # runs of one workflow
gh run view <run-id>                             # per-job status of a run
gh run view <run-id> --log-failed                # only the failing steps' logs
gh run view <run-id> --log > /tmp/run.log        # full log
gh run watch <run-id> --exit-status              # block until the run finishes
gh run download <run-id> -n <artifact-name>      # fetch an uploaded artifact
gh workflow run branch-cleanup.yml --ref main    # manual dispatch (workflow must support it)
gh api repos/{owner}/{repo}/actions/runs/<id>/artifacts   # artifact metadata (REST)
gh secret list                                   # configured Actions secrets (names only)
```

Never paste a token into a command line, a comment, or a card. See §5.

---

## 1. Authentication

### 1.1 How agents are authenticated today

Agents use the **`gh` CLI**, authenticated **once per host account** (not per task). On this host:

```
$ gh --version
gh version 2.87.3

$ gh auth status
github.com
  ✓ Logged in to github.com account askarahodov (keyring)
  - Active account: true
  - Git operations protocol: https
  - Token: gho_************************************
  - Token scopes: 'gist', 'read:org', 'repo', 'workflow'
```

Facts that matter:

- **Storage:** the token is held by `gh` in the **system keyring** (secret-service), not in a dotfile.
  Do not copy it into `.env`, a scratch file, a card field, or an environment export. `gh` retrieves it
  transparently; git over HTTPS uses the `gh auth` credential helper.
- **Scopes:** `repo` (read/write repo contents, PRs, checks) and `workflow` (**required to push or
  modify anything under `.github/workflows/`** — without it, pushes touching workflow files are
  rejected) are the two that matter. `read:org` and `gist` are incidental.
- **Token type:** `gho_…` = a GitHub OAuth token issued by `gh auth login --web`. It is a *user* token;
  the task runner does not use a per-task PAT.

### 1.2 Verifying and repairing auth

```bash
gh auth status                 # non-zero exit / "not logged in" => fix before any gh command
gh auth refresh -s workflow    # add a missing scope to the existing token (opens browser/device flow)
gh auth login --scopes repo,workflow --git-protocol https
gh auth setup-git              # (re)install the git credential helper
```

Rules for agents:

- **DO** run `gh auth status` as the first step of any task that talks to GitHub. If it fails, the task
  is blocked on credentials — `kanban_block(kind="capability")` rather than guessing.
- **DO NOT** run `gh auth login` interactively from a headless worker; it needs a browser/device code and
  will hang. Escalate to the human/operator instead.
- **DO NOT** print `GH_TOKEN` / `GITHUB_TOKEN`, run `env | grep -i token`, or `set -x` in a shell that
  sees a token. `gh` already knows how to authenticate.

### 1.3 `GITHUB_TOKEN` inside workflows

Workflows authenticate to the API with the automatically-provisioned **`GITHUB_TOKEN`**, scoped by the
workflow's `permissions:` block — no secret needs to be configured for this. Current blocks:
`ci.yml` requests `contents: read, packages: read, attestations: write, checks: write`;
`release.yml` requests `contents: write, packages: write, attestations: write`;
`quality-gate.yml` and `branch-cleanup.yml` request `contents: read`.

---

## 2. Workflows in this repository

| File | Trigger | Purpose | Manual `workflow_dispatch`? |
|------|---------|---------|------------------------------|
| `.github/workflows/quality-gate.yml` | `push`, `pull_request` (all branches) | The merge gate: `backend` pytest matrix (5 subsystems), `frontend` (tsc + vitest + schema + build), `lint` (eslint), `security` (`scripts/security_scan.py`), aggregated by the `quality-gate` job | No |
| `.github/workflows/ci.yml` | `push` / `pull_request` to `main`, `develop` | Backend pytest matrix + frontend typecheck/vitest + eslint, with artifact uploads | No |
| `.github/workflows/release.yml` | `push` of tags matching `v*` | Builds the distribution (`python -m build`) and uploads `dist/` as `distribution-<tag>` | No |
| `.github/workflows/branch-cleanup.yml` | `schedule` (daily `17 4 * * *`) + `workflow_dispatch` | Report-only branch-hygiene audit; the manual input `delete: true` additionally prunes remote-tracking refs on the **ephemeral CI clone** | **Yes** — input `delete` (boolean, default `false`) |

The **merge gate is `quality-gate.yml`** (see `AGENT_GITFLOW_RULES.md` GF-09). `make check` is its local
analog — run it before requesting review.

`release.yml` only *builds and uploads* the artifact; it performs no PyPI publish. `branch-cleanup.yml`
never deletes real branches — host-side cleanup is done by
`scripts/git/maintenance/install-cron.sh` (see `docs/branch-cleanup/`).

---

## 3. Triggering workflows

### 3.1 The normal path

Most workflows run themselves on `push` branches and `pull_request` events. To exercise one:

```bash
# quality-gate.yml and ci.yml run on push / PR:
git push -u origin wt/t_XXXXXX
gh pr create --fill          # opens a PR; pull_request-triggered workflows start
gh pr checks                 # watch the required checks on the PR
```

`quality-gate.yml` triggers on **any** `push`, so a plain `git push origin wt/t_XXXXXX` (no PR needed)
starts it. `ci.yml` only triggers for `main`/`develop` targets (and it is currently broken — §6.3).

### 3.2 Manual dispatch (`workflow_dispatch`)

Only workflows that declare `workflow_dispatch:` in their `on:` block can be started by hand.
Today that is **`branch-cleanup.yml` only**:

```bash
gh workflow run branch-cleanup.yml --ref main
gh workflow run branch-cleanup.yml --ref main -f delete=true   # real prune on the throwaway clone
gh run list --workflow=branch-cleanup.yml --limit 5            # find the run it created
```

Notes:

- `gh workflow run <file> --ref <branch>` dispatches the workflow **as it exists on that ref**. To run an
  edited workflow you must have pushed the edit first.
- GitHub's Actions *UI* only lists dispatchable workflows that exist on the **default branch (`main`)**;
  the CLI can target another ref with `--ref`, but a workflow that is not yet on `main` will not appear in
  the UI's "Run workflow" button.
- To make a workflow dispatchable, add to its `on:` block (and commit on your branch):

  ```yaml
  on:
    workflow_dispatch:
      inputs:
        ref_hint:
          description: "why this manual run"
          required: false
  ```

  Adding `workflow_dispatch` to a workflow is a normal change under `AGENT_GITFLOW_RULES.md` (branch +
  PR + green gate). Do not push such a change straight to `main`.

- A **failed/invalid workflow file schedules zero jobs** (`run` finishes in 0s with no jobs). If
  `gh run list` shows a `0s` run, the first suspect is YAML validity, not the code — see §6.

---

## 4. Reading runs, logs, and artifacts

```bash
# 1. Find the run of interest.
gh run list --workflow=quality-gate.yml --limit 10

# 2. Per-job / per-step status (+ conclusion).
gh run view <run-id>

# 3. Logs.
gh run view <run-id> --log                     # full log (can be large; redirect to a file)
gh run view <run-id> --log-failed              # only failing steps — start here
gh run view --job <job-id> --log               # one job

# 4. Follow it live.
gh run watch <run-id> --exit-status            # exit code reflects the run's conclusion

# 5. Check statuses on a PR (what branch protection evaluates).
gh pr checks <pr-number>
gh api repos/askarahodov/multi-agent-workflow/commits/<sha>/check-runs
```

### Artifacts

Artifacts are the only durable output of a run besides the log. Current uploads:

| Workflow | Artifact name | Path | Retention |
|----------|----------------|------|-----------|
| `ci.yml` → each matrix leg | `test-reports-<subsystem>` | `<subsystem>/tests/` | 30 days |
| `ci.yml` → frontend job | `test-reports-frontend` | `apps/frontend/` | 30 days |
| `release.yml` → build | `distribution-<tag>` | `dist/` | 90 days |
| `quality-gate.yml` | *(none — this workflow uploads no artifacts)* | — | — |

```bash
gh api repos/askarahodov/multi-agent-workflow/actions/runs/<run-id>/artifacts   # list + metadata
gh run download <run-id>                       # download all artifacts of the run
gh run download <run-id> -n test-reports-frontend -D /tmp/artifacts
```

Gotchas:

- Artifacts expire (30/90 days). A run with no upload step has nothing to download — `quality-gate.yml`
  declares no `upload-artifact` step, so an empty artifact list there is **expected**, not a failure.
- Artifacts are per-run and immutable; there is no "latest" alias — resolve the run id first.
- Logs larger than the terminal budget should be redirected to a file and grepped, e.g.
  `gh run view <run-id> --log-failed | grep -E 'FAILED|ERROR|Error:'`.

---

## 5. Secrets and repository settings

### 5.1 What is required today

**No repository Actions secrets are currently required.** None of the four workflows reference
`secrets.*`; they rely on the auto-provided `GITHUB_TOKEN` (scoped by `permissions:`) and on public
`actions/*` building blocks. There is therefore nothing an agent must configure before CI runs.

If you *think* a workflow needs a secret, first prove it: `grep -n 'secrets\.' .github/workflows/*.yml`.
An empty result means no secret is needed and no secret should be invented.

### 5.2 Configuring a secret when one is genuinely needed

Two supported paths, both require **write/admin access to the repository** (an ordinary agent token with
`repo` scope may lack admin rights — escalate rather than assuming success):

```bash
# Preferred for agents: never echo the value to a terminal.
gh secret set MY_SECRET --body "$MY_SECRET_VALUE"          # value comes from env, not argv
gh secret set MY_SECRET < /path/to/value_file              # or pipe from a file

gh secret list                                             # verify the NAME exists (values stay masked)
gh variable set MY_VAR --body "non-sensitive-value"        # non-secret config
gh variable list
```

Human/UI path: **GitHub → the repo → Settings → Secrets and variables → Actions → New repository
secret**. Environment-scoped secrets and deployment protection live under Settings → Environments.

Rules:

- **DO** keep every secret server-side (Actions secret or environment secret). A value must never appear
  in a workflow file, a committed `.env`, a card field, a comment, or a log line.
- **DO** verify with `gh secret list` (names only) after setting; never re-read a value to "check" it.
- **DO NOT** `echo` a secret into a file or a step output, and do not pass one on a command line that a
  shell history or `ps` can capture.
- **DO NOT** add a secret until a workflow actually consumes it — unused secrets are attack surface and
  configuration drift.
- The `security` job of `quality-gate.yml` runs `python scripts/security_scan.py` (a static scan, no
  credentials). `make security` runs the same script locally.

---

## 6. Troubleshooting common failures

### 6.1 Triage order (30 seconds)

```bash
gh auth status                                   # 1. credentials valid?
gh run list --limit 10                           # 2. which run, what conclusion
gh run view <run-id>                             # 3. which job/step failed
gh run view <run-id> --log-failed                # 4. the error itself
```

A run that ends in `0s` with **no jobs** is a workflow-file problem (invalid YAML / unknown key), not a
test failure. A run whose job fails at *Install dependencies* is an environment/spec problem, not a test
failure. Only when a step reaches `Run tests` and reports failures is it a genuine test failure.

### 6.2 Failure → cause → fix

| Symptom | Likely cause | Fix |
|---------|--------------|-----|
| Run shows `0s`, no jobs, "invalid workflow file" | YAML not schema-valid for GitHub Actions (e.g. an unknown top-level key) | Validate before pushing — see §6.3; run `actionlint .github/workflows/*.yml` |
| Job fails at **Install dependencies** with `ERROR: Invalid requirement: '\n'` | A literal `\n` (or broken line-continuation) pasted into a `run: |` block | Rewrite the shell block as real newlines; never embed `\n` in YAML |
| `uses: astral/setup-uv@…` → `repository not found` / 404 | Wrong action owner | Use `astral-sh/setup-uv@v4` |
| "refusing to allow an OAuth App to create or update workflow" on push | token lacks the `workflow` scope | `gh auth refresh -s workflow` (needs a human) |
| Workflow did not run on push | its `on:` filters don't match (branch, path or event) | Check the `on:` block; `ci.yml` only fires on `main`/`develop` |
| `workflow_dispatch` not offered / "workflow not found" | workflow has no `workflow_dispatch` input, or isn't on the default branch | Add `workflow_dispatch:` and merge it to `main`, then dispatch `--ref` |
| No artifacts to download | the workflow has no `upload-artifact` step (e.g. `quality-gate.yml`), or they expired | Use the workflow that uploads (e.g. `ci.yml`), or check the run's artifact list via the API |
| Required check never appears on a PR | the workflow is invalid or never scheduled | Re-check the workflow file and the run for that SHA |
| `gh pr checks` shows pending forever | a job is queued behind concurrency / runner capacity, or the run was cancelled | `gh run view <id>`; re-run with `gh run rerun <id>` |
| HTTP 403 / `rate limit exceeded` from `gh api` | unauthenticated or exhausted quota | `gh auth status`; `gh api rate_limit`; wait or authenticate |
| Second push rebuilds everything (cache miss) | cache key or path changed (e.g. `cache-dependency-path`) | Verify the `actions/setup-*` cache config; npm caching is confirmed working |

### 6.3 Known state of this repository's workflows (as of 2026-10-13)

The workflows were verified green by remediation card `t_8e8f3315` (done). The historical failure→cause→fix
triage table below is retained for reference; the **current verified state** is:

- **main CI** (`ci.yml`): run **38404508997** = **success** (7/7 jobs, 6 artifacts: `test-reports-{agent-management,orchestration-server,quality-gates,runtime-hardening,tools,frontend}`); commit `ca77e45`.
- **main Quality Gate** (`quality-gate.yml`): run **38404508955** = **success** (11/11 jobs).
- **test-workflows-1791891554 Quality Gate** (`quality-gate.yml`): run **38404788426** = **success** (5/5 backend pytest jobs).
- **actionlint 1.7.12**: clean on all four workflows in both trees (`main` and `test-workflows-1791891554`).
- `release.yml` and `branch-cleanup.yml` have never executed (no `v*` tag; schedule/dispatch only), so
  they remain unverified — they are syntactically valid and pass `actionlint`.

#### Historical failure → cause → fix (retained for reference)

The following triage table documents the defects that were fixed by `t_8e8f3315`. It is kept as a historical
reference; **do not treat these as current issues**.

| Symptom | Likely cause | Fix |
|---------|--------------|-----|
| Run shows `0s`, no jobs, "invalid workflow file" | YAML not schema-valid for GitHub Actions (e.g. an unknown top-level key) | Validate before pushing — see below; run `actionlint .github/workflows/*.yml` |
| Job fails at **Install dependencies** with `ERROR: Invalid requirement: '\\n'` | A literal `\\n` (or broken line-continuation) pasted into a `run: |` block | Rewrite the shell block as real newlines; never embed `\\n` in YAML |
| `uses: astral/setup-uv@…` → `repository not found` / 404 | Wrong action owner | Use `astral-sh/setup-uv@v4` |
| "refusing to allow an OAuth App to create or update workflow" on push | token lacks the `workflow` scope | `gh auth refresh -s workflow` (needs a human) |
| Workflow did not run on push | its `on:` filters don't match (branch, path or event) | Check the `on:` block; `ci.yml` only fires on `main`/`develop` |
| `workflow_dispatch` not offered / "workflow not found" | workflow has no `workflow_dispatch` input, or isn't on the default branch | Add `workflow_dispatch:` and merge it to `main`, then dispatch `--ref` |
| No artifacts to download | the workflow has no `upload-artifact` step (e.g. `quality-gate.yml`), or they expired | Use the workflow that uploads (e.g. `ci.yml`), or check the run's artifact list via the API |
| Required check never appears on a PR | the workflow is invalid or never scheduled | Re-check the workflow file and the run for that SHA |
| `gh pr checks` shows pending forever | a job is queued behind concurrency / runner capacity, or the run was cancelled | `gh run view <id>`; re-run with `gh run rerun <id>` |
| HTTP 403 / `rate limit exceeded` from `gh api` | unauthenticated or exhausted quota | `gh auth status`; `gh api rate_limit`; wait or authenticate |
| Second push rebuilds everything (cache miss) | cache key or path changed (e.g. `cache-dependency-path`) | Verify the `actions/setup-*` cache config; npm caching is confirmed working |

**Always validate workflow YAML before pushing.** `actionlint` is the tool used for verification:

```bash
actionlint .github/workflows/*.yml     # if installed; otherwise install it first
python -c "import yaml,sys; yaml.safe_load(open('.github/workflows/quality-gate.yml'))"  # YAML-only check
```

`yaml.safe_load` catches syntax/serialization errors (like a stray `\\n`); it does **not** catch
Actions-schema errors (like an unknown top-level key) — `actionlint` does. There is no repo-local
`actionlint` wrapper, so install/availability must be confirmed before relying on it.

---

## 7. Definition of done for a CI / GitHub change

An agent touching authentication behaviour, workflows, or secrets is done only when all hold:

- [ ] `gh auth status` shows the required scopes (`repo`, `workflow`).
- [ ] Every changed workflow validates (`actionlint`) before push.
- [ ] Any workflow change landed on a `wt/<task-id>` branch with a conventional commit that names the
      task (`AGENT_GITFLOW_RULES.md` GF-01/GF-04) — **never** pushed directly to `main`.
- [ ] The relevant workflow was actually triggered (`gh run list`) and its conclusion read from CI, not
      assumed (`gh pr checks` / `gh run view`); a green claim is backed by a fresh `gh` read.
- [ ] Artifact expectations are stated: which workflow uploads what, and that a workflow with no upload
      step legitimately has none.
- [ ] No secret value was echoed, committed, or pasted into a card; only secret *names* were listed.
- [ ] Verified state is recorded in the card handoff (run ids, conclusions, artifact names), so the next
      agent does not have to re-derive it.

---

## 8. Version history

| Version | Date | Author | Change |
|---------|------|--------|--------|
| 1.0 | 2026-10-13 | `sdlc-planner` (task `t_aea44484`) | Initial guide: `gh` auth + scopes/storage, workflow inventory and manual dispatch, reading logs/artifacts, secrets configuration, failure triage, and the current known-broken workflow state with its remediation card. |
| 1.1 | 2026-10-14 | `sdlc-developer` (task `t_25ec9e17`) | Refreshed §6.3 to verified green state (runs 38404508997, 38404508955, 38404788426; actionlint clean); moved remediation details to historical triage table; added cross-references from README.md and AGENT_GITFLOW_RULES.md. |
