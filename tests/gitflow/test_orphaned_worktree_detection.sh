#!/usr/bin/env bash
# GF-08: the reaper must REPORT orphaned worktrees (merged-but-not-cleaned and
# idle > 7 days) and must never delete anything itself.
source "$(cd "$(dirname "$0")" && pwd)/lib.sh"
begin_test test_orphaned_worktree_detection

repo="$(new_tmp_repo)"
seed_project_repo "$repo"

# --- orphan 1: merged but never cleaned up -------------------------------
merged_task="t_11112222"
python3 "$repo/scripts/git/worktree-lifecycle.py" --repo "$repo" create --task "$merged_task" --from main \
    >/dev/null 2>&1 || fail "precondition: create failed for $merged_task"
printf 'done\n' >"$repo/.worktrees/$merged_task/done.txt"
git -C "$repo/.worktrees/$merged_task" add done.txt
git -C "$repo/.worktrees/$merged_task" commit -q -m "feat(test): completed work"
git -C "$repo" merge -q --ff-only "wt/$merged_task" || fail "precondition: merge failed"

# --- orphan 2: idle for more than seven days -----------------------------
idle_task="t_33334444"
python3 "$repo/scripts/git/worktree-lifecycle.py" --repo "$repo" create --task "$idle_task" --from main \
    >/dev/null 2>&1 || fail "precondition: create failed for $idle_task"
old_date="$(date -u -d '10 days ago' +%Y-%m-%dT%H:%M:%SZ)"
printf 'stale\n' >"$repo/.worktrees/$idle_task/stale.txt"
git -C "$repo/.worktrees/$idle_task" add stale.txt
GIT_AUTHOR_DATE="$old_date" GIT_COMMITTER_DATE="$old_date" \
    git -C "$repo/.worktrees/$idle_task" commit -q -m "feat(test): stale work"

out="$(python3 "$repo/scripts/git/worktree-lifecycle.py" --repo "$repo" reap 2>&1)"
rc=$?
echo "$out" | tee -a "$TEST_LOG" >/dev/null
[ "$rc" -eq 0 ] || fail "reap failed (rc=$rc)"

assert_contains "$out" "$merged_task" "merged orphan not reported"
assert_contains "$out" "merged but not cleaned up" "merged orphan reason missing"
assert_contains "$out" "$idle_task" "idle orphan not reported"
assert_contains "$out" "no commit for" "idle orphan reason missing"

# The reaper is report-only: both worktrees and branches must survive.
[ -d "$repo/.worktrees/$merged_task" ] || fail "reap deleted the merged orphan worktree"
git -C "$repo" rev-parse --verify --quiet "refs/heads/wt/$merged_task" >/dev/null \
    || fail "reap deleted the merged orphan branch"
[ -d "$repo/.worktrees/$idle_task" ] || fail "reap deleted the idle orphan worktree"
pass "orphans reported and nothing deleted"
