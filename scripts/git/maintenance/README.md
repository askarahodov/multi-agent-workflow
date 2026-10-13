# Git Branch Cleanup & Maintenance

Automated, safe removal of stale local branches for the `multi-agent-workflow`
repository, following the branching/merge model in `gitflow-strategy.md`.

Because agent work is **squash-merged** into `main`, a completed agent branch's
commits are usually *not* ancestors of `main` — so a naive `git branch --merged`
scan would never find them. The reliable signal is the branch's **upstream going
away**: once the remote PR is merged and the remote branch deleted, `git fetch
--prune` removes the tracking ref and the local branch has a dangling upstream.
That is the primary cleanup criterion here (`[upstream gone]`); `[merged]`
covers merge-commit based branches.

## Files

| Path | Purpose |
|------|---------|
| `cleanup-branches.py` | The cleanup engine (see CLI below). |
| `tests/test_cleanup_branches.py` | Integration tests against real temp git repos. |
| `install-cron.sh` | Installs a daily cron job on the agent host (dry-run by default). |
| `../../.github/workflows/branch-cleanup.yml` | Daily CI hygiene audit (report-only). |

## `cleanup-branches.py`

```
usage: cleanup-branches.py [options]

  --repo DIR           git repository root (default: cwd)
  -r, --remote NAME    remote to fetch (default: origin)
  -t, --target NAME    target(s) for merged detection (default: main + develop)
  -p, --protect NAME   extra branch name(s) to never delete (repeatable)
  --dry-run            report only; delete nothing (safe default)
  -y, --yes            delete without prompting (for cron/CI)
  --prune-remotes      prune remote-tracking refs (fetch --prune + remote prune)
  --no-fetch           skip the initial fetch
```

### What it does

1. **Fetches** the remote (fresh view of which remote branches still exist).
2. **Identifies** local branches that are safe to remove:
   - `[upstream gone]` — configured upstream ref no longer exists after prune
     (the primary signal for squash-merged agent branches), or
   - `[merged]` — tip is reachable from a target branch (`main` / `develop`).
3. **Deletes** those local branches (`-d` for merged, `-D` for upstream-gone).
4. **Optionally prunes** remote-tracking refs with `--prune-remotes`.

### Safety guarantees

- **Never deletes**: the current branch, `main`, `master`, `develop`, any
  `--target`, or anything listed with `--protect`.
- **Dry-run by default** — pass `--yes` to actually delete.
- **Interactive confirmation** when a TTY is present and `--yes` is not given.
- **Refuses to run headless without `--yes`** (exit code 2) so a cron/CI
  misconfiguration can never silently delete branches.
- A branch checked out in **another linked worktree** is refused by git itself;
  the script logs a warning and continues rather than failing the run.

### Examples

```bash
# Report what would be deleted (safe default)
python3 scripts/git/maintenance/cleanup-branches.py --repo /mnt/data/multi-agent-workflow

# Actually delete, pruning remote-tracking refs, non-interactively
python3 scripts/git/maintenance/cleanup-branches.py \
  --repo /mnt/data/multi-agent-workflow --yes --prune-remotes

# Run the tests
cd scripts/git/maintenance && python3 -m pytest tests -q
```

## Daily automation

### Host cron (real local-branch cleanup)

The host where agent worktrees live is the only place local branches actually
accumulate, so that is where deletions happen. `install-cron.sh` adds a crontab
entry running at 04:17 daily:

```bash
# Report-only daily audit (default, recommended)
./scripts/git/maintenance/install-cron.sh /mnt/data/multi-agent-workflow

# Enable actual deletions once you are confident in the report
CLEANUP_APPLY=1 ./scripts/git/maintenance/install-cron.sh /mnt/data/multi-agent-workflow
```

Logs land in `~/.branch-cleanup/cleanup-<date>.log` (last 7 kept). The default
mode is **dry-run**; enable real deletion explicitly with `CLEANUP_APPLY=1`.

### GitHub Actions (daily hygiene audit)

`.github/workflows/branch-cleanup.yml` runs every night at 04:17 UTC:

- runs the cleanup test suite,
- produces a **dry-run report** of merged / missing-upstream branches in the CI
  logs, and
- never deletes anything in CI (an ephemeral checkout has no stale local
  branches — deletion is the host cron's job).

A manual `workflow_dispatch` with `delete: true` prunes remote-tracking refs on
the ephemeral checkout only, which is already a fresh clone and thus harmless.