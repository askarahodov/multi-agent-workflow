#!/usr/bin/env bash
# L2: every task workspace must receive the live policy bundle (branch name +
# policy path) and live hooks; a tampered core.hooksPath must be detected
# instead of silently disabling enforcement (SEC-010).
source "$(cd "$(dirname "$0")" && pwd)/lib.sh"
begin_test test_policy_injection

repo="$(new_tmp_repo)"
seed_project_repo "$repo"
task="t_abc12345"
wt="$repo/.worktrees/$task"

python3 "$repo/scripts/git/worktree-lifecycle.py" --repo "$repo" create --task "$task" --from main \
    >/dev/null 2>&1 || fail "precondition: create failed"

# --- policy pointer + bundle ---------------------------------------------
[ -f "$wt/.agent-gitflow.json" ] || fail "policy pointer .agent-gitflow.json missing"
pointer="$(cat "$wt/.agent-gitflow.json")"
assert_contains "$pointer" "\"branch_name\": \"wt/$task\"" "pointer lacks the task branch"
assert_contains "$pointer" "AGENT_GITFLOW_RULES.md" "pointer lacks the policy path"

context="$(cat "$wt/AGENT_GITFLOW_CONTEXT.json" 2>/dev/null)" \
    || fail "policy bundle AGENT_GITFLOW_CONTEXT.json missing"
for id in GF-01 GF-02 GF-03 GF-04 GF-05 GF-06 GF-07 GF-08 GF-09 GF-10; do
    assert_contains "$context" "\"$id\"" "policy bundle misses rule $id"
done
python3 - "$wt/AGENT_GITFLOW_CONTEXT.json" "$wt" <<'PY' || exit 1
import json, os, sys
bundle = json.load(open(sys.argv[1], encoding="utf-8"))
wt = sys.argv[2]
assert os.path.realpath(bundle["rules_path"]).endswith("AGENT_GITFLOW_RULES.md"), bundle["rules_path"]
assert bundle["branch_name"].startswith("wt/t_"), bundle["branch_name"]
assert bundle["worktree_path"] == os.path.realpath(wt) or bundle["worktree_path"] == wt, bundle["worktree_path"]
PY
pass "workspace received branch name, policy path and full rule set"

# --- hooks live ----------------------------------------------------------
python3 "$repo/scripts/git/gitflow_context.py" --repo "$repo" verify --worktree "$wt" >/dev/null \
    || fail "verify reports the hooks as inert"
pass "hooks verified live"

# --- tampered core.hooksPath is detected (SEC-010) -----------------------
git -C "$wt" config core.hooksPath /tmp/attacker-hooks
if (cd "$wt" && bash .githooks/pre-commit) >/dev/null 2>&1; then
    fail "hook ran despite a redirected core.hooksPath (SEC-010)"
fi
pass "tampered core.hooksPath rejected"
