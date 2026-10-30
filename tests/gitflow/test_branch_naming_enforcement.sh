#!/usr/bin/env bash
# GF-02 / GF-05: a commit on a non-compliant branch must be rejected by
# pre-commit; a valid task branch must be accepted; main must be protected.
source "$(cd "$(dirname "$0")" && pwd)/lib.sh"
begin_test test_branch_naming_enforcement

repo="$(new_tmp_repo)"
install_hooks "$repo"

# --- violation: arbitrary branch name -------------------------------------
git -C "$repo" checkout -q -b bad-branch
printf 'x\n' >"$repo/file.txt"
git -C "$repo" add file.txt
if record git -C "$repo" commit -m "feat(test): add file" >/dev/null; then
    fail "pre-commit accepted a commit on branch 'bad-branch' (GF-02)"
fi
pass "invalid branch name rejected"

# --- allowed: agent task branch ------------------------------------------
git -C "$repo" checkout -q main
git -C "$repo" checkout -q -b wt/t_deadbeef
if ! record git -C "$repo" commit -m "feat(test): add file" >/dev/null; then
    fail "pre-commit rejected a valid commit on wt/t_deadbeef"
fi
pass "valid agent branch accepted"

# --- violation: protected branch -----------------------------------------
git -C "$repo" checkout -q main
printf 'y\n' >>"$repo/file.txt"
git -C "$repo" add file.txt
if record git -C "$repo" commit -m "feat(test): direct main commit" >/dev/null; then
    fail "pre-commit accepted a direct commit on main (GF-05)"
fi
pass "direct commit on main rejected"
