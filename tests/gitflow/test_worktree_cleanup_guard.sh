#!/usr/bin/env bash
# GF-06 / GF-07: post-merge cleanup must never discard uncommitted work or a
# branch with unmerged unique commits, and must clean up once the work is
# really merged.
source "$(cd "$(dirname "$0")" && pwd)/lib.sh"
begin_test test_worktree_cleanup_guard

repo="$(new_tmp_repo)"
seed_project_repo "$repo"
task="t_0badc0de"
wt="$repo/.worktrees/$task"

python3 "$repo/scripts/git/worktree-lifecycle.py" --repo "$repo" create --task "$task" --from main \
    >/dev/null 2>&1 || fail "precondition: worktree creation failed"
[ -d "$wt" ] || fail "precondition: worktree missing"
[ -e "$wt/.githooks" ] || fail "create did not install hooks in the worktree"
[ -f "$wt/.agent-gitflow.json" ] || fail "create did not inject the policy pointer"
pass "create produced an isolated, hooked, policy-injected worktree"

# Exercise the exact policy emitter used by dispatcher-policy-hook.sh.
python3 "$repo/scripts/git/gitflow_context.py" --repo "$repo" claim \
    --task-id "$task" --worktree "$wt" --emit-env >"$wt/.agent-gitflow.env" \
    || fail "precondition: dispatcher policy emission failed"
python3 "$repo/scripts/git/worktree-lifecycle.py" --repo "$repo" validate --task "$task" \
    >/dev/null 2>&1 || fail "generated dispatcher env made a clean worktree invalid"
cp "$wt/.agent-gitflow.env" "$repo/expected-dispatcher.env"
printf 'export USER_DATA=precious\n' >>"$wt/.agent-gitflow.env"
out="$(python3 "$repo/scripts/git/worktree-lifecycle.py" --repo "$repo" cleanup --task "$task" --maintenance-window 2>&1)"
rc=$?
[ "$rc" -ne 0 ] || fail "cleanup accepted a modified dispatcher env"
assert_contains "$out" "uncommitted_work_guard" "modified env not guarded"
grep -q 'USER_DATA=precious' "$wt/.agent-gitflow.env" || fail "modified env was lost"
cp "$repo/expected-dispatcher.env" "$wt/.agent-gitflow.env"
rm "$repo/expected-dispatcher.env"
printf 'user data\n' >"$wt/.agent-gitflow.env.tmp"
out="$(python3 "$repo/scripts/git/worktree-lifecycle.py" --repo "$repo" cleanup --task "$task" --maintenance-window 2>&1)"
rc=$?
[ "$rc" -ne 0 ] || fail "cleanup accepted an unverified temporary env"
assert_contains "$out" "uncommitted_work_guard" "temporary env not guarded"
[ -f "$wt/.agent-gitflow.env.tmp" ] || fail "temporary env was lost"
rm "$wt/.agent-gitflow.env.tmp"
pass "dispatcher env recognized; modified and temporary env preserved"

# --- guard 1: uncommitted work -------------------------------------------
printf 'precious\n' >"$wt/uncommitted.txt"
out="$(python3 "$repo/scripts/git/worktree-lifecycle.py" --repo "$repo" cleanup --task "$task" --maintenance-window 2>&1)"
rc=$?
echo "$out" | tee -a "$TEST_LOG" >/dev/null
[ "$rc" -ne 0 ] || fail "cleanup succeeded despite uncommitted work"
assert_contains "$out" "uncommitted_work_guard" "uncommitted guard not reported"
[ -f "$wt/uncommitted.txt" ] || fail "cleanup destroyed uncommitted work"
pass "uncommitted work guarded and preserved"

# --- guard 2: unmerged unique commits ------------------------------------
git -C "$wt" add uncommitted.txt
git -C "$wt" commit -q -m "feat(test): keep precious work"
out="$(python3 "$repo/scripts/git/worktree-lifecycle.py" --repo "$repo" cleanup --task "$task" --maintenance-window 2>&1)"
rc=$?
echo "$out" | tee -a "$TEST_LOG" >/dev/null
[ "$rc" -ne 0 ] || fail "cleanup succeeded despite unmerged unique commits"
assert_contains "$out" "unmerged_commits_guard" "unmerged guard not reported"
git -C "$repo" rev-parse --verify --quiet "refs/heads/wt/$task" >/dev/null \
    || fail "cleanup deleted the branch although its commit was unmerged"
pass "unmerged unique commits guarded and preserved"

# --- allowed: after a real merge -----------------------------------------
git -C "$repo" checkout -q main
git -C "$repo" merge -q --ff-only "wt/$task" || fail "precondition: merge failed"
out="$(python3 "$repo/scripts/git/worktree-lifecycle.py" --repo "$repo" cleanup --task "$task" --maintenance-window 2>&1)"
rc=$?
echo "$out" | tee -a "$TEST_LOG" >/dev/null
[ "$rc" -eq 0 ] || fail "cleanup failed after a clean merge"
assert_contains "$out" '"status": "cleaned"' "cleanup did not report a clean state"
[ -d "$wt" ] && fail "worktree directory survived a successful cleanup"
git -C "$repo" rev-parse --verify --quiet "refs/heads/wt/$task" >/dev/null \
    && fail "merged branch survived a successful cleanup"
pass "merged branch and worktree removed safely"
