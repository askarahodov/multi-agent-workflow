#!/usr/bin/env bash
# Squash-merge artefacts: a commit carrying git's squash marker must never be
# pushed onto a branch that is under review. The commit itself can only get
# there by bypassing commit-msg, so the test creates it with --no-verify and
# requires pre-push to stop it (defence in depth).
source "$(cd "$(dirname "$0")" && pwd)/lib.sh"
begin_test test_squash_merge_blocked

repo="$(new_tmp_repo)"
install_hooks "$repo"
remote="$(new_bare_remote)"
git -C "$repo" remote add origin "$remote"
git -C "$repo" push -q origin main --no-verify

git -C "$repo" checkout -q -b wt/t_5a5a5a5a
printf 'one\n' >"$repo/a.txt"
git -C "$repo" add a.txt
git -C "$repo" commit -q -m "feat(test): first change"
record env GITFLOW_SKIP_CI_CHECK=1 git -C "$repo" push origin wt/t_5a5a5a5a >/dev/null \
    || fail "precondition: normal push was rejected"

# --- violation: squash-marker commit (hook bypassed at commit time) ------
printf 'two\n' >>"$repo/a.txt"
git -C "$repo" add a.txt
git -C "$repo" commit -q --no-verify -m "Squashed commit of the following:"
if record env GITFLOW_SKIP_CI_CHECK=1 git -C "$repo" push origin wt/t_5a5a5a5a >/dev/null; then
    fail "pre-push allowed a squash-merge artefact onto wt/t_5a5a5a5a"
fi
assert_contains "$TEST_LOG" "squash-merge" "expected squash-merge diagnostic" 1
pass "squash-merge artefact rejected on push"
