# t_5a3e90c3 — FIX-GITFLOW-FOLLOWUP evidence

Base: `e01efa1` (origin/main). Branch: `fix/gitflow-followup`.
Workspace: `/mnt/data/multi-agent-workflow/.worktrees/fix-gitflow-followup`.

Closes three confirmed defects in the GitFlow enforcement tooling. The live
activation of hooks in the **primary** repo is deliberately NOT performed here
(see "Activation order" below).

## Defect 1 — `check_commits.py` was never invoked by CI

**Before** (script dead code):

```
$ grep -c check_commits .github/workflows/gitflow-policy.yml
0
$ echo $?
1
```

**After** — the GF-04 step runs the canonical checker, materialized from the
trusted BASE commit (never the PR head, so a PR cannot inject code or weaken the
pattern it is judged by):

```yaml
tmp="$(mktemp -d)"
git worktree add -q --detach "$tmp/base" "$BASE"
python3 "$tmp/base/scripts/git/gitflow-hooks/check_commits.py" "$BASE" "$HEAD" --repo "$tmp/base"
```

Local simulation of both verdicts:

```
$ BASE=$(git rev-parse HEAD~1); HEAD=$(git rev-parse HEAD); tmp=$(mktemp -d)
$ git worktree add -q --detach "$tmp/base" "$BASE"
$ python3 "$tmp/base/scripts/git/gitflow-hooks/check_commits.py" "$BASE" "$HEAD" --repo "$tmp/base"
check_commits: 4 commit(s) in range comply with GF-04     # rc=0

# negative case (a planted non-conventional commit in a scratch worktree):
$ python3 .../check_commits.py "$B" "$H" --repo "$tmp2/base"
GF-04 violations (Conventional Commits required):
  85ade2606e44  'totally invalid subject'                 # rc=1
```

## Defect 2 — dead hint `make gitflow-reap`

**Before:**

```
$ make -n gitflow-reap
make: *** No rule to make target 'gitflow-reap'.  Stop.     # rc=2
```

**After** (`Makefile` now defines `gitflow-reap`, backed by the existing
`worktree-lifecycle.py reap` subcommand):

```
$ make gitflow-reap
"python3" scripts/git/worktree-lifecycle.py reap
{ "orphans": [ ... ] }                                       # rc=0
```

## Defect 3 — `core.hooksPath` pointed into the void in the primary repo

**Before** (primary repo, where direct commits to `main` happen):

```
$ git -C /mnt/data/multi-agent-workflow config --get core.hooksPath
.githooks
$ test -e /mnt/data/multi-agent-workflow/.githooks || echo '.githooks MISSING'
.githooks MISSING
$ git -C /mnt/data/multi-agent-workflow hook run --ignore-missing pre-commit
$ echo $?
0            # no-op: git silently runs nothing
```

**After** — the installer and `gitflow_context.py` now REPORT and refuse to
leave this state. Read-only check against the (still-inert) primary repo:

```
$ bash scripts/install-gitflow-hooks.sh --check --repo /mnt/data/multi-agent-workflow
[gitflow] not active: /mnt/data/multi-agent-workflow/.githooks is missing — core.hooksPath points into the void
$ echo $?
1

$ python3 scripts/git/gitflow_context.py verify
{ "root": ".../multi-agent-workflow", "hooks_path": ".githooks",
  "resolved_target": ".../multi-agent-workflow/.githooks", "active": false,
  "checks": {"hooks_path_configured": true, "hooks_dir_present": false,
             "pre_commit_present": false} }
$ echo $?
1
```

**Real rejection** once the hooks are installed (here in this fix worktree, which
is safe — it does not touch the shared `main` tree):

```
$ bash scripts/install-gitflow-hooks.sh --repo .
[gitflow] hooks installed: hooksPath = .githooks ; .githooks -> scripts/git/gitflow-hooks
[gitflow] hooks active in .../fix-gitflow-followup                       # rc=0

$ python3 scripts/git/gitflow_context.py verify --worktree .
{ "active": true, "checks": {"hooks_path_configured": true,
  "hooks_dir_present": true, "pre_commit_present": true} }               # rc=0

# GF-04: a non-Conventional message is rejected
$ git commit -m "bad message no conventional"
[gitflow] GF-04: invalid commit message: 'bad message no conventional'    # rc=1

# GF-05: a direct commit on a protected branch is rejected (scratch repo)
$ git commit -m "chore(t_00000000): direct on main"   # on branch main
[gitflow] GF-05: refusing a direct commit on protected branch 'main'.     # rc=1
```

## Test matrix

```
$ python3 -m pytest scripts/git/tests -q
23 passed        # 18 pre-existing + 5 new (no regressions)

$ python3 -m pytest scripts/git/maintenance/tests -q
8 passed
```

## Activation order (IMPORTANT)

`core.hooksPath` lives in the shared `.git/config`, so creating the root
`.githooks` symlink takes effect for the primary worktree immediately — and the
primary worktree is usually parked on `main`, where GF-05 refuses a direct
commit. That would strand in-flight workers/orchestrator that commit to `main`
from the root tree. Therefore this branch only makes the state *creatable* and
*verifiable*; the live root activation is a separate, coordinated step:

```bash
bash scripts/install-gitflow-hooks.sh --repo /mnt/data/multi-agent-workflow
```

Run it once no in-flight worker depends on direct commits to `main` from the
root worktree.
