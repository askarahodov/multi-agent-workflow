#!/usr/bin/env bash
# GF-05: pre-push must reject a push that targets main, and must allow the same
# branch to be pushed under its own name.
source "$(cd "$(dirname "$0")" && pwd)/lib.sh"
begin_test test_forbidden_direct_push_to_main

repo="$(new_tmp_repo)"
install_hooks "$repo"
remote="$(new_bare_remote)"
git -C "$repo" remote add origin "$remote"
git -C "$repo" push -q origin main --no-verify   # seed the remote protected ref

git -C "$repo" checkout -q -b wt/t_cafebabe
printf 'work\n' >"$repo/work.txt"
git -C "$repo" add work.txt
git -C "$repo" commit -q -m "feat(test): add work"

# --- allowed: push the agent branch to its own ref -----------------------
if ! record env GITFLOW_SKIP_CI_CHECK=1 git -C "$repo" push origin wt/t_cafebabe >/dev/null; then
    fail "pre-push rejected a valid push of wt/t_cafebabe"
fi
pass "agent branch push allowed"

# --- violation: push the same commit onto main ---------------------------
if record env GITFLOW_SKIP_CI_CHECK=1 git -C "$repo" push origin wt/t_cafebabe:main >/dev/null; then
    fail "pre-push allowed a direct push to main (GF-05)"
fi
assert_contains "$TEST_LOG" "refusing a direct push to protected branch" "expected GF-05 message" 1
pass "direct push to main rejected"

# --- violation: force-push to main ---------------------------------------
git -C "$repo" checkout -q -b wt/t_0badf00d main
printf 'rewrite\n' >"$repo/rewrite.txt"
git -C "$repo" add rewrite.txt
git -C "$repo" commit -q -m "feat(test): rewrite history"
if record env GITFLOW_SKIP_CI_CHECK=1 git -C "$repo" push --force origin wt/t_0badf00d:main >/dev/null; then
    fail "pre-push allowed a force-push to main (GF-05)"
fi
pass "force-push to main rejected"
